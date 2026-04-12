"""
Chatty — Provider-agnostic AI service.

Orchestrates the AI provider call + tool execution loop and SSE streaming.
Works with any AIProvider implementation (Anthropic, OpenAI, Google Gemini).

SSE event types emitted:
  conversation_id  — new/existing conversation ID
  text             — streamed assistant text
  tool_start       — tool call beginning  {tool, tool_use_id}
  tool_args        — tool call arguments  {tool, tool_use_id, args, description}
  tool_end         — tool result          {tool, tool_use_id, result, elapsed_ms}
  confirm          — write tool needs approval {tool, args, tool_use_id, description}
  plan_ready       — plan mode completed  {plan_text, status}
  usage            — token usage          {input_tokens, output_tokens, context_window}
  title_update     — AI-generated title   {title, conversation_id}
  done             — stream complete
  error            — error message
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from core.storage import upload_config, delete_config
from core.providers.base import AIProvider, _sse
from .config import AgentConfig
from .context_manager import ContextManager
from .tool_registry import ToolRegistry
from .tool_definitions import get_tool_definitions, get_report_instructions, get_scheduling_instructions, get_qb_csv_instructions, build_writes_map, build_context_memory_map
from .tools.real_tools import load_all_real_tools

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")

# How many user messages between knowledge checkpoints
KNOWLEDGE_CHECKPOINT_EVERY = 4


# ── System prompt ─────────────────────────────────────────────────────────────

def _knowledge_management_instructions() -> str:
    return """# Knowledge Management Protocol

## CRITICAL RULES

1. **NEVER narrate saving without actually calling a tool.** Phrases like "I'll save that" or "Let me note that down" are FORBIDDEN unless immediately followed by a `write_context_file` or `append_to_context_file` tool call in the same response.

2. **Save knowledge proactively.** When the user tells you something new — a fact, preference, rule, correction, or insight — call `write_context_file` or `append_to_context_file` immediately. Do not batch saves for later.

3. **Organize knowledge by topic.** Use descriptive hyphenated filenames (e.g. `team-preferences.md`, `scheduling-rules.md`). Don't dump everything into one file.

4. **When you update a file, include the full content.** `write_context_file` overwrites the file. Always include everything that should remain. Read with `read_context_file` first if unsure.

## KNOWLEDGE CHECKPOINT

When you see a message containing "[KNOWLEDGE CHECKPOINT]", you MUST:
1. Review the conversation so far
2. Identify any new facts, preferences, rules, or insights
3. Call `write_context_file` or `append_to_context_file` for each piece of new knowledge
4. Briefly confirm what you saved (1-2 sentences max), then continue naturally

If there is genuinely nothing new to save, say so in one sentence and move on."""


def _improve_instructions(config: AgentConfig) -> str:
    """Return system prompt for knowledge improvement mode."""
    return f"""# Instructions — Knowledge Improvement Mode

You are {config.agent_name} in **Improve Mode**. Your goal is to strengthen your knowledge base — not learn from scratch, but fill gaps, fix stale info, and deepen thin coverage.

## Procedure

