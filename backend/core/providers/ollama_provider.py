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

TOOL_CAPABLE_FAMILIES = [
    "llama3.1", "llama3.2", "llama3.3", "llama4",
    "qwen2.5", "qwen3", "qwen3.5",
    "mistral", "mistral-nemo", "mistral-small", "mistral-large",
    "command-r", "command-r-plus",
    "phi4",
    "nemotron",
    "hermes3",
    "firefunction",
]


def _is_tool_capable(model_name: str) -> bool:
    """Check if a model name matches a known tool-capable family."""
    base = model_name.split(":")[0].lower()
    return any(base == family or base.startswith(family + "-") for family in TOOL_CAPABLE_FAMILIES)


class OllamaProvider(AIProvider):
    _tool_support_cache: dict[str, bool] = {}

    def __init__(self, base_url: str = "http://localhost:11434", model: str = ""):
        super().__init__(model=model)
        self.base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def _recommend_tool_models(self) -> str:
        """Build a recommendation string for tool-capable models."""
        try:
            installed = await self.list_models()
        except Exception:
            installed = []
        capable = [m for m in installed if _is_tool_capable(m)]
        if capable:
            model_list = ", ".join(f"**{m}**" for m in capable[:5])
            return (
                f"{self.model} doesn't support tool calling, which Chatty needs for "
                f"memory, search, and integrations. "
                f"Switch to a tool-capable model: {model_list}"
            )
        return (
            f"{self.model} doesn't support tool calling, which Chatty needs for "
            f"memory, search, and integrations. "
            f"Install a compatible model: `ollama pull llama3.1` or `ollama pull qwen3.5`"
        )

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

        # Skip tools for models known not to support them
        model_known_no_tools = OllamaProvider._tool_support_cache.get(self.model) is False
        effective_tools = [] if model_known_no_tools else tools

        if model_known_no_tools and tools:
            recommendation = await self._recommend_tool_models()
            yield {"type": "error", "error": recommendation}

        needs_retry = False

        async for event in stream_openai_turn(
            client=client,
            model=self.model,
            messages=messages,
            tools=effective_tools,
            system_prompt=system_prompt,
            max_tokens=4096,
        ):
            # Detect "does not support tools" and retry without them
            if (
                event.get("type") == "error"
                and "does not support tools" in event.get("error", "")
                and effective_tools
            ):
                OllamaProvider._tool_support_cache[self.model] = False
                needs_retry = True
                continue

            if needs_retry:
                continue

            if event.get("type") == "error" and event.get("error") == "connection_error":
                yield {
                    "type": "error",
                    "error": f"Cannot connect to Ollama at {self.base_url}. Is it running? Start with: ollama serve",
                }
            else:
                yield event

        if needs_retry:
            logger.info("Model %s does not support tools, retrying without", self.model)
            recommendation = await self._recommend_tool_models()
            yield {"type": "error", "error": recommendation}

            async for event in stream_openai_turn(
                client=client,
                model=self.model,
                messages=messages,
                tools=[],
                system_prompt=system_prompt,
                max_tokens=4096,
            ):
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
