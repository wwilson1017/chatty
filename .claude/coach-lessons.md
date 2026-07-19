# Coach Lessons

> Instincts extracted from development sessions. Evidence: `[✓confirmed ✗violated · last-event]`.
> Scan this index; grep the quoted phrase for the full instinct.
<!-- coach-last-sweep: 2026-07-19T14:30:00Z -->

## Index

- [Git] committing frontend changes: run `npm run lint` too
- [Git] resolving merge conflicts: `git add <specific files>`, never `-A`
- [DB] SQLite column adds: `_migrate_schema()` try/except pattern
- [Testing] credential-store helpers: monkeypatch `_fetch_anthropic_key` too
- [Testing] tamper tests on random tokens: replacement char must differ
- [Testing] approved-tool tests: end with literal `[Approved] <tool>` message
- [Code] `ensure_memory_db(slug)` in system prompt, not `get_instance`
- [Code] admin settings go in `core/admin_settings.py`
- [Code] injected results ("[X happened]" blocks): frame as agent's own action
- [Code] key-validation probes: `models.list`, never a tiny chat completion
- [Code] connect-key must not flip the active provider; filter tier inference
- [Code] provider messages array: `ends on a user turn` (`stream_turn`)
- [Code] SSE `usage` event: account for React hook AND CLI `StreamRenderer`
- [Code] `sanitize_memory_content` redacts legitimate `{{...}}` template syntax
- [Code] proactive content: wire `_process_heartbeat`, not only reminders
- [Code] sync SQLite routes: `def`, not `async def`
- [Code] feature reading historical rows: check `cleanup_old()` retention pruning
- [Code] "persist or remove dead tracking": remove `_track_recall_usage`-style dead code
- [Code] extracting shared functions: keep a re-export in the original module
- [Code] replacing `getattr` fallbacks: verify every call site passes the arg

## Git & Workflow

- `[✓2 ✗0 · 2026-07-19]` **When** committing frontend changes → **do** run `npm run lint` (eslint) in addition to `npm run build` → **because** CI's build-and-lint job enforces react-hooks rules (e.g. `set-state-in-effect`) that tsc and vite never check — the playbooks PR went red on exactly this
- `[✓2 ✗0 · 2026-06-12]` **When** resolving merge conflicts → **do** use `git add <specific files>`, never `git add -A` → **because** `-A` pulled `.claude/fresh-eyes/context.md` (216 lines of session research notes) into the merge commit, which then shipped in the PR

## Database & Migration

- `[✓1 ✗0 · 2026-06-12]` **When** adding columns to an existing SQLite table in Chatty → **do** use the `_migrate_schema()` try/except pattern (`SELECT col LIMIT 0` / `ALTER TABLE ADD COLUMN`) → **because** this pattern handles both fresh installs and upgrades atomically without a migration framework, and `DEFAULT` values are stored in schema not per-row

## Testing

