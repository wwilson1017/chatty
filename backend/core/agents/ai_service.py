"""
Chatty — Provider-agnostic AI service.

Orchestrates the AI provider call + tool execution loop and SSE streaming.
Works with any AIProvider implementation (Anthropic, OpenAI, Google Gemini).

SSE event types emitted:
  conversation_id  — new/existing conversation ID
  text             — streamed assistant text
  tool_start       — tool call beginning  {tool, tool_use_id}
  tool_args        — tool call arguments  {tool, tool_use_id, args}
  tool_end         — tool result          {tool, tool_use_id, result, elapsed_ms}
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
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

from core.storage import upload_config, delete_config
from core.providers.base import AIProvider, _sse
from .config import AgentConfig
from .context_manager import ContextManager
from .tool_registry import ToolRegistry
from .tool_definitions import get_tool_definitions, get_report_instructions, get_scheduling_instructions

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


def _training_instructions(config: AgentConfig) -> str:
    """Return system prompt for onboarding/training mode."""
    topic_lines = []
    for i, topic in enumerate(config.training_topics, 1):
        if isinstance(topic, dict):
            topic_lines.append(f"{i}. **{topic.get('name', topic)}** — {topic.get('description', '')}. Save to `{topic.get('filename', 'notes.md')}`.")
        else:
            topic_lines.append(f"{i}. **{topic}**")
    topics_text = "\n".join(topic_lines) if topic_lines else "(No topics defined)"

    return f"""# Instructions — ONBOARDING MODE

You are in ONBOARDING MODE. Your job is to interview the user to learn about them so you can be more effective.

## PROCEDURE

1. First, call list_context_files and read any existing files to see what you already know.
2. Check for _onboarding-progress.md. If it doesn't exist, create it with the full topic checklist. If it exists, read it to find where you left off.
3. Work through topics one at a time. For each:
   - Ask clear, specific questions (one or two at a time)
   - When you have enough info, confirm by summarizing back what you heard
   - Save answers to the appropriate context file
   - Mark the topic complete in _onboarding-progress.md
4. If the user says "skip", mark the topic as skipped and move on.
5. If the user says "done" or "exit", summarize progress and end gracefully.

## TOPICS

{topics_text}

## PROGRESS FILE FORMAT (_onboarding-progress.md)

```
- [x] Topic Name
- [ ] Another Topic
- [~] Skipped Topic
```

Use [x] for done, [ ] for pending, [~] for skipped.

## STYLE

- Be friendly and efficient. Ask one topic at a time.
- Use tables or structured formats when saving data.
- Save incrementally using append_to_context_file as you learn — don't wait until the end."""


def _build_system_prompt(
    config: AgentConfig,
    ctx_manager: ContextManager,
    training_mode: bool = False,
) -> str:
    """Assemble the full system prompt."""
    now_ct = datetime.now(CT_TZ)
    date_str = now_ct.strftime("%A, %B %d, %Y")
    time_str = now_ct.strftime("%I:%M %p CT")

    context = ctx_manager.load_all_context()

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
        "# Current Session",
        "",
        f"- Date: {date_str}",
        f"- Time: {time_str}",
        "",
    ]

    if training_mode:
        parts.append(_training_instructions(config))
    else:
        parts.extend([
            "# Instructions",
            "",
            f"- You are {config.agent_name}. Be helpful, concise, and proactive.",
            "- Use your knowledge files to personalize every response.",
            "- When you learn something new, save it immediately.",
            "",
        ])
        parts.append(_knowledge_management_instructions())
        parts.append(get_report_instructions())
        parts.append(get_scheduling_instructions())

    return "\n".join(parts)


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
    conversation_id: str | None = None,
    chat_service=None,
    anthropic_api_key: str = "",
    integration_tool_defs: list[dict] | None = None,
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
        conversation_id: Existing conversation ID (None to create new)
        chat_service: Optional ChatHistoryService for persistence
        anthropic_api_key: For smart title generation (uses haiku, optional)
        integration_tool_defs: Extra tool definitions from enabled integrations
    """
    persist = not training_mode and chat_service is not None

    # ── Get tool definitions ──────────────────────────────────────────
    tool_defs = get_tool_definitions(
        gmail_enabled=config.gmail_enabled,
        calendar_enabled=config.calendar_enabled,
        integration_tools=integration_tool_defs,
    )
    kind_map = _build_kind_map(tool_defs)

    # Strip internal 'kind' field before sending to provider
    provider_tools = [{k: v for k, v in t.items() if k != "kind"} for t in tool_defs]

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

    # ── Build system prompt ───────────────────────────────────────────
    system_prompt = _build_system_prompt(config, ctx_manager, training_mode=training_mode)

    # Append integration-specific instructions
    if integration_tool_defs:
        crm_tools = [t for t in integration_tool_defs if t.get("name", "").startswith("crm_")]
        if crm_tools:
            system_prompt += (
                "\n\n# CRM Tools Available\n\n"
                "You have CRM tools for managing contacts, deals, tasks, and activities. "
                "When the user mentions a customer, prospect, deal, or follow-up, proactively use CRM tools. "
                "After logging a meeting or call, suggest creating follow-up tasks. "
                "Use crm_dashboard when the user asks for an overview or summary of their business."
            )

    accumulated_text = ""

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
                yield _sse({
                    "type": "tool_args",
                    "tool": event["tool"],
                    "tool_use_id": event["tool_use_id"],
                    "args": event.get("args", {}),
                })

            elif etype == "_turn_complete":
                tool_calls_this_turn = event.get("tool_calls", [])
                stop_reason = event.get("stop_reason", "stop")

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
        for tc in tool_calls_this_turn:
            tool_name = tc.get("name", "")
            tool_use_id = tc.get("id", "")
            tool_args = tc.get("args", {})
            kind = kind_map.get(tool_name, "context")

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

    # Exceeded max iterations
    yield _sse({"type": "error", "error": "Tool loop exceeded maximum iterations"})
