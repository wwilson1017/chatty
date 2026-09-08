"""
Chatty — runtime dispatch.

`get_runtime(agent, conversation)` is the single place that decides which
runtime a turn runs on. `guard_unresolved` is the durable guard above dispatch:
an unresolved external turn blocks the conversation whatever runtime it now
dispatches to, after giving the owning runtime one chance to reconcile.
"""

from __future__ import annotations

from fastapi import HTTPException

from .base import AgentRuntime, RequestCtx, TurnPlan  # noqa: F401
from .native import NativeRuntime
from .hermes import HermesRuntime, turn_public

_NATIVE = NativeRuntime()
_HERMES = HermesRuntime()


def effective_runtime(agent: dict, conversation: dict | None = None) -> str:
    """Runtime name a turn in this conversation dispatches to.

    Cutover conversations (PR 3) will override the agent's runtime here.
    """
    return "hermes" if agent.get("runtime") == "hermes" else "chatty"


def get_runtime(agent: dict, conversation: dict | None = None) -> AgentRuntime:
    return _HERMES if effective_runtime(agent, conversation) == "hermes" else _NATIVE


async def guard_unresolved(agent: dict, conversation_id: str | None, chat_service) -> None:
    if not conversation_id:
        return
    row = chat_service.unresolved_turn(conversation_id)
    if not row:
        return
    still = await _HERMES.reconcile(agent=agent, conversation_id=conversation_id,
                                    chat_service=chat_service)
    if still:
        raise HTTPException(status_code=409, detail={
            "message": "A previous Hermes turn is unresolved; resolve it first",
            "turn": turn_public(still)})
