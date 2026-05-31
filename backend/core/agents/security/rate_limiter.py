"""Global hourly write rate limiter.

Optional, off by default. Tracks write tool executions across all turns
within a rolling 1-hour window. Uses an in-memory deque -- resets on
server restart, which is acceptable for a single-user app.
"""

import threading
import time
from collections import deque


class HourlyRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timestamps: deque[float] = deque()

    def check_and_record(self, limit: int) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        cutoff = now - 3600
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= limit:
                return False
            self._timestamps.append(now)
            return True

    @property
    def count_last_hour(self) -> int:
        now = time.monotonic()
        cutoff = now - 3600
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            return len(self._timestamps)


_limiter = HourlyRateLimiter()


def get_limiter() -> HourlyRateLimiter:
    return _limiter
