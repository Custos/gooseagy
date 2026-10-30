# Security and privacy

This project is a local, single-user adapter. The ACP worker communicates over
stdin/stdout; it is not a public model server or a multi-tenant isolation layer.
The native Buzz host owns agent identity, owner checks and scoped MCP authority.
The adapter does not extract OAuth credentials or call private Google endpoints.
Authentication stays with the official `agy` executable.

## Permissions

Fresh installations preserve native approval rules and permit only the
conversation-scoped MCP servers supplied by the client. Interactive approval
prompts are not bridged into Buzz. Explicitly enabling unrestricted tools passes
`--dangerously-skip-permissions` for every agent using this adapter on the Mac.
Those agents can execute commands and modify files with the user's access.
The setting persists until changed. Plan mode refuses unrestricted tools.

The ACP backend selects subscription authentication and removes `GEMINI_API_KEY`
and `GOOGLE_API_KEY` from its child environment. The terminal Goose adapter uses
the authentication selected in the official CLI; confirm its account/provider
before use if that CLI was previously configured for API billing.

## Local data

Adapter state defaults to `~/.local/state/gooseagy` (directory mode 0700).
Saved sessions include prompts, assistant text, project paths and backend
conversation IDs (file mode 0600). They exclude supplied MCP configuration.
Native Antigravity keeps its own history and logs under its own data directory.

MCP credentials are written to a private, per-session runtime configuration
needed by the official CLI. Normal completion and cancellation remove it.
SIGKILL, power loss or another abrupt crash can leave that private file behind.
Stop adapter activity before manually removing stale runtime files. Do not share
state directories or log files without reviewing them. No automatic retention
policy is implemented. A shared OS account is not a privacy boundary.

Failed/interrupted turns are marked uncertain before dispatch and are never
retried automatically. Users start a new session before retrying. Process-group
termination is best effort; the adapter is not an OS sandbox.

## Dependencies and reporting

The plugin bundle includes pinned upstream Buzz code and locked JavaScript build
dependencies. It is unsigned community code. Review its requested process, MCP
and file capabilities before importing it. Buzz's and Antigravity's future
versions can change their protocols or policies.

Use this repository's private vulnerability reporting feature when available.
Do not post tokens, MCP URLs with credentials, private conversations or full app
profiles in public issues. For ordinary bugs, include versions, minimal
reproduction steps and a redacted error.