1. **Read all your context files** — list_context_files, then read each one.
2. **Identify the weakest spots:**
   - Thin files (< 3 meaningful lines)
   - Stale info (hasn't been updated, may be outdated)
   - Missing topics (things you should know but don't have a file for)
   - Contradictions or duplicates
3. **Rank by impact** — which gap, if filled, would help you most in daily work?
4. **Suggest the highest-impact area** to the user and ask focused questions about it.
5. **Save incrementally** — after each answer, update the relevant file immediately.
6. **Repeat** — move to the next gap until the user exits.

## Rules
- Always save with `write_context_file` or `append_to_context_file` — never narrate without saving.
- Don't re-ask things you already know. Reference existing knowledge.
- One topic at a time. Go deep, not wide.
- If the user wants to talk about something else, go with it — save what you learn."""


def _plan_mode_instructions() -> str:
    """Return system prompt addendum for plan mode."""
    return """# Plan Mode — Active

You are in Plan Mode. Investigate the user's request thoroughly before proposing changes.

## Rules
1. **Read before writing.** Use read-only tools to gather information.
2. **Think step by step.** Understand the full picture before acting.
3. **Present a structured plan** when you're ready:
   - What you'll do (numbered steps)
   - What files/data you'll modify
   - Any risks or considerations
4. When your plan is complete, call `exit_plan_mode` with the plan text.
5. Do NOT execute changes until the user approves the plan.

You are operating in read-only mode — write tools are disabled until the plan is approved."""


def _training_instructions(config: AgentConfig) -> str:
    """Return system prompt for onboarding/training mode."""
    topic_lines = []
    for i, topic in enumerate(config.training_topics, 1):
        if isinstance(topic, dict):
            topic_lines.append(f"{i}. **{topic.get('name', topic)}** — {topic.get('description', '')}. Save to `{topic.get('filename', 'notes.md')}`.")
        else:
            topic_lines.append(f"{i}. **{topic}**")
    topics_text = "\n".join(topic_lines) if topic_lines else "(No topics defined)"

    return f"""# Instructions — Getting to Know Your Human

You're still getting to know your human. This is just a normal conversation — there's no special "onboarding mode" from their perspective. Just be yourself and get to know them naturally.

## FIRST THING

Read your knowledge files. Check what you already know:
- `soul.md` — your personality
- `identity.md` — your identity
- `user.md` — about your human
- `_bootstrap.md` — if it exists, follow its guidance
- `_onboarding-progress.md` — if it exists, see where you left off

If you have progress from a previous conversation, pick up naturally. Don't say "Welcome back to onboarding" — just continue the conversation. Reference what you already know and ask about what you don't.

## HOW TO BE

This is a conversation, not a form. Don't interrogate. Don't be robotic. Just... talk.

You're figuring out who you are *together*. Be curious. Be real. React to what they say. If something is interesting, say so. If something is funny, laugh.

**Rules:**
- Never say "Great question!" or "I'd be happy to help!" or "Absolutely!" — just respond naturally.
- Never mention "onboarding", "training", "topics", or "progress tracking" to the user. This is just a conversation.
- Ask one or two questions at a time, max. Don't overwhelm.
- When you have enough on a topic, save it and move on naturally.
- If they want to talk about something else, go with it. You can come back to getting-to-know-you later.
- If they ask you to do something, just do it — you're their assistant, not an interviewer.
- Save knowledge as you go using write_context_file. Don't wait until the end.

## THINGS TO LEARN (weave these in naturally)

{topics_text}

**The personality topic is important.** This is where you figure out your voice together. Ask things like:
- "How do you want me to talk to you? Formal? Casual? Should I be blunt or diplomatic?"
- "Do you want me to have opinions, or stay neutral?"
- "What do AI assistants do that drives you crazy? I'll avoid that."
- "Should I be proactive or wait to be asked?"

Save their answers to `soul.md` — rewrite it in first person based on what you figured out together. Keep the structure but make it personal.

Also update `identity.md` and `user.md` as you learn things.

## BEHIND THE SCENES

Track your progress quietly in `_onboarding-progress.md`:

```
- [x] Topic Name
- [ ] Another Topic
- [~] Skipped Topic
```

The user never sees this — it's just for you to know where you are if the conversation spans multiple sessions.

## WHEN YOU'VE COVERED EVERYTHING

When you've naturally covered the key topics:

1. Mention something like "I feel like I'm getting a good sense of how we'll work together" — keep it natural
2. Delete `_bootstrap.md` if it still exists
3. Call `mark_onboarding_complete` silently — don't announce it to the user
4. Just keep chatting normally. The transition should be invisible."""


def _build_system_prompt(
    config: AgentConfig,
    ctx_manager: ContextManager,
    training_mode: bool = False,
    training_type: str | None = None,
    plan_mode: bool = False,
    first_user_message: str = "",
) -> str:
    """Assemble the full system prompt."""
    now_ct = datetime.now(CT_TZ)
    date_str = now_ct.strftime("%A, %B %d, %Y")
    time_str = now_ct.strftime("%I:%M %p CT")

    context = ctx_manager.load_all_context(agent_name=config.agent_name)

    personality = config.personality or (
        f"You are {config.agent_name}, a helpful personal AI assistant."
    )

    parts = [
        personality,
        "",
        "# Your Knowledge (Long-Term Memory)",
        "",
        "These are your persistent memory files. They carry forward across all conversations. "
        "Read them carefully — this is what you know. Update them actively when you learn new things.",
        "",
        context if context else "(No knowledge files yet. Create them using write_context_file.)",
        "",
    ]

    # Daily notes — inject today's note if it exists
    today_note = ctx_manager.today_daily_note_text()
    if today_note:
        parts.extend([
            "# Today's Daily Note",
            "",
            today_note,
            "",
        ])

    # Daily notes manifest — recent days for reference
    daily_manifest = ctx_manager.daily_notes_manifest(limit=30)
    if daily_manifest:
        parts.extend([
            "# Recent Daily Notes",
            "",
            daily_manifest,
            "",
        ])

    # Topic files manifest
    topic_manifest = ctx_manager.topic_files_manifest()
    if topic_manifest:
        parts.extend([
            "# Topic Files",
            "",
            topic_manifest,
            "",
        ])

    # Shared context manifest
    try:
        from core.agents.shared_context.service import get_shared_manifest
        shared_manifest = get_shared_manifest()
        if shared_manifest:
            parts.extend([
                "# Shared Knowledge (visible to all agents)",
                "",
                shared_manifest,
                "",
            ])
    except Exception:
        pass

    # Relevance pre-fetch — on first message, inject relevant context.
    # Capped at 30K chars to avoid prompt bloat on broad queries.
    if first_user_message:
        relevant = ctx_manager.relevance_prefetch(first_user_message)
        if relevant:
            prefetch_parts: list[str] = []
            prefetch_chars = 0
            max_prefetch = 30_000
            for item in relevant:
                section = f"## [{item['kind']}] {item['name']}\n\n{item['content']}"
                if prefetch_chars + len(section) > max_prefetch:
                    break
                prefetch_parts.append(section)
                prefetch_chars += len(section)
            if prefetch_parts:
                parts.append("# Likely Relevant Context")
                parts.append("")
                parts.extend(prefetch_parts)
                parts.append("")

    parts.extend([
        "# Current Session",
        "",
        f"- Date: {date_str}",
        f"- Time: {time_str}",
        "",
    ])

    if training_mode:
        if training_type == "improve":
            parts.append(_improve_instructions(config))
        else:
            parts.append(_training_instructions(config))
    else:
        parts.extend([
            "# Instructions",
            "",
            f"- You are {config.agent_name}.",
            "- If you have a `soul.md` in your knowledge files, follow it — that's your personality. It defines how you talk, what you do and don't do, and your general vibe.",
            "- Use your knowledge files to personalize every response.",
            "- When you learn something new, save it immediately.",
            "- Be genuinely helpful, not performatively helpful. Skip filler phrases.",
            "",
        ])
        parts.append(_knowledge_management_instructions())
        parts.append(_memory_instructions())
        parts.append(get_report_instructions())
        parts.append(get_scheduling_instructions())

        # QB CSV Analysis instructions (if enabled)
        from integrations.registry import is_enabled as _integration_enabled
        if _integration_enabled("qb_csv"):
            parts.append(get_qb_csv_instructions())

    if plan_mode:
        parts.append(_plan_mode_instructions())

    return "\n".join(parts)


def _memory_instructions() -> str:
    """Instructions for using the memory system (daily notes, MEMORY.md, search)."""
    return """## Memory System

You have a structured memory system beyond basic context files:

- **Daily Notes** — Use `append_daily_note` to log significant events, decisions, and information as they happen. Each entry is timestamped automatically. Optionally tag entries with a type (decision, person, task, etc.).
- **MEMORY.md** — Your living snapshot of key facts. Read with `read_memory`, update with `update_memory`. This file is automatically regenerated nightly from your daily notes.
- **Search** — Use `search_memory` to find information across all your files, daily notes, and facts.
- **Facts** — Use `add_fact` to record structured entity-relationship facts (e.g. "John Smith works at Acme Corp"). Query with `query_facts`.
- **Shared Context** — Use `list_shared_context` / `read_shared_context` / `write_shared_context` to access knowledge shared across all agents.

Guidelines:
- Log important events and decisions to daily notes as they happen
- Use search_memory before saying "I don't know" — you might have recorded it
- When you learn structured facts (people, relationships, dates), use add_fact"""


# ── Background GCS sync ────────────────────────────────────────────────────────

def _bg_upload(filepath, name, prefix):
    try:
        upload_config(filepath, name, prefix=prefix)
    except Exception:
        logger.warning("Background GCS upload failed for %s", name, exc_info=True)


def _bg_delete(name, prefix):
    try:
        delete_config(name, prefix=prefix)
    except Exception:
        logger.warning("Background GCS delete failed for %s", name, exc_info=True)


def _sync_context_after_tool(tool_name: str, tool_result: dict, ctx_manager: ContextManager):
    """Sync files to GCS after context file mutations (non-blocking)."""
    data_dir = ctx_manager.data_dir
    gcs_prefix = ctx_manager.gcs_prefix

    if tool_name in ("write_context_file", "append_to_context_file"):
        if tool_result.get("ok"):
            filename = tool_result.get("filename", "")
            if filename:
                filepath = data_dir / filename
                if filepath.exists():
                    threading.Thread(
                        target=_bg_upload, args=(filepath, filename, gcs_prefix),
                        daemon=True,
                    ).start()

    elif tool_name == "delete_context_file":
        if tool_result.get("deleted"):
            filename = tool_result.get("filename", "")
            if filename:
                threading.Thread(
                    target=_bg_delete, args=(filename, gcs_prefix),
                    daemon=True,
                ).start()


# ── Smart title ───────────────────────────────────────────────────────────────

async def _maybe_smart_title(
    persist: bool,
    conversation_id: str | None,
    messages: list[dict],
    accumulated_text: str,
    chat_service,
    anthropic_api_key: str,
) -> str | None:
    """Generate a smart title after the 3rd user message. Returns SSE string or None."""
    if not persist or not conversation_id or not chat_service:
        return None
    user_msg_count = sum(1 for m in messages if m.get("role") == "user")
    if user_msg_count != 3:
        return None
    try:
        all_msgs = messages + [{"role": "assistant", "content": accumulated_text}]
        new_title = await asyncio.to_thread(
            chat_service.generate_smart_title, conversation_id, all_msgs, anthropic_api_key
        )
        if new_title:
            return _sse({"type": "title_update", "title": new_title, "conversation_id": conversation_id})
    except Exception as e:
        logger.warning("Smart auto-title failed: %s", e)
    return None


# ── Build tool kind map ────────────────────────────────────────────────────────

def _build_kind_map(tool_defs: list[dict]) -> dict[str, str]:
    """Map tool name → kind for dispatch."""
    return {t["name"]: t.get("kind", "context") for t in tool_defs}


# ── Main chat coroutine ────────────────────────────────────────────────────────

async def chat(
    config: AgentConfig,
    provider: AIProvider,
    registry: ToolRegistry,
    ctx_manager: ContextManager,
    messages: list[dict],
    training_mode: bool = False,
    training_type: str | None = None,
    plan_mode: bool = False,
    conversation_id: str | None = None,
    chat_service=None,
    anthropic_api_key: str = "",
    integration_tool_defs: list[dict] | None = None,
    tool_mode: str = "normal",
    approved_tool: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Stream a chat response as SSE events.

    Yields SSE-formatted strings: "data: {json}\\n\\n"

    Args:
        config: Agent configuration
        provider: AI provider instance (Anthropic, OpenAI, or Google)
        registry: Tool registry for dispatching tool calls
        ctx_manager: Context file manager
        messages: Full conversation history
        training_mode: If True, injects onboarding system prompt
        training_type: 'topic' (default training) or 'improve' (knowledge refinement)
        plan_mode: If True, forces read-only mode and injects plan instructions
        conversation_id: Existing conversation ID (None to create new)
        chat_service: Optional ChatHistoryService for persistence
        anthropic_api_key: For smart title generation (uses haiku, optional)
        integration_tool_defs: Extra tool definitions from enabled integrations
        tool_mode: 'read-only', 'normal', or 'power'
        approved_tool: Previously confirmed tool execution result to reconstruct
    """
    # Validate tool_mode
    if tool_mode not in ("read-only", "normal", "power"):
        tool_mode = "normal"

    # Training mode forces power (no confirmations needed during onboarding)
    if training_mode:
        tool_mode = "power"

    # Plan mode forces read-only
    if plan_mode:
        tool_mode = "read-only"

    persist = not training_mode and chat_service is not None

    # ── Get tool definitions ──────────────────────────────────────────
    # Load agent-created real tools from filesystem
    real_tools_dir = str(Path(config.context_dir).parent / "real_tools")
    dynamic_real_tools = load_all_real_tools(real_tools_dir)

    tool_defs = get_tool_definitions(
        gmail_enabled=config.gmail_enabled,
        calendar_enabled=config.calendar_enabled,
        integration_tools=integration_tool_defs,
        dynamic_real_tools=dynamic_real_tools or None,
    )
    kind_map = _build_kind_map(tool_defs)
    writes_map = build_writes_map(tool_defs)
    cm_map = build_context_memory_map(tool_defs)

    # ── Read-only mode: filter out write tools (except context_memory) ──
    if tool_mode == "read-only":
        tool_defs = [
            t for t in tool_defs
            if not t.get("writes", False) or t.get("context_memory", False)
        ]

    # Strip internal fields before sending to provider
    _internal_fields = {"kind", "writes", "context_memory"}
    provider_tools = [{k: v for k, v in t.items() if k not in _internal_fields} for t in tool_defs]

    # ── Chat history persistence ──────────────────────────────────────
    if persist:
        try:
            if not conversation_id:
                conv = chat_service.create_conversation()
                conversation_id = conv["id"]
                last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
                if last_user:
                    chat_service.auto_title(conversation_id, last_user.get("content", ""))

            yield _sse({"type": "conversation_id", "id": conversation_id})

            last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            if last_user:
                chat_service.save_message(
                    conversation_id=conversation_id,
                    msg_id=str(uuid.uuid4()),
                    role="user",
                    content=last_user.get("content", ""),
                )
        except Exception as e:
            logger.warning("Chat history save (user msg) failed: %s", e)

    # ── Maybe inject knowledge checkpoint ────────────────────────────
    current_messages = list(messages)
    if not training_mode:
        user_count = sum(1 for m in current_messages if m.get("role") == "user")
        if user_count > 0 and user_count % KNOWLEDGE_CHECKPOINT_EVERY == 0:
            last = current_messages[-1] if current_messages else None
            if last and last.get("role") == "user":
                current_messages[-1] = {
                    **last,
                    "content": last.get("content", "") + "\n\n[KNOWLEDGE CHECKPOINT]",
                }

    # ── Plan mode: add virtual exit_plan_mode tool ──────────────────
    if plan_mode:
        exit_plan_tool = {
            "name": "exit_plan_mode",
            "description": "Call this when your investigation is complete and you have a structured plan to present. Include the full plan as the 'plan' argument.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "string",
                        "description": "The full structured plan in markdown format",
                    },
                },
                "required": ["plan"],
            },
            "kind": "plan",
            "writes": False,
        }
        tool_defs.append(exit_plan_tool)
        kind_map["exit_plan_mode"] = "plan"

    # ── Build system prompt ───────────────────────────────────────────
    # Determine first user message for relevance pre-fetch
    first_user_msg = ""
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if len(user_msgs) == 1:
        first_user_msg = user_msgs[0].get("content", "")

    system_prompt = _build_system_prompt(
        config, ctx_manager,
        training_mode=training_mode,
        training_type=training_type,
        plan_mode=plan_mode,
        first_user_message=first_user_msg,
    )

    # Append integration-specific instructions
    if integration_tool_defs:
        odoo_tools = [t for t in integration_tool_defs if t.get("name", "").startswith("odoo_")]
        if odoo_tools:
            system_prompt += (
                "\n\n# Odoo ERP Tools Available\n\n"
                "You have Odoo tools for CRM, helpdesk, sales, purchasing, contacts, projects, "
                "accounting, manufacturing, inventory, quality, and maintenance. "
                "When the user asks about orders, tickets, leads, invoices, projects, equipment, "
                "or quality checks, use the appropriate odoo_ tool. "
                "For CRM: use odoo_search_leads, odoo_get_pipeline_summary, odoo_create_lead, etc. "
                "For helpdesk: use odoo_search_tickets, odoo_send_ticket_reply, etc. "
                "For generic queries against any model: use odoo_query."
            )

        crm_tools = [t for t in integration_tool_defs if t.get("name", "").startswith("crm_")]
        if crm_tools:
            system_prompt += (
                "\n\n# CRM Tools Available\n\n"
                "You have CRM tools for managing contacts, deals, tasks, and activities. "
                "When the user mentions a customer, prospect, deal, or follow-up, proactively use CRM tools. "
                "After logging a meeting or call, suggest creating follow-up tasks. "
                "Use crm_dashboard when the user asks for an overview or summary of their business."
            )

        qbo_tools = [t for t in integration_tool_defs if t.get("name", "").startswith("qbo_")]
        if qbo_tools:
            system_prompt += (
                "\n\n# QuickBooks Online Tools Available\n\n"
                "You have QuickBooks tools for invoicing, payments, estimates, customers, vendors, items, "
                "and financial reports.\n\n"
                "**Key patterns:**\n"
                "- Use `qbo_query` to look up IDs first: `SELECT Id, DisplayName FROM Customer WHERE DisplayName LIKE '%Smith%'`\n"
                "- Use `qbo_get_entity` for full details of any record.\n"
                "- For invoices: create with `qbo_create_invoice`, then optionally send with `qbo_send_invoice`.\n"
                "- For estimates: create with `qbo_create_estimate`, then send with `qbo_send_estimate`.\n"
                "- To record payments: use `qbo_record_payment`, optionally link to invoice IDs.\n"
                "- For customers, vendors, items, bills: use `qbo_create_entity` / `qbo_update_entity`.\n"
                "- **Never guess IDs** — always query first to find the correct Customer, Item, or Invoice ID.\n"
                "- Amounts are in the company's home currency.\n"
            )

    accumulated_text = ""

    # ── Reconstruct approved tool in message history ──────────────────
    if approved_tool:
        at_tool = approved_tool.get("tool", "")
        at_args = approved_tool.get("args", {})
        at_id = approved_tool.get("toolUseId", str(uuid.uuid4()))
        at_result = approved_tool.get("result", {})

        # Build fake tool_calls and results for provider reconstruction
        fake_tc = [{"name": at_tool, "id": at_id, "args": at_args}]
        fake_results = [{
            "tool_use_id": at_id,
            "tool_name": at_tool,
            "content": json.dumps(at_result),
        }]

        # Remove the "[Approved]" user message (last in the list) since the
        # provider needs tool_use/tool_result blocks instead
        if (current_messages
            and current_messages[-1].get("role") == "user"
            and str(current_messages[-1].get("content", "")).startswith("[Approved]")):
            current_messages = current_messages[:-1]

        # Reconstruct via provider abstraction
        current_messages = provider.add_tool_results(current_messages, fake_tc, fake_results)

    # ── Tool execution loop ───────────────────────────────────────────
    max_iterations = 20
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        tool_calls_this_turn: list[dict] = []
        turn_text = ""

        # Stream one turn from the provider
        async for event in provider.stream_turn(current_messages, provider_tools, system_prompt):
            etype = event.get("type")

            if etype == "text":
                turn_text += event["text"]
                accumulated_text += event["text"]
                yield _sse({"type": "text", "text": event["text"]})

            elif etype == "tool_start":
                yield _sse({
                    "type": "tool_start",
                    "tool": event["tool"],
                    "tool_use_id": event["tool_use_id"],
                })

            elif etype == "tool_args":
                tool_name_for_desc = event["tool"]
                tool_desc = next(
                    (t.get("description", "") for t in tool_defs if t["name"] == tool_name_for_desc),
                    "",
                )
                yield _sse({
                    "type": "tool_args",
                    "tool": event["tool"],
                    "tool_use_id": event["tool_use_id"],
                    "args": event.get("args", {}),
                    "description": tool_desc,
                })

            elif etype == "_turn_complete":
                tool_calls_this_turn = event.get("tool_calls", [])
                stop_reason = event.get("stop_reason", "stop")

                # Emit usage event
                usage = event.get("usage", {})
                if usage:
                    yield _sse({
                        "type": "usage",
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "context_window": 200000,  # Default context window
                    })

                # Save assistant turn to history
                if persist and turn_text and conversation_id:
                    try:
                        chat_service.save_message(
                            conversation_id=conversation_id,
                            msg_id=str(uuid.uuid4()),
                            role="assistant",
                            content=turn_text,
                        )
                    except Exception as e:
                        logger.warning("Chat history save (assistant) failed: %s", e)

                # Check for smart title
                if persist and conversation_id:
                    title_sse = await _maybe_smart_title(
                        persist, conversation_id, current_messages,
                        accumulated_text, chat_service, anthropic_api_key
                    )
                    if title_sse:
                        yield title_sse

                # If no tool calls, we're done
                if stop_reason != "tool_use" or not tool_calls_this_turn:
                    yield _sse({"type": "done"})
                    return

            elif etype == "error":
                yield _sse({"type": "error", "error": event.get("error", "Unknown error")})
                return

        # ── Execute tool calls ────────────────────────────────────────
        if not tool_calls_this_turn:
            yield _sse({"type": "done"})
            return

        results = []
        has_pending_confirmation = False

        for tc in tool_calls_this_turn:
            tool_name = tc.get("name", "")
            tool_use_id = tc.get("id", "")
            tool_args = tc.get("args", {})
            kind = kind_map.get(tool_name, "context")

            # ── Plan mode: intercept exit_plan_mode ──
            if tool_name == "exit_plan_mode" and plan_mode:
                plan_text = tool_args.get("plan", "")
                yield _sse({
                    "type": "plan_ready",
                    "plan_text": plan_text,
                    "status": "pending",
                })
                # Feed a result back so provider can wrap up
                results.append({
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "content": json.dumps({"ok": True, "message": "Plan presented to user for approval."}),
                })
                # Let the AI do one more turn to narrate, then stop
                current_messages = provider.add_tool_results(current_messages, tool_calls_this_turn, results)
                async for event in provider.stream_turn(current_messages, provider_tools, system_prompt):
                    etype = event.get("type")
                    if etype == "text":
                        accumulated_text += event["text"]
                        yield _sse({"type": "text", "text": event["text"]})
                    elif etype == "_turn_complete":
                        break
                yield _sse({"type": "done"})
                return

            # ── Normal mode: intercept write tools (not context_memory) ──
            is_write = writes_map.get(tool_name, False)
            is_cm = cm_map.get(tool_name, False)

            if tool_mode == "normal" and is_write and not is_cm:
                # Get human-readable description
                tool_desc = next(
                    (t.get("description", tool_name) for t in tool_defs if t["name"] == tool_name),
                    tool_name,
                )
                yield _sse({
                    "type": "confirm",
                    "tool": tool_name,
                    "args": tool_args,
                    "tool_use_id": tool_use_id,
                    "description": tool_desc,
                })

                # Feed pending result to provider so it can describe the action
                result = {"status": "pending_user_approval", "message": f"Waiting for user to approve: {tool_name}"}
                result_str = json.dumps(result)
                results.append({
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "content": result_str,
                })
                has_pending_confirmation = True
                continue

            t_start = time.time()
            result = await registry.execute_tool(tool_name, tool_args, kind)
            elapsed_ms = int((time.time() - t_start) * 1000)

            # Sync context files to GCS
            _sync_context_after_tool(tool_name, result, ctx_manager)

            result_str = json.dumps(result)
            results.append({
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "content": result_str,
            })

            yield _sse({
                "type": "tool_end",
                "tool": tool_name,
                "tool_use_id": tool_use_id,
                "result": result,
                "elapsed_ms": elapsed_ms,
            })

        # Append tool results to messages for next turn
        current_messages = provider.add_tool_results(current_messages, tool_calls_this_turn, results)

        # If we have a pending confirmation, do one more streaming turn
        # to let the AI describe the pending action, then stop
        if has_pending_confirmation:
            async for event in provider.stream_turn(current_messages, provider_tools, system_prompt):
                etype = event.get("type")
                if etype == "text":
                    accumulated_text += event["text"]
                    yield _sse({"type": "text", "text": event["text"]})
                elif etype == "_turn_complete":
                    break
            yield _sse({"type": "done"})
            return

    # Exceeded max iterations
    yield _sse({"type": "error", "error": "Tool loop exceeded maximum iterations"})


