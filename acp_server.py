#!/usr/bin/env python3
"""ACP worker for released Buzz apps, backed by the official agy CLI."""

import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import uuid

from adapter import AdapterError, MAX_INPUT, response_text, stop_child

VERSION = "0.2.2"
MODES = {"default": "Use Antigravity permissions", "plan": "Plan",
         "accept-edits": "Accept edits", "auto": "Antigravity Auto"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class RpcError(Exception):
    def __init__(self, message, code=-32602):
        super().__init__(message)
        self.code = code


def state_root():
    return Path(os.environ.get("GOOSE_AGY_STATE_DIR", Path.home() / ".local/state/gooseagy"))


def allow_all_tools():
    override = os.environ.get("GOOSE_AGY_ALLOW_ALL")
    if override is not None:
        if override not in ("0", "1"):
            raise RpcError("GOOSE_AGY_ALLOW_ALL must be 0 or 1")
        return override == "1"
    path = state_root() / "runtime.json"
    value = json.loads(path.read_text()).get("allowAllTools", False) if path.exists() else False
    if not isinstance(value, bool):
        raise RpcError("allowAllTools must be a boolean")
    return value


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RpcError("State directories must not be symlinks")
    path.chmod(0o700)
    return path


def write_private(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def mcp_config(servers):
    """Convert ACP stdio/HTTP declarations to Antigravity's native MCP format."""
    if not isinstance(servers, list):
        raise RpcError("mcpServers must be an array")
    converted = {}
    for server in servers:
        if not isinstance(server, dict):
            raise RpcError("Invalid MCP declaration")
        name = server.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", name):
            raise RpcError("MCP names must contain only letters, digits, underscores, or hyphens")
        if name in converted:
            raise RpcError("Duplicate MCP server name")
        kind = server.get("type", "stdio")
        if kind == "http":
            url = server.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                raise RpcError("Invalid MCP HTTP URL")
            entry = {"serverUrl": url}
            pairs = server.get("headers", [])
            label = "headers"
        elif kind == "stdio":
            cmd = server.get("command")
            args = server.get("args", [])
            if not isinstance(cmd, str) or not cmd or "\0" in cmd:
                raise RpcError("Invalid MCP executable")
            if not isinstance(args, list) or any(not isinstance(a, str) or "\0" in a for a in args):
                raise RpcError("Invalid MCP arguments")
            entry = {"command": cmd, "args": args}
            pairs = server.get("env", [])
            label = "env"
        else:
            raise RpcError("Only stdio and Streamable HTTP MCP servers are supported")
        if not isinstance(pairs, list):
            raise RpcError(f"MCP {label} must be an array of name/value pairs")
        values = {}
        for pair in pairs:
            if (not isinstance(pair, dict) or not isinstance(pair.get("name"), str)
                    or not pair["name"] or not isinstance(pair.get("value"), str)
                    or "\0" in pair["name"] + pair["value"] or pair["name"] in values):
                raise RpcError(f"Invalid MCP {label} pair")
            values[pair["name"]] = pair["value"]
        if values:
            entry[label] = values
        converted[name] = entry
    return {"mcpServers": converted}


def prompt_text(blocks):
    if not isinstance(blocks, list) or not blocks:
        raise RpcError("Expected nonempty text prompt blocks")
    text = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
            raise RpcError("This adapter accepts text only; attachments are unsupported")
        text.append(block["text"])
    joined = "\n".join(text)
    if not joined.strip():
        raise RpcError("Prompt cannot be empty")
    return joined


class Server:
    def __init__(self):
        self.root = private_dir(state_root())
        self.sessions_dir = private_dir(self.root / "sessions")
        self.sessions = {}
        self.active = {}
        self.tasks = set()
        self.initialized = False
        # Never persist credentials; a one-way owner scope prevents reattaching
        # another app-managed agent's sessions when its identity is available.
        identity = "\0".join(os.environ.get(k, "") for k in (
            "BUZZ_AGENT_PUBKEY", "BUZZ_PUBLIC_KEY", "BUZZ_PRIVATE_KEY", "BUZZ_RELAY_URL"))
        self.scope = hashlib.sha256(identity.encode()).hexdigest()
        self.models = self.load_models()
        self.default_model = os.environ.get("BUZZ_ACP_MODEL") or os.environ.get("GOOSE_AGY_MODEL", "gemini-4-argon-high")
        if self.default_model not in {m["modelId"] for m in self.models}:
            self.models.append({"modelId": self.default_model, "name": self.default_model})

    def load_models(self):
        path = self.root / "models.json"
        if not path.exists():
            return [{"modelId": "gemini-4-argon-high", "name": "Gemini 4 Argon (High)"}]
        data = json.loads(path.read_text())
        if not isinstance(data, list) or not data:
            raise RpcError("Invalid models cache; run goose-agy doctor --refresh-models")
        for item in data:
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ("modelId", "name")):
                raise RpcError("Invalid models cache")
        return data

    def send(self, value):
        print(json.dumps({"jsonrpc": "2.0", **value}, ensure_ascii=False), flush=True)

    def update(self, sid, update):
        self.send({"method": "session/update", "params": {"sessionId": sid, "update": update}})

    def session_path(self, sid):
        if not isinstance(sid, str) or not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise RpcError("Invalid session ID")
        return self.sessions_dir / f"{sid}.json"

    def save(self, session):
        write_private(self.session_path(session["id"]), {k: v for k, v in session.items() if k != "mcp"})

    def get(self, sid):
        if sid not in self.sessions:
            raise RpcError("Session is not attached; use session/load first")
        return self.sessions[sid]

    def options(self, s):
        return {"modes": {"currentModeId": s["mode"], "availableModes": [
                    {"id": k, "name": v} for k, v in MODES.items()]},
                "models": {"currentModelId": s["model"], "availableModels": self.models},
                "configOptions": [
                    {"id": "model", "name": "Model", "category": "model", "type": "select",
                     "currentValue": s["model"], "options": [
                         {"value": m["modelId"], "name": m["name"]} for m in self.models]},
                    {"id": "effort", "name": "Reasoning effort", "category": "thought_level",
                     "type": "select", "currentValue": s["effort"],
                     "options": [{"value": e, "name": e.capitalize()} for e in EFFORTS]},
                ]}

    async def dispatch(self, method, p):
        if method == "initialize":
            self.initialized = True
            return {"protocolVersion": 1, "agentInfo": {"name": "antigravity-ultra", "version": VERSION},
                    "agentCapabilities": {"loadSession": True,
                        "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False},
                        "mcpCapabilities": {"http": True, "sse": False},
                        "sessionCapabilities": {"close": {}}}, "authMethods": []}
        if not self.initialized:
            raise RpcError("Initialize the ACP connection first", -32000)
        if method == "authenticate":
            raise RpcError("Sign in interactively using agy on this computer", -32000)
        if method in ("session/new", "session/load"):
            cwd = p.get("cwd")
            if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
                raise RpcError("cwd must be an existing absolute directory")
            config = mcp_config(p.get("mcpServers", []))
            if method == "session/new":
                effort = os.environ.get("GOOSE_AGY_EFFORT", "high")
                mode = os.environ.get("GOOSE_AGY_MODE", "default")
                if effort not in EFFORTS or mode not in MODES:
                    raise RpcError("Invalid startup effort/mode")
                system = p.get("systemPrompt", p.get("_meta", {}).get("systemPrompt", ""))
                if not isinstance(system, str):
                    raise RpcError("systemPrompt must be text")
                s = {"id": uuid.uuid4().hex, "scope": self.scope, "cwd": str(Path(cwd).resolve()),
                     "model": self.default_model, "effort": effort, "mode": mode,
                     "conversation": None, "system": system, "history": [], "broken": False}
            else:
                path = self.session_path(p.get("sessionId"))
                if not path.exists():
                    raise RpcError("Session not found", -32000)
                s = json.loads(path.read_text())
                if s["scope"] != self.scope or s["cwd"] != str(Path(cwd).resolve()):
                    raise RpcError("Session owner or working directory does not match", -32000)
                if s["id"] in self.active:
                    raise RpcError("Session is busy", -32000)
                for turn in s["history"]:
                    for role in ("user", "agent"):
                        self.update(s["id"], {"sessionUpdate": f"{role}_message_chunk",
                                             "content": {"type": "text", "text": turn[role]}})
            s["mcp"] = config
            self.sessions[s["id"]] = s
            if method == "session/new":
                self.save(s)
            result = self.options(s)
            if method == "session/new":
                result["sessionId"] = s["id"]
            return result
        sid = p.get("sessionId")
        s = self.get(sid)
        if method == "session/close":
            if sid in self.active:
                self.active[sid].cancel()
                await asyncio.gather(self.active[sid], return_exceptions=True)
            self.sessions.pop(sid, None)
            return {}
        if method == "session/cancel":
            if sid in self.active:
                self.active[sid].cancel()
            return {}
        if method == "session/prompt":
            text = prompt_text(p.get("prompt"))
            if sid in self.active:
                raise RpcError("Session already has an active prompt", -32000)
            if s["broken"]:
                raise RpcError("Previous turn failed or was interrupted; start a new session to avoid replaying actions", -32000)
            task = asyncio.current_task()
            self.active[sid] = task
            try:
                answer = await self.turn(s, text)
                s["history"].append({"user": text, "agent": answer})
                s["broken"] = False
                self.save(s)
                return {"stopReason": "end_turn"}
            except asyncio.CancelledError:
                s["broken"] = True
                self.save(s)
                return {"stopReason": "cancelled"}
            finally:
                self.active.pop(sid, None)
        if sid in self.active:
            raise RpcError("Cannot reconfigure a session during a prompt", -32000)
        if method in ("session/set_model", "session/set_mode", "session/set_config_option"):
            key = {"session/set_model": "model", "session/set_mode": "mode"}.get(method, p.get("configId"))
            value = p.get("value") if method == "session/set_config_option" else p.get("modelId" if key == "model" else "modeId")
            choices = {"model": [m["modelId"] for m in self.models], "mode": MODES, "effort": EFFORTS}
            if key not in choices or value not in choices[key]:
                raise RpcError("Unsupported configuration value")
            s[key] = value
            self.save(s)
            return {"configOptions": self.options(s)["configOptions"]} if method == "session/set_config_option" else {}
        raise RpcError("Method not found", -32601)

    async def turn(self, s, text):
        timeout = float(os.environ.get("GOOSE_AGY_TIMEOUT", "600"))
        if not 0 < timeout < float("inf"):
            raise RpcError("GOOSE_AGY_TIMEOUT must be positive and finite")
        # Retain the user's ask/deny rules when adding session-scoped MCP
        # permissions. --settings replaces the top-level permissions object.
        settings_file = Path.home() / ".gemini/antigravity-cli/settings.json"
        user_settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
        permissions = dict(user_settings.get("permissions", {}))
        allowed = permissions.get("allow", [])
        if not isinstance(allowed, list) or any(not isinstance(rule, str) for rule in allowed):
            raise RpcError("Invalid Antigravity permissions.allow settings")
        permissions["allow"] = list(dict.fromkeys([*allowed, *[
            f"mcp({name}/*)" for name in s["mcp"]["mcpServers"]]]))
        settings = {"modelProvider": "", "permissions": permissions}
        cmd = [os.environ.get("GOOSE_AGY_COMMAND", "agy"), "--input-format", "stream-json",
               "--output-format", "stream-json", "--disable-slash-commands", "--print-timeout", "0",
               "--add-dir", s["cwd"], "--model", s["model"], "--effort", s["effort"],
               "--settings", json.dumps(settings)]
        if s["mode"] != "default":
            cmd += ["--mode", s["mode"]]
        if allow_all_tools():
            if s["mode"] == "plan":
                raise RpcError("Unrestricted tools cannot be combined with plan mode")
            cmd += ["--dangerously-skip-permissions"]
        if s["conversation"]:
            cmd += ["--conversation", s["conversation"]]
        prompt = text
        if not s["conversation"]:
            prompt = (f"Project working directory: {s['cwd']}\n"
                      "Use absolute paths in this project for file operations and set command cwd to this directory. "
                      "The current directory is adapter-owned runtime state; do not edit it. "
                      "Buzz MCP tools are supplied for this session. Follow the Buzz instructions for channel replies.\n\n"
                      + s["system"] + "\n\n" + text)
        workspace = private_dir(self.root / "workspaces" / s["id"])
        lock = open(workspace / ".lock", "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RpcError("Session is active in another process", -32000)
        config_file = workspace / ".agents/mcp_config.json"
        proc = None
        chunks = ""
        result = None
        observed_id = s["conversation"]
        writer = None
        seen_tools = set()
        tools = {}
        try:
            saved = json.loads(self.session_path(s["id"]).read_text())
            if saved.get("broken") or saved.get("conversation") != s["conversation"]:
                raise RpcError("Session changed in another process; start a new session", -32000)
            private_dir(config_file.parent)
            write_private(config_file, s["mcp"])
            # Mark before dispatch so a crash cannot replay an uncertain action.
            s["broken"] = True
            self.save(s)
            async with asyncio.timeout(timeout):
                env = dict(os.environ)
                # Account login only. API-key configuration must not silently
                # charge a separate Gemini API billing account.
                for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                    env.pop(key, None)
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=workspace, env=env, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=None, limit=MAX_INPUT,
                    start_new_session=(os.name == "posix"))
                async def write():
                    proc.stdin.write((json.dumps({"event": "user", "message": {"content": prompt}}) + "\n").encode())
                    try:
                        await proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        proc.stdin.close()
                writer = asyncio.create_task(write())
                async for line in proc.stdout:
                    try:
                        e = json.loads(line)
                    except ValueError as exc:
                        raise RpcError("Antigravity emitted malformed JSON", -32000) from exc
                    if not isinstance(e, dict):
                        raise RpcError("Antigravity emitted an invalid event", -32000)
                    if result is not None:
                        raise RpcError("Antigravity emitted events after its final result", -32000)
                    if e.get("event") == "init":
                        cid = e.get("conversation_id")
                        if not isinstance(cid, str) or not cid or (observed_id and observed_id != cid):
                            raise RpcError("Antigravity conversation identity mismatch", -32000)
                        observed_id = cid
                    elif e.get("event") == "step_update":
                        step = e.get("step_update", {})
                        if not isinstance(step, dict):
                            raise RpcError("Invalid Antigravity step", -32000)
                        if step.get("step_type") == "agent_response":
                            delta = step.get("text_delta", "")
                            if not isinstance(delta, str):
                                raise RpcError("Invalid assistant delta", -32000)
                            chunks += delta
                            if delta:
                                self.update(s["id"], {"sessionUpdate": "agent_message_chunk",
                                                     "content": {"type": "text", "text": delta}})
                        elif step.get("step_type") == "tool":
                            call_id = str(step.get("step_index", "tool"))
                            tools[call_id] = step
                            status = {"DONE": "completed", "ERROR": "failed"}.get(step.get("state"), "in_progress")
                            self.update(s["id"], {"sessionUpdate": "tool_call_update" if call_id in seen_tools else "tool_call",
                                "toolCallId": call_id, "title": step.get("tool_name", "Antigravity tool"),
                                "kind": "other", "status": status})
                            seen_tools.add(call_id)
                    elif e.get("event") == "result":
                        if result is not None:
                            raise RpcError("Antigravity returned duplicate results", -32000)
                        result = e.get("result")
                code = await proc.wait()
                await writer
                if code or not isinstance(result, dict) or result.get("status") != "SUCCESS":
                    detail = result.get("error", result.get("status")) if isinstance(result, dict) else "missing result"
                    raise RpcError(f"Antigravity failed (exit {code}): {detail}", -32000)
                cid = result.get("conversation_id")
                if not isinstance(cid, str) or not cid or (observed_id and cid != observed_id):
                    raise RpcError("Antigravity conversation identity mismatch", -32000)
                answer = response_text(result, chunks, tools)
                if answer and (not chunks or not chunks.endswith(answer)):
                    suffix = answer[len(chunks):] if answer.startswith(chunks) else "\n" + answer
                    self.update(s["id"], {"sessionUpdate": "agent_message_chunk",
                                         "content": {"type": "text", "text": suffix.lstrip("\n") if not chunks else suffix}})
                s["conversation"] = cid
                return answer
        except TimeoutError as exc:
            raise RpcError(f"Antigravity timed out after {timeout:g}s; session requires reset", -32000) from exc
        finally:
            if writer and not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            if proc:
                await stop_child(proc)
            config_file.unlink(missing_ok=True)
            lock.close()

    async def handle(self, request):
        rid = request.get("id")
        try:
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise RpcError("params must be an object")
            result = await self.dispatch(request.get("method"), params)
            if "id" in request:
                self.send({"id": rid, "result": result})
        except (RpcError, AdapterError, OSError, ValueError, KeyError, TypeError) as exc:
            # Never log prompt text, MCP config, or environment values.
            if "id" in request:
                self.send({"id": rid, "error": {"code": getattr(exc, "code", -32000), "message": str(exc)}})
            else:
                print(f"agy-acp: {type(exc).__name__}", file=sys.stderr)

    async def run(self):
        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()
        loop.add_signal_handler(signal.SIGTERM, main_task.cancel)
        reader = asyncio.StreamReader(limit=MAX_INPUT)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)
        try:
            while line := await reader.readline():
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                        raise ValueError("invalid request")
                except ValueError:
                    self.send({"id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC request"}})
                    continue
                task = asyncio.create_task(self.handle(request))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
        finally:
            transport.close()
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args()
    try:
        asyncio.run(Server().run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except (OSError, ValueError, RpcError) as exc:
        print(f"agy-acp: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
