# Contributing

Runtime Python code uses the standard library only. Use Python 3.11+ on a POSIX
system and Node 22+ for development. Live checks require your own authenticated
`agy` account and consume quota. Do not put credentials, conversations, app
profile snapshots or machine-specific installation notes in this repository.

## Offline checks

From the repository root:

```sh
python3 -m unittest discover -s tests -v
node tests/plugin_contract.mjs
```

The plugin contract test starts the ACP worker directly from this checkout with
a fake backend. No installed Buzz, Goose, global launcher or account is required.
`PYTHON` selects the Python executable for that check. `GOOSE_AGY_TEST_WORKER`
can explicitly select an installed ACP launcher instead.

## Rebuild the plugin

The plugin reuses Apache-2.0 code from `block/buzz-app`, pinned at
`1c0f6d68ae11d834f6ac8a9287b3b983cc967275`.

```sh
git clone https://github.com/block/buzz-app.git /tmp/gooseagy-buzz-app-source
git -C /tmp/gooseagy-buzz-app-source checkout 1c0f6d68ae11d834f6ac8a9287b3b983cc967275
npm ci --prefix scripts
node scripts/build-plugin.mjs /tmp/gooseagy-buzz-app-source
node tests/plugin_contract.mjs
```

Skip the clone when that directory already exists. The build rejects a different
upstream revision or tracked source modifications. Commit the rebuilt
`buzz-plugin/dist` files with relevant source changes. Source comments are
normalized so the bundle does not depend on the upstream checkout's location.
Retain `buzz-plugin/LICENSE`, `NOTICE.md` and `UPSTREAM_NOTICE.md` and dependency
license notices when rebuilding. Runtime users import the committed artifact.

CI runs offline tests on macOS and Linux and checks that a clean pinned upstream
build reproduces the committed plugin. Test results do not certify compatibility
with untested native app versions.

## Live checks

```sh
python3 tests/live_buzz_smoke.py
goose-agy doctor --live
```

These exercise real Antigravity with local MCP endpoints; they do not publish
messages to real communities. The second command additionally needs the existing
Buzz installation and enabled plugin in its default profile. Do not run live
checks in CI with personal account credentials.

## Review and releases

Include the trigger, expected behavior and relevant validation in changes.
For protocol changes, cover real regressions: cancellation, uncertain turns,
conversation continuity, credential cleanup and tool-only responses.
Avoid automatic retries of actions whose outcome is unknown.

Before a release, run offline checks, rebuild from the pinned upstream source,
scan the tracked source for secrets and machine-specific paths, and update
`docs/REVIEW.md` and `CHANGELOG.md`. Publish a source archive that includes the
ready-to-import plugin, plus SHA-256 checksums. Never package local state,
`node_modules`, login data or a Buzz app bundle.
