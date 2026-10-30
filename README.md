# gooseagy

Use the official **Antigravity CLI (`agy`)** from the released Buzz desktop app
or the Goose terminal app, with the Google account already signed in to `agy`.
This is a community adapter; it does not modify Buzz or Goose, extract OAuth
credentials, or provide a raw Gemini API endpoint.

| Integration | How it connects | Setup |
| --- | --- | --- |
| Buzz desktop | External API-v1 plugin → ACP worker → official `agy` CLI | [Buzz setup](BUZZ_SETUP.md) |
| Goose terminal | Goose's deprecated `gemini-cli` transport → adapter → `agy` | [Terminal setup](docs/TERMINAL_SETUP.md) |

Your Google plan, account, region and available models determine what `agy` can
use. This adapter does not grant a subscription or guarantee access to a model.
Authentication remains in the official CLI. It does not require a Gemini API key.

## Buzz quick start

Tested with the official [block/buzz-app](https://github.com/block/buzz-app)
macOS release **0.7.0-preview.215.1**. Keep using its normal updater.

Requirements: macOS, `python3` **3.11+**, and an authenticated official
[Antigravity CLI](https://antigravity.google/docs/install?tab=cli).
Download/clone this repository into a permanent directory, then:

```sh
agy                              # sign in if needed, then exit
git clone https://github.com/Custos/gooseagy.git
cd gooseagy
python3 install.py --buzz
```

The installer prints the plugin folder to import. In your existing Buzz:

1. Open **Settings → Plugins → Add → Browse**.
2. Select this checkout's **buzz-plugin/dist** folder, install **Antigravity
   Ultra**, and enable it.
3. Run `goose-agy doctor --refresh-models` in Terminal.
4. Create an agent or change an existing agent's **Harness** to
   **Antigravity (Ultra)**. Choose a model ID from `agy models`, reasoning
   effort, working directory and instructions. Mention it or use Solo chat.

The generated launchers reference this checkout, so keep it in place.
No app rebuild, separate Buzz installation or always-running proxy is needed.
A compatible official `buzzodz` plugin manager, if already installed, can perform
step 2 automatically. It is optional; the manual UI import is the default path.

## Permissions

Fresh installations keep Antigravity's approval rules. Headless operations that
need interactive approval are denied; those prompts are not bridged into Buzz.
The adapter permits the app-supplied, conversation-scoped MCP tools.

To explicitly allow shell commands and file changes without prompts:

```sh
python3 install.py --buzz --buzz-allow-all-tools
```

This passes `agy --dangerously-skip-permissions` for **every agent using this
adapter on your Mac**, with your user account's access. To restore approval rules:

```sh
python3 install.py --buzz --buzz-require-approvals
```

The choice persists across reinstalls. Plan mode refuses unrestricted tools.
This setting does not change other Buzz harnesses or ordinary Goose.

## Compatibility and limits

- Buzz support targets macOS and the plugin API/version above. Terminal Goose
  support targets POSIX systems with Python 3.11+ and was validated on macOS with
  Goose **1.57.0**. Other app/CLI versions are not certified by this project.
- Text prompts only. Antigravity supplies tools and manages its own context.
- Buzz tools use the app's authenticated MCP bridge. Goose terminal extensions
  and builtins do not pass through its CLI transport.
- Buzz keeps one backend conversation per thread while running. After an app
  restart it opens a new backend conversation with visible thread context.
  Terminal Goose cross-process resume/fork is unsupported.
- Model IDs vary by account. `gemini-4-argon-high` was used for validation;
  `agy models` and `goose-agy doctor --refresh-models` discover your own choices.
- Failed/interrupted turns are not retried automatically. Use **New session**
  before retrying uncertain actions. Manual Buzz **Compact** is unsupported.
- Runtime authentication/configuration may contain sensitive data. Session MCP
  files are private and removed after normal completion/cancellation; abrupt
  termination can leave private files behind. See [security notes](SECURITY.md).

## Verification

Offline checks do not need credentials, a Buzz installation, or model quota:

```sh
python3 -m unittest discover -s tests -v
node tests/plugin_contract.mjs
```

Node **22+** is needed only for the contract check and development builds.
The optional live checks use subscription quota and local mock Buzz handles;
they do not publish to real communities:

```sh
goose-agy doctor --live
python3 tests/live_buzz_smoke.py
```

The initial user also confirmed a real mention completed in the released Buzz
app. That is a manual observation, separate from the automated local checks.
The [implementation review](docs/REVIEW.md) records findings and remaining limits.

## Development and license

See [contributing](CONTRIBUTING.md) for the pinned upstream rebuild and CI.
The committed `buzz-plugin/dist` artifact is ready to import; runtime users do
not need npm, Rust or the upstream source checkout.

Apache-2.0. The plugin includes adapted Buzz harness code and preserves its
license and attribution. See [NOTICE](NOTICE), [LICENSE](LICENSE), and
[bundled notices](buzz-plugin/NOTICE.md). This project is not affiliated with
Google, Block or the Goose project.
