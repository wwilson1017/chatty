"""
Chatty — Anthropic (Claude) provider.

Streaming via anthropic.AsyncAnthropic with tool_use and prompt caching.
"""

import hashlib
import json
import logging
import time
from typing import AsyncGenerator

import anthropic

from core.providers.base import AIProvider

logger = logging.getLogger(__name__)

ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

_CACHE_CONTROL: dict = {"type": "ephemeral"}

# Reuse client instances for connection pool amortization
_client_cache: dict[str, anthropic.AsyncAnthropic] = {}


def _get_client(api_key: str = "", auth_token: str = "") -> anthropic.AsyncAnthropic:
    cache_key = hashlib.sha256(f"{api_key or ''}:{auth_token or ''}".encode()).hexdigest()
    client = _client_cache.get(cache_key)
    if client is None:
        client = anthropic.AsyncAnthropic(
            api_key=api_key or None,
            auth_token=auth_token or None,
        )
        _client_cache[cache_key] = client
    return client


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str = "", auth_token: str = "", model: str = "claude-opus-4-6"):
        super().__init__(model=model)
        self.api_key = api_key
        self.auth_token = auth_token

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert internal tool format to Anthropic format (same schema)."""
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

    def _build_system_blocks(self, system_prompt: "str | tuple[str, str]") -> list[dict]:
        """Build Anthropic system content blocks with cache_control on the static portion."""
        if isinstance(system_prompt, tuple):
            static_text, volatile_text = system_prompt
            blocks = [
                {
                    "type": "text",
                    "text": static_text,
                    "cache_control": _CACHE_CONTROL,
                },
            ]
            if volatile_text:
                blocks.append({"type": "text", "text": volatile_text})
            return blocks
        return [{"type": "text", "text": system_prompt}]

    def _cached_tools(self, tools: list[dict]) -> list[dict]:
        """Return tools with cache_control on the last tool for prefix caching."""
        if not tools:
            return tools
        out = [dict(t) for t in tools]
        out[-1] = {**out[-1], "cache_control": _CACHE_CONTROL}
        return out

    def _cache_last_user_message(self, api_messages: list[dict]) -> list[dict]:
        """Add cache_control to the last user message for conversation prefix caching."""
        if not api_messages:
            return api_messages
        out = list(api_messages)
        last = out[-1]
        if last.get("role") != "user":
            return out
        content = last.get("content")
        if isinstance(content, str):
            out[-1] = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": _CACHE_CONTROL,
                    }
                ],
            }
        elif isinstance(content, list) and content:
            new_content = list(content)
            new_content[-1] = {**new_content[-1], "cache_control": _CACHE_CONTROL}
            out[-1] = {"role": "user", "content": new_content}
        return out

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: "str | tuple[str, str]",
    ) -> AsyncGenerator[dict, None]:
        client = _get_client(self.api_key, self.auth_token)
        anthropic_tools = self._format_tools(tools)

        # Build system blocks with caching
        system = self._build_system_blocks(system_prompt)

        # Apply cache_control to tools and conversation prefix
        cached_tools = self._cached_tools(anthropic_tools) if anthropic_tools else []

        # Convert messages: filter to user/assistant only
        api_messages = [
            m for m in messages if m.get("role") in ("user", "assistant")
        ]
        api_messages = self._cache_last_user_message(api_messages)

        full_text = ""
        tool_calls = []

        t_start = time.monotonic()
        ttft = None

        try:
            async with client.messages.stream(
                model=self.model,
                max_tokens=16384,
                system=system,
                messages=api_messages,
                tools=cached_tools if cached_tools else anthropic.NOT_GIVEN,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if ttft is None:
                            ttft = (time.monotonic() - t_start) * 1000
                        if hasattr(event.content_block, "type"):
                            if event.content_block.type == "tool_use":
                                tool_calls.append({
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input_json": "",
                                })
                                yield {"type": "tool_start", "tool": event.content_block.name, "tool_use_id": event.content_block.id}

                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            full_text += event.delta.text
                            yield {"type": "text", "text": event.delta.text}
                        elif hasattr(event.delta, "partial_json") and tool_calls:
                            tool_calls[-1]["input_json"] += event.delta.partial_json

                    elif event.type == "content_block_stop":
                        # If this ended a tool_use block, emit tool_args
                        if tool_calls and tool_calls[-1].get("input_json") is not None:
                            last = tool_calls[-1]
                            if last.get("input_json"):
                                try:
                                    args = json.loads(last["input_json"])
                                    yield {
                                        "type": "tool_args",
                                        "tool": last["name"],
                                        "tool_use_id": last["id"],
                                        "args": args,
                                    }
                                    last["args"] = args
                                except Exception:
                                    pass

                final_message = await stream.get_final_message()
                stop_reason = final_message.stop_reason

        except anthropic.RateLimitError:
            yield {"type": "error", "error": "Claude is rate-limited. Please try again in a moment."}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            yield {"type": "error", "error": f"AI service error: {str(e)}"}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        # Extract usage and cache info from the final message
        usage_info = {}
        if hasattr(final_message, "usage") and final_message.usage:
            usage = final_message.usage
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0)
            cache_read = getattr(usage, "cache_read_input_tokens", 0)
            usage_info = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            }
            if ttft is not None:
                cache_status = "hit" if cache_read > 0 else ("write" if cache_creation > 0 else "none")
                logger.info(
                    "TTFT %.0fms | cache=%s (read=%d, write=%d) | model=%s",
                    ttft, cache_status, cache_read, cache_creation, self.model,
                )

        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            "usage": usage_info,
        }

    def add_tool_results(
        self,
        messages: list[dict],
        tool_calls: list[dict],
        results: list[dict],
    ) -> list[dict]:
        """Append assistant tool_use block + user tool_result block to messages."""
        # Build assistant content block with tool_use entries
        assistant_content = []
        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc.get("args", {}),
            })

        # Build user content block with tool_result entries
        user_content = []
        for r in results:
            user_content.append({
                "type": "tool_result",
                "tool_use_id": r["tool_use_id"],
                "content": str(r["content"]),
            })

        return messages + [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": user_content},
        ]

    async def list_models(self) -> list[str]:
        return ANTHROPIC_MODELS

    async def validate(self) -> bool:
        try:
            client = anthropic.Anthropic(
                api_key=self.api_key or None,
                auth_token=self.auth_token or None,
            )
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception as e:
            logger.error("Anthropic validation failed: %s", e)
            return False
