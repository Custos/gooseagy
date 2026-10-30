# Terminal Goose setup

Run the commands below from the repository root.

Use your existing Antigravity (`agy`) login and Google AI Ultra subscription
from the Goose CLI. No API key, HTTP server, or third-party Python package is
required. The adapter invokes the official `agy` executable; it does not read
OAuth tokens or call Google's private endpoints.

## Install and run

Requirements: Python 3.11+, Goose, and an authenticated Antigravity CLI.

```sh
# Sign in with the Google account that has your Ultra subscription, if needed.
agy

# From this repository:
python3 install.py

goose-agy
goose-agy run -t 'Explain this repository'
goose-agy run --model gemini-4-argon-high -t 'Review this code'
```

The installer links `~/.local/bin/goose-agy` to this checkout. Keep the checkout
in place and include `~/.local/bin` on your `PATH`. You can also run
`./bin/goose-agy` directly, or install elsewhere with `--bin-dir /your/bin`.
It refuses to overwrite an existing unrelated command.

`goose-agy` sets the provider only for the launched process. Your normal `goose`
command and saved Goose configuration are unchanged. It starts in your current
directory, so run it from the project you want Antigravity to work on.

The default model is `current`, meaning the model already selected in `agy`.
Use `agy models` to list models available to your account. Model slugs are sent
through exactly; unavailable models cause an error rather than a fallback.
`gemini-4-argon-high` was available on the account used for validation.

## Configuration

```sh
GOOSE_AGY_MODEL=gemini-4-argon-high GOOSE_AGY_EFFORT=high goose-agy
GOOSE_AGY_MODE=plan goose-agy run -t 'Inspect this project and suggest improvements'
GOOSE_AGY_TIMEOUT=1200 goose-agy run -t 'Review this large repository'
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOSE_AGY_MODEL` | `current` | Antigravity model; Goose's `--model` takes precedence |
| `GOOSE_AGY_EFFORT` | Antigravity setting | `low`, `medium`, `high`, `xhigh`, or `max`; backend checks model support |
| `GOOSE_AGY_MODE` | Antigravity setting | `plan`, `accept-edits`, or `auto` |
| `GOOSE_AGY_TIMEOUT` | `600` | Positive wall-clock timeout in seconds per turn |
| `GOOSE_AGY_COMMAND` | `agy` | Executable path; a single program, not a shell command |
| `GOOSE_AGY_GOOSE_COMMAND` | `goose` on `PATH` | Alternative Goose executable |
| `GOOSE_AGY_ALLOW_ALL` | `0` | Set to `1` to explicitly pass `--dangerously-skip-permissions` |

The adapter preserves Antigravity's permission settings. In headless mode,
operations needing interactive approval are denied by Antigravity unless
allowed in its settings. Goose approval prompts are not connected to Antigravity.
Goose's `GOOSE_MODE=chat` requests Antigravity `plan` mode unless
`GOOSE_AGY_MODE` is explicitly set. Goose's `auto` mode and the `--yolo` argument
that its CLI provider always sends do **not** enable a permission bypass.
`GOOSE_AGY_ALLOW_ALL=1` cannot be combined with plan/chat mode.

Authenticate `agy` with your personal subscription account. If you previously
configured `agy` to use a Gemini API key or a Cloud account, change its
authentication back to the subscription account first; the adapter uses the
authentication selected by the official CLI.

## How it works and limits

```text
Goose's gemini-cli provider
  → adapter.py (prompt on stdin, model, conversation ID)
  → official agy CLI (streaming JSON, existing login)
  → translated init / assistant text / usage / errors back to Goose
```

Goose 1.57.0 still ships the deprecated `gemini-cli` transport with a configurable
`GEMINI_CLI_COMMAND`. We use that transport, replacing the executable with this
adapter. Gemini CLI itself is not invoked. No Goose rebuild is needed.

- Antigravity runs its own tools and manages context. This is an agent
  integration, not a raw model API or an OpenAI-compatible HTTP endpoint.
- Follow-up messages in the **same running Goose session** resume the exact
  Antigravity conversation returned on the first turn.
- Restarting/resuming/forking old **Goose** sessions is unsupported: Goose's
  transport does not persist the Antigravity conversation mapping. The launcher
  refuses resume/fork flags to prevent silent context loss. The conversation
  remains accessible through Antigravity's own history.
- Goose MCP extensions and builtins do not pass through. The launcher disables
  profile extensions and refuses explicit extension flags. Configure needed MCP
  servers in `agy` itself. Its existing tools and plugins remain available.
- Text prompts and assistant text are supported. Antigravity tool progress and
  reasoning events are not shown as Goose tool cards. Attachments are unsupported.
- Use `session` or `run`; Goose management commands still use normal `goose`.
  Recipe-driven provider/model/extension overrides are not supported by this
  launcher; use plain prompts or instruction files.
- Backend errors, quota failures, malformed output, changed conversation IDs,
  and missing results fail visibly. There are no automatic retries or model
  substitutions. Partial streamed output can precede a backend failure.
- Canceling Goose or exceeding the timeout stops the running `agy` process.
  On POSIX, the adapter also watches for its Goose parent exiting unexpectedly.
- Compatibility depends on Goose retaining this deprecated transport. Upgrade
  Goose or `agy` deliberately and rerun the checks below after upgrades.

## Checks

Deterministic tests launch a fake `agy` and do not spend subscription quota:

```sh
python3 -m unittest discover -s tests -v
```

Live checks use your existing Antigravity account and consume normal quota:

```sh
goose-agy run --no-session -q -t 'Reply with exactly GOOSE_AGY_READY. Do not use tools.'
```

For a manual continuity check, start `goose-agy`, ask it to remember a unique
word, then ask for that word in your next message. Exit with Goose's `/exit`.

Validated locally with Goose 1.57.0: streaming response, explicit Gemini model,
two-turn conversation continuity, and reading a randomly generated file from
the caller's working directory. Failure tests cover backend errors, missing or
malformed results, timeouts, termination, parent death, and large stderr output.

## Remove

```sh
rm ~/.local/bin/goose-agy
```

This removes only the installed launcher symlink. No authentication or Goose
configuration needs to be reverted.

## References

- [Goose CLI providers](https://goose.vcorp.ai/docs/guides/cli-providers/)
- [Goose 1.57.0 Gemini CLI transport source](https://github.com/aaif-goose/goose/blob/v1.57.0/crates/goose/src/providers/gemini_cli.rs)
- [Antigravity headless mode and streaming protocol](https://antigravity.google/docs/cli/headless/)
- [Antigravity authentication](https://antigravity.google/docs/install?tab=cli)
