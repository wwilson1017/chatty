# OB1 Integration Research

Notes from a research session exploring how to incorporate ideas from
[OB1](https://github.com/NateBJones-Projects/OB1) into Chatty.

## Background

### What OB1 is

OB1 ("Open Brain") is an infrastructure layer that creates a unified, portable
memory system for AI tools. Tagline: *"The infrastructure layer for your
thinking. One database, one AI gateway, one chat channel."*

It solves fragmented AI memory by consolidating thoughts into a single
searchable store that any AI client (Claude, ChatGPT, Cursor, etc.) can read
and write through a Model Context Protocol (MCP) server.

**Tech stack:**
- Postgres + pgvector (via Supabase, or self-hosted)
- TypeScript/JavaScript edge functions for ingestion + embedding
- MCP server as the AI-facing interface
- Slack/Discord capture bots for quick ingestion
- Import recipes for ChatGPT, Obsidian, Gmail, Twitter/X, Instagram, etc.
- SvelteKit / Next.js dashboard options

**How it works:**
1. User spins up a Supabase project (or self-hosts on Kubernetes); OB1 ships
   SQL migrations creating tables like `thoughts`, `skills`, `sources`.
2. Content is ingested (Slack DM, import recipe, etc.). Edge functions embed
   each thought and fingerprint it for dedup.
3. An MCP server exposes tools like `search_thoughts`, `capture`, `list_skills`.
4. Any MCP-aware AI client connects to the same endpoint, so memory is shared
   and portable across tools.
5. "Skill packs" are rows in a table — reusable prompt recipes that agents can
   pull down and execute. Skills can be auto-generated from work sessions.

### What Supabase is

Open-source Firebase alternative — managed Postgres with batteries:
- Real Postgres + pgvector for embeddings/similarity search
- Auto-generated REST and GraphQL APIs (PostgREST)
- Row-level security
- Edge Functions (Deno-based serverless)
- Auth, file storage, realtime subscriptions

You get a connection string + HTTPS API URL + JWT, and you can read/write your
data from anywhere. Hosted at supabase.com or self-hostable.

## Why this matters for Chatty

Chatty already has the bones: `core/agents/memory/` (FTS5 search),
`shared_context/`, `dreaming/` (context archival), and a pluggable
`agents/import_service/`. OB1 overlaps significantly but adds vector search,
content fingerprinting, more import recipes, skill packs, and — most
importantly — **portability across AI tools** via MCP.

The hard constraint from `CLAUDE.md`: no required Postgres, no external
services. Chatty must remain SQLite-only and one-click-deployable on Railway.

## Approach 1 — Integrate with OB1 directly

Add OB1 as an optional integration (mirroring `integrations/quickbooks/` or
`integrations/google/`). User connects their own Supabase/OB1 project; agents
get tools like `ob1_search_thoughts`, `ob1_capture`, `ob1_list_skills` via the
existing `_load_integration_tools()` path.

| Option | What it does | Tradeoff |
|---|---|---|
| **A. Tool-only** | Agents call OB1 tools when they choose to. Local memory unchanged. | Simplest, fully optional. But two parallel memory systems. |
| **B. Write-through mirror** | When OB1 is connected, every `memory.save()` and `shared_context.write()` also writes to OB1. Reads stay local. | Portability "just works." Adds latency + a Supabase failure mode. |
| **C. Canonical when connected** | OB1 *replaces* the local memory store; SQLite becomes a cache. | Maximum portability. Violates no-external-services principle and is the biggest refactor. |

Recommendation if going this route: **B + treat OB1's MCP server as the
connection surface** (Chatty becomes an MCP client) rather than talking to
Supabase directly.

## Approach 2 — Absorb the good ideas (recommended)

Don't depend on OB1; cherry-pick its best ideas into Chatty's existing
modules.

### Tier 1 — high leverage, fits cleanly

| Idea from OB1 | Where it lands in Chatty |
|---|---|
| **Semantic / vector search on memory** (alongside existing FTS5) | `core/agents/memory/db.py` — add `sqlite-vec` (pure-SQLite extension, no Postgres). Hybrid retrieval = FTS5 + vector. |
| **Content fingerprinting + dedup** | `agents/import_service/scrubber.py` — hash each chunk on import, skip dupes. |
| **More import recipes** (ChatGPT export, Obsidian vault, Twitter archive, Instagram archive) | New files under `agents/import_service/adapters/`. ChatGPT export is highest demand. |
| **Skill packs** as portable JSON | New `core/agents/skills/` module — reusable prompt/recipe bundles. Start local; marketplace later. |

### Tier 2 — worthwhile but bigger surface

- **Unified "Thoughts" view** in the dashboard — a tab listing everything
  across sources with vector search.
- **Quick-capture inbox** — a dedicated triage queue separate from
  `shared_context` so raw thoughts don't pollute agent context. Telegram /
  WhatsApp already provide the channel.
- **Self-improving skills** — agent notices a repeated workflow and offers
  "save as skill?". Novel UX, needs care to avoid noise.

### Tier 3 — the strategic move

**Make Chatty itself an MCP server.** OB1's whole pitch is "your memory,
portable across Claude / Cursor / ChatGPT." If Chatty exposes its `memory`,
`shared_context`, and skills via an MCP endpoint, **Chatty becomes the OB1**,
except free, open source, and with a real UI. No Supabase ever required.
Sharpens Chatty's value prop: *"your AI brain, queryable from every tool you
use."*

### Skip / defer

- Adopting Supabase/Postgres — against `CLAUDE.md`'s no-external-services
  principle; `sqlite-vec` covers ~95% of the value.
- Slack / Discord capture bots — Telegram + WhatsApp already serve that role
  for the small-business audience.

## Suggested first slice

Tier 1 rows 1+2 in a single PR:

1. Add `sqlite-vec` dependency, verify it loads on Railway's image.
2. New `memory_vectors` table + embedding pipeline.
3. Hybrid-rank FTS5 + vector results in `memory/search_tools.py`.
4. Fingerprint-based dedup in `agents/import_service/scrubber.py`.

A few hundred lines, makes Chatty's memory noticeably smarter, no
external-service dependencies. Validate `sqlite-vec` on Railway in a 10-minute
spike before committing.

## Reference repos worth studying

### Memory layers (the OB1 category, more mature)

| Repo | What to learn |
|---|---|
| **mem0** (`mem0ai/mem0`) | Reference implementation for "memory as a service." Hybrid vector + graph + facts. Best blueprint for what `core/agents/memory/` could become. |
| **Letta** (`letta-ai/letta`, formerly MemGPT) | Self-editing memory blocks; hierarchical core/archival memory split — directly relevant to `dreaming/`. |
| **Zep** + **Graphiti** (`getzep/*`) | Temporal knowledge graphs — memory that understands *when* things happened. |
| **Cognee** (`topoteretes/cognee`) | Research-flavored graph + vector blend. Skim, don't copy. |

### Multi-provider AI platforms (Chatty's broader category)

| Repo | What to learn — and what to avoid |
|---|---|
| **AnythingLLM** (`Mintplex-Labs/anything-llm`) | Closest direct analog. Steal: connector breadth, workspace-as-isolation. Avoid: enterprise-leaning bloat. |
| **LibreChat** (`danny-avila/LibreChat`) | Most polished multi-provider chat UI. Reference for provider abstraction, MCP client integration, plugins. |
| **Khoj** (`khoj-ai/khoj`) | Closest spiritual sibling — single-user, local-first, second-brain angle, multi-provider. |
| **Open WebUI** (`open-webui/open-webui`) | Self-hosted UX patterns, plugin/tool/function-calling architecture, "Pipelines" concept. |
| **LobeChat** (`lobehub/lobe-chat`) | UI patterns and an agent marketplace concept. |

### Personal capture / "thoughts" inbox

| Repo | What to learn |
|---|---|
| **Memos** (`usememos/memos`) | Lightweight thought-capture UX. |
| **Karakeep** (`karakeep-app/karakeep`, formerly Hoarder) | AI auto-tagging on ingest — applicable to `import_service`. |

### Connectors / RAG infrastructure

| Repo | What to learn |
|---|---|
| **Onyx** (`onyx-dot-app/onyx`, formerly Danswer) | Best-in-class open-source connector library (Gmail, Drive, Slack, Notion, Confluence). Copy adapter patterns, not architecture. |
| **LlamaIndex** (`run-llama/llama_index`) | Ingestion pipelines and retrieval strategies (hybrid search, re-ranking, sub-document chunking). Read for ideas; don't take as a dep. |

### Agent orchestration

| Repo | What to learn |
|---|---|
| **CrewAI** (`crewAIInc/crewAI`) | Role-based multi-agent collaboration patterns. Adjacent to `paperclip`. |
| **AutoGen** (`microsoft/autogen`) | Conversation-based agent orchestration. Academic but influential. |

### Top three to study first

1. **mem0** — what semantic memory should feel like.
2. **Letta** — self-editing memory blocks and the dreaming/archival pattern.
3. **AnythingLLM** — what Chatty looks like if it grows up "wrong"
   (enterprise-heavy), so we know what to avoid while mining for ideas.

## Guiding filter

Most of these references are more mature than Chatty in their narrow domain.
The temptation is to absorb everything and lose focus. Chatty's edge is
**"a personal AI for small-business owners that deploys in one click"** —
every borrowed idea should pass that filter.
