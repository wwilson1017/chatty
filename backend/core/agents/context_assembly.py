"""
Chatty — server-side conversation assembler.

Rebuilds the provider `messages` array for a turn from chat_history.db by
conversation_id, so context BUILDS and PERSISTS within a chat instead of
relying on a thin client transcript (which drops tool results between turns).

Each DB row maps independently because persistence is per-iteration faithful
(ai_service saves one assistant row per model iteration, carrying that
iteration's own full `tool_calls` + `tool_results`):

    user row                        -> {"role": "user", "content": text}
    assistant row, no tool_calls    -> {"role": "assistant", "content": text}
    assistant row, with tool_calls  -> provider.build_tool_turn(text, calls, results)
                                       (native: Anthropic blocks / OpenAI
                                        tool_calls+role:tool / Gemini parts)

`provider.build_tool_turn` keeps the assembler provider-neutral, so a thread
triaged across models still reconstructs in whatever format the active turn
needs. Old rows (pre-persistence) and interrupted finals (`tool_results IS
NULL`) fall back to the per-call 2000-char preview; build_tool_turn stubs any
result still missing so the model never sees an orphaned tool_use.

Compaction (PR-B) is applied here: HEAD (opening exchange) verbatim, the aged
middle replaced by a `<conversation_summary>` gist riding on the first
retained human-user turn, then the TAIL verbatim. The gist is prepended to a
real user row (never a synthetic standalone turn) so role alternation stays
valid across every provider.

The oversized-row guard truncates any single row that would blow the live
context (huge fetched articles, write_context_file bodies, pasted uploads) —
storage stays full, only the assembled copy is bounded. Truncation of a
wrapped tool result is delimiter-safe: it never cuts inside the
`<untrusted_tool_result>` XML, which would let injected text escape its tags.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Opening user+assistant exchange kept verbatim across compactions. Shared with
# the compaction module so "the middle" (what gets summarized) is exactly the
# rows between HEAD and first_kept_seq. Tune on real threads.
HEAD_MSGS = 2

# Per-row live-context cap as a fraction of the budget (storage is never capped).
_OVERSIZED_ROW_FRACTION = 0.25
_CHARS_PER_TOKEN = 4
# Conservative budget when the provider doesn't report a context window
# (non-Anthropic providers, until they expose one — deferred scope).
_DEFAULT_BUDGET_TOKENS = 128_000

_TRUNCATION_MARKER = "\n…[truncated]"
_UNTRUSTED_OPEN = "<untrusted_tool_result"
_UNTRUSTED_CLOSE = "</untrusted_tool_result>"


def assemble_messages(chat_service, provider, conversation_id, compaction=None):
    """Rebuild the provider `messages` array for `conversation_id` from the DB.

    Args:
        chat_service: ChatHistoryService for this agent.
        provider: the active AIProvider (supplies build_tool_turn + context_window).
        conversation_id: the conversation to reconstruct.
        compaction: optional (summary, first_kept_seq) override. When None, the
            stored compaction on the conversation row is used (so PR-B's
            maybe_compact persists it and the assembler picks it up).

    Returns the messages list ending with the latest persisted user turn
    (callers persist the new user row BEFORE assembling), ready for stream_turn.
    """
    conv = chat_service.get_conversation(conversation_id)
    if not conv:
        return []
    rows = conv.get("messages") or []

    if compaction is None:
        summary = conv.get("compaction_summary")
        first_kept_seq = conv.get("compaction_first_kept_seq")
    else:
        summary, first_kept_seq = compaction

    rows = _apply_compaction(rows, summary, first_kept_seq)

    budget = provider.context_window or _DEFAULT_BUDGET_TOKENS
    max_row_chars = int(_OVERSIZED_ROW_FRACTION * budget * _CHARS_PER_TOKEN)

    messages: list[dict] = []
    for row in rows:
        messages.extend(_row_to_messages(provider, row, max_row_chars))
    return _coalesce_consecutive(messages)


def _coalesce_consecutive(messages):
    """Merge consecutive same-role user/assistant messages so providers that
    require strict turn alternation (Anthropic, Gemini) never see two in a row.

    This happens legitimately: Telegram busy-skipped messages save several user
    rows with no assistant between them, and a compaction gist folds onto a tail
    that may follow a HEAD ending in a tool_result (also user-role for Anthropic).
    Role 'tool' (OpenAI) is left untouched — those must stay one-per-tool_call."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if out and role in ("user", "assistant") and out[-1].get("role") == role:
            out[-1] = {**out[-1], "content": _merge_content(out[-1].get("content"), m.get("content"))}
            continue
        out.append(dict(m))
    return out


def _merge_content(a, b):
    """Combine two message contents: blocks concatenate; strings join; a mix is
    normalized to a block list (so a tool_result user turn can absorb a text gist)."""
    if isinstance(a, list) and isinstance(b, list):
        return a + b
    if isinstance(a, str) and isinstance(b, str):
        return f"{a}\n\n{b}" if a and b else (a or b)
    return _as_blocks(a) + _as_blocks(b)


def _as_blocks(content):
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": content}] if content else []


