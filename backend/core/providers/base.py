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


class AIProvider(ABC):
    """Abstract AI provider. Subclasses implement stream_turn() for each API."""

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream one LLM turn (one API call).

        Args:
            messages: Conversation history in internal format:
                      [{"role": "user"|"assistant", "content": str|list}, ...]
            tools: Tool definitions in internal format (input_schema style).
            system_prompt: The full system prompt string.

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

        Each result: {"tool_use_id": "...", "tool_name": "...", "content": "..."}
        Returns the updated messages list.
        """
        ...

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
