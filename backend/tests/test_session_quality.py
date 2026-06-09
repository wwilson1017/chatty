"""Tests for session quality scoring."""

from core.agents.memory.processor import score_session_quality


def test_empty_messages():
    assert score_session_quality([]) == 0.0


def test_trivial_conversation():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]
    score = score_session_quality(messages)
    assert score < 0.3


def test_substantive_conversation_with_decisions():
    messages = [
        {"role": "user", "content": "We need to decide on the deployment strategy for the new API. " * 3},
        {"role": "assistant", "content": "I've analyzed the options. We decided to use blue-green deployment with automated rollback. " * 2},
        {"role": "user", "content": "That sounds right. Let's go with the containerized approach for staging too. " * 2},
        {"role": "assistant", "content": "I've resolved the configuration issue. The staging environment is now approved and deployed. " * 2},
        {"role": "user", "content": "Great work on the deployment. Going forward, we should always test in staging first. " * 2},
        {"role": "assistant", "content": "Noted. From now on, all deployments will go through staging before production. " * 2},
    ]
    score = score_session_quality(messages)
    assert score > 0.5


def test_recall_tracking_affects_score():
    messages = [
        {"role": "user", "content": "Tell me about the project status and what we decided last week about timelines."},
        {"role": "assistant", "content": "Based on the notes, we decided to ship the alpha release by Friday. The deployment strategy was approved."},
    ]
    # With no recall data -> 0.5 (neutral)
    score_neutral = score_session_quality(messages, recall_tracking=None)

    # With good recall
    score_good = score_session_quality(messages, recall_tracking={"a": True, "b": True, "c": True})

    # With bad recall
    score_bad = score_session_quality(messages, recall_tracking={"a": False, "b": False, "c": False})

    assert score_good > score_bad
    assert score_neutral > score_bad


def test_recall_default_is_neutral():
    messages = [
        {"role": "user", "content": "What happened with the project?"},
        {"role": "assistant", "content": "The project is on track."},
    ]
    score = score_session_quality(messages)
    # Recall contributes 0.2 * 0.5 = 0.1 when no tracking data
    assert score > 0.0


def test_engagement_matters():
    # Long user messages = high engagement
    long = [
        {"role": "user", "content": "x" * 100},
        {"role": "assistant", "content": "Response here with some content to make it substantial enough."},
        {"role": "user", "content": "y" * 100},
        {"role": "assistant", "content": "Another response with good detail and analysis."},
        {"role": "user", "content": "z" * 100},
        {"role": "assistant", "content": "Final response wrapping up the conversation."},
    ]
    short = [
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "Sure."},
    ]
    assert score_session_quality(long) > score_session_quality(short)
