"""
Chatty — per-IP rate limiting for the no-login todo endpoints.

Shared by /capture and the public todo web app: both are reachable without
a JWT, so both need a cheap in-process guard against flooding and against
brute-forcing the secret path token.
"""

import time
from collections import defaultdict

# Above this many tracked IPs, whole expired buckets are dropped. Pruning
# timestamps alone still leaks the keys, so an attacker cycling source IPs
# could grow the dict unboundedly.
_SWEEP_AT = 256


class IPRateLimiter:
    """Fixed-window-ish counter: at most `max_hits` per `window` seconds per IP."""

    def __init__(self, window: int, max_hits: int):
        self.window = window
        self.max_hits = max_hits
        self.hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, ip: str) -> bool:
        now = time.time()
        if len(self.hits) > _SWEEP_AT:
            for stale in [k for k, v in self.hits.items()
                          if not v or now - v[-1] >= self.window]:
                del self.hits[stale]
        self.hits[ip] = [t for t in self.hits[ip] if now - t < self.window]
        if len(self.hits[ip]) >= self.max_hits:
            return False
        self.hits[ip].append(now)
        return True

    def clear(self) -> None:
        self.hits.clear()
