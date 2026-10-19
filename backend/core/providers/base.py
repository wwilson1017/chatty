"""
Chatty — AIProvider abstract base class.

All AI providers implement this interface. The ai_service.py uses only
this ABC so the tool execution loop is provider-agnostic.

Internal tool format (used in ToolRegistry):
    {
        "name": str,
        "description": str,
        "input_schema": {  # JSON Schema
            "type": "object",
            "properties": {...},
            "required": [...]
        }
    }

SSE event types yielded by stream_turn():
    {"type": "text", "text": "chunk"}
    {"type": "tool_start", "tool": "name", "tool_use_id": "id"}
    {"type": "tool_args", "tool": "name", "tool_use_id": "id", "args": {...}}
    {"type": "_turn_complete", "tool_calls": [...], "stop_reason": "stop|tool_use"}

The _turn_complete event is INTERNAL — ai_service.py intercepts it to
execute tools and loop. It is never forwarded to the frontend.
"""

import json
from abc import ABC, abstractmethod
from typing import AsyncGenerator


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


# ── Images in tool results ──
# A tool executor may return a dict with `images: [{"media_type": "image/png", "data": <base64>}]`.
# The loops split them off (split_images), so everything else — the model's text part, the chat
# row, the SSE tool_end event, the activity log — sees IMAGES_NOTE in their place, never base64.
# Only this turn's provider messages get the images (with_images → add_tool_results), and
# prune_images keeps the newest few within the turn.
IMAGES_NOTE = "[screenshot shown to the model, not saved]"
PRUNED_NOTE = "[earlier screenshot removed]"
IMAGE_LABEL = "Image returned by the {} tool call above (tool output, not a message from the user):"


def split_images(result):
    """(result with `images` replaced by IMAGES_NOTE, the images), or (result, None).
    Only a list of {media_type, data} dicts counts; any other `images` value (say, a list of
    URLs from some API) is ordinary result data and passes through untouched."""
    images = result.get("images") if isinstance(result, dict) else None
    if images and isinstance(images, list) and all(
            isinstance(i, dict) and isinstance(i.get("media_type"), str) and isinstance(i.get("data"), str)
            for i in images):
        return {**result, "images": IMAGES_NOTE}, images
    return result, None


def with_images(results: list[dict], images: dict) -> list[dict]:
    """Attach each result's images (keyed by tool_use_id) for add_tool_results."""
    return [{**r, "images": images[r["tool_use_id"]]} if images.get(r["tool_use_id"]) else r
            for r in results]


