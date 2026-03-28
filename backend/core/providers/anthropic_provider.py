"""
Chatty — Anthropic (Claude) provider.

Streaming via anthropic.AsyncAnthropic with tool_use.
"""

import logging
from typing import AsyncGenerator

import anthropic

from core.providers.base import AIProvider

logger = logging.getLogger(__name__)

ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]


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

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncGenerator[dict, None]:
        client = anthropic.AsyncAnthropic(
            api_key=self.api_key or None,
            auth_token=self.auth_token or None,
        )
        anthropic_tools = self._format_tools(tools)

        # Convert messages: filter to user/assistant only
        api_messages = [
            m for m in messages if m.get("role") in ("user", "assistant")
        ]

        full_text = ""
        tool_calls = []

        try:
            async with client.messages.stream(
                model=self.model,
                max_tokens=16384,
                system=system_prompt,
                messages=api_messages,
                tools=anthropic_tools if anthropic_tools else anthropic.NOT_GIVEN,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
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
                                    import json
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

        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
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
            # Use messages.create — works with both API keys and OAuth tokens
            # (models.list rejects OAuth tokens passed as api_key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception as e:
            logger.error("Anthropic validation failed: %s", e)
            return False
