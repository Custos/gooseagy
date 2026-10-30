# Buzz setup

Use the official [block/buzz-app](https://github.com/block/buzz-app) desktop app.
The tested macOS version is **0.7.0-preview.215.1**, bundle ID
`xyz.block.buzz.desktop`. The older `block/buzz` app uses a different harness
mechanism and is not supported by this plugin. No app bundle is modified.

## Install

1. Install Python 3.11+ and the official authenticated `agy` CLI. Verify
   `python3 --version`, launch `agy` to sign in if needed, then exit it.
2. Put this repository in a permanent directory. From that directory run:

   ```sh
   python3 install.py --buzz
   ```

   For a different Buzz location, add `--buzz-app /path/to/Buzz.app`.
   The installer creates `~/.local/bin/goose-agy` and a Python-pinned
   `~/.local/bin/agy-acp`. Include `~/.local/bin` on your Terminal `PATH`.
   Buzz's tested native host searches that directory when launched from Finder.
3. In Buzz, use **Settings → Plugins → Add**. In **Add from folder**, choose
   **Browse**, select **buzz-plugin/dist** in this checkout, review the declared
   access, click **Install plugin**, and enable **Antigravity Ultra**.
4. Run:

   ```sh
   goose-agy doctor --refresh-models
   agy models
   ```

   The doctor checks the default profile, app signature, executable and installed
   artifact. Its contents must match this checkout. Refreshing the model cache
   queries your account; it does not run a model turn.

If you already have the official compatible `buzzodz` CLI at
`~/.local/share/gooseagy/bin/buzzodz`, the installer uses it to import and enable
the plugin in the default profile. Otherwise use the UI; no CLI build is required.
An optional `--plugin-manager /path/to/buzzodz` selects another compatible CLI.
For non-default profiles use the plugin import UI. The current doctor checks
only the default profile.

## Configure an agent

Go to **Agents** and either create an agent or change an existing agent's
**Harness** to **Antigravity (Ultra)**. Fill in:

| Setting | Value |
| --- | --- |
| Model | An exact ID listed by `agy models`; the tested default is `gemini-4-argon-high` |
| Reasoning effort | `low`, `medium`, `high`, `xhigh`, or `max`, if the model supports it; default `high` |
| Working directory | An existing project directory, or the default `~/.buzz` |
| Agent instructions | Your normal instructions; may be empty |

Mention that agent in a conversation or open its Solo chat. A first check:

> Reply here with exactly ULTRA_READY using Buzz's send tool. Do not use other tools.

The harness uses the account signed in to the official `agy` CLI. It forces the
subscription provider and removes Gemini API-key environment variables from the
backend process. There is no API-key or Goose-provider field for this harness.
Account/model availability and Google quota still apply.

If a model is rejected, refresh the model cache and check its ID. If the new
harness does not appear, reopen Settings; when no agents are working, quit and
reopen your same Buzz installation if needed.

## Tool permissions

New installations keep native approval rules. Only the session's app-supplied
MCP tools are added to the native allow list; existing ask/deny rules remain.
Interactive approvals are not bridged into Buzz. To explicitly bypass native
approval prompts for all agents using this adapter on this Mac:

```sh
python3 install.py --buzz --buzz-allow-all-tools
```

This invokes `agy --dangerously-skip-permissions`, allowing commands and file
changes with your user account's access. To restore approval rules:

```sh
python3 install.py --buzz --buzz-require-approvals
```

The setting is stored privately in `~/.local/state/gooseagy/runtime.json`, persists
across reinstalls and applies on the next turn. Plan mode refuses unrestricted
tools. `GOOSE_AGY_ALLOW_ALL=0` or `1`, if provided to the ACP worker's environment,
overrides the saved choice; GUI apps do not automatically inherit Terminal exports.

## Troubleshoot a missing reply

- Run `goose-agy doctor`. A successful install check does not prove a model turn
  has finished. Live calls may take minutes; check the agent's activity before
  sending the same task again.
- Make sure the mention targets an agent whose harness is **Antigravity (Ultra)**,
  and that it is active on this device. A plain model text response does not
  publish itself: the agent uses Buzz's send tool to reply to a conversation.
- **Antigravity needs approval for a tool action** means the CLI denied an
  interactive permission request. Review the action in `agy` and allow a specific
  rule, or explicitly opt into unrestricted tools as above. Use **New session**
  before retrying a failed turn.
- An empty free-text result is accepted after completed tools, including a Buzz
  send. `SUCCESS` with `denied_actions` is reported as an approval failure.
  A truly empty result with no completed tool remains an error.
- **Previous turn failed or was interrupted** requires **New session**. The
  adapter does not automatically repeat actions with uncertain outcomes.
- **Compact** is unsupported. Antigravity handles its own context; use
  **New session** to reset. Attachments are unsupported.

## Verification and updates

```sh
goose-agy doctor
goose-agy doctor --live
```

The live check consumes subscription quota and exercises the installed ACP
launcher with the distributed plugin, HTTP MCP and two successive replies in a
local test host. No real community messages are published. It does not automate
or visually inspect Buzz's UI. Test your own real-app conversation separately.

Keep updating Buzz through its normal updater and `agy` through its normal
update mechanism. External plugin registrations live in the profile. A future
API change may require an adapter update; this project does not promise forward
compatibility with untested versions.

To update this repository, pull/download its new version, then run
`python3 install.py --buzz` and update the plugin from its source folder in Buzz.
Buzz imports a snapshot, so replacing source files or rebuilding alone does not
update the installed plugin. An available compatible plugin-manager CLI performs
the import automatically. Keep the checkout at the installed path; if you move
it, rerun the installer from the new directory.

The ACP backend supports session load, but Buzz's reused runtime opens a fresh
backend session with visible conversation history after restarting the app.
Private unsent tool results or backend reasoning are not fully restored.

## Disable or remove

Disable **Antigravity Ultra** in **Settings → Plugins** and wait for its work to
stop. You may then remove the installed `~/.local/bin/agy-acp` launcher and
`~/.local/bin/goose-agy` symlink. Retain `~/.local/state/gooseagy` until you no
longer need its saved conversation records. Do not remove a command you replaced
with an unrelated installation. Authentication remains owned by `agy`.
