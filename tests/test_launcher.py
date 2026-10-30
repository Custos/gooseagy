import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fake_goose = self.root / "goose"
        self.fake_goose.write_text(
            f"#!{sys.executable}\nimport json,os,sys\n"
            "print(json.dumps({'args':sys.argv[1:],'env':{k:v for k,v in os.environ.items() "
            "if k in ('GOOSE_PROVIDER','GOOSE_MODEL','GEMINI_CLI_COMMAND')}}))\n"
        )
        self.fake_goose.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GOOSE_AGY_")}
        self.env.update(GOOSE_AGY_GOOSE_COMMAND=str(self.fake_goose))

    def launch(self, *args, entry=None):
        return subprocess.run([sys.executable, str(entry or ROOT / "bin/goose-agy"), *args],
                              capture_output=True, text=True, env=self.env, timeout=5)

    def test_default_session_and_provider_override_are_scoped_to_process(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["args"], ["session", "--no-profile"])
        self.assertEqual(data["env"], {
            "GOOSE_PROVIDER": "gemini-cli", "GOOSE_MODEL": "current",
            "GEMINI_CLI_COMMAND": str(ROOT / "adapter.py"),
        })

    def test_model_and_prompt_pass_through_without_interpretation(self):
        self.env["GOOSE_AGY_MODEL"] = "selected-model"
        result = self.launch("run", "-t", "--resume", "--model", "another-model", "-q")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["env"]["GOOSE_MODEL"], "selected-model")
        self.assertEqual(data["args"], ["run", "--no-profile", "-t", "--resume",
                                         "--model", "another-model", "-q"])

    def test_unsupported_extensions_resume_and_provider_cannot_be_silent(self):
        for flag in ("--with-builtin=developer", "--with-extension", "--resume", "-r",
                     "-qr", "--fork", "--provider=openai", "--session-id", "--path",
                     "--recipe=file.yaml", "--sub-recipe", "--params", "--container"):
            with self.subTest(flag=flag):
                result = self.launch("run", flag)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("goose-agy:", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_installer_is_idempotent_and_symlink_resolves_adapter(self):
        bindir = self.root / "bin"
        for _ in range(2):
            result = subprocess.run([sys.executable, str(ROOT / "install.py"),
                                     "--bin-dir", str(bindir)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        entry = bindir / "goose-agy"
        result = self.launch(entry=entry)
        self.assertEqual(json.loads(result.stdout)["env"]["GEMINI_CLI_COMMAND"], str(ROOT / "adapter.py"))

    def test_installer_refuses_to_replace_an_existing_command(self):
        (self.root / "goose-agy").write_text("user-owned command")
        result = subprocess.run([sys.executable, str(ROOT / "install.py"),
                                 "--bin-dir", str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "goose-agy").read_text(), "user-owned command")


if __name__ == "__main__":
    unittest.main()
