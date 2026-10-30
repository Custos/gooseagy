# Changelog

## 0.2.2 — initial public release

- External API-v1 plugin for the official Buzz desktop app, backed by a local
  ACP worker and the official authenticated Antigravity CLI.
- Scoped Buzz MCP tools, per-thread conversations, cancellation, model/effort
  configuration and optional unrestricted native tools.
- Terminal Goose integration through its existing `gemini-cli` transport.
- Correct handling of tool-only successful turns, permission-denied results and
  failed tools; no automatic retries of uncertain actions.
- Public installation, troubleshooting, security, contribution and review notes.
- Offline regression tests, portable plugin contract test and pinned build CI.