def _apply_compaction(rows, summary, first_kept_seq):
    """Replace the aged middle with a gist. HEAD verbatim, gist folded into the
    first retained human-user turn, TAIL verbatim. No-op when there's nothing
    valid to compact (so PR-A, which never sets a boundary, returns rows as-is)."""
    if not summary or first_kept_seq is None or len(rows) <= HEAD_MSGS:
        return rows
    head = rows[:HEAD_MSGS]
    # Only compact rows strictly past the head; guard against a boundary that
    # would overlap or precede the head (then there's no real middle to drop).
    if first_kept_seq <= head[-1]["seq"]:
        return rows
    tail = [r for r in rows if r["seq"] >= first_kept_seq]
    if not tail:
        return rows

    gist = _gist_marker(summary)
    first = tail[0]
    if first.get("role") == "user":
        # Fold the gist onto the first kept human turn — adds no synthetic
        # message, so role alternation stays valid for every provider.
        merged = {**first, "content": f"{gist}\n\n{first.get('content') or ''}"}
        tail = [merged] + tail[1:]
    else:
        # Defensive: boundary didn't land on a user turn (shouldn't happen —
        # compaction snaps to one) — inject a standalone gist user turn.
        tail = [{"role": "user", "content": gist, "tool_calls": None,
                 "tool_results": None, "seq": first_kept_seq}] + tail
    return head + tail


def _row_to_messages(provider, row, max_row_chars):
    """Convert one DB row to provider-native message(s), applying the oversized
    guard. Malformed tool JSON degrades to a plain assistant text message."""
    role = row.get("role")
    content = row.get("content") or ""

    if role == "user":
        return [{"role": "user", "content": _truncate_text(content, max_row_chars)}]

    tool_calls_json = row.get("tool_calls")
    if not tool_calls_json:
        if not content:
            return []  # nothing to say and no tools — skip empty row
        return [{"role": "assistant", "content": _truncate_text(content, max_row_chars)}]

    # Assistant iteration that used tools — reconstruct natively.
    try:
        tool_calls = json.loads(tool_calls_json) or []
        results_json = row.get("tool_results")
        if results_json:
            tool_results = json.loads(results_json) or []
        else:
            # Old row or interrupted final: fall back to each call's stored
            # preview; build_tool_turn stubs any result still missing.
            tool_results = [
                {
                    "tool_use_id": tc.get("tool_use_id") or tc.get("id"),
                    "tool_name": tc.get("tool") or tc.get("name"),
                    "content": tc["result"],
                }
                for tc in tool_calls
                if tc.get("result")
            ]
        tool_calls = [_truncate_call_args(tc, max_row_chars) for tc in tool_calls]
        tool_results = [_truncate_result(r, max_row_chars) for r in tool_results]
        return provider.build_tool_turn(
            _truncate_text(content, max_row_chars), tool_calls, tool_results
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("Assembler: malformed tool row %s, using text fallback: %s",
                       row.get("id"), e)
        return [{"role": "assistant", "content": _truncate_text(content, max_row_chars)}] if content else []


# ── Oversized-row guard (live context only; stored rows stay full) ────────────

def _truncate_text(text, limit):
    if not text or len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_MARKER


def _truncate_result(result, limit):
    """Delimiter-safe truncation of one persisted tool result."""
    content = result.get("content") or ""
    if len(content) <= limit:
        return result
    return {**result, "content": _truncate_wrapped(content, limit)}


def _truncate_wrapped(content, limit):
    """Truncate tool-result content without splitting `<untrusted_tool_result>`
    XML — cut the inner body and re-close the tag so injected text can't escape."""
    if content.startswith(_UNTRUSTED_OPEN) and content.rstrip().endswith(_UNTRUSTED_CLOSE):
        nl = content.find("\n")
        open_tag = content[:nl] if nl != -1 else content
        inner = content[nl + 1:] if nl != -1 else ""
        keep = max(0, limit - len(open_tag) - len(_UNTRUSTED_CLOSE) - len(_TRUNCATION_MARKER) - 2)
        return f"{open_tag}\n{inner[:keep]}{_TRUNCATION_MARKER}\n{_UNTRUSTED_CLOSE}"
    return content[:limit] + _TRUNCATION_MARKER


def _truncate_call_args(tool_call, limit):
    """Bound a tool call's argument payload (write_context_file bodies, email
    bodies, playbook content can be huge). Truncates the largest string fields
    rather than dropping args wholesale, so the call stays legible to the model."""
    args = tool_call.get("args")
    if not isinstance(args, dict) or not args:
        return tool_call
    try:
        if len(json.dumps(args, default=str)) <= limit:
            return tool_call
    except (TypeError, ValueError):
        return tool_call
    per_field = max(500, limit // max(1, len(args)))
    bounded = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > per_field:
            bounded[k] = v[:per_field] + _TRUNCATION_MARKER
        else:
            bounded[k] = v
    return {**tool_call, "args": bounded}


def _gist_marker(summary):
    """Trusted compaction gist marker (distinct from `<untrusted_tool_result>`)."""
    return (
        '<conversation_summary reference_only="true">\n'
        f"{summary}\n"
        "</conversation_summary>"
    )
