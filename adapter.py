#!/usr/bin/env python3
"""Translate Goose's Gemini CLI transport to the official Antigravity CLI."""

import argparse
import asyncio
import json
import os
import signal
import sys

VERSION = "0.1.1"
MAX_INPUT = 16 * 1024 * 1024


class AdapterError(Exception):
    pass


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def message(text):
    if text:
        emit({"type": "message", "role": "assistant", "content": text, "delta": True})


def response_text(result, streamed, tools):
    """A successful tool-only turn need not have a free-text response.

    agy can also return SUCCESS after a headless permission denial. Inspect
    denied_actions before accepting that status, even when it returned text.
    Never echo tool parameters, output or backend error payloads here.
    """
    if result.get("denied_actions"):
        raise AdapterError(
            "Antigravity needs approval for a tool action. Buzz cannot show agy's "
            "interactive approval prompt. Review the action in agy and configure "
            "a specific permission rule if appropriate, then use New session in Buzz.")
    answer = result.get("response")
    if not isinstance(answer, str):
        raise AdapterError("Antigravity returned an invalid response field")
    if answer.strip():
        return answer
    if any(step.get("state") == "ERROR" or
           isinstance(step.get("tool_info"), dict) and step["tool_info"].get("error")
           for step in tools.values()):
        raise AdapterError("An Antigravity tool failed; inspect the conversation in agy, then use New session in Buzz.")
    if streamed.strip():
        return streamed
    if tools and all(step.get("state") == "DONE" for step in tools.values()):
        return ""
    raise AdapterError("Antigravity completed without a reply or a completed tool call")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-m", "--model", default="current")
    parser.add_argument("-r", "--resume", metavar="CONVERSATION_ID")
    parser.add_argument("--output-format", choices=["stream-json"], default="stream-json")
    # Goose 1.57 unconditionally sends this. It is deliberately NOT forwarded.
    parser.add_argument("--yolo", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=VERSION)
    return parser.parse_args(argv)


def command(args, env):
    cmd = [env.get("GOOSE_AGY_COMMAND", "agy"),
           "--input-format", "stream-json", "--output-format", "stream-json",
           "--disable-slash-commands"]
    if args.model not in ("current", "default", "auto"):
        cmd += ["--model", args.model]
    if args.resume:
        cmd += ["--conversation", args.resume]
    if env.get("GOOSE_AGY_EFFORT"):
        effort = env["GOOSE_AGY_EFFORT"]
        if effort not in ("low", "medium", "high", "xhigh", "max"):
            raise AdapterError("GOOSE_AGY_EFFORT must be low, medium, high, xhigh, or max")
        cmd += ["--effort", effort]
    mode = env.get("GOOSE_AGY_MODE")
    if not mode and env.get("GOOSE_MODE") == "chat":
        mode = "plan"
    if mode:
        if mode not in ("plan", "accept-edits", "auto"):
            raise AdapterError("GOOSE_AGY_MODE must be plan, accept-edits, or auto")
        cmd += ["--mode", mode]
    allow_all = env.get("GOOSE_AGY_ALLOW_ALL", "0")
    if allow_all not in ("0", "1"):
        raise AdapterError("GOOSE_AGY_ALLOW_ALL must be 0 or 1")
    if allow_all == "1":
        if mode == "plan":
            raise AdapterError("GOOSE_AGY_ALLOW_ALL=1 cannot be combined with plan/chat mode")
        cmd += ["--dangerously-skip-permissions"]
    # Avoid the CLI's own default ceiling competing with the adapter's timeout.
    cmd += ["--print-timeout", "0"]
    return cmd


