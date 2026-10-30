import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from doctor import verify_plugin


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "dist"
        self.source.mkdir()
        self.manifest = {"id": "local.gooseagy", "apiVersion": 1,
                         "host": {"processes": [{"id": "agent", "program": "agy-acp"}]}}
        (self.source / "manifest.json").write_text(json.dumps(self.manifest))
        (self.source / "plugin.js").write_text("export function apply() {}\n")
        native = json.loads(json.dumps(self.manifest))
        native["host"].update(commands=[], networkOrigins=[])
        native["host"]["processes"][0]["args"] = []
        data = json.dumps({"manifest": native, "code": (self.source / "plugin.js").read_text()}).encode()
        self.revision = hashlib.sha256(data).hexdigest()
        self.artifact = self.root / "artifacts/local.gooseagy" / (self.revision + ".json")
        self.artifact.parent.mkdir(parents=True)
        self.artifact.write_bytes(data)
        self.registry = self.root / "registry.json"
        self.registry.write_text(json.dumps({"installed": {"local.gooseagy": {
            "current": self.revision, "enabled": True}}}))

    def test_native_snapshot_matches_then_detects_stale_build(self):
        verify_plugin(self.registry, self.source)
        (self.source / "plugin.js").write_text("export function apply() { return 1; }\n")
        with self.assertRaisesRegex(ValueError, "differs from this checkout"):
            verify_plugin(self.registry, self.source)

    def test_tampered_snapshot_is_rejected(self):
        self.artifact.write_bytes(self.artifact.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "content hash"):
            verify_plugin(self.registry, self.source)

    def test_disabled_or_invalid_revision_is_rejected(self):
        for record, message in (({"enabled": False}, "Enable Antigravity"),
                                ({"enabled": True, "current": "../outside"}, "Invalid installed")):
            self.registry.write_text(json.dumps({"installed": {"local.gooseagy": record}}))
            with self.assertRaisesRegex(ValueError, message):
                verify_plugin(self.registry, self.source)
