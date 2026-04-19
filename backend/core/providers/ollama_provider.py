"""
Chatty — Ollama provider for local models.

Connects to a local Ollama instance via its OpenAI-compatible API.
Users run models on their own hardware for free.
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


class OllamaProvider(AIProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = ""):
        super().__init__(model=model)
        self.base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: "str | tuple[str, str]",
    ) -> AsyncGenerator[dict, None]:
        if isinstance(system_prompt, tuple):
            system_prompt = "\n".join(system_prompt)
        client = openai.AsyncOpenAI(
            api_key="ollama",
            base_url=f"{self.base_url}/v1",
        )

        async for event in stream_openai_turn(
            client=client,
            model=self.model,
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            max_tokens=4096,
        ):
            # Rewrite generic connection error with Ollama-specific message
            if event.get("type") == "error" and event.get("error") == "connection_error":
                yield {
                    "type": "error",
                    "error": f"Cannot connect to Ollama at {self.base_url}. Is it running? Start with: ollama serve",
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
        """Return locally-installed Ollama model names."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
            return []

    async def validate(self) -> bool:
        """Check if Ollama is reachable (no inference burn)."""
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
