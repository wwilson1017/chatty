# Coach Lessons

> Instincts extracted from development sessions. Scores reflect real-world effectiveness.
> Format: `[score]` **When** trigger → **do** action → **because** reason

## Deploy & Infrastructure

- `[0.90]` **When** running the backend from a git worktree → **do** use the absolute venv path (`/Users/willwilson/ai/chatty/.venv/bin/python`), not relative (`../../.venv/bin/python`) → **because** worktrees live under `.claude/worktrees/<name>/backend/` and the relative path resolves to a nonexistent location

## Git & Workflow

- `[0.85]` **When** resolving merge conflicts → **do** use `git add <specific files>`, never `git add -A` → **because** `-A` pulled `.claude/fresh-eyes/context.md` (216 lines of session research notes) into the merge commit, which then shipped in the PR
- `[0.75]` **When** committing frontend changes → **do** run `npm run lint` (eslint) in addition to `npm run build` → **because** CI's build-and-lint job enforces react-hooks rules (e.g. `set-state-in-effect`) that tsc and vite never check — the playbooks PR went red on exactly this

## Database & Migration

- `[0.80]` **When** adding columns to an existing SQLite table in Chatty → **do** use the `_migrate_schema()` try/except pattern (`SELECT col LIMIT 0` / `ALTER TABLE ADD COLUMN`) → **because** this pattern handles both fresh installs and upgrades atomically without a migration framework, and `DEFAULT` values are stored in schema not per-row

## Testing

- `[0.70]` **When** testing Chatty chat flows that resume or reconstruct state (`approved_tool`) → **do** end the messages with the frontend's literal `[Approved] <tool>` user message → **because** `ai_service` strips that placeholder conditionally (ai_service.py:1143) — a generic message silently bypasses the strip branch, and the test stays green while production leaks `[Approved] send_email` into provider history

## Code & Architecture

- `[0.80]` **When** reading per-agent MemoryDB data inside `_build_system_prompt` (e.g. observations) → **do** use `ensure_memory_db(slug)`, not `get_instance(data_dir)` → **because** the Telegram and Paperclip entry points don't pre-initialize MemoryDB, so `get_instance` returns None and the data silently never appears on non-web channels
- `[0.75]` **When** adding new admin settings to Chatty → **do** add them to `core/admin_settings.py` (not `setup/router.py`) → **because** admin settings were extracted to a dedicated cached module; adding to the old location creates conflicts and bypasses the mtime cache
- `[0.70]` **When** adding content that agents should proactively surface in Chatty → **do** wire it into `scheduled_actions/processor.py` `_process_heartbeat` (peeked before the empty-checklist gate, triage bypassed when present), not only `reminders/heartbeat.py` → **because** the reminders heartbeat fires only when a reminder is due — wiring only there means agents without reminders never deliver, and the scheduled path's triage ALL_CLEAR early-return silently skips full runs
- `[0.70]` **When** a code review offers "persist data or remove dead tracking" for an in-memory-only pipeline → **do** remove the dead code unless the consumer is actively planned → **because** half-built pipelines (`_track_recall_usage` writing data `score_session_quality` never reads) create false expectations; a docstring "kept for future use" doesn't justify dead code
- `[0.70]` **When** extracting a shared function from a module that others import → **do** keep a re-export in the original module and update all internal callers to the new location → **because** external callers (tests, plugins) may import from the old path; re-export prevents silent breakage while the new canonical path is established
- `[0.70]` **When** replacing `getattr(obj, "attr", fallback)` with an explicit parameter → **do** verify every call site passes the parameter, or keep the `getattr` fallback at the entry point → **because** the `_slug` UnboundLocalError was introduced by removing `getattr` in the outer function without ensuring callers pass the new arg
- `[0.70]` **When** building a feature that reads historical data from an existing table → **do** check for retention/cleanup jobs that prune old rows → **because** the usage dashboard would have been silently capped at 30 days without discovering `cleanup_old()`'s pruning; the fresh-eyes agent caught this but the original plan missed it entirely
- `[0.70]` **When** injecting stored user/legacy content into prompts via `sanitize_memory_content` → **do** check the content for legitimate `{{...}}`/`${...}` syntax first → **because** the sanitizer redacts template syntax to `[REDACTED]` at injection time — migrated skill-pack `{{param}}` playbooks were silently corrupted for the model while looking fine in the editor
- `[0.60]` **When** adding a new FastAPI route that performs synchronous SQLite I/O → **do** use `def`, not `async def` → **because** FastAPI only offloads sync work to a thread pool for plain `def` routes; `async def` with blocking SQLite calls freezes the entire event loop for the duration of the query
