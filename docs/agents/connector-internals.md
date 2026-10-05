# Claude Code connector internals

Trust model and invariants for `integrations/claude_code/` and `connector/`. User guide: `docs/claude-code-connector.md`. Moved verbatim from the root `AGENTS.md`.

## Claude Code connector

`integrations/claude_code/` lets agents hand tasks to the user's own Claude Code or Codex. `connector/` is a separate package (`chatty-connector`, httpx only) that the user installs on their machine, pairs with a one-time code from the integration card, and runs as a service. It **polls outbound** (`/api/connector/*`, bearer token, only the sha256 is stored) and runs `claude -p` / `codex exec` per job. Agent tools: `delegate`, `job_get`, `job_list`, `job_cancel`, `connector_info` (`writes: False`; they gate themselves). User guide: `docs/claude-code-connector.md`; design record: `connector/SPIKE.md`.

**Trust model.** Three levels (`db.LEVELS`: `look` < `sandbox` < `full`; the column is still `jobs.mode`). The machine sets the **ceiling** (`chatty-connector setup`, reported on every poll); the card's one dropdown sets `access_level` (creds, default `sandbox`) within it. `db.level_error()` checks both at queue time and the claim in `connector_api.poll` re-checks both, cancelling the job; the connector refuses anything above its ceiling itself, so a compromised Chatty can't exceed it. A poll without a ceiling (0.1.x) claims nothing.
- `full` only from a user-originated turn, and only after the owner approves the verbatim task: `approvals.py` (Telegram `cc:<id>:full|sandbox|cancel` buttons or the card, 24 h expiry, single-use conditional UPDATE, prompt sha256 checked at claim).
- Background, group, Paperclip and job-completion turns never go above `sandbox`, 10 per agent per rolling 24 h. Turn origin is server-injected via `_ctx`, never taken from the model.
- What `look`/`sandbox` can actually do is the settings files `setup` writes (`look-settings.json`, `sandbox-settings.json`); their strength is the user's responsibility. Without a working OS sandbox it is "deny rules only".

**Invariants.** `db.finish_job()` is the only code path that makes a job terminal (results, lost/stale jobs, cancels, disconnect, re-pair). Completion runs the agent's background turn **at most once**; everything after it goes through the idempotent `completion.finalize()`, which recovery paths re-run and which never invokes a turn. Tests: `backend/tests/test_claude_code.py`, `backend/tests/test_claude_code_approvals.py`, `connector/tests/`.
