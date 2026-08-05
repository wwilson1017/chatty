"""Unit tests for the per-IP rate limiter behind /capture and the /todo web app."""

import pytest

import core.todo.ratelimit as ratelimit
from core.todo.ratelimit import IPRateLimiter


@pytest.fixture
def clock(monkeypatch):
    """Controllable stand-in for time.time as the limiter sees it."""
    state = {"now": 1_000_000.0}
    monkeypatch.setattr(ratelimit.time, "time", lambda: state["now"])
    return state


def test_limits_at_max_hits_within_window(clock):
    limiter = IPRateLimiter(window=60, max_hits=3)
    for _ in range(3):
        assert limiter.allow("1.2.3.4")
    assert not limiter.allow("1.2.3.4")
    # Each IP has its own budget.
    assert limiter.allow("5.6.7.8")


def test_window_expiry_frees_blocked_ip(clock):
    limiter = IPRateLimiter(window=60, max_hits=2)
    assert limiter.allow("1.2.3.4")
    assert limiter.allow("1.2.3.4")
    assert not limiter.allow("1.2.3.4")
    clock["now"] += 61
    assert limiter.allow("1.2.3.4")


def test_sweep_drops_stale_buckets_and_keeps_fresh(clock):
    limiter = IPRateLimiter(window=60, max_hits=5)
    for i in range(300):
        assert limiter.allow(f"stale-{i}")
    limiter.allow("fresh")
    clock["now"] += 30
    limiter.allow("fresh")  # last hit now mid-window; the stale IPs never return
    clock["now"] += 31      # stale last-hits are ≥ window old, fresh's is not
    limiter.allow("trigger")  # >_SWEEP_AT tracked → sweep runs
    assert not any(k.startswith("stale-") for k in limiter.hits)
    assert "fresh" in limiter.hits
    assert "trigger" in limiter.hits


def test_max_tracked_cap_bounds_dict(clock, monkeypatch):
    # The real cap is 10k; a small one proves the bound without an O(n²) test.
    monkeypatch.setattr(ratelimit, "_MAX_TRACKED", 300)
    limiter = IPRateLimiter(window=60, max_hits=5)
    for i in range(400):
        # Every fresh IP is still admitted — eviction makes room, never rejects.
        assert limiter.allow(f"flood-{i}")
    assert len(limiter.hits) == 300
    assert "flood-399" in limiter.hits
    # An already-tracked IP at the cap evicts nothing and keeps its budget.
    assert limiter.allow("flood-399")
    assert len(limiter.hits) == 300
