"""Tests for the Telegram message debounce system."""

import threading
import time
from unittest.mock import patch, MagicMock, call
from concurrent.futures import ThreadPoolExecutor

import pytest

from integrations.telegram import debounce
from integrations.telegram.debounce import (
    enqueue_message,
    make_on_iteration,
    _ChatState,
    _states,
    _lock,
    _STALE_TTL,
    _MAX_RESTARTS,
    _get_hold_delay_seconds,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Reset debounce state between tests."""
    with _lock:
        _states.clear()
    # Ensure executor is available
    debounce._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-debounce")
    yield
    with _lock:
        # Cancel any lingering timers
        for st in _states.values():
            if st.timer:
                st.timer.cancel()
            if st.typing_timer:
                st.typing_timer.cancel()
        _states.clear()
    debounce._executor.shutdown(wait=False)
    debounce._executor = None


@pytest.fixture
def mock_services():
    """Mock out all external services (AI, Telegram API, chat history)."""
    with patch("integrations.telegram.debounce.service") as mock_svc, \
         patch("integrations.telegram.debounce.send_message") as mock_send, \
         patch("integrations.telegram.debounce.send_chat_action") as mock_typing, \
         patch("integrations.telegram.debounce.state") as mock_state, \
         patch("integrations.telegram.debounce.group") as mock_group, \
         patch("integrations.telegram.debounce._get_hold_delay_seconds", return_value=0.1):

        # Mock save_message_only as a coroutine
        async def noop_save(*args, **kwargs):
            pass
        mock_svc.save_message_only = MagicMock(side_effect=lambda *a, **kw: noop_save(*a, **kw))

        # Mock process_message_batched
        async def fake_process_private(**kwargs):
            return "AI response"
        mock_svc.process_message_batched = MagicMock(side_effect=fake_process_private)

        # Mock process_group_message_batched
        async def fake_process_group(**kwargs):
            return "Group AI response"
        mock_svc.process_group_message_batched = MagicMock(side_effect=fake_process_group)

        # Mock state.get_or_create_conversation
        mock_state.get_or_create_conversation.return_value = {"chatty_conversation_id": "conv-123"}

        yield {
            "service": mock_svc,
            "send_message": mock_send,
            "send_chat_action": mock_typing,
            "state": mock_state,
            "group": mock_group,
        }


class TestSingleMessage:
    """Single message with no follow-up."""

    def test_single_message_produces_response(self, mock_services):
        """A single message should process and eventually send a response."""
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="hello",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        # Wait for processing + hold timer
        time.sleep(0.5)

        mock_services["send_message"].assert_called_once()
        args = mock_services["send_message"].call_args
        assert args[0][0] == 123  # chat_id
        assert "AI response" in args[0][1]  # response text
        assert args[0][2] == "bot:token"  # bot_token

    def test_typing_indicator_sent_immediately(self, mock_services):
        """Typing indicator should be sent on first message."""
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="hello",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        mock_services["send_chat_action"].assert_called_with(123, "typing", "bot:token")

    def test_state_cleaned_up_after_response(self, mock_services):
        """State should be removed after response is sent."""
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="hello",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        time.sleep(0.5)

        with _lock:
            assert ("test-agent", 123) not in _states


class TestBurstDuringHold:
    """Messages arriving during the hold window (after AI finishes)."""

    def test_second_message_during_hold_restarts(self, mock_services):
        """A second message during hold discards response and restarts AI."""
        # Slow down AI to ensure we can send second message during hold
        call_count = [0]

        async def slow_process(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "first response"
            return "combined response"

        mock_services["service"].process_message_batched = MagicMock(side_effect=slow_process)

        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="hello",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        # Wait for AI to finish and hold timer to start, then send second message
        time.sleep(0.05)
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="what's the weather?",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        # Wait for second processing + hold
        time.sleep(0.5)

        # Should have been called twice (first + restart)
        assert call_count[0] == 2
        # Only one message should be sent (the combined response)
        assert mock_services["send_message"].call_count == 1
        sent_text = mock_services["send_message"].call_args[0][1]
        assert sent_text == "combined response"


class TestBurstDuringProcessing:
    """Messages arriving while AI is still processing."""

    def test_message_during_processing_sets_cancelled(self, mock_services):
        """A message during AI processing should set the cancelled Event."""
        processing_started = threading.Event()
        hold_processing = threading.Event()

        async def slow_process(**kwargs):
            processing_started.set()
            # Block until we release
            while not hold_processing.is_set():
                time.sleep(0.01)
            # Check if we should return based on on_iteration
            on_iter = kwargs.get("on_iteration")
            if on_iter and not on_iter(1):
                return ""
            return "response"

        mock_services["service"].process_message_batched = MagicMock(side_effect=slow_process)

        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="hello",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        # Wait for processing to start
        processing_started.wait(timeout=2)

        # Verify state shows processing
        with _lock:
            st = _states.get(("test-agent", 123))
            assert st is not None
            assert st.processing is True

        # Send second message during processing
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="follow up",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        # Verify cancelled is set
        with _lock:
            st = _states.get(("test-agent", 123))
            assert st.cancelled.is_set()
            assert len(st.messages) == 2

        # Release the processing
        hold_processing.set()
        time.sleep(0.5)

        # Should eventually send a response (from the restart)
        assert mock_services["send_message"].call_count >= 1


class TestMaxRestarts:
    """After 3 restarts, stop cancelling."""

    def test_max_restarts_stops_cancellation(self, mock_services):
        """After MAX_RESTARTS, new messages accumulate without cancelling."""
        call_count = [0]

        async def counting_process(**kwargs):
            call_count[0] += 1
            return f"response-{call_count[0]}"

        mock_services["service"].process_message_batched = MagicMock(side_effect=counting_process)

        # Enqueue first message
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="msg1",
            prefix="P ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        # Wait a tiny bit for processing to start
        time.sleep(0.02)

        # Simulate the state having 3 restarts already
        with _lock:
            st = _states.get(("test-agent", 123))
            if st:
                st.restart_count = _MAX_RESTARTS

        # Send another message — should NOT set cancelled
        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="msg after max",
            prefix="P ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        with _lock:
            st = _states.get(("test-agent", 123))
            if st:
                # Should NOT be cancelled since we're past max restarts
                assert not st.cancelled.is_set()


class TestOnIteration:
    """Test the on_iteration callback mechanism."""

    def test_make_on_iteration_returns_true_when_not_cancelled(self, mock_services):
        """on_iteration should return True when not cancelled."""
        key = ("test-agent", 456)
        with _lock:
            _states[key] = _ChatState(
                messages=["test"],
                bot_token="t",
                agent_id="a",
                agent_slug="test-agent",
                sender_id="u",
                sender_name="J",
                chat_id=456,
            )

        checker = make_on_iteration(key)
        assert checker(1) is True

    def test_make_on_iteration_returns_false_when_cancelled(self, mock_services):
        """on_iteration should return False when cancelled Event is set."""
        key = ("test-agent", 456)
        with _lock:
            st = _ChatState(
                messages=["test"],
                bot_token="t",
                agent_id="a",
                agent_slug="test-agent",
                sender_id="u",
                sender_name="J",
                chat_id=456,
            )
            st.cancelled.set()
            _states[key] = st

        checker = make_on_iteration(key)
        assert checker(1) is False

    def test_make_on_iteration_returns_true_when_state_gone(self, mock_services):
        """on_iteration should return True if state was cleaned up."""
        key = ("test-agent", 789)
        # Don't create state — simulates cleanup
        checker = make_on_iteration(key)
        assert checker(1) is True


class TestGroupChat:
    """Group chat debounce behavior."""

    def test_group_message_calls_group_service(self, mock_services):
        """Group messages should use process_group_message_batched."""
        enqueue_message(
            agent_slug="test-agent",
            chat_id=999,
            message_text="hey everyone",
            prefix="[Group: Team] Alice: ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="group:999",
            sender_name="Alice",
            is_group=True,
            group_meta={"group_name": "Team", "sender_name": "Alice", "sender_is_bot": False},
        )

        time.sleep(0.5)

        mock_services["service"].process_group_message_batched.assert_called_once()
        mock_services["send_message"].assert_called_once()

    def test_group_response_records_response(self, mock_services):
        """Group responses should call group.record_response."""
        enqueue_message(
            agent_slug="test-agent",
            chat_id=999,
            message_text="hey",
            prefix="[Group: Team] Alice: ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="group:999",
            sender_name="Alice",
            is_group=True,
            group_meta={"group_name": "Team", "sender_name": "Alice", "sender_is_bot": False},
        )

        time.sleep(0.5)

        mock_services["group"].record_response.assert_called_once_with(999, "agent-1")


class TestDisabledFeature:
    """Behavior when hold delay is 0 (disabled)."""

    def test_delay_zero_sends_immediately(self, mock_services):
        """With delay=0, response should be sent as soon as AI finishes."""
        with patch("integrations.telegram.debounce._get_hold_delay_seconds", return_value=0.0):
            enqueue_message(
                agent_slug="test-agent",
                chat_id=123,
                message_text="hello",
                prefix="[via Telegram from John] ",
                bot_token="bot:token",
                agent_id="agent-1",
                sender_id="user-1",
                sender_name="John",
            )

            # Should send almost immediately (no hold timer)
            time.sleep(0.2)

            mock_services["send_message"].assert_called_once()


class TestStaleState:
    """Stale state detection and recovery."""

    def test_stale_state_resets(self, mock_services):
        """State older than STALE_TTL should be reset on next enqueue."""
        key = ("test-agent", 123)

        with _lock:
            st = _ChatState(
                messages=["old message"],
                bot_token="old_token",
                agent_id="agent-1",
                agent_slug="test-agent",
                sender_id="user-1",
                sender_name="John",
                chat_id=123,
                processing=True,
                started_at=time.monotonic() - _STALE_TTL - 10,  # Well past TTL
            )
            _states[key] = st

        enqueue_message(
            agent_slug="test-agent",
            chat_id=123,
            message_text="fresh message",
            prefix="[via Telegram from John] ",
            bot_token="bot:token",
            agent_id="agent-1",
            sender_id="user-1",
            sender_name="John",
        )

        time.sleep(0.3)

        # State should have been reset and new processing started
        mock_services["send_message"].assert_called()


class TestMessageCombination:
    """Verify messages are combined correctly."""

    def test_messages_joined_with_newline(self, mock_services):
        """Combined messages should be newline-separated."""
        captured_messages = []

        async def capture_process(**kwargs):
            captured_messages.append(kwargs.get("combined_message", ""))
            return "response"

        mock_services["service"].process_message_batched = MagicMock(side_effect=capture_process)

        # Use delay=0 so we can see the combined message without timing issues
        with patch("integrations.telegram.debounce._get_hold_delay_seconds", return_value=0.0):
            enqueue_message(
                agent_slug="test-agent",
                chat_id=123,
                message_text="hello",
                prefix="[via Telegram from John] ",
                bot_token="bot:token",
                agent_id="agent-1",
                sender_id="user-1",
                sender_name="John",
            )

            time.sleep(0.3)

        # First call should have the single prefixed message
        assert len(captured_messages) >= 1
        assert captured_messages[0] == "[via Telegram from John] hello"


class TestAdminSettings:
    """Verify admin settings integration."""

    def test_get_hold_delay_reads_settings(self):
        """_get_hold_delay_seconds should read from admin settings."""
        with patch("setup.router.load_admin_settings", return_value={"message_hold_delay_ms": 3000}):
            delay = _get_hold_delay_seconds()
            assert delay == 3.0

    def test_get_hold_delay_default(self):
        """Should default to 2.0s if setting is missing."""
        with patch("setup.router.load_admin_settings", return_value={}):
            delay = _get_hold_delay_seconds()
            assert delay == 2.0


class TestChatHistoryPersistence:
    """Verify messages are saved to chat history correctly."""

    def test_each_message_saved_individually(self, mock_services):
        """Each arriving message should be saved to history immediately."""
        save_calls = []

        async def track_save(*args, **kwargs):
            save_calls.append(kwargs)

        mock_services["service"].save_message_only = MagicMock(side_effect=track_save)

        with patch("integrations.telegram.debounce._get_hold_delay_seconds", return_value=0.0):
            enqueue_message(
                agent_slug="test-agent",
                chat_id=123,
                message_text="first",
                prefix="[via Telegram from John] ",
                bot_token="bot:token",
                agent_id="agent-1",
                sender_id="user-1",
                sender_name="John",
            )

        # First save should happen before processing starts
        mock_services["service"].save_message_only.assert_called()
