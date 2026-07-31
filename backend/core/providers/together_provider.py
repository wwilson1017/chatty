"""
Chatty — Together AI provider for hosted open-weight models.

Uses Together AI's OpenAI-compatible API to run open-weight models
in the cloud at a fraction of the cost of proprietary APIs.
$25 free credits at signup, no credit card required.
"""

import logging
from typing import AsyncGenerator

import httpx
import openai

from core.providers.base import AIProvider
from core.providers.openai_compat import (
    build_openai_tool_results,
    stream_openai_turn,
)

logger = logging.getLogger(__name__)

TOGETHER_BASE_URL = "https://api.together.xyz/v1"

# Curated list of models known to work well with tool calling and agents.
TOGETHER_MODELS = [
    "Qwen/Qwen3.7-Max",
    "Qwen/Qwen3.7-Plus",
    "Qwen/Qwen3.5-9B",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "google/gemma-4-31B-it",
    "deepseek-ai/DeepSeek-V4-Pro",
    "openai/gpt-oss-120b",
]

TOGETHER_DEFAULT_MODEL = "Qwen/Qwen3.5-9B"

# Together's catalog is large and mixes chat, embedding, image, rerank, etc.
# Prefer the per-model `type` (chat/language) when present; otherwise exclude
# obvious non-chat ids by name. The curated TOGETHER_MODELS is the fallback.
_TOGETHER_NON_CHAT = (
    "embedding", "rerank", "image", "audio", "moderation",
    "whisper", "guard", "vision", "tts", "flux",
)


def _is_together_chat(model: dict) -> bool:
    mtype = model.get("type")
    if mtype:
        return mtype in ("chat", "language")
    low = model.get("id", "").lower()
    return not any(token in low for token in _TOGETHER_NON_CHAT)


class TogetherProvider(AIProvider):
    def __init__(self, api_key: str, model: str = TOGETHER_DEFAULT_MODEL):
        super().__init__(model=model)
        self.api_key = api_key
        # Set by validate() on failure so callers (router.py) can surface the
        # real cause instead of a blanket "invalid key" message.
        self.last_error: str | None = None

    @property
    def provider_name(self) -> str:
        return "together"

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: "str | tuple[str, str]",
    ) -> AsyncGenerator[dict, None]:
        if isinstance(system_prompt, tuple):
            system_prompt = "\n".join(system_prompt)
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=TOGETHER_BASE_URL,
        )

        async for event in stream_openai_turn(
            client=client,
            model=self.model,
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            max_tokens=8192,
        ):
            # Rewrite generic connection error with Together-specific message
            if event.get("type") == "error" and event.get("error") == "connection_error":
                yield {
                    "type": "error",
                    "error": "Cannot connect to Together AI. Check your internet connection.",
                }
            else:
                yield event

    def add_tool_results(
        self,
        messages: list[dict],
        tool_calls: list[dict],
        results: list[dict],
    ) -> list[dict]:
        return build_openai_tool_results(messages, tool_calls, results)

    async def _list_models_raw(self) -> list[dict]:
        """GET /models directly with httpx.

        Together's /v1/models is NOT OpenAI-compatible: it returns a bare JSON
        array instead of {"object": "list", "data": [...]}, so the openai
        SDK's client.models.list() crashes while parsing the response
        (AttributeError deep in its pagination model). Chat completions ARE
        compatible, so the SDK is still used everywhere else.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{TOGETHER_BASE_URL}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])

    async def _fetch_models(self) -> list[str]:
        models = await self._list_models_raw()
        return sorted(m["id"] for m in models if _is_together_chat(m))

    async def list_models(self) -> list[str]:
        from core.providers.model_listing import cache_key, cached_models, materialize_inference
        key = cache_key("together", self.api_key)
        models, is_live = await cached_models(key, self._fetch_models, TOGETHER_MODELS)
        materialize_inference("together", models, is_live)
        return models

    async def validate(self) -> bool:
        """Validate the API key with a cheap, model-agnostic authenticated call.

        Deliberately does NOT probe with a chat completion against a specific
        model: Together's catalog turns over, and a stale/renamed model id in
        the probe would 400 and make a genuinely valid key read as invalid
        (same failure mode fixed for OpenAI in openai_provider.py). Goes
        through _list_models_raw() because the openai SDK cannot parse
        Together's non-standard /models response shape.
        """
        self.last_error = None
        try:
            await self._list_models_raw()
            return True
        except httpx.HTTPStatusError as e:
            self.last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.warning("Together AI key validation failed: %s", self.last_error)
            return False
        except Exception as e:
            self.last_error = str(e)
            logger.warning("Together AI key validation failed: %s", e)
            return False
