"""
Chatty — per-IP rate limiting for the no-login todo endpoints.

Shared by /capture and the public todo web app: both are reachable without
a JWT, so both need a cheap in-process guard against flooding and against
brute-forcing the secret path token.
"""

import time
from collections import OrderedDict

# Above this many tracked IPs, whole expired buckets are dropped. Pruning
# timestamps alone still leaks the keys, so an attacker cycling source IPs
# could grow the dict unboundedly.
_SWEEP_AT = 256

# Hard ceiling on tracked IPs. The sweep only drops *expired* buckets, so a
# flood of ever-new source IPs inside one window (spoofed X-Forwarded-For
# behind a misconfigured proxy, or a real distributed flood) could still
# grow the dict to rate × window. At the cap, the least-recently-touched
# bucket is evicted to admit the newcomer, bounding memory.
_MAX_TRACKED = 10_000


class IPRateLimiter:
    """Fixed-window-ish counter: at most `max_hits` per `window` seconds per IP."""

    def __init__(self, window: int, max_hits: int):
        self.window = window
        self.max_hits = max_hits
        # OrderedDict as an LRU: every touched IP moves to the end, so the
        # eviction at the cap is an O(1) popitem instead of a full scan on
        # every request during exactly the flood the cap exists to bound.
        self.hits: OrderedDict[str, list[float]] = OrderedDict()
        self._last_sweep = 0.0

    def allow(self, ip: str) -> bool:
        now = time.time()
        # The sweep is O(tracked IPs), so once past _SWEEP_AT a spoofed-IP
        # flood would pay a full scan on every request. At most once per
        # second is plenty — the cap below bounds memory between sweeps.
        if len(self.hits) > _SWEEP_AT and now - self._last_sweep >= 1.0:
            self._last_sweep = now
            for stale in [k for k, v in self.hits.items()
                          if not v or now - v[-1] >= self.window]:
                del self.hits[stale]
        if ip not in self.hits and len(self.hits) >= _MAX_TRACKED:
            self.hits.popitem(last=False)
        self.hits[ip] = [t for t in self.hits.get(ip, []) if now - t < self.window]
        self.hits.move_to_end(ip)
        if len(self.hits[ip]) >= self.max_hits:
            return False
        self.hits[ip].append(now)
        return True

    def clear(self) -> None:
        self.hits.clear()
