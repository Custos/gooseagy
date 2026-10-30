import importlib.util
import json
import os
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallBuzzTests(unittest.TestCase):
    def test_registration_is_idempotent_for_existing_buzz_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / "bin"
            bindir.mkdir()
            app = root / "Buzz.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "xyz.block.buzz.desktop"}))
            with patch.object(installer.shutil, "which", return_value="/some/agy"), patch.dict(os.environ, {"GOOSE_AGY_STATE_DIR": str(root / "state")}):
                installer.install_buzz(ROOT, bindir, app, root / "missing-manager")

                installer.install_buzz(ROOT, bindir, app, root / "missing-manager", True)
                policy = root / "state/runtime.json"
                self.assertEqual(json.loads(policy.read_text()), {"allowAllTools": True})
                installer.install_buzz(ROOT, bindir, app, root / "missing-manager")
                self.assertTrue(json.loads(policy.read_text())["allowAllTools"])
                installer.install_buzz(ROOT, bindir, app, root / "missing-manager", False)
                self.assertFalse(json.loads(policy.read_text())["allowAllTools"])
                path = root / "state/installation.json"
                config = json.loads(path.read_text())
                self.assertEqual(config["pluginId"], "local.gooseagy")
                self.assertEqual(config["launcherPath"], str(bindir / "agy-acp"))
                self.assertNotIn("BUZZ_PRIVATE_KEY", path.read_text())
                installer.install_buzz(ROOT, bindir, app, root / "missing-manager")

    def test_refuses_unrelated_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agy-acp").write_text("user-owned-command")
            app = root / "Buzz.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "xyz.block.buzz.desktop"}))
            with patch.object(installer.shutil, "which", return_value="/some/agy"):
                with self.assertRaises(ValueError):
                    installer.install_buzz(ROOT, root, app)
            self.assertEqual((root / "agy-acp").read_text(), "user-owned-command")



if __name__ == "__main__":
    unittest.main()
