#!/usr/bin/env python3
"""Deterministic CLI fixture; never contacts a model provider."""

import json
import os
from pathlib import Path
import signal
import sys
import time


def emit(value):
    print(json.dumps(value), flush=True)


data = sys.stdin.readline()
request = json.loads(data)
if os.environ.get("FAKE_RECORD"):
    Path(os.environ["FAKE_RECORD"]).write_text(json.dumps({
        "argv": sys.argv[1:], "request": request,
        "eof": sys.stdin.read() == "", "cwd": os.getcwd(),
    }))
case = os.environ.get("FAKE_CASE", "success")
if case in ("timeout", "stubborn"):
    if case == "stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(os.environ["FAKE_PID"]).write_text(str(os.getpid()))
    time.sleep(60)
if case == "bad-json":
    print("this is not NDJSON", flush=True)
    sys.exit(0)
if case == "scalar":
    emit([])
    sys.exit(0)
cid = "conversation-test"
if "--conversation" in sys.argv:
    cid = sys.argv[sys.argv.index("--conversation") + 1]
if case == "wrong-id":
    cid = "another-conversation"
emit({"event": "init", "conversation_id": cid, "init": {}})
if case == "missing-result":
    sys.exit(0)
if case == "failure":
    emit({"event": "result", "result": {"status": "ERROR", "error": "quota exhausted"}})
    sys.exit(1)
if case == "nonterminal":
    emit({"event": "result", "result": {"status": "WAITING", "error": "needs approval"}})
    sys.exit(0)
if case == "slow-stderr":
    # Larger than the OS pipe buffer. The adapter must not deadlock on stderr.
    sys.stderr.write("diagnostic\n" * 20000)
    sys.stderr.flush()
answer = "héllo\nworld"
emit({"event": "future_event", "other": 1})
emit({"event": "step_update", "step_update": {
    "step_type": "tool", "text_delta": "NOT ASSISTANT TEXT",
}})
if case in ("tool-only", "denied", "denied-with-text", "tool-error", "recovered"):
    step = {"step_type": "tool", "step_index": 1, "tool_name": "test_tool",
            "state": "DONE" if case == "tool-only" else "ERROR"}
    if case != "tool-only":
        step["tool_info"] = {"error": {"type": "TOOL_ERROR", "message": "private tool details"}}
    # Replace the generic progress event with a real terminal step in fixtures.
    step.pop("step_index")
    emit({"event": "step_update", "step_update": step})
if case not in ("result-only", "empty", "tool-only", "denied", "tool-error"):
    for text, state in (("héllo\n", "ACTIVE"), ("world", "DONE")):
        emit({"event": "step_update", "step_update": {
            "step_type": "agent_response", "state": state, "text_delta": text,
        }})
result = {
    "conversation_id": cid, "status": "SUCCESS",
    "response": None if case == "invalid-response" else "" if case in
        ("empty", "tool-only", "denied", "tool-error", "streamed-only") else answer,
    "usage": {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24,
              "cache_read_tokens": 10},
}
if case in ("denied", "denied-with-text"):
    result["denied_actions"] = [{"action": "command", "display_name": "RunCommand"}]
emit({"event": "result", "result": result})
if case == "exit-failure":
    sys.exit(7)
