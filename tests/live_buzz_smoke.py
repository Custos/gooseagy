#!/usr/bin/env python3
"""Live ACP + agy + local MCP proof. Does not connect to a Buzz community."""
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile

from acp_client import Client

ROOT = Path(__file__).resolve().parent.parent
env = dict(os.environ)
command = ([env["GOOSE_AGY_TEST_WORKER"]] if env.get("GOOSE_AGY_TEST_WORKER")
           else [sys.executable, str(ROOT / "acp_server.py")])
with tempfile.TemporaryDirectory(prefix="buzz-agy-live-") as temp:
    tmp = Path(temp)
    env["GOOSE_AGY_STATE_DIR"] = str(tmp / "state")
    agy = env.get("GOOSE_AGY_COMMAND") or shutil.which("agy")
    if not agy:
        sys.exit("Install and sign in to agy before running this live check")
    env["GOOSE_AGY_COMMAND"] = agy
    proof = "buzz-mcp-" + secrets.token_hex(8)
    server = {"name": "buzzproof", "command": sys.executable,
              "args": [str(ROOT / "tests/mcp_probe.py")],
              "env": [{"name": "PROOF_TOKEN", "value": proof},
                      {"name": "PROOF_LOG", "value": str(tmp / "proof.log")}]}
    client = Client(command, env)
    try:
        assert "result" in client.request("initialize", {"protocolVersion": 2})
        response = client.request("session/new", {"cwd": str(tmp), "mcpServers": [server]})
        sid = response["result"]["sessionId"]
        response = client.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text":
            "Call the buzzproof MCP server get_proof tool to learn its secret token. Remember it and reply with only the token. Do not read files or use any other tools."}]}, timeout=180)
        assert response.get("result", {}).get("stopReason") == "end_turn", response
        text = "".join(e.get("params", {}).get("update", {}).get("content", {}).get("text", "") for e in client.events)
        assert proof in text and (tmp / "proof.log").read_text() == "called\n"
        print("PASS: ACP initialization, streaming, and real MCP tool call", flush=True)
        client.close()
        client = Client(command, env)
        client.request("initialize", {"protocolVersion": 1})
        response = client.request("session/load", {"cwd": str(tmp), "sessionId": sid, "mcpServers": [server]})
        assert "result" in response, response
        client.events.clear()
        response = client.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text":
            "What exact token did that tool return in our previous turn? Reply with only that token. Do not use any tools."}]}, timeout=180)
        assert response.get("result", {}).get("stopReason") == "end_turn", response
        text = "".join(e.get("params", {}).get("update", {}).get("content", {}).get("text", "") for e in client.events)
        assert proof in text, text
        assert (tmp / "proof.log").read_text() == "called\n"
        assert not list((tmp / "state").rglob("mcp_config.json"))
        print("PASS: process restart, session load, remembered tool result, MCP credential cleanup", flush=True)
    finally:
        diagnostics = client.close()
        if diagnostics:
            print("Diagnostics:", diagnostics[-1500:], file=sys.stderr)
