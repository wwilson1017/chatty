"""Tests for per-turn relevance gating: social closer detection and overlap."""

from core.agents.context_manager import is_social_closer, _tokenize


class TestSocialCloser:
    def test_thanks(self):
        assert is_social_closer("thanks")

    def test_thanks_with_punctuation(self):
        assert is_social_closer("Thanks!")

    def test_ok(self):
        assert is_social_closer("ok")

    def test_ok_period(self):
        assert is_social_closer("ok.")

    def test_single_emoji(self):
        assert is_social_closer("👍")

    def test_short_emoji(self):
        assert is_social_closer("🙂")

    def test_empty_message(self):
        assert is_social_closer("")

    def test_real_question(self):
        assert not is_social_closer("What's the status of the project?")

    def test_long_message_with_closer_word(self):
        assert not is_social_closer("This is a real question about thanks and gratitude")

    def test_got_it(self):
        assert is_social_closer("got it")

    def test_sounds_good(self):
        assert is_social_closer("Sounds good!")

    def test_noted(self):
        assert is_social_closer("Noted.")

    def test_substantial_sentence(self):
        assert not is_social_closer("Can you check the email from John about the meeting?")


class TestQueryOverlap:
    def test_identical_queries(self):
        tokens_a = set(_tokenize("tell me about project alpha"))
        tokens_b = set(_tokenize("tell me about project alpha"))
        overlap = len(tokens_a & tokens_b) / max(len(tokens_a), 1)
        assert overlap > 0.85

    def test_different_topics(self):
        tokens_a = set(_tokenize("tell me about project alpha"))
        tokens_b = set(_tokenize("what did john say about the budget"))
        overlap = len(tokens_a & tokens_b) / max(len(tokens_a), 1)
        assert overlap < 0.85

    def test_similar_but_different(self):
        tokens_a = set(_tokenize("how is the alpha project going"))
        tokens_b = set(_tokenize("what about the beta project status"))
        overlap = len(tokens_a & tokens_b) / max(len(tokens_a), 1)
        assert overlap < 0.85
