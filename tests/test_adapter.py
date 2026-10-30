import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("adapter", ROOT / "adapter.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.record = self.root / "record.json"
        self.pid_file = self.root / "child.pid"
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GOOSE_AGY_", "FAKE_")) and k != "GOOSE_MODE"}
        self.env.update(GOOSE_AGY_COMMAND=str(ROOT / "tests/fake_agy.py"),
                        FAKE_RECORD=str(self.record), FAKE_PID=str(self.pid_file))

    def run_adapter(self, case="success", args=(), prompt="prompt with ünicode\nand lines", env=None):
        config = dict(self.env, FAKE_CASE=case)
        config.update(env or {})
        result = subprocess.run(
            [sys.executable, str(ROOT / "adapter.py"), *args], input=prompt,
            text=True, capture_output=True, env=config, cwd=self.root, timeout=12,
        )
        events = [json.loads(line) for line in result.stdout.splitlines()]
        return result, events

    def assert_failure(self, case, detail, **kwargs):
        result, events = self.run_adapter(case=case, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn(detail, events[-1]["error"])
        self.assertFalse(any(e["type"] == "result" for e in events))

    def test_streaming_translates_text_session_usage_and_keeps_prompt_off_argv(self):
        result, events = self.run_adapter(args=["-m", "current", "--yolo"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events[0], {"type": "init", "session_id": "conversation-test"})
        text = "".join(e["content"] for e in events if e["type"] == "message")
        self.assertEqual(text, "héllo\nworld")
        self.assertEqual(events[-1]["stats"], {
            "input_tokens": 20, "output_tokens": 4, "total_tokens": 24,
            "cache_read_input_tokens": 10,
        })
        record = json.loads(self.record.read_text())
        self.assertEqual(record["request"]["message"]["content"], "prompt with ünicode\nand lines")
        self.assertNotIn("prompt with", " ".join(record["argv"]))
        self.assertNotIn("--model", record["argv"])
        self.assertNotIn("--dangerously-skip-permissions", record["argv"])
        self.assertTrue(record["eof"])
        self.assertEqual(Path(record["cwd"]).resolve(), self.root.resolve())

    def test_resume_passes_exact_conversation_id_and_explicit_model(self):
        result, events = self.run_adapter(args=["-r", "previous-id", "-m", "account-model"])
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(self.record.read_text())["argv"]
        self.assertEqual(argv[argv.index("--conversation") + 1], "previous-id")
        self.assertEqual(argv[argv.index("--model") + 1], "account-model")
        self.assertEqual(events[0]["session_id"], "previous-id")

    def test_final_response_fallback_is_emitted_once(self):
        result, events = self.run_adapter("result-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([e["content"] for e in events if e["type"] == "message"], ["héllo\nworld"])

    def test_final_only_answer_after_intermediate_commentary_is_not_lost(self):
        for streamed, final, suffix in (("Thinking…", "Finished.", "\nFinished."),
                                         ("Progress\nFin", "Finished.", "ished."),
                                         ("Progress\nFinished.", "Finished.", "")):
            with self.subTest(streamed=streamed):
                out = io.StringIO()
                translator = adapter.Translator()
                translator.text = streamed
                translator.result = {"response": final}
                with contextlib.redirect_stdout(out):
                    translator.finish()
                events = [json.loads(line) for line in out.getvalue().splitlines()]
                self.assertEqual("".join(e["content"] for e in events if e["type"] == "message"), suffix)

    def test_failures_do_not_emit_success_or_retry(self):
        for case, detail in (("failure", "quota exhausted"), ("nonterminal", "WAITING"),
                             ("bad-json", "invalid JSON"), ("scalar", "non-object"),
                             ("missing-result", "without a final result"),
                             ("empty", "without a reply"), ("exit-failure", "code 7")):
            with self.subTest(case=case):
                self.assert_failure(case, detail)

    def test_tool_only_and_streamed_only_success_and_permission_denial(self):
        for case in ("tool-only", "streamed-only", "recovered"):
            with self.subTest(case=case):
                result, events = self.run_adapter(case)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events[-1]["status"], "success")
                text = "".join(e["content"] for e in events if e["type"] == "message")
                self.assertEqual(text, "" if case == "tool-only" else "héllo\nworld")
        for case in ("denied", "denied-with-text"):
            self.assert_failure(case, "needs approval")
        self.assert_failure("tool-error", "tool failed")
        self.assert_failure("invalid-response", "invalid response field")

    def test_conversation_cannot_silently_change(self):
        self.assert_failure("wrong-id", "changed the conversation ID", args=["-r", "previous"])

    def test_timeout_stops_backend_even_if_it_ignores_sigterm(self):
        for case in ("timeout", "stubborn"):
            with self.subTest(case=case):
                self.assert_failure(case, "timed out", env={"GOOSE_AGY_TIMEOUT": "0.5"})
                pid = int(self.pid_file.read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_large_stderr_cannot_block_response(self):
        result, events = self.run_adapter("slow-stderr")
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertEqual(events[-1]["type"], "result")

    def test_missing_cli_and_empty_input_are_clear_errors(self):
        self.assert_failure("success", "Cannot find", env={"GOOSE_AGY_COMMAND": "/missing/agy"})
        self.assert_failure("success", "nonempty", prompt="")

    def test_invalid_settings_fail_before_launch(self):
        for settings in ({"GOOSE_AGY_TIMEOUT": "nan"}, {"GOOSE_AGY_TIMEOUT": "0"},
                         {"GOOSE_AGY_EFFORT": "invalid"}, {"GOOSE_AGY_MODE": "invalid"},
                         {"GOOSE_AGY_ALLOW_ALL": "yes"},
                         {"GOOSE_AGY_ALLOW_ALL": "1", "GOOSE_AGY_MODE": "plan"}):
            with self.subTest(settings=settings):
                result, events = self.run_adapter(env=settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events[-1]["type"], "error")
                self.assertFalse(self.record.exists())

    def test_permissions_are_explicit_and_chat_uses_plan(self):
        args = adapter.parse_args(["--yolo"])
        for env in ({}, {"GOOSE_MODE": "auto"}, {"GOOSE_MODE": "approve"}):
            self.assertNotIn("--dangerously-skip-permissions", adapter.command(args, env))
        cmd = adapter.command(args, {"GOOSE_MODE": "chat"})
        self.assertEqual(cmd[cmd.index("--mode") + 1], "plan")
        self.assertIn("--dangerously-skip-permissions",
                      adapter.command(args, {"GOOSE_AGY_ALLOW_ALL": "1"}))

    def test_sigterm_stops_backend(self):
        env = dict(self.env, FAKE_CASE="timeout")
        proc = subprocess.Popen([sys.executable, str(ROOT / "adapter.py")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, text=True)
        try:
            proc.stdin.write("test")
            proc.stdin.close()
            for _ in range(100):
                if self.pid_file.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(self.pid_file.exists())
            pid = int(self.pid_file.read_text())
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=6)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_parent_death_stops_orphaned_backend(self):
        # Kill the adapter's parent without giving it a chance to send a signal.
        code = (
            "import subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,sys.argv[1]],stdin=subprocess.PIPE); "
            "p.stdin.write(b'test'); p.stdin.close(); time.sleep(60)"
        )
        proc = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "adapter.py")],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(self.env, FAKE_CASE="timeout"))
        try:
            for _ in range(100):
                if self.pid_file.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(self.pid_file.exists())
            pid = int(self.pid_file.read_text())
            proc.kill()
            proc.communicate(timeout=6)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


if __name__ == "__main__":
    unittest.main()
