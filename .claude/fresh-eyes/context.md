# Fresh Eyes Context

## Problem Statement

Chatty is a free, open-source personal AI agent platform with a browser-based UI for small business owners. We're building two features in a single branch (`feature/quick-wins-0626`), inspired by patterns from OpenClaw (`~/ai/openclaw/`) and Hermes (`~/ai/hermes-agent/`) but adapted to Chatty's architecture.

A third feature (context file caching for `ContextManager.load_all_context()`) was evaluated and cut — the file I/O savings (~2ms on SSD) aren't worth the cache invalidation complexity for a single-user app. Both OpenClaw and Hermes cache at the API prompt level (prefix token reuse), not at the file-read level, and Chatty already does Anthropic prompt caching via `cache_control` breakpoints in `ai_service.py`.

## The Two Features to Build

### Feature A: Bot Reply Limit Setting

**What**: Surface the existing `telegram_max_bot_turns` counter as a user-configurable global setting in Settings > Chat.

**Why**: Chatty already has a 3-level bot loop prevention system in `backend/integrations/telegram/group.py` for Telegram group chats: (1) self-message filtering, (2) consecutive bot turn counter with `telegram_max_bot_turns` default 3, (3) per-agent 2s response cooldown. But this setting is hidden — it's a per-agent database field with no UI. The user wants to prepare for a future where multiple Chatty agents deliberately share a Telegram group and can converse with each other.

**User decisions**:
- Global setting (not per-agent), lives in Settings > Chat section
- Toggle on/off + number input
- Default: enabled, limit = 5
- "Off" means unlimited bot replies (no cap), NOT "never respond to bots"
- The toggle label should be "Limit bot replies" or similar

### Feature B: Session-Scoped Observation Memory

**What**: After each day's conversations, automatically extract factual observations about the user/business, store them, and inject them into future prompts. Add a UI panel to view/delete observations.

**Why**: Agents don't learn from conversations automatically. The user has to explicitly teach the agent by importing knowledge. Over time, agents should build a profile of the business organically — "prefers morning deliveries," "busy season is March-May," "accountant is Sarah at 555-1234."

**User decisions**:
- Trigger: Nightly dreaming pass (runs at 23:00 CT via APScheduler)
- Input: Last 10 user+assistant turns per conversation with 4+ user messages updated that day
- Extraction: New AI call (same model as existing dreaming — currently Haiku)
- Output: 2-5 plain strings per conversation (no metadata/categories/confidence scores)
- Safety: Prompt instructs no passwords, account numbers, or financial details
- Dedup: Extra AI call comparing candidates against existing observations before insert
- Storage: New `observations` table in memory.db (not reusing the existing `facts` table — different lifecycle)
- Injection: Static section of system prompt after MEMORY.md content, top 10 by reference_count, as "## Things I've Noticed About You"
- Reference counting: Increment each time an observation is included in a prompt
- Pruning: Dreaming deletes observations unused for 90+ days
- UI: Collapsible section within the Knowledge tab (not a new tab), view + delete only (no edit)
- Model selection: Follow existing dreaming model selection pattern, provider-agnostic

## Codebase Research

### Global Settings System

**`backend/setup/router.py`** (lines 22-129):
- Settings stored in `data/admin-settings.json` (not database)
- `ADMIN_DEFAULTS` dict defines all settings with defaults (lines 25-32)
- `load_admin_settings()` merges file with defaults (lines 38-49)
- `GET /api/setup/admin-settings` returns all settings
- `PUT /api/setup/admin-settings` updates with validation (lines 116-129)
- Current settings: `always_power_mode`, `triage_mode`, `default_model_tier`, `notifications_*`
- Uses `atomic_write_json()` for safe writes

### Settings UI — Chat Tab

**`frontend/src/dashboard/SettingsPanel.tsx`** (lines 240-384):
- Chat section has: "Show tool calls" toggle (localStorage), "Always power mode" toggle (admin-settings), "Default model" dropdown, "Heartbeat triage" dropdown, NotificationSettings component
- Toggle pattern: flex row with label+description left, 44x24px toggle button right
- Admin settings loaded on mount via `useEffect` at line 48
- State: `alwaysPowerMode`, `triageMode`, `defaultModelTier` loaded from `/api/setup/admin-settings`
- Save pattern: immediate PUT on toggle/change, optimistic UI update

### Telegram Bot Loop Prevention

