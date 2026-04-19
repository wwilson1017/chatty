"""
Chatty — Together AI provider for hosted open-weight models.

Uses Together AI's OpenAI-compatible API to run open-weight models
in the cloud at a fraction of the cost of proprietary APIs.
$25 free credits at signup, no credit card required.
"""

import logging
from typing import AsyncGenerator

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
    "Qwen/Qwen3.5-32B",
    "Qwen/Qwen3.5-14B",
    "Qwen/Qwen3.5-7B",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "google/gemma-3-27b-it",
    "deepseek-ai/DeepSeek-V3-0324",
    "mistralai/Mistral-Small-24B-Instruct-2501",
]

TOGETHER_DEFAULT_MODEL = "Qwen/Qwen3.5-7B"


class TogetherProvider(AIProvider):
    def __init__(self, api_key: str, model: str = TOGETHER_DEFAULT_MODEL):
        super().__init__(model=model)
        self.api_key = api_key

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

    async def list_models(self) -> list[str]:
        return TOGETHER_MODELS

    async def validate(self) -> bool:
        """Validate the API key with a minimal completion."""
        try:
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=TOGETHER_BASE_URL,
            )
            await client.chat.completions.create(
                model=TOGETHER_DEFAULT_MODEL,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return True
        except Exception:
            return False