class Translator:
    def __init__(self, expected_id=None):
        self.session_id = expected_id
        self.initialized = False
        self.text = ""
        self.result = None
        self.tools = {}

    def initialize(self, cid):
        if not isinstance(cid, str) or not cid:
            raise AdapterError("Antigravity did not return a conversation ID")
        if self.session_id and self.session_id != cid:
            raise AdapterError("Antigravity changed the conversation ID unexpectedly")
        self.session_id = cid
        if not self.initialized:
            emit({"type": "init", "session_id": cid})
            self.initialized = True

    def consume(self, event):
        if not isinstance(event, dict):
            raise AdapterError("Antigravity emitted a non-object event")
        if self.result is not None:
            raise AdapterError("Antigravity emitted events after its final result")
        kind = event.get("event")
        if kind == "init":
            self.initialize(event.get("conversation_id"))
        elif kind == "step_update":
            step = event.get("step_update")
            if not isinstance(step, dict):
                raise AdapterError("Invalid Antigravity step update")
            if step.get("step_type") == "agent_response":
                text = step.get("text_delta", "")
                if not isinstance(text, str):
                    raise AdapterError("Invalid Antigravity text delta")
                self.text += text
                message(text)
            elif step.get("step_type") == "tool":
                self.tools[str(step.get("step_index", "tool"))] = step
        elif kind == "result":
            result = event.get("result")
            if not isinstance(result, dict):
                raise AdapterError("Invalid Antigravity result")
            status = result.get("status")
            if status != "SUCCESS":
                detail = result.get("error") or "no error detail provided"
                raise AdapterError(f"Antigravity {status or 'missing status'}: {detail}")
            self.initialize(result.get("conversation_id"))
            self.result = {**result, "response": response_text(result, self.text, self.tools)}
        elif kind == "error":
            raise AdapterError(f"Antigravity error: {event.get('error', 'unknown error')}")
        # Tool/checkpoint/progress and future event types are not assistant text.

    def finish(self):
        if self.result is None:
            raise AdapterError("Antigravity exited without a final result")
        answer = self.result["response"]
        if not self.text:
            message(answer)
        elif answer.startswith(self.text):
            message(answer[len(self.text):])
        elif not self.text.endswith(answer):
            # A backend may stream intermediate commentary but return the final
            # answer only in result.response. Do not silently lose that answer.
            overlap = min(len(answer), len(self.text))
            while overlap and not self.text.endswith(answer[:overlap]):
                overlap -= 1
            message(answer[overlap:] if overlap else "\n" + answer)
        usage = self.result.get("usage") or {}
        if not isinstance(usage, dict):
            raise AdapterError("Invalid Antigravity usage")
        stats = {}
        for source, target in (("input_tokens", "input_tokens"),
                               ("output_tokens", "output_tokens"),
                               ("total_tokens", "total_tokens"),
                               ("cache_read_tokens", "cache_read_input_tokens")):
            value = usage.get(source)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                stats[target] = value
        emit({"type": "result", "status": "success", "stats": stats})


async def stop_child(proc):
    if proc.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), 2)
    except asyncio.TimeoutError:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


async def read_output(proc, translator):
    async for line in proc.stdout:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            # Do not echo malformed output, which could contain prompt contents.
            raise AdapterError("Antigravity emitted invalid JSON on stdout") from exc
        translator.consume(event)
    code = await proc.wait()
    if code:
        raise AdapterError(f"Antigravity exited with code {code}; see diagnostics on stderr")


async def write_prompt(proc, prompt):
    data = {"event": "user", "message": {"content": prompt}}
    proc.stdin.write((json.dumps(data, ensure_ascii=False) + "\n").encode())
    try:
        await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        # Read the backend's error result/exit status before reporting a failure.
        pass
    finally:
        proc.stdin.close()


async def watch_parent(pid):
    while os.getppid() == pid:
        await asyncio.sleep(0.25)
    raise AdapterError("Goose disconnected; Antigravity was stopped")


async def execute(args, prompt, env):
    parent_pid = os.getppid()
    try:
        timeout = float(env.get("GOOSE_AGY_TIMEOUT", "600"))
    except ValueError as exc:
        raise AdapterError("GOOSE_AGY_TIMEOUT must be a positive number of seconds") from exc
    if not 0 < timeout < float("inf"):
        raise AdapterError("GOOSE_AGY_TIMEOUT must be a positive finite number of seconds")
    cmd = command(args, env)
    translator = Translator(args.resume)
    proc = None
    tasks = []
    try:
        async with asyncio.timeout(timeout):
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                # stderr goes directly to Goose's diagnostic pipe; never parse it.
                stderr=None, start_new_session=(os.name == "posix"), limit=MAX_INPUT,
            )
            reader = asyncio.create_task(read_output(proc, translator))
            writer = asyncio.create_task(write_prompt(proc, prompt))
            parent = asyncio.create_task(watch_parent(parent_pid))
            tasks = [reader, writer, parent]
            done, _ = await asyncio.wait([reader, parent], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            await writer
            translator.finish()
    except FileNotFoundError as exc:
        raise AdapterError("Cannot find Antigravity CLI; install agy or set GOOSE_AGY_COMMAND") from exc
    except TimeoutError as exc:
        raise AdapterError(f"Antigravity timed out after {timeout:g}s; no automatic retry") from exc
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if proc:
            await stop_child(proc)


def main(argv=None):
    args = parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise AdapterError("Prompt exceeds the 16 MiB adapter input limit")
        prompt = raw.decode("utf-8")
        if not prompt.strip():
            raise AdapterError("Expected a nonempty UTF-8 prompt on stdin")
        asyncio.run(execute(args, prompt, os.environ))
        return 0
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 1
    except (AdapterError, OSError, UnicodeError, ValueError) as exc:
        emit({"type": "error", "error": str(exc)})
        print(f"goose-agy: {exc}", file=sys.stderr)
        return 1


def terminate(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())
