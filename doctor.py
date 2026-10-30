#!/usr/bin/env python3
"""Check the installed released-app integration without touching identities."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

from acp_server import RpcError, allow_all_tools, private_dir, state_root, write_private


def canonical_manifest(manifest):
    result = json.loads(json.dumps(manifest))
    # Buzz serializes omitted default capability lists into its native snapshot.
    # Compare their meanings while retaining checks for additional capabilities.
    host = result.setdefault("host", {})
    for key in ("commands", "networkOrigins", "processes"):
        host.setdefault(key, [])
    for process in host["processes"]:
        process.setdefault("args", [])
    return result


def verify_plugin(registry_path, source):
    record = json.loads(registry_path.read_text()).get("installed", {}).get("local.gooseagy")
    if not record or not record.get("enabled"):
        raise ValueError("Enable Antigravity Ultra in Settings → Plugins → Manage plugins")
    revision = record.get("current", "")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        raise ValueError("Invalid installed plugin revision")
    artifact = registry_path.parent / "artifacts/local.gooseagy" / (revision + ".json")
    data = artifact.read_bytes()
    if hashlib.sha256(data).hexdigest() != revision:
        raise ValueError("Installed plugin artifact failed its content hash check")
    installed = json.loads(data)
    if (installed.get("code") != (source / "plugin.js").read_text() or
            canonical_manifest(installed.get("manifest", {})) !=
            canonical_manifest(json.loads((source / "manifest.json").read_text()))):
        raise ValueError("Installed plugin differs from this checkout; update Antigravity Ultra in Buzz or rerun install.py --buzz")


def refresh_models():
    agy = os.environ.get("GOOSE_AGY_COMMAND") or shutil.which("agy")
    if not agy:
        raise ValueError("agy is not installed")
    result = subprocess.run([agy, "models"], text=True, capture_output=True, timeout=45)
    if result.returncode:
        raise ValueError("agy models failed; open agy and check your Google account login")
    models = []
    for line in result.stdout.splitlines():
        if "\t" in line:
            key, name = line.split("\t", 1)
            models.append({"modelId": key.strip(), "name": name.strip()})
    if not models:
        raise ValueError("agy returned no parseable models")
    root = private_dir(state_root())
    write_private(root / "models.json", models)
    print(f"PASS: {len(models)} available models cached from your Antigravity account")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-models", action="store_true")
    parser.add_argument("--live", action="store_true", help="Use subscription quota to test the built plugin, ACP, and local HTTP MCP; no community messages")
    parser.add_argument("--buzz-app", type=Path, help="Override the registered app location")
    args = parser.parse_args(argv)
    try:
        print("Python:", sys.version.split()[0])
        agy = os.environ.get("GOOSE_AGY_COMMAND") or shutil.which("agy")
        if not agy:
            raise ValueError("agy executable is missing")
        print("Antigravity executable:", agy)
        manifest_file = state_root() / "installation.json"
        if not manifest_file.exists():
            raise ValueError("No registered Buzz integration; run python3 install.py --buzz")
        manifest = json.loads(manifest_file.read_text())
        app = args.buzz_app or Path(manifest["buzzApp"])
        p = app / "Contents/Info.plist"
        if not p.exists():
            raise ValueError(f"Buzz app not found at {app}")
        info = plistlib.loads(p.read_bytes())
        print("Buzz:", info.get("CFBundleShortVersionString"), "bundle:", info.get("CFBundleIdentifier"))
        verified = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True)
        if verified.returncode:
            raise ValueError("Buzz app code signature verification failed")
        print("PASS: Buzz app code signature is intact")
        if info.get("CFBundleIdentifier") != "xyz.block.buzz.desktop":
            raise ValueError("Registered app is not the existing block/buzz-app installation")
        registry = Path.home() / "Library/Application Support/xyz.block.buzz.desktop/profiles/default/registry.json"
        if not registry.exists():
            raise ValueError("Buzz plugin registry is missing; open your normal Buzz app")
        verify_plugin(registry, Path(manifest["pluginSource"]))
        print("PASS: installed plugin hash and contents match this checkout")
        command = manifest["launcherPath"]
        check = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5)
        if check.returncode:
            raise ValueError("ACP launcher failed its version check")
        print("PASS: Antigravity Ultra plugin installed and enabled; adapter", check.stdout.strip())
        print("Plugin source:", manifest["pluginSource"])
        print("Tool permissions:", "unrestricted (--dangerously-skip-permissions)" if allow_all_tools() else "Antigravity approval rules")
        manager = Path.home() / ".local/share/gooseagy/bin/buzzodz"
        if manager.exists():
            listing = subprocess.run([str(manager), "plugin", "list"], text=True, capture_output=True, timeout=10)
            if listing.returncode or not any("local.gooseagy" in line and "enabled" in line for line in listing.stdout.splitlines()):
                raise ValueError("Native plugin manager could not validate the enabled artifact")
            print("PASS: native Buzz plugin manager validates the installed artifact")
        if args.refresh_models:
            refresh_models()
        if args.live:
            result = subprocess.run(["node", str(Path(__file__).parent / "tests/plugin_contract.mjs"), "--live"],
                                    env={**os.environ, "GOOSE_AGY_TEST_WORKER": command, "PYTHON": sys.executable})
            if result.returncode:
                raise ValueError("Live ACP/MCP test failed")
    except (RpcError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("FAIL:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
