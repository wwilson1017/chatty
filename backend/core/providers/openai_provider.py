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


def _ensure_array_items(schema: dict) -> dict:
    """Recursively ensure all array types have an items field (OpenAI requirement)."""
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    if result.get("type") == "array" and "items" not in result:
        result["items"] = {}
    if "properties" in result:
        result["properties"] = {
            k: _ensure_array_items(v) for k, v in result["properties"].items()
        }
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = _ensure_array_items(result["items"])
    return result

# Fallback list only — list_models() fetches live from the OpenAI Models API
# and this is used when that call fails. Kept current by the price-check skill.
OPENAI_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
]

CHATGPT_PROXY_URL = "http://127.0.0.1:9877/v1"

# OpenAI's /v1/models exposes no capability flag, so chat-vs-not is heuristic:
# a conservative prefix allowlist minus obvious non-chat substrings. The
# hardcoded OPENAI_MODELS fallback is the known-good safety net.
_OPENAI_CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
_OPENAI_EXCLUDE = (
    "embedding", "tts", "whisper", "audio", "realtime",
    "image", "moderation", "-instruct", "dall-e", "search", "transcribe",
)


def _is_openai_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    if not low.startswith(_OPENAI_CHAT_PREFIXES):
        return False
    return not any(token in low for token in _OPENAI_EXCLUDE)


# Models observed to reject function tools + an implicit reasoning_effort on
# /v1/chat/completions. Populated lazily, only after a retry with
# reasoning_effort="none" has actually succeeded for that model.
_NEEDS_REASONING_NONE: set[str] = set()


def _is_reasoning_effort_tool_conflict(e: Exception) -> bool:
    """Detect OpenAI's 400 for reasoning models that reject tools + reasoning_effort together."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        param = body.get("param") or body.get("error", {}).get("param")
        if param == "reasoning_effort":
            return True
    low = str(e).lower()
    return "reasoning_effort" in low and "function tools" in low


class OpenAIProvider(AIProvider):
    def __init__(self, access_token: str, model: str = "gpt-5.4", use_chatgpt_api: bool = False):
        super().__init__(model=model)
        self.access_token = access_token
        self.use_chatgpt_api = use_chatgpt_api

    def _build_client_kwargs(self) -> dict:
        kwargs: dict = {"api_key": self.access_token}
        if self.use_chatgpt_api:
            kwargs["base_url"] = CHATGPT_PROXY_URL
        return kwargs

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
                    "parameters": _ensure_array_items(
                        t.get("input_schema", {"type": "object", "properties": {}})
                    ),
                },
            }
            for t in tools
        ]

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: "str | tuple[str, str]",
    ) -> AsyncGenerator[dict, None]:
        client = openai.AsyncOpenAI(**self._build_client_kwargs())
        openai_tools = self._format_tools(tools)

        # Join static+volatile if tuple (caching is Anthropic-only)
        if isinstance(system_prompt, tuple):
            system_prompt = "\n".join(system_prompt)

        # Build messages with system prompt prepended
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

        full_text = ""
        tool_calls: list[dict] = []

        try:
            # Newer models (o-series, gpt-5.x) require max_completion_tokens
            uses_completion_tokens = self.model.startswith(("o1", "o3", "o4", "gpt-5"))
            token_param = "max_completion_tokens" if uses_completion_tokens else "max_tokens"
            kwargs = {
                "model": self.model,
                "messages": api_messages,
                "stream": True,
                token_param: 16384,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools
                if self.model in _NEEDS_REASONING_NONE:
                    kwargs["reasoning_effort"] = "none"

            try:
                stream = await client.chat.completions.create(**kwargs)
            except openai.BadRequestError as e:
                if (
                    openai_tools
                    and "reasoning_effort" not in kwargs
                    and _is_reasoning_effort_tool_conflict(e)
                ):
                    retry_kwargs = {**kwargs, "reasoning_effort": "none"}
                    stream = await client.chat.completions.create(**retry_kwargs)
                    # Only cache the workaround once the retry has actually
                    # succeeded — if the retry itself raises, this line never
                    # runs and the model isn't wrongly marked as needing
                    # reasoning_effort="none".
                    _NEEDS_REASONING_NONE.add(self.model)
                    kwargs = retry_kwargs
                else:
                    raise

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

    async def _fetch_models(self) -> list[str]:
        client = openai.AsyncOpenAI(**self._build_client_kwargs())
        resp = await client.models.list()
        ids = [m.id for m in resp.data if _is_openai_chat_model(m.id)]
        # Roughly newest-first (gpt-5.5 > gpt-5.4 > gpt-4o > o3...).
        return sorted(ids, reverse=True)

    async def list_models(self) -> list[str]:
        from core.providers.model_listing import cache_key, cached_models, materialize_inference
        # use_chatgpt_api routes through a local proxy that may not implement
        # /v1/models; on failure cached_models falls back to OPENAI_MODELS.
        key = cache_key("openai", self.access_token, str(self.use_chatgpt_api))
        models, is_live = await cached_models(key, self._fetch_models, OPENAI_MODELS)
        materialize_inference("openai", models, is_live)
        return models

    async def validate(self) -> bool:
        try:
            client = openai.OpenAI(**self._build_client_kwargs())
            model = "gpt-5.4-nano"
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_completion_tokens=1,
            )
            return True
        except Exception:
            return False
