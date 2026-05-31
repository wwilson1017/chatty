"""Telegram message debounce — response hold system.

Batches rapid-fire messages into a single AI turn. When a message arrives:
1. Save it to chat history immediately
2. Start AI processing immediately (no delay on first message)
3. Hold the AI response for a configurable window before sending
4. If a new message arrives during the hold, discard the response and restart

Thread-based: uses threading.Timer for hold windows, threading.Event for
cancellation, threading.Lock for state protection.
"""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from .client import send_chat_action, send_message
from . import group, service, state

logger = logging.getLogger(__name__)

_STALE_TTL = 300  # 5 minutes — same as old busy TTL
_MAX_RESTARTS = 3
_TYPING_INTERVAL = 4.0  # Telegram typing expires after ~5s


@dataclass
class _ChatState:
    messages: list[str] = field(default_factory=list)
    held_response: str | None = None
    timer: threading.Timer | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    restart_count: int = 0
    processing: bool = False
    generation: int = 0
    bot_token: str = ""
    agent_id: str = ""
    agent_slug: str = ""
    sender_id: str = ""
    sender_name: str = ""
    chat_id: int = 0
    is_group: bool = False
    group_meta: dict | None = None
    typing_timer: threading.Timer | None = None
    started_at: float = 0.0


_states: dict[tuple[str, int], _ChatState] = {}
_lock = threading.Lock()

# Use the router's executor for AI processing
_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        from .router import _executor as router_executor
        _executor = router_executor
    return _executor


def _get_hold_delay_seconds() -> float:
    from setup.router import load_admin_settings
    settings = load_admin_settings()
    return settings.get("message_hold_delay_ms", 2000) / 1000.0


def make_on_iteration(key: tuple[str, int]) -> Callable[[int], bool]:
    """Build an on_iteration callback that checks the cancellation Event."""
    def check(_iteration: int) -> bool:
        with _lock:
            st = _states.get(key)
            if st is None:
                return True
            return not st.cancelled.is_set()
    return check


def enqueue_message(
    agent_slug: str,
    chat_id: int,
    message_text: str,
    prefix: str,
    bot_token: str,
    agent_id: str,
    sender_id: str,
    sender_name: str,
    is_group: bool = False,
    group_meta: dict | None = None,
) -> None:
    """Enqueue a message for debounced processing.

    Called from the router's _safe_process_telegram(). This is the main
    entry point for the debounce system.
    """
    key = (agent_slug, chat_id)
    prefixed_text = prefix + message_text

    # Save to chat history immediately (fire-and-forget)
    _save_message_async(agent_id, agent_slug, sender_id, prefixed_text,
                        source="telegram-group" if is_group else "telegram")

    # Send typing indicator
    send_chat_action(chat_id, "typing", bot_token)

    with _lock:
        st = _states.get(key)

        if st is None:
            # First message for this chat — create state and start processing
            st = _ChatState(
                messages=[prefixed_text],
                bot_token=bot_token,
                agent_id=agent_id,
                agent_slug=agent_slug,
                sender_id=sender_id,
                sender_name=sender_name,
                chat_id=chat_id,
                is_group=is_group,
                group_meta=group_meta,
                processing=True,
                started_at=time.monotonic(),
            )
            _states[key] = st
            _start_typing_refresh(key, st)
            generation = st.generation
            # Release lock before submitting to executor
            _get_executor().submit(_run_ai, key, generation)
            return

        # Stale state detection
        if st.processing and (time.monotonic() - st.started_at) > _STALE_TTL:
            logger.warning("Debounce: stale state for %s, resetting", key)
            _cancel_timers(st)
            st.messages = [prefixed_text]
            st.held_response = None
            st.cancelled.clear()
            st.restart_count = 0
            st.processing = True
            st.generation += 1
            st.started_at = time.monotonic()
            st.bot_token = bot_token
            st.agent_id = agent_id
            st.sender_id = sender_id
            st.sender_name = sender_name
            st.is_group = is_group
            st.group_meta = group_meta
            _start_typing_refresh(key, st)
            generation = st.generation
            _get_executor().submit(_run_ai, key, generation)
            return

        # Update group_meta with latest message's sender info
        if is_group and group_meta:
            st.group_meta = group_meta
        st.sender_name = sender_name

        if st.held_response is not None:
            # AI finished, response is being held — cancel timer, discard, restart
            if st.timer is not None:
                st.timer.cancel()
                st.timer = None
            st.held_response = None
            st.messages.append(prefixed_text)
            st.processing = True
            st.cancelled.clear()
            st.generation += 1
            st.started_at = time.monotonic()
            generation = st.generation
            _get_executor().submit(_run_ai, key, generation)
            return

        if st.processing:
            # AI is still running — accumulate and signal cancellation if allowed
            st.messages.append(prefixed_text)
            if st.restart_count < _MAX_RESTARTS:
                st.cancelled.set()
            return

        # Shouldn't reach here, but handle gracefully
        st.messages.append(prefixed_text)
        st.processing = True
        st.cancelled.clear()
        st.generation += 1
        st.started_at = time.monotonic()
        generation = st.generation
        _get_executor().submit(_run_ai, key, generation)


