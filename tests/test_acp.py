import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from acp_client import Client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from acp_server import mcp_config


class AcpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GOOSE_AGY_", "BUZZ_", "FAKE_"))}
        self.env.update(GOOSE_AGY_STATE_DIR=str(self.root / "state"),
                        GOOSE_AGY_COMMAND=str(ROOT / "tests/fake_agy.py"),
                        FAKE_RECORD=str(self.root / "record"), FAKE_PID=str(self.root / "pid"))
        self.client = self.start()
        self.addCleanup(lambda: self.client.close())

    def start(self):
        client = Client([sys.executable, str(ROOT / "acp_server.py")], self.env)
        response = client.request("initialize", {"protocolVersion": 2, "clientCapabilities": {}})
        self.assertEqual(response["result"]["protocolVersion"], 1)
        return client

    def new(self, servers=None):
        response = self.client.request("session/new", {"cwd": str(self.root), "mcpServers": servers or []})
        self.assertIn("result", response, response)
        return response["result"]["sessionId"]

    def prompt(self, sid, text="hello"):
        return self.client.request("session/prompt", {"sessionId": sid,
                                   "prompt": [{"type": "text", "text": text}]})

    def test_streaming_context_reload_and_private_mcp_cleanup(self):
        server = {"name": "buzz", "command": "test-server", "args": [],
                  "env": [{"name": "APP_TOKEN", "value": "private-value"}]}
        sid = self.new([server])
        self.assertEqual(self.prompt(sid)["result"]["stopReason"], "end_turn")
        record = json.loads((self.root / "record").read_text())
        self.assertNotIn("--conversation", record["argv"])
        self.assertNotIn("--dangerously-skip-permissions", record["argv"])
        self.assertNotIn("private-value", " ".join(record["argv"]))
        self.assertIn("--add-dir", record["argv"])
        cfg = self.root / "state/workspaces" / sid / ".agents/mcp_config.json"
        self.assertFalse(cfg.exists())
        state = self.root / "state/sessions" / (sid + ".json")
        self.assertNotIn("private-value", state.read_text())
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.client.close()
        self.client = self.start()
        loaded = self.client.request("session/load", {"sessionId": sid, "cwd": str(self.root), "mcpServers": [server]})
        self.assertIn("result", loaded, loaded)
        self.assertTrue(any(e.get("params", {}).get("update", {}).get("sessionUpdate") == "user_message_chunk"
                            for e in self.client.events))
        self.assertEqual(self.prompt(sid, "second")["result"]["stopReason"], "end_turn")
        record = json.loads((self.root / "record").read_text())
        i = record["argv"].index("--conversation")
        self.assertEqual(record["argv"][i + 1], "conversation-test")

    def test_model_controls_and_reject_changes_unsupported_values(self):
        sid = self.new()
        result = self.client.request("session/set_model", {"sessionId": sid, "modelId": "unavailable"})
        self.assertIn("error", result)
        result = self.client.request("session/set_config_option", {"sessionId": sid, "configId": "effort", "value": "low"})
        self.assertIn("result", result)
        result = self.client.request("session/set_mode", {"sessionId": sid, "modeId": "plan"})
        self.assertIn("result", result)
        self.prompt(sid)
        argv = json.loads((self.root / "record").read_text())["argv"]
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")
        self.assertEqual(argv[argv.index("--effort") + 1], "low")

    def test_attachments_and_bad_parameters_fail_without_starting_backend(self):
        sid = self.new()
        response = self.client.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "image"}]})
        self.assertIn("error", response)
        response = self.client.request("session/new", {"cwd": "relative", "mcpServers": []})
        self.assertIn("error", response)
        self.assertFalse((self.root / "record").exists())

    def test_failure_and_timeout_mark_session_for_reset(self):
        for case in ("failure", "bad-json", "empty", "exit-failure", "missing-result", "timeout"):
            with self.subTest(case=case):
                self.client.close()
                self.env.update(FAKE_CASE=case, GOOSE_AGY_TIMEOUT="0.5")
                self.client = self.start()
                sid = self.new()
                response = self.prompt(sid)
                self.assertIn("error", response, response)
                self.assertIn("error", self.prompt(sid, "do not replay"))
                self.assertFalse((self.root / "state/workspaces" / sid / ".agents/mcp_config.json").exists())

    def test_cancel_and_eof_terminate_backend(self):
        self.client.close()
        self.env["FAKE_CASE"] = "timeout"
        self.client = self.start()
        sid = self.new()
        rid = self.client.send("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "wait"}]})
        import time
        for _ in range(100):
            if (self.root / "pid").exists():
                break
            time.sleep(0.02)
        self.assertTrue((self.root / "pid").exists())
        self.client.send("session/cancel", {"sessionId": sid}, notify=True)
        response = self.client.wait(rid)
        self.assertEqual(response["result"]["stopReason"], "cancelled")
        pid = int((self.root / "pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertIn("error", self.prompt(sid))

    def test_tool_only_and_streamed_only_turns_keep_session_usable(self):
        for case in ("tool-only", "streamed-only", "recovered"):
            with self.subTest(case=case):
                self.client.close()
                self.env["FAKE_CASE"] = case
                self.client = self.start()
                sid = self.new()
                self.assertEqual(self.prompt(sid)["result"]["stopReason"], "end_turn")
                state = json.loads((self.root / "state/sessions" / (sid + ".json")).read_text())
                self.assertEqual(state["history"][-1]["agent"], "" if case == "tool-only" else "héllo\nworld")
                self.assertFalse(state["broken"])
                self.assertEqual(self.prompt(sid, "follow up")["result"]["stopReason"], "end_turn")

    def test_unrestricted_tool_policy_applies_on_next_turn_and_preserves_plan_mode(self):
        sid = self.new()
        policy = self.root / "state/runtime.json"
        policy.write_text(json.dumps({"allowAllTools": True}))
        self.assertEqual(self.prompt(sid)["result"]["stopReason"], "end_turn")
        self.assertIn("--dangerously-skip-permissions", json.loads((self.root / "record").read_text())["argv"])
        policy.write_text(json.dumps({"allowAllTools": False}))
        self.assertEqual(self.prompt(sid)["result"]["stopReason"], "end_turn")
        self.assertNotIn("--dangerously-skip-permissions", json.loads((self.root / "record").read_text())["argv"])
        policy.write_text(json.dumps({"allowAllTools": True}))
        self.client.request("session/set_mode", {"sessionId": sid, "modeId": "plan"})
        self.assertIn("plan mode", self.prompt(sid)["error"]["message"])

    def test_success_with_denied_actions_reports_approval_instead_of_empty_response(self):
        for case in ("denied", "denied-with-text", "tool-error", "invalid-response"):
            with self.subTest(case=case):
                self.client.close()
                self.env["FAKE_CASE"] = case
                self.client = self.start()
                sid = self.new()
                response = self.prompt(sid)
                error = response["error"]["message"]
                self.assertIn("needs approval" if case.startswith("denied") else
                              "invalid response field" if case == "invalid-response" else "tool failed", error)
                self.assertNotIn("private tool details", error)
                self.assertIn("error", self.prompt(sid, "do not replay"))
                self.assertTrue(any(e.get("params", {}).get("update", {}).get("status") == "failed"
                                    for e in self.client.events) or case == "invalid-response")

    def test_session_load_is_scoped_to_owner_and_workspace(self):
        sid = self.new()
        self.client.close()
        self.env["BUZZ_PUBLIC_KEY"] = "another-identity"
        self.client = self.start()
        response = self.client.request("session/load", {"sessionId": sid, "cwd": str(self.root), "mcpServers": []})
        self.assertIn("error", response)
        response = self.client.request("session/load", {"sessionId": "../outside", "cwd": str(self.root)})
        self.assertIn("error", response)

    def test_stdio_http_conversion_and_reject_sse_wildcards_duplicates(self):
        result = mcp_config([{"type": "http", "name": "buzz", "url": "http://127.0.0.1/mcp",
                              "headers": [{"name": "Authorization", "value": "Bearer test"}]}])
        self.assertEqual(result["mcpServers"]["buzz"]["headers"]["Authorization"], "Bearer test")
        for servers in ([{"name": "*", "command": "test"}],
                        [{"name": "buzz", "type": "sse"}],
                        [{"name": "buzz", "command": "x"}, {"name": "buzz", "command": "y"}]):
            with self.assertRaises(Exception):
                mcp_config(servers)

    def test_invalid_permissions_do_not_leave_credentials_or_start_backend(self):
        self.client.close()
        self.env["HOME"] = str(self.root)
        settings = self.root / ".gemini/antigravity-cli/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"permissions": {"allow": "invalid"}}))
        self.client = self.start()
        sid = self.new([{"name": "buzz", "command": "test-server", "args": [],
                         "env": [{"name": "TOKEN", "value": "test-private"}]}])
        self.assertIn("error", self.prompt(sid))
        self.assertFalse((self.root / "record").exists())
        self.assertFalse(list((self.root / "state").rglob("mcp_config.json")))
        settings.write_text(json.dumps({"permissions": {"allow": []}}))
        self.assertEqual(self.prompt(sid)["result"]["stopReason"], "end_turn")

    def test_stale_loaded_session_cannot_overwrite_another_process_turn(self):
        sid = self.new()
        other = self.start()
        try:
            loaded = other.request("session/load", {"sessionId": sid, "cwd": str(self.root), "mcpServers": []})
            self.assertIn("result", loaded)
            self.assertEqual(self.prompt(sid)["result"]["stopReason"], "end_turn")
            stale = other.request("session/prompt", {"sessionId": sid,
                "prompt": [{"type": "text", "text": "stale turn"}]})
            self.assertIn("error", stale)
            saved = json.loads((self.root / "state/sessions" / (sid + ".json")).read_text())
            self.assertEqual(saved["conversation"], "conversation-test")
            self.assertFalse(saved["broken"])
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
