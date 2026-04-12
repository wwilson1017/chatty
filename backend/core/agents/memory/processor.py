"""Memory processor — nightly daily-note summarizer and weekly MEMORY.md consolidator.

Both functions are called from the scheduled_actions processor. Each runs
one Claude API call and updates the agent's data dir (with GCS sync).
"""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.agents.context_manager import ContextManager
from core.agents.tools.memory_tools import consolidate_memory

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")

# Cap on chat content sent to the daily summarizer — don't include more
# than a day's worth of actual chat. In practice a single day of traffic
# is well under this limit.
_MAX_CHAT_INPUT_CHARS = 80_000


def process_daily_note_summary(
    agent_name: str,
    ctx_manager: ContextManager,
    chat_service,
    api_key: str,
) -> dict:
    """Summarize yesterday's chat traffic into the daily note file.

    Appends an `## End-of-day summary` section to
    `daily/YYYY-MM-DD.md` for yesterday (Central Time), with a single
    `Headline:` line at the top so the manifest surfaces a one-line
    recap for the agent's future prompts.

    If there are no messages for yesterday, no-ops.
    """
    start = time.monotonic()
    yesterday = (datetime.now(CT_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    if chat_service is None:
        return {"agent": agent_name, "date": yesterday, "status": "skipped",
                "reason": "no chat_service registered"}
    if not api_key:
        return {"agent": agent_name, "date": yesterday, "status": "skipped",
                "reason": "no api key"}

    try:
        messages = chat_service.get_messages_on_date(yesterday)
    except Exception as e:
        logger.warning("daily_note_summary: failed to read messages for %s/%s: %s",
                       agent_name, yesterday, e)
        return {"agent": agent_name, "date": yesterday, "status": "error", "error": str(e)}

    if not messages:
        return {"agent": agent_name, "date": yesterday, "status": "skipped",
                "reason": "no messages", "duration_ms": int((time.monotonic() - start) * 1000)}

    # Group messages by conversation and build a compact transcript
    transcript_parts: list[str] = []
    total_chars = 0
    current_conv: str | None = None
    for m in messages:
        conv_id = m.get("conversation_id")
        if conv_id != current_conv:
            title = (m.get("conversation_title") or "Conversation").strip() or "Conversation"
            transcript_parts.append(f"\n### {title}\n")
            current_conv = conv_id
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        line = f"{role}: {content}"
        if total_chars + len(line) > _MAX_CHAT_INPUT_CHARS:
            transcript_parts.append("... (remaining messages truncated)")
            break
        transcript_parts.append(line)
        total_chars += len(line)

    transcript = "\n".join(transcript_parts).strip()
    if not transcript:
        return {"agent": agent_name, "date": yesterday, "status": "skipped",
                "reason": "empty transcript"}

    system_prompt = (
        f"You are summarizing yesterday's chat traffic for an AI agent named {agent_name}. "
        "Produce a terse end-of-day log in markdown. The VERY FIRST line MUST be:\n\n"
        "Headline: <single-sentence summary under 80 chars>\n\n"
        "Then include short bulleted sections only for what applies:\n"
        "- Decisions made\n"
        "- People mentioned\n"
        "- Actions taken (tools invoked, emails sent, tickets updated, etc.)\n"
        "- Commitments made\n"
        "- Open questions / follow-ups for tomorrow\n\n"
        "Be factual. Compress aggressively. Skip small talk and boilerplate. "
        "Do not invent anything — only summarize what's actually in the transcript. "
        "Do NOT wrap the output in triple backticks."
    )
    user_message = f"Transcript for {yesterday}:\n\n{transcript}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.warning("daily_note_summary Claude call failed for %s/%s: %s",
                       agent_name, yesterday, e)
        return {"agent": agent_name, "date": yesterday, "status": "error", "error": str(e)}

    summary = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            summary += block.text
    summary = summary.strip()
    if not summary:
        return {"agent": agent_name, "date": yesterday, "status": "error",
                "error": "empty summary from Claude"}

    # Inject the summary into the daily note. Prepend the Headline line at
    # the top of the file so _first_headline() picks it up for the manifest.
    ctx_manager.ensure_daily_dir()
    path = ctx_manager._daily_path(yesterday)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {yesterday}\n"

    lines = summary.splitlines()
    headline_line = lines[0] if lines and lines[0].lower().startswith("headline:") else ""
    summary_body = "\n".join(lines[1:]).strip() if headline_line else summary

    new_content_parts = []
    if headline_line:
        # Move the headline to the very top of the file (after the # YYYY-MM-DD)
        existing_lines = existing.splitlines()
        # Drop any pre-existing "Headline:" line near the top so we don't double up
        cleaned = [ln for ln in existing_lines if not ln.lower().startswith("headline:")]
        if cleaned and cleaned[0].startswith("#"):
            new_content_parts.append(cleaned[0])
            new_content_parts.append("")
            new_content_parts.append(headline_line)
            new_content_parts.extend(cleaned[1:])
        else:
            new_content_parts.append(f"# {yesterday}")
            new_content_parts.append("")
            new_content_parts.append(headline_line)
            new_content_parts.extend(cleaned)
    else:
        new_content_parts.append(existing.rstrip())

    new_content_parts.append("")
    new_content_parts.append("## End-of-day summary")
    new_content_parts.append("")
    new_content_parts.append(summary_body if headline_line else summary)
    new_content_parts.append("")

    new_content = "\n".join(new_content_parts)
    path.write_text(new_content, encoding="utf-8")

    try:
        from core.storage import upload_config
        upload_config(path, f"daily/{yesterday}.md", prefix=ctx_manager.gcs_prefix)
    except Exception:
        logger.warning("GCS upload failed for daily summary %s/%s", agent_name, yesterday,
                       exc_info=True)

    duration_ms = int((time.monotonic() - start) * 1000)
    input_tokens = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
    output_tokens = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
    logger.info(
        "daily_note_summary %s/%s: %d messages, tokens %d/%d, %dms",
        agent_name, yesterday, len(messages), input_tokens, output_tokens, duration_ms,
    )
    return {
        "agent": agent_name,
        "date": yesterday,
        "status": "ok",
        "messages_summarized": len(messages),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_ms": duration_ms,
    }


def process_memory_consolidation(
    agent_name: str,
    ctx_manager: ContextManager,
    api_key: str,
    days: int = 7,
) -> dict:
    """Regenerate MEMORY.md from the last N days of daily notes."""
    start = time.monotonic()
    result = consolidate_memory(
        data_dir=str(ctx_manager.data_dir),
        gcs_prefix=ctx_manager.gcs_prefix,
        api_key=api_key,
        days=days,
    )
    result["agent"] = agent_name
    result["duration_ms"] = int((time.monotonic() - start) * 1000)
    return result