- `[✓0 ✗0 · 2026-06-17]` **When** unit-testing Chatty code that calls a provider but first fetches the key via a credential-store helper (`_fetch_anthropic_key` and friends) → **do** monkeypatch that helper to return a stub key too, not just `anthropic.Anthropic` → **because** with no credential the helper returns `""` and the caller (e.g. the compaction summarizer) short-circuits before constructing the mocked client — the tests pass locally where a dev key exists and fail only in CI (Codex caught exactly this on the compaction tests)
- `[✓0 ✗0 · 2026-06-12]` **When** testing Chatty chat flows that resume or reconstruct state (`approved_tool`) → **do** end the messages with the frontend's literal `[Approved] <tool>` user message → **because** `ai_service` strips that placeholder conditionally (ai_service.py:1143) — a generic message silently bypasses the strip branch, and the test stays green while production leaks `[Approved] send_email` into provider history
- `[✓0 ✗0 · 2026-07-19]` **When** writing a tamper test that corrupts one char of a random token (Fernet/JWT/base64) → **do** pick a replacement guaranteed to differ from the original (`"X" if orig != "X" else "Y"`), never a fixed char → **because** the token embeds a random IV, so a fixed char matches the original ~1/64 runs, the "tampered" token round-trips fine, and the test flakes only in CI (`test_tampered_ciphertext_returns_empty` blocked PR #132)

## Code & Architecture

- `[✓1 ✗0 · 2026-06-12]` **When** reading per-agent MemoryDB data inside `_build_system_prompt` (e.g. observations) → **do** use `ensure_memory_db(slug)`, not `get_instance(data_dir)` → **because** the Telegram and Paperclip entry points don't pre-initialize MemoryDB, so `get_instance` returns None and the data silently never appears on non-web channels
- `[✓1 ✗0 · 2026-06-12]` **When** adding new admin settings to Chatty → **do** add them to `core/admin_settings.py` (not `setup/router.py`) → **because** admin settings were extracted to a dedicated cached module; adding to the old location creates conflicts and bypasses the mtime cache
- `[✓0 ✗0 · 2026-07-19]` **When** injecting system-prepared results into an agent's turn (pre-stream transcripts, file-extraction prepends, any "[X happened]" context block) → **do** frame the injection as the agent's own just-completed action in active voice ("You just transcribed…"), with presentation instructions covering the asked-for case, not only the no-request case → **because** the passive past-tense block "[Meeting recording transcribed: …]" made Dana answer "can you transcribe this?" with "already transcribed automatically on upload, you're all set" — narrating internal plumbing instead of owning the work and delivering the result
- `[✓0 ✗0 · 2026-07-19]` **When** writing a provider key-validation probe → **do** use the cheapest metadata call (`models.list`), never a tiny chat completion → **because** reasoning models burn thinking tokens before any output, so a `max_completion_tokens=1` probe 400s ("output limit was reached") and every VALID OpenAI key read as "Invalid OpenAI API key" at connect time
- `[✓0 ✗0 · 2026-07-19]` **When** storing a newly connected provider API key → **do** activate it only when no provider is active yet (connect ≠ switch), and filter live-catalog tier inference to actual chat models (`gemini-*` minus image/tts/robotics/computer-use variants) → **because** connect-key silently flipped the active chat provider to google, whose inferred top tier was `deep-research-pro-preview-12-2025` — a specialty model whose metadata claims generateContent support but rejects every call ("only supports Interactions API"), bricking all chat until the user hand-fixed settings
- `[✓0 ✗0 · 2026-06-17]` **When** building the provider `messages` array from stored history in Chatty (server-side reconstruction in `context_assembly`, approved-tool reconcile, compaction) → **do** ensure the array ends on a user turn, on every path including those that save no new user row → **because** Google's `stream_turn` resends `messages[-1]` AS the user turn (hardcoded `role="user"`) and Anthropic treats a trailing assistant as a prefill, so a persisted assistant wrap-up tail makes Gemini answer its own question and Anthropic continue mid-thought — and a fix that persists a new assistant row can silently flip the tail (Opus caught this on #130; assert `messages[-1]["role"] == "user"` in tests)
- `[✓0 ✗0 · 2026-06-17]` **When** changing a field on the chat SSE `usage` event (or any `ai_service` SSE event) → **do** account for BOTH consumers — the React `useAgentChat` hook AND the terminal CLI `StreamRenderer` (`backend/cli/output.py`), which sums every `usage` event's `input_tokens`/`output_tokens` into the session total → **because** redefining `input_tokens` to a cache-inclusive value silently inflated the CLI's running count; the fix was a `meter_only` flag that zeros raw fields on display-only emits plus a separate `context_tokens` field for the meter
- `[✓0 ✗0 · 2026-06-12]` **When** injecting stored user/legacy content into prompts via `sanitize_memory_content` → **do** check the content for legitimate `{{...}}`/`${...}` syntax first → **because** the sanitizer redacts template syntax to `[REDACTED]` at injection time — migrated skill-pack `{{param}}` playbooks were silently corrupted for the model while looking fine in the editor
- `[✓0 ✗0 · 2026-06-12]` **When** adding content that agents should proactively surface in Chatty → **do** wire it into `scheduled_actions/processor.py` `_process_heartbeat` (peeked before the empty-checklist gate, triage bypassed when present), not only `reminders/heartbeat.py` → **because** the reminders heartbeat fires only when a reminder is due — wiring only there means agents without reminders never deliver, and the scheduled path's triage ALL_CLEAR early-return silently skips full runs
- `[✓0 ✗0 · 2026-06-12]` **When** adding a new FastAPI route that performs synchronous SQLite I/O → **do** use `def`, not `async def` → **because** FastAPI only offloads sync work to a thread pool for plain `def` routes; `async def` with blocking SQLite calls freezes the entire event loop for the duration of the query
- `[✓0 ✗0 · 2026-06-11]` **When** building a feature that reads historical data from an existing table → **do** check for retention/cleanup jobs that prune old rows → **because** the usage dashboard would have been silently capped at 30 days without discovering `cleanup_old()`'s pruning; the fresh-eyes agent caught this but the original plan missed it entirely
- `[✓0 ✗0 · 2026-06-09]` **When** a code review offers "persist data or remove dead tracking" for an in-memory-only pipeline → **do** remove the dead code unless the consumer is actively planned → **because** half-built pipelines (`_track_recall_usage` writing data `score_session_quality` never reads) create false expectations; a docstring "kept for future use" doesn't justify dead code
- `[✓0 ✗0 · 2026-06-01]` **When** extracting a shared function from a module that others import → **do** keep a re-export in the original module and update all internal callers to the new location → **because** external callers (tests, plugins) may import from the old path; re-export prevents silent breakage while the new canonical path is established
- `[✓0 ✗0 · 2026-06-01]` **When** replacing `getattr(obj, "attr", fallback)` with an explicit parameter → **do** verify every call site passes the parameter, or keep the `getattr` fallback at the entry point → **because** the `_slug` UnboundLocalError was introduced by removing `getattr` in the outer function without ensuring callers pass the new arg