**`backend/integrations/telegram/group.py`** (full file, 121 lines):
- Module-level `_group_states: dict[int, _GroupState]` tracks per-chat state
- `_GroupState` dataclass: `consecutive_bot_turns: int`, `last_response_times: dict[str, float]`
- `should_respond()` (lines 54-91): checks group enabled, self-message, bot turn limit, cooldown
- Currently reads from per-agent dict: `agent.get("telegram_respond_to_bots")` (line 80) and `agent.get("telegram_max_bot_turns", 3)` (line 82)
- Per-agent fields defined in `backend/agents/db.py` lines 76-77, 196-197
- Thread-safe via `threading.Lock`

### Nightly Jobs Flow

**`backend/core/agents/scheduled_actions/nightly.py`** (full file, 75 lines):
```python
def run_nightly_jobs():
    # Get Anthropic API key
    store = CredentialStore()
    _, anthropic_profile = store.get_active_profile(provider_override="anthropic")
    api_key = (anthropic_profile or {}).get("key", "")

    for agent in agents:
        if not agent.get("onboarding_complete"): continue
        # 1. Daily note summarization (Haiku)
        process_daily_note_summary(agent_name, ctx_manager, chat_service, api_key)
        # 2. Memory consolidation (Sonnet, if api_key)
        process_memory_consolidation(agent_name, ctx_manager, api_key, days=7)
        # 3. Dreaming (pure Python — score files, archive dormant)
        process_dreaming(agent_name, ctx_manager)
        # 4. Archive old daily notes (>90 days)
        ctx_manager.archive_old_daily_notes(max_age_days=90)
```

### Memory Processor — Model Usage

**`backend/core/agents/memory/processor.py`**:
- Daily note summary (line 106-111): `anthropic.Anthropic(api_key=api_key)` with model `claude-haiku-4-5-20251001`, max_tokens=1200
- Memory consolidation: uses Sonnet via `consolidate_memory()` in `memory_tools.py`
- Both use the Anthropic SDK directly with the API key from `CredentialStore`
- Transcript built from `chat_service.get_messages_on_date(date)` — returns `[{conversation_id, conversation_title, role, content}]` grouped by conversation_id then seq

### Memory Database

**`backend/core/agents/memory/db.py`**:
- Module-level instance cache: `_instances: dict[str, "MemoryDB"] = {}` with `get_instance(data_dir)` accessor
- Schema in `_SCHEMA` string constant (lines 40-115)
- Tables: `memory_documents` (FTS5), `memory_chunks`, `memory_embedding_config`, `skill_packs`, `facts`
- `facts` table (lines 97-114): id, subject, predicate, object, valid_from, valid_to, confidence, memory_type, created_at, updated_at
- WAL mode, write lock (`self._write_lock`), GCS backup via `safe_backup_sqlite()`
- Migrations: `ALTER TABLE` checks in `_setup_connection()` method

### Chat History Database

**`backend/core/agents/chat_history/service.py`**:
- `get_messages_on_date(date)` (lines 136-151): returns flat list `[{conversation_id, conversation_title, role, content}]` ordered by conversation_id, seq. Used by daily note summarizer.
- `list_conversations()`, `get_conversation()`, `save_message()`, `search_conversations()`
- DB schema: `conversations` (id, title, created_at, updated_at, source, pinned, mode), `messages` (id, conversation_id, role, content, created_at, seq, tool_calls, model)
- No existing method to get conversations filtered by user message count

### System Prompt Assembly

**`backend/core/agents/ai_service.py`** (lines 320-440):
- `_build_system_prompt()` returns `(static_text, volatile_text)` tuple
- Static section order:
  1. Personality (line 331-333)
  2. "# Your Knowledge (Long-Term Memory)" + `ctx_manager.load_all_context()` (lines 336-346)
  3. Manifests: topic files, daily notes (lines 348-368)
  4. Shared team context (lines 370-388)
  5. Instructions: knowledge management, memory system, reports, scheduling (lines 396-419)
- Volatile section: today's daily note, relevance pre-fetch, fired reminders, current time
- MemoryDB accessed via `get_instance(str(ctx_manager.data_dir))` at line 443-444 (in volatile section for relevance pre-fetch)
- `_memory_instructions()` at lines 553-565 describes the memory system to the agent

### Agent Engine

**`backend/agents/engine.py`**:
- `get_context_manager(slug)` — creates fresh ContextManager per call (line 87-92)
- `ensure_memory_db(slug)` (line 151-153) — returns initialized MemoryDB for agent
- `_get_initialized_memory_db(slug)` (lines 106-113) — creates MemoryDB with proper paths

### Knowledge Tab UI

**`frontend/src/agent/components/AgentContextEditor.tsx`** (80+ lines read):
- Two-pane layout: file list left, editor right (desktop); toggle between them (mobile)
- Files fetched from `/api/agents/{agentId}/context` on mount
- `ContextFile` interface: `{name, size_bytes, modified}`
- Actions: select/view file, save file, delete file
- Uses `useIsMobile()` hook for responsive layout
- Mono style function: `mono(size, color)` returns JetBrains Mono uppercase styling