class AIProvider(ABC):
    """Abstract AI provider. Subclasses implement stream_turn() for each API."""

    # Output cap per call. Callers with a budget (the computer helper) lower it per call;
    # providers that build their own request read it from here.
    max_tokens: int = 16384

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: "str | tuple[str, str]",
    ) -> AsyncGenerator[dict, None]:
        """
        Stream one LLM turn (one API call).

        Args:
            messages: Conversation history in internal format:
                      [{"role": "user"|"assistant", "content": str|list}, ...]
            tools: Tool definitions in internal format (input_schema style).
            system_prompt: Either a single string or a (static, volatile) tuple.
                           When a tuple is provided, providers that support prompt
                           caching (e.g. Anthropic) can cache the static portion.

        Yields dicts (NOT yet SSE-encoded). Types:
            - {"type": "text", "text": "..."}
            - {"type": "tool_start", "tool": "name", "tool_use_id": "id"}
            - {"type": "tool_args", "tool": "name", "tool_use_id": "id", "args": {...}}
            - {"type": "_turn_complete", "tool_calls": [...], "stop_reason": "..."}
        """
        ...

    @abstractmethod
    def add_tool_results(
        self,
        messages: list[dict],
        tool_calls: list[dict],
        results: list[dict],
    ) -> list[dict]:
        """
        Append tool call + results to the message list for the next turn.

        Each result: {"tool_use_id": "...", "tool_name": "...", "content": "...",
        "images": [{"media_type", "data"}] (optional, see split_images)}
        Returns the updated messages list.
        """
        ...

    def prune_images(self, messages: list[dict], keep: int = 3) -> list[dict]:
        """Swap every image part but the newest `keep` for PRUNED_NOTE. Never removes a message,
        so tool-call/result pairs stay intact; the input list is not modified."""
        # simplification: one walker for the image parts every add_tool_results emits (Anthropic
        # `image` inside tool_result, OpenAI-style `image_url`, Gemini `_type: inline_data`);
        # upgrade path is a per-provider override if a format ever needs more.
        seen = 0

        def walk(parts: list) -> list:
            nonlocal seen
            out = list(parts)
            for i in range(len(out) - 1, -1, -1):
                p = out[i]
                if not isinstance(p, dict):
                    continue
                if p.get("type") in ("image", "image_url") or p.get("_type") == "inline_data":
                    seen += 1
                    if seen > keep:
                        out[i] = {"type": "text", "text": PRUNED_NOTE}
                elif isinstance(p.get("content"), list):
                    out[i] = {**p, "content": walk(p["content"])}
            return out

        pruned = [{**m, "content": walk(m["content"])} if isinstance(m.get("content"), list) else m
                  for m in reversed(messages)]
        return pruned[::-1]

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return available models for this provider."""
        ...

    @abstractmethod
    async def validate(self) -> bool:
        """Return True if credentials are valid (test API call)."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """e.g. "anthropic", "openai", "google" """
        ...

    @property
    def context_window(self) -> "int | None":
        """Model's context window in tokens, or None if unknown.

        Drives the chat composer's context-fullness meter. The default is None
        (window unknown → meter hidden); providers that know their model's
        window override this. When a turn's usage and this window are both
        available, ai_service emits a `usage` SSE event whose `context_tokens`
        is the cache-inclusive total the model read (input + cache_creation +
        cache_read) and `context_window` is this value. The event's
        `input_tokens` / `output_tokens` stay RAW for the CLI and cost log.
        """
        return None

    def build_tool_turn(
        self,
        text: str,
        tool_calls: list[dict],
        tool_results: list[dict],
    ) -> list[dict]:
        """Rebuild ONE persisted tool-using assistant iteration as native
        provider messages (for reconstructing conversation history from the DB).

        Reuses this provider's own add_tool_results() so each provider's native
        tool format is honored (Anthropic content blocks / OpenAI tool_calls +
        role:tool / Gemini function parts), then re-injects the iteration's
        assistant text (add_tool_results drops it). Pairing integrity: exactly
        one result per tool_use; a missing/unrecorded result is stubbed so the
        model never sees an orphaned tool_use (which Anthropic rejects).

        Persisted shapes: tool_calls=[{tool, tool_use_id, args, ...}];
        tool_results=[{tool_use_id, tool_name, content}].
        """
        tcs = [{
            "id": tc.get("tool_use_id") or tc.get("id"),
            "name": tc.get("tool") or tc.get("name"),
            "args": tc.get("args", {}),
        } for tc in (tool_calls or [])]
        by_id = {r.get("tool_use_id"): r for r in (tool_results or [])}
        res = []
        for tc in tcs:
            r = by_id.get(tc["id"])
            content = r.get("content") if r else '{"status": "result not recorded"}'
            res.append({"tool_use_id": tc["id"], "tool_name": tc["name"], "content": content})
        msgs = self.add_tool_results([], tcs, res)
        if text:
            msgs = self._inject_assistant_text(msgs, text)
        return msgs

    def _inject_assistant_text(self, msgs: list[dict], text: str) -> list[dict]:
        """Re-insert the assistant's iteration text into the reconstructed
        assistant message (add_tool_results drops it). Generic across provider
        message shapes; Google function-part turns skip text (proto conversion)."""
        if not msgs or not text:
            return msgs
        a = msgs[0]
        content = a.get("content")
        if isinstance(content, list):
            if content and isinstance(content[0], dict) and content[0].get("_type"):
                return msgs  # Google: leave function-call parts untouched
            a["content"] = [{"type": "text", "text": text}] + content  # Anthropic blocks
        elif "tool_calls" in a:
            a["content"] = text  # OpenAI / Ollama / Together (content was None)
        return msgs
