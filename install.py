#!/usr/bin/env python3
"""Install the CLI launcher and the plugin for your existing Buzz app."""

import argparse
import json
import plistlib
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import subprocess

MARKER = "# gooseagy managed ACP launcher"


def install_buzz(root, bindir, app=None, manager=None, allow_all_tools=None):
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11 or newer is required")
    if not shutil.which("agy"):
        raise ValueError("Install and sign in to agy first")
    app = app or Path("/Applications/Buzz.app")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != "xyz.block.buzz.desktop":
        raise ValueError("This integration targets the current block/buzz-app app")
    artifact = root / "buzz-plugin/dist"
    for name in ("manifest.json", "plugin.js"):
        if not (artifact / name).is_file():
            raise ValueError(f"Built plugin is missing {name}")
    launcher = bindir / "agy-acp"
    if launcher.exists() or launcher.is_symlink():
        if launcher.is_symlink() or MARKER not in launcher.read_text():
            raise ValueError(f"{launcher} exists and is not owned by this installer")
    import os
    script = ("#!/bin/sh\n" + MARKER + "\nexec " + shlex.quote(sys.executable) + " "
              + shlex.quote(str(root / "acp_server.py")) + ' "$@"\n')
    fd, temp = tempfile.mkstemp(dir=bindir)
    try:
        with os.fdopen(fd, "w") as out:
            out.write(script)
        Path(temp).chmod(0o755)
        os.replace(temp, launcher)
    finally:
        Path(temp).unlink(missing_ok=True)
    from acp_server import private_dir, state_root, write_private
    state = private_dir(state_root())
    if allow_all_tools is not None:
        write_private(state / "runtime.json", {"allowAllTools": allow_all_tools})
    write_private(state / "installation.json", {
        "buzzApp": str(app.resolve()), "pluginId": "local.gooseagy",
        "pluginSource": str(artifact), "launcherPath": str(launcher),
    })
    manager = manager or Path.home() / ".local/share/gooseagy/bin/buzzodz"
    if manager.is_file():
        for action, value in (("install", str(artifact)), ("enable", "local.gooseagy")):
            subprocess.run([str(manager), "plugin", action, value], check=True)
    else:
        print(f"In Buzz: Settings → Plugins → Add → Browse → {artifact}")
        print("Install Antigravity Ultra, then enable it in Manage plugins.")
    print(f"ACP executable: {launcher}")
    print(f"Current Buzz app: {app}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--buzz", action="store_true", help="Install the plugin for your existing Buzz app")
    parser.add_argument("--buzz-app", type=Path, default=Path("/Applications/Buzz.app"))
    parser.add_argument("--plugin-manager", type=Path, help="Optional official buzzodz CLI used to install and enable the plugin")
    permissions = parser.add_mutually_exclusive_group()
    permissions.add_argument("--buzz-allow-all-tools", dest="allow_all_tools", action="store_const", const=True,
                             help="Use agy --dangerously-skip-permissions for all agents using this adapter")
    permissions.add_argument("--buzz-require-approvals", dest="allow_all_tools", action="store_const", const=False,
                             help="Restore Antigravity's normal approval policy for this adapter")
    args = parser.parse_args()
    if args.allow_all_tools is not None and not args.buzz:
        parser.error("Buzz permission options require --buzz")
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    root = Path(__file__).resolve().parent
    for script in (root / "adapter.py", root / "bin/goose-agy"):
        script.chmod(script.stat().st_mode | 0o111)
    args.bin_dir.mkdir(parents=True, exist_ok=True)
    dest = args.bin_dir / "goose-agy"
    source = root / "bin/goose-agy"
    if dest.is_symlink() and dest.resolve() == source:
        print(f"Already installed: {dest}")
    elif dest.exists() or dest.is_symlink():
        parser.error(f"{dest} already exists; refusing to replace it")
    else:
        dest.symlink_to(source)
        print(f"Installed: {dest}")
    try:
        if args.buzz:
            app = args.buzz_app.expanduser().resolve()
            install_buzz(root, args.bin_dir.resolve(), app, args.plugin_manager, args.allow_all_tools)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
