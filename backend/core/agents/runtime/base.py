"""
Chatty — agent runtime seam.

A runtime turns one user message into Chatty SSE events. The native runtime
wraps today's ai_service.chat() loop; the Hermes runtime proxies a Hermes run.
The HTTP layer (agents/router.py::_stream_chat) picks the runtime per
conversation, runs `prepare` BEFORE the StreamingResponse exists (so HTTP
errors are still real 4xx responses), then iterates `stream_turn`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator


@dataclass
class RequestCtx:
    """Chatty-side mode flags for one chat request."""
    training_mode: bool = False
    training_type: str | None = None
    plan_mode: bool = False
    import_mode: bool = False
    has_attachments: bool = False
    upload: bool = False
    playbook_slug: str | None = None

    @property
    def chatty_only_mode(self) -> str | None:
        """Name of the first Chatty-only mode in use, if any."""
        if self.training_mode:
            return "training"
        if self.plan_mode:
            return "plan mode"
        if self.import_mode:
            return "knowledge import"
        if self.playbook_slug:
            return "playbooks"
        if self.upload:
            return "file upload"
        return None


@dataclass
class TurnPlan:
    """Everything `prepare` decided for one turn."""
    runtime: str
    context_dir: str
    gcs_prefix: str | None
    data: dict[str, Any] = field(default_factory=dict)


class AgentRuntime(abc.ABC):
    name: str = ""

    @abc.abstractmethod
    async def prepare(self, *, agent: dict, config, conversation_id: str | None,
                      request_ctx: RequestCtx, chat_service, **kw) -> TurnPlan:
        """Preflight. May raise fastapi.HTTPException; must not stream."""

    @abc.abstractmethod
    def stream_turn(self, plan: TurnPlan, **kw) -> AsyncGenerator[str, None]:
        """Yield SSE strings (`data: {...}\\n\\n` or `: comment\\n\\n`)."""

    async def release(self, plan: TurnPlan) -> None:
        """Called from the response generator's `finally`."""

    async def reconcile(self, *, agent: dict, conversation_id: str, chat_service) -> dict | None:
        """Settle any unresolved journal row for the conversation; return the
        row that is still unresolved afterwards, or None."""
        return None

    async def handle_approval(self, *, agent: dict, conversation_id: str,
                              tool_use_id: str, choice: str) -> dict:
        raise NotImplementedError