# ── Non-streaming sync execution (for Telegram / messaging channels) ──────────

async def run_sync(
    config: AgentConfig,
    provider: AIProvider,
    registry: ToolRegistry,
    ctx_manager: ContextManager,
    messages: list[dict],
    chat_service=None,
    conversation_id: str | None = None,
    integration_tool_defs: list[dict] | None = None,
) -> str:
    """Run an agent synchronously, returning the final text response.

    This is the non-streaming counterpart to ``chat()``.  Used by inbound
    messaging integrations (Telegram) where the caller needs a single text
    response rather than an SSE stream.

    Works with any AIProvider (Anthropic, OpenAI, Google Gemini).
    Supports full multi-turn tool execution loop.
    """
    # Build tool definitions (same as streaming path)
    real_tools_dir = str(Path(config.context_dir).parent / "real_tools")
    dynamic_real_tools = load_all_real_tools(real_tools_dir)

    tool_defs = get_tool_definitions(
        gmail_enabled=config.gmail_enabled,
        calendar_enabled=config.calendar_enabled,
        integration_tools=integration_tool_defs,
        dynamic_real_tools=dynamic_real_tools or None,
    )
    kind_map = _build_kind_map(tool_defs)

    # Strip internal fields before sending to provider
    _internal_fields = {"kind", "writes", "context_memory"}
    provider_tools = [{k: v for k, v in t.items() if k not in _internal_fields} for t in tool_defs]

    # Build system prompt
    system_prompt = _build_system_prompt(config, ctx_manager)

    # Append integration-specific instructions (same as chat())
    if integration_tool_defs:
        odoo_tools = [t for t in integration_tool_defs if t.get("name", "").startswith("odoo_")]
        if odoo_tools:
            system_prompt += (
                "\n\n# Odoo ERP Tools Available\n\n"
                "You have Odoo tools for CRM, helpdesk, sales, purchasing, contacts, projects, "
                "and timesheets. Use them when the user asks about business operations."
            )

        qbo_tools = [t for t in integration_tool_defs if t.get("name", "").startswith("qbo_")]
        if qbo_tools:
            system_prompt += (
                "\n\n# QuickBooks Online Tools Available\n\n"
                "You have QuickBooks tools for invoicing, payments, estimates, customers, vendors, items, "
                "and financial reports.\n\n"
                "**Key patterns:**\n"
                "- Use `qbo_query` to look up IDs first: `SELECT Id, DisplayName FROM Customer WHERE DisplayName LIKE '%Smith%'`\n"
                "- Use `qbo_get_entity` for full details of any record.\n"
                "- For invoices: create with `qbo_create_invoice`, then optionally send with `qbo_send_invoice`.\n"
                "- For estimates: create with `qbo_create_estimate`, then send with `qbo_send_estimate`.\n"
                "- To record payments: use `qbo_record_payment`, optionally link to invoice IDs.\n"
                "- For customers, vendors, items, bills: use `qbo_create_entity` / `qbo_update_entity`.\n"
                "- **Never guess IDs** — always query first to find the correct Customer, Item, or Invoice ID.\n"
                "- Amounts are in the company's home currency.\n"
            )

    # Chat history — save user message
    persist = chat_service is not None
    if persist:
        try:
            if not conversation_id:
                conv = chat_service.create_conversation()
                conversation_id = conv["id"]

            last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
            if last_user:
                chat_service.save_message(
                    conversation_id=conversation_id,
                    msg_id=str(uuid.uuid4()),
                    role="user",
                    content=last_user.get("content", ""),
                )
        except Exception as e:
            logger.warning("run_sync: chat history save (user msg) failed: %s", e)

    current_messages = list(messages)
    accumulated_text = ""
    max_iterations = 20

    for iteration in range(max_iterations):
        tool_calls_this_turn: list[dict] = []
        turn_text = ""
        stop_reason = "stop"

        # Stream one turn, collecting all events
        async for event in provider.stream_turn(current_messages, provider_tools, system_prompt):
            etype = event.get("type")

            if etype == "text":
                turn_text += event["text"]
                accumulated_text += event["text"]

            elif etype == "_turn_complete":
                tool_calls_this_turn = event.get("tool_calls", [])
                stop_reason = event.get("stop_reason", "stop")

            elif etype == "error":
                logger.error("run_sync: provider error: %s", event.get("error"))
                return accumulated_text or "I encountered an error. Please try again."

        # Save assistant turn to history
        if persist and turn_text and conversation_id:
            try:
                chat_service.save_message(
                    conversation_id=conversation_id,
                    msg_id=str(uuid.uuid4()),
                    role="assistant",
                    content=turn_text,
                )
            except Exception as e:
                logger.warning("run_sync: chat history save (assistant) failed: %s", e)

        # If no tool calls, we're done
        if stop_reason != "tool_use" or not tool_calls_this_turn:
            break

        # Execute tool calls (power mode — no confirmation flow for messaging)
        results = []
        for tc in tool_calls_this_turn:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            tool_use_id = tc.get("id", "")
            kind = kind_map.get(tool_name, "context")

            try:
                result = await registry.execute_tool(tool_name, tool_args, kind)
                _sync_context_after_tool(tool_name, result, ctx_manager)
            except Exception as e:
                logger.error("run_sync: tool %s failed: %s", tool_name, e)
                result = {"error": str(e)}

            results.append({
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "content": json.dumps(result),
            })

        # Append tool results for next turn
        current_messages = provider.add_tool_results(current_messages, tool_calls_this_turn, results)

    return accumulated_text or "I had trouble generating a response. Please try again."