def _run_ai(key: tuple[str, int], generation: int) -> None:
    """Run AI processing in a thread. Handles completion, cancellation, and restart."""
    with _lock:
        st = _states.get(key)
        if st is None or st.generation != generation:
            return
        combined = "\n".join(st.messages)
        is_group = st.is_group
        agent_id = st.agent_id
        sender_id = st.sender_id
        sender_name = st.sender_name

    # Run the AI call (blocking, with its own event loop)
    loop = asyncio.new_event_loop()
    try:
        on_iter = make_on_iteration(key)
        if is_group:
            chat_id = key[1]
            response = loop.run_until_complete(
                service.process_group_message_batched(
                    chat_id=chat_id,
                    agent_id=agent_id,
                    combined_message=combined,
                    on_iteration=on_iter,
                )
            )
        else:
            response = loop.run_until_complete(
                service.process_message_batched(
                    sender_id=sender_id,
                    sender_name=sender_name,
                    combined_message=combined,
                    agent_id=agent_id,
                    on_iteration=on_iter,
                )
            )
    except Exception:
        logger.exception("Debounce: AI processing failed for %s", key)
        response = ""
    finally:
        loop.close()

    # Handle completion
    with _lock:
        st = _states.get(key)
        if st is None or st.generation != generation:
            return  # Stale — a newer run superseded us

        if st.cancelled.is_set():
            # Cancelled — restart with accumulated messages
            st.cancelled.clear()
            st.restart_count += 1
            st.generation += 1
            st.started_at = time.monotonic()
            new_generation = st.generation
            _get_executor().submit(_run_ai, key, new_generation)
            return

        st.processing = False

        if not response:
            # AI returned empty (error) — send error message and cleanup
            _stop_typing_refresh(st)
            del _states[key]
            send_message(st.chat_id, "I had trouble processing that. Please try again.", st.bot_token)
            return

        # Normal completion — check hold delay
        hold_delay = _get_hold_delay_seconds()
        if hold_delay <= 0:
            # Disabled — send immediately
            chat_id = st.chat_id
            bot_token = st.bot_token
            is_group = st.is_group
            agent_id = st.agent_id
            agent_slug = st.agent_slug
            sender_id = st.sender_id
            _stop_typing_refresh(st)
            del _states[key]
            send_message(chat_id, response, bot_token)
            if is_group:
                group.record_response(chat_id, agent_id)
            _save_response_async(agent_slug, sender_id, agent_id, response,
                                 source="telegram-group" if is_group else "telegram")
            return

        # Start hold timer
        st.held_response = response
        st.timer = threading.Timer(hold_delay, _on_hold_expired, args=[key, generation])
        st.timer.daemon = True
        st.timer.start()


def _on_hold_expired(key: tuple[str, int], generation: int) -> None:
    """Hold window expired — send the response."""
    with _lock:
        st = _states.get(key)
        if st is None or st.generation != generation:
            return
        if st.held_response is None:
            return  # Already cancelled by a new message

        response = st.held_response
        chat_id = st.chat_id
        bot_token = st.bot_token
        agent_slug = st.agent_slug
        sender_id = st.sender_id
        agent_id = st.agent_id
        is_group = st.is_group

        _stop_typing_refresh(st)
        del _states[key]

    send_message(chat_id, response, bot_token)
    if is_group:
        group.record_response(chat_id, agent_id)
    _save_response_async(agent_slug, sender_id, agent_id, response,
                         source="telegram-group" if is_group else "telegram")


# ---------------------------------------------------------------------------
# Typing indicator refresh
# ---------------------------------------------------------------------------

def _start_typing_refresh(key: tuple[str, int], st: _ChatState) -> None:
    """Start a repeating timer to refresh the typing indicator."""
    _stop_typing_refresh(st)
    t = threading.Timer(_TYPING_INTERVAL, _typing_tick, args=[key])
    t.daemon = True
    t.start()
    st.typing_timer = t


def _typing_tick(key: tuple[str, int]) -> None:
    """Send typing indicator and schedule next tick."""
    with _lock:
        st = _states.get(key)
        if st is None:
            return
        chat_id = st.chat_id
        bot_token = st.bot_token

    send_chat_action(chat_id, "typing", bot_token)

    with _lock:
        st = _states.get(key)
        if st is None:
            return
        t = threading.Timer(_TYPING_INTERVAL, _typing_tick, args=[key])
        t.daemon = True
        t.start()
        st.typing_timer = t


def _stop_typing_refresh(st: _ChatState) -> None:
    """Cancel the typing refresh timer."""
    if st.typing_timer is not None:
        st.typing_timer.cancel()
        st.typing_timer = None


def _cancel_timers(st: _ChatState) -> None:
    """Cancel all timers on a state."""
    if st.timer is not None:
        st.timer.cancel()
        st.timer = None
    _stop_typing_refresh(st)


# ---------------------------------------------------------------------------
# Chat history helpers (fire-and-forget, non-blocking)
# ---------------------------------------------------------------------------

def _save_message_async(
    agent_id: str, agent_slug: str, sender_id: str, content: str, source: str = "telegram",
) -> None:
    """Save a user message to chat history without blocking."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(service.save_message_only(
            agent_id=agent_id,
            agent_slug=agent_slug,
            sender_id=sender_id,
            content=content,
            source=source,
        ))
    except Exception:
        logger.warning("Debounce: failed to save message for %s/%s", agent_slug, sender_id, exc_info=True)
    finally:
        loop.close()


def _save_response_async(
    agent_slug: str, sender_id: str, agent_id: str, response: str, source: str = "telegram",
) -> None:
    """Save the assistant response to chat history."""
    try:
        from agents.engine import get_chat_service
        chat_service = get_chat_service(agent_slug)
        if not chat_service:
            return

        conv = state.get_or_create_conversation(sender_id, agent_id)
        chatty_conv_id = conv.get("chatty_conversation_id")
        if not chatty_conv_id:
            return

        chat_service.save_message(
            conversation_id=chatty_conv_id,
            msg_id=str(uuid.uuid4()),
            role="assistant",
            content=response,
        )
    except Exception:
        logger.warning("Debounce: failed to save response for %s", agent_slug, exc_info=True)
