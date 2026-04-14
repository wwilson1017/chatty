"""
Chatty — Shared helpers for OpenAI-compatible providers.

Used by OllamaProvider and TogetherProvider. Both speak the same
OpenAI wire protocol (tool calling, streaming, message format) so
the core logic lives here to avoid duplication.
"""

import json
import logging
from typing import AsyncGenerator

import openai

logger = logging.getLogger(__name__)


def ensure_array_items(schema: dict) -> dict:
    """Recursively ensure all array types have an items field (OpenAI requirement)."""
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    if result.get("type") == "array" and "items" not in result:
        result["items"] = {}
    if "properties" in result:
        result["properties"] = {
            k: ensure_array_items(v) for k, v in result["properties"].items()
        }
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = ensure_array_items(result["items"])
    return result


def format_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert internal tool format to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": ensure_array_items(
                    t.get("input_schema", {"type": "object", "properties": {}})
                ),
            },
        }
        for t in tools
    ]


def build_openai_messages(
    messages: list[dict],
    system_prompt: str,
) -> list[dict]:
    """Build OpenAI-format message list with system prompt prepended."""
    api_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        role = m.get("role")
        if role == "user":
            api_messages.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            msg: dict = {"role": "assistant"}
            if m.get("content") is not None:
                msg["content"] = m["content"]
            if m.get("tool_calls"):
                msg["tool_calls"] = m["tool_calls"]
            api_messages.append(msg)
        elif role == "tool":
            api_messages.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            })
    return api_messages


async def stream_openai_turn(
    client: openai.AsyncOpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict],
    system_prompt: str,
    max_tokens: int = 4096,
) -> AsyncGenerator[dict, None]:
    """
    Stream one LLM turn using the OpenAI-compatible chat completions API.

    Yields event dicts: text, tool_start, tool_args, _turn_complete, error.
    """
    openai_tools = format_openai_tools(tools)
    api_messages = build_openai_messages(messages, system_prompt)

    full_text = ""
    tool_calls: list[dict] = []

    try:
        kwargs: dict = {
            "model": model,
            "messages": api_messages,
            "stream": True,
            "max_tokens": max_tokens,
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

        # Parse accumulated tool args
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

    except openai.APIConnectionError:
        yield {"type": "error", "error": "connection_error"}
        yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
        return

    except openai.RateLimitError:
        yield {"type": "error", "error": "Rate-limited. Please try again in a moment."}
        yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
        return

    except openai.APIError as e:
        logger.error("OpenAI-compat API error: %s", e)
        yield {"type": "error", "error": f"AI service error: {str(e)}"}
        yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
        return

    yield {
        "type": "_turn_complete",
        "tool_calls": tool_calls,
        "stop_reason": stop_reason,
    }


def build_openai_tool_results(
    messages: list[dict],
    tool_calls: list[dict],
    results: list[dict],
) -> list[dict]:
    """Append assistant tool_calls message + tool result messages (OpenAI format)."""
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
