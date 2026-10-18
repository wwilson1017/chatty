# Basic command-line Chatty — v1 (`chatty` terminal client)

## Problem / Goal
Will wants to chat with his Chatty agents from a terminal on macOS and Linux — the web UI's chat as a plain terminal app, in the spirit of OpenClaw / Hermes / Claude Code but far simpler. Done = one-line install, scan a QR to log in to his Railway Chatty, pick an agent, chat (mostly in power mode).

## Decisions
- **Thin client of a running Chatty** (Railway, or localhost) — no embedded backend. Agents and data live on the server; a local backend would split them. A full local install is later (#170).
- **Login = QR device pairing** (device-code flow, inverse of Collie's `collie pair`): `chatty login <url>` prints a short code + a QR that opens Settings → Terminal on the already-logged-in phone with the code filled in; Will approves; the CLI polls and receives a long-lived per-device token. The web is the trusted side, so the web approves and the terminal spends.
- **Device tokens never expire; revoke per device** in the Terminal card. Server stores only the sha256 (same as the connector). The CLI exchanges the device token for a normal short-lived JWT, so the rest of the API is untouched.
- **Approval screen shows the code, device name and IP and says "approve only if your terminal shows this code"** — guards against being tricked into approving someone else's terminal.
- **Fallback: `chatty login --password`** (password + TOTP via the existing login endpoints) for when no browser is handy. It then enrolls the same revocable device token as pairing, so there is one auth path (changed in plan review).
- **Install:** `uv tool install "git+…#subdirectory=cli"` → `chatty login <url>` → `chatty`. Same pattern as the connector; uv brings its own Python.
- **Own package, new top-level `cli/` dir**, versioned with the server; separate from the connector (always-on executor vs interactive client with no execution power).
- **Settings → Terminal card**: install command with the URL filled in, pairing approval, and the paired-device list with revoke.
- **One saved server per config file**; `chatty login <url>` switches it and `CHATTY_CONFIG=<path>` keeps a second one. No `--url` flag, so a token is never sent to a server it wasn't issued by (changed in plan review).
- **Threads:** `chatty` starts a new conversation; `-c` continues the latest with that agent (any device); `/new` starts fresh; `/resume` picks a recent one.
- **Agent selection:** auto if only one, else numbered list, last pick remembered; `-a <slug>`; `/agent` switches.
- **Tool calls** as one dim line (name, ✓/✗, time); `/verbose` shows args and results.
- **Write tools ask y/N** with args shown, using the web's existing approval flow.
- **Modes:** `/mode normal|power|read-only` + `--power`, remembered across launches, `⚡` in the prompt. Will mostly runs power.
- **Power = the web's power mode** (no y/N). Server guardrails stay: per-integration ceilings, write budget, hourly limit, Claude Code `full` approvals. A real bypass would let a stolen token switch off server-side safety.
- **Ctrl+C stops the display, not the turn:** the CLI keeps draining the stream in the background so the server finishes and saves the reply; a new send waits for it. (Today the server cancels a turn when the client disconnects.)
- **`/attach <path>`, `/resume`, `/model` are in v1** — the server already supports all three. `/model` changes the agent's model server-side, so the web sees it too.
- **No execution on the user's machine in v1.** CLI-attached local tools are v2 (#170); the connector stays the always-on path; the virtual computer is vm-research's.

## Scope
**In:** QR pairing + `--password` fallback; agent selection; streaming plain text (markdown rendering moved to #170 in plan review); tool lines; write-tool approvals; three modes (power remembered); Ctrl+C interrupt with background drain; Ctrl+D exit; input history; multiline; `/help /new /agent /mode /verbose /attach /resume /model /quit`; `-c -a --power`; Settings → Terminal card (install command, approve, device list, revoke); README section + `docs/cli.md`.

**Out (tracked in #170):** notifications in the terminal, todo capture, CLI-attached local tools, full local install, single binary / Homebrew, full-screen TUI, "always allow this tool", `curl | sh` installer, Windows.

## Constraints & Assumptions
- macOS + Linux, Python via uv; deps limited to an HTTP client and terminal rendering/input (httpx, rich, prompt_toolkit, plus a small QR renderer).
- Backend work is limited to pairing (table, start / poll / approve endpoints, token → JWT exchange, revoke) and the Terminal card; every other endpoint is reused as is.
- `backend/cli/` (in-process dev harness) stays unchanged; vm-research's PR 0 keeps its `agents.tool_loader` imports working.
- Single user; JWT lifetime 8 h by default (`JWT_EXPIRE_MINUTES`).
- SSE already streams through Railway for the web.

## Open Questions
- [deferred] Server-side: run chat turns detached from the HTTP connection, so web turns also survive a dropped client (e.g. phone screen lock). Not needed for the CLI's drain approach.
- [deferred] Whether the 2FA trust cookie is `Secure`-only — affects only `--password` against plain-http localhost (TOTP each login there).
