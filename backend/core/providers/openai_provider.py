"""
Chatty — OpenAI (GPT) provider.

Streaming via openai.AsyncOpenAI with function calling.
"""

import json
import logging
from typing import AsyncGenerator

import openai

from core.providers.base import AIProvider

logger = logging.getLogger(__name__)

OPENAI_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "o1",
    "o3-mini",
]


class OpenAIProvider(AIProvider):
    def __init__(self, access_token: str, model: str = "gpt-4o"):
        super().__init__(model=model)
        self.access_token = access_token

    @property
    def provider_name(self) -> str:
        return "openai"

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert internal tool format to OpenAI function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncGenerator[dict, None]:
        client = openai.AsyncOpenAI(api_key=self.access_token)
        openai_tools = self._format_tools(tools)

        # Build messages with system prompt prepended
        api_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                api_messages.append({"role": m["role"], "content": m["content"]})

        full_text = ""
        tool_calls: list[dict] = []

        try:
            kwargs = {
                "model": self.model,
                "messages": api_messages,
                "stream": True,
                "max_tokens": 16384,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools

            stream = await client.chat.completions.create(**kwargs)

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                # Text content
                if delta.content:
                    full_text += delta.content
                    yield {"type": "text", "text": delta.content}

                # Tool call streaming
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        # Extend list as needed
                        while len(tool_calls) <= idx:
                            tool_calls.append({"id": "", "name": "", "input_json": ""})

                        if tc_delta.id:
                            tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls[idx]["name"] = tc_delta.function.name
                                yield {"type": "tool_start", "tool": tc_delta.function.name, "tool_use_id": tc_delta.id or ""}
                            if tc_delta.function.arguments:
                                tool_calls[idx]["input_json"] += tc_delta.function.arguments

            # Parse accumulated tool args and emit tool_args events
            for tc in tool_calls:
                if tc.get("input_json"):
                    try:
                        args = json.loads(tc["input_json"])
                        tc["args"] = args
                        yield {
                            "type": "tool_args",
                            "tool": tc["name"],
                            "tool_use_id": tc["id"],
                            "args": args,
                        }
                    except Exception:
                        tc["args"] = {}

            stop_reason = "tool_use" if tool_calls else "stop"

        except openai.RateLimitError:
            yield {"type": "error", "error": "OpenAI is rate-limited. Please try again in a moment."}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        except openai.APIError as e:
            logger.error("OpenAI API error: %s", e)
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
        """Append assistant tool_calls message + tool result messages."""
        assistant_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                }
                for tc in tool_calls
            ],
        }

        result_msgs = [
            {
                "role": "tool",
                "tool_call_id": r["tool_use_id"],
                "content": str(r["content"]),
            }
            for r in results
        ]

        return messages + [assistant_msg] + result_msgs

    async def list_models(self) -> list[str]:
        return OPENAI_MODELS

    async def validate(self) -> bool:
        try:
            client = openai.OpenAI(api_key=self.access_token)
            client.models.list()
            return True
        except Exception:
            return False
