# Implementation review

Reviewed for the initial public release on 2026-10-30. This is an implementation
review by the coding agent that built the adapter, not an independent security
audit. The real-app user confirmed that a mention completed successfully.

## Scope

Reviewed Python CLI/ACP boundaries, child process lifecycle, conversation
mapping, native MCP configuration, permission handling, installer behavior,
plugin registration, upstream attribution, documentation and publication inputs.
The plugin derives from Buzz source revision
`1c0f6d68ae11d834f6ac8a9287b3b983cc967275`.

## Findings addressed

| Finding | Resolution |
| --- | --- |
| Empty free-text responses can be legitimate after a Buzz send | Completed tool-only turns succeed without inventing assistant text; empty results without completed work remain errors |
| Native CLI can report SUCCESS after denying a tool | Inspect `denied_actions`, show the approval requirement, mark failed tool activity, and avoid automatic replay |
| Interrupted or failed turns can have uncertain side effects | Persist uncertainty before dispatch; require a fresh session; check persisted state under a per-session lock |
| MCP configuration could survive setup exceptions | Parse settings before writing configuration; cleanup and lock release cover setup/dispatch; document abrupt-crash limits |
| Development check required the author's installed launcher | Contract check launches this checkout directly; doctor explicitly tests the installed launcher |
| Doctor could overlook a stale imported plugin | Verify native snapshot SHA-256, manifest and code against the distributed artifact |
| Installer contained one-machine legacy redirect cleanup | Remove that code and private local setup history from public source |
| Generated source comments depended on checkout paths | Normalize upstream paths and verify a pinned clean rebuild in CI |
| Sharing unrestricted local settings could surprise new users | Keep permissions in private runtime state; default to native rules; document explicit opt-in and its scope |

## Validation

- Python regression suite and distributed-plugin offline contract test.
- Real Antigravity text streaming, file read and same-process conversational
  continuity during terminal integration validation.
- Live ACP → Antigravity → local MCP proof with process restart/session load.
- Two real Antigravity/HTTP-MCP Buzz tool replies in the same thread, using local
  mock app handles and verifying backend conversation continuity.
- Real headless shell denial produces an approval error, and explicitly enabled
  unrestricted mode executes a harmless shell command without approval.
- Existing Buzz bundle signature and native external-plugin registration checked.
- Secret scan and tracked-file review before public push; exact automated CI
  status is available in the repository's Actions tab.

Automated live checks do not send real community messages or visually drive the
native UI. Native host integration is partly verified by source review, local
contract tests and manual user confirmation. Account/model availability,
Google entitlements and future upstream releases are outside these checks.

## Remaining limits

Text only; no interactive approval bridge; no manual Buzz compaction; no terminal
Goose resume/fork across processes; fresh backend context after a Buzz restart;
private runtime configuration can remain after abrupt termination. Saved state
has no retention policy. Session owner scoping supplements a trusted local host
and is not a multi-user security boundary. See SECURITY.md and setup guides.
