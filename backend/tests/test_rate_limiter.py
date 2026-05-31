"""Tests for hourly write rate limiter."""

import threading
from unittest.mock import patch

from core.agents.security.rate_limiter import HourlyRateLimiter


class TestHourlyRateLimiter:
    def test_under_limit_allows(self):
        limiter = HourlyRateLimiter()
        assert limiter.check_and_record(5) is True
        assert limiter.check_and_record(5) is True
        assert limiter.check_and_record(5) is True

    def test_at_limit_blocks(self):
        limiter = HourlyRateLimiter()
        for _ in range(3):
            limiter.check_and_record(3)
        assert limiter.check_and_record(3) is False

    def test_zero_limit_always_allows(self):
        limiter = HourlyRateLimiter()
        for _ in range(100):
            assert limiter.check_and_record(0) is True

    def test_expired_entries_purged(self):
        limiter = HourlyRateLimiter()
        with patch("core.agents.security.rate_limiter.time.monotonic", return_value=1000.0):
            limiter.check_and_record(2)
            limiter.check_and_record(2)
            assert limiter.check_and_record(2) is False

        with patch("core.agents.security.rate_limiter.time.monotonic", return_value=4601.0):
            assert limiter.check_and_record(2) is True

    def test_count_last_hour(self):
        limiter = HourlyRateLimiter()
        limiter.check_and_record(10)
        limiter.check_and_record(10)
        limiter.check_and_record(10)
        assert limiter.count_last_hour == 3

    def test_thread_safety(self):
        limiter = HourlyRateLimiter()
        results = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            results.append(limiter.check_and_record(5))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        allowed = sum(1 for r in results if r)
        denied = sum(1 for r in results if not r)
        assert allowed == 5
        assert denied == 5
