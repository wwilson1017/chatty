"""Telegram group chat support.

Handles group-specific routing decisions, loop prevention for bot-to-bot
conversations, and message formatting for group context.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

RESPONSE_COOLDOWN = 2.0

_lock = threading.Lock()
_group_states: dict[int, "_GroupState"] = {}


@dataclass
class _GroupState:
    consecutive_bot_turns: int = 0
    last_response_times: dict[str, float] = field(default_factory=dict)


def _get_state(chat_id: int) -> _GroupState:
    if chat_id not in _group_states:
        _group_states[chat_id] = _GroupState()
    return _group_states[chat_id]


def is_group_chat(chat_type: str) -> bool:
    return chat_type in ("group", "supergroup")


def should_respond(
    chat_id: int,
    sender_is_bot: bool,
    sender_username: str,
    agent: dict,
) -> tuple[bool, str]:
    """Decide whether the agent should respond to a group message.

    Returns (should_respond, reason).
    """
    if not agent.get("telegram_group_enabled"):
        return False, "group_disabled"

    bot_username = agent.get("telegram_bot_username", "")
    if sender_username and bot_username and sender_username.lower() == bot_username.lower():
        return False, "self_message"

    with _lock:
        state = _get_state(chat_id)

        if sender_is_bot:
            if not agent.get("telegram_respond_to_bots"):
                return False, "bot_messages_disabled"
            max_turns = agent.get("telegram_max_bot_turns", 3)
            if state.consecutive_bot_turns >= max_turns:
                return False, "max_bot_turns"

        agent_id = agent["id"]
        last = state.last_response_times.get(agent_id, 0)
        if time.time() - last < RESPONSE_COOLDOWN:
            return False, "cooldown"

    return True, "ok"


def record_human_message(chat_id: int) -> None:
    with _lock:
        state = _get_state(chat_id)
        state.consecutive_bot_turns = 0


def record_bot_message(chat_id: int) -> None:
    with _lock:
        state = _get_state(chat_id)
        state.consecutive_bot_turns += 1


def record_response(chat_id: int, agent_id: str) -> None:
    with _lock:
        state = _get_state(chat_id)
        state.last_response_times[agent_id] = time.time()


def build_group_prefix(
    group_name: str, sender_name: str, sender_is_bot: bool,
) -> str:
    bot_tag = " [bot]" if sender_is_bot else ""
    return f"[Group: {group_name}] {sender_name}{bot_tag}: "