### Agent API Routes

**`backend/agents/router.py`**:
- REST endpoints under `/api/agents/{agent_id}/...`
- Context CRUD: GET/PUT/DELETE `/api/agents/{id}/context/{filename}`
- Pattern: `_get_agent_or_404(agent_id)`, `Depends(get_current_user)` for auth
- Imports `ensure_memory_db` from `agents.engine`

## Key Questions Discussed and Answered

1. **Where should context cache live?** → Cut — not building this feature.
2. **What's the threat model for bot loops?** → Main goal is surfacing the existing setting, not building new detection. WhatsApp protection is not a priority (WhatsApp itself might be removed).
3. **Per-agent or global setting for bot reply limit?** → Global, in Settings > Chat.
4. **Default value for bot reply limit?** → 5 (changed from current hardcoded 3).
5. **What does "off" mean?** → Unlimited bot replies (no cap on consecutive turns).
6. **When does observation extraction happen?** → Nightly dreaming pass, not per-turn or idle-based.
7. **New AI call or mine from existing checkpoints?** → New AI call (Haiku) at dreaming time.
8. **What gets sent to extraction?** → Last 10 user+assistant turns per qualifying conversation (4+ user messages).
9. **Output format?** → Plain list of strings, no metadata/categories/confidence.
10. **Where stored?** → New `observations` table, not reusing `facts` table.
11. **How injected into prompt?** → Static section after MEMORY.md, top 10 by reference_count.
12. **UI location?** → Section within Knowledge tab (not new tab), view + delete only.
13. **Dedup approach?** → Extra Haiku call comparing candidates against existing observations.
14. **Which model?** → Follow existing dreaming model selection (currently Haiku via Anthropic SDK).

## Failed Approaches and Rejected Ideas

1. **Context file caching** — Cut entirely. Mtime-based in-memory cache for `load_all_context()` saves ~2ms per call on SSD, noise against 2-30s API calls. Not worth the invalidation complexity (new/deleted files, thread safety, stale cache bugs).

2. **OpenClaw's sliding-window pair loop guard** — Too complex for current needs. Chatty already has adequate Telegram loop protection; the main gap (WhatsApp) isn't a priority since the feature might be removed entirely.

3. **Mining from existing knowledge checkpoints instead of new AI call** — Rejected by user. Knowledge checkpoints (every 4th message) already capture facts, but the user prefers a dedicated extraction pass for cleaner, purpose-built observations.

4. **Structured observations with metadata** (categories, confidence scores) — Rejected. Model's confidence self-assessment is unreliable, categories add maintenance overhead without clear benefit. Plain strings are self-describing.

5. **Per-agent bot reply setting** — Rejected in favor of global setting since it's simpler and the user controls all agents.

6. **Idle detection trigger for observations** — Rejected. No existing idle/session-end detection in Chatty. Adding it creates new infrastructure for questionable value. Nightly batch is simpler.

7. **New "Observations" tab in agent dashboard** — Rejected. A dedicated tab for 5-15 short strings is overkill. Section within Knowledge tab is more appropriate.

8. **Edit capability for observations** — Rejected for v1. Users can delete wrong observations and let the agent re-learn. Editing blurs auto-learned vs user-taught knowledge.

## Hermes and OpenClaw Research Findings

### Hermes Hindsight System (observation memory inspiration)
- Auto-retains every conversation turn to an external Hindsight API
- Server-side LLM extracts facts, observations, and entities
- Three fact types: observation (consolidated), world (raw), experience (raw)
- Default recall type is observation-only (dense per token, deduplicated)
- Session-scoped document_id with append semantics for dedup
- Configurable: `retain_every_n_turns`, `retain_async`, `recall_budget`, `recall_max_tokens`

### OpenClaw Memory System
- No explicit extraction — tracks what the agent naturally recalls during conversations
- Short-term recall store logs search results with scores, query hashes, recall counts
- Dreaming promotes snippets meeting thresholds: minScore 0.75, minRecallCount 3, minUniqueQueries 2
- Weighted scoring: frequency 0.24, relevance 0.3, diversity 0.15, recency 0.15, consolidation 0.1, conceptual 0.06
- Pure usage-based: if the agent never looked something up, it doesn't get promoted

### Key takeaway
Hermes's approach (send conversation turns to an LLM for extraction) is the closer fit for Chatty's nightly batch model. OpenClaw's usage-based promotion is elegant but requires infrastructure Chatty doesn't have (embedding search, recall tracking).
