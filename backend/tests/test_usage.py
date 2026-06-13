"""Tests for the usage/cost dashboard: pricing, aggregation, retention."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.providers.pricing import estimate_cost, get_model_pricing


@pytest.fixture
def reminders_db(monkeypatch, tmp_path):
    """Fresh reminders DB (execution_history lives here) using production schema."""
    import core.agents.reminders.db as db_mod

    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "reminders.db")
    db_mod._connection = None
    db_mod.init_db()
    yield db_mod.get_db()
    if db_mod._connection:
        db_mod._connection.close()
    db_mod._connection = None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _insert_event(
    conn,
    *,
    agent="test-agent",
    event_type="chat",
    status="ok",
    started_at=None,
    model="claude-sonnet-4-6",
    provider=None,
    input_tokens=0,
    output_tokens=0,
    result_full=None,
    tool_calls=None,
):
    """Insert an execution_history row directly (allows backdating)."""
    eid = str(uuid.uuid4())
    started = started_at or _iso(datetime.now(timezone.utc))
    conn.execute(
        """INSERT INTO execution_history
           (id, action_id, agent, action_type, event_type, started_at,
            completed_at, status, result_full, tool_calls, model_used, provider,
            input_tokens, output_tokens)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (eid, eid, agent, "chat" if event_type == "chat" else "heartbeat",
         event_type, started, started, status, result_full, tool_calls,
         model, provider, input_tokens, output_tokens),
    )
    conn.commit()
    return eid


# ── Pricing ───────────────────────────────────────────────────────────────────


class TestPricing:
    def test_exact_match(self):
        assert get_model_pricing("claude-opus-4-6") == (5.00, 25.00)
        assert get_model_pricing("claude-sonnet-4-6") == (3.00, 15.00)
        assert get_model_pricing("claude-haiku-4-5") == (1.00, 5.00)

    def test_prefix_match_dated_snapshot(self):
        assert get_model_pricing("claude-haiku-4-5-20251001") == (1.00, 5.00)

    def test_unknown_model_returns_none_and_zero_cost(self):
        assert get_model_pricing("llama3.2") is None
        assert estimate_cost("llama3.2", 1_000_000, 1_000_000) == 0.0

    def test_empty_model_zero_cost(self):
        assert get_model_pricing("") is None
        assert estimate_cost("", 500, 500) == 0.0

    def test_estimate_cost_math(self):
        # 1M input + 1M output on sonnet = $3 + $15
        assert estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)
        assert estimate_cost("claude-haiku-4-5-20251001", 2_000_000, 0) == pytest.approx(2.0)

    def test_current_models_priced(self):
        from core.providers.pricing import is_priced
        assert is_priced("claude-opus-4-8") is True
        assert is_priced("gpt-5.5") is True
        assert is_priced("gemini-2.5-flash-lite") is True
        # Together is paid but not priced yet; local models unpriced
        assert is_priced("Qwen/Qwen3.5-32B") is False
        assert is_priced("llama3.2") is False
        assert is_priced("") is False


# ── Provider-aware unknown pricing ──────────────────────────────────────────────


class TestUnknownPricing:
    def test_ollama_row_is_free_not_flagged(self, reminders_db):
        from core.agents.usage.service import get_usage_summary
        _insert_event(reminders_db, agent="local", model="llama3.2",
                      provider="ollama", input_tokens=1_000_000, output_tokens=1_000_000)
        s = get_usage_summary(days=7, tz="UTC")
        assert s["totals"]["cost"] == 0.0
        assert s["unknown_pricing_models"] == []
        assert s["agents"][0]["has_unknown_pricing"] is False
        assert s["agents"][0]["unknown_pricing_models"] == []

    def test_unpriced_paid_model_is_flagged(self, reminders_db):
        from core.agents.usage.service import get_usage_summary
        _insert_event(reminders_db, agent="t", model="Qwen/Qwen3.5-32B",
                      provider="together", input_tokens=1_000_000, output_tokens=0)
        s = get_usage_summary(days=7, tz="UTC")
        assert s["totals"]["cost"] == 0.0  # unknown → 0 but FLAGGED, not silent
        assert "Qwen/Qwen3.5-32B" in s["unknown_pricing_models"]
        assert s["agents"][0]["has_unknown_pricing"] is True
        assert "Qwen/Qwen3.5-32B" in s["agents"][0]["unknown_pricing_models"]

    def test_priced_paid_model_not_flagged(self, reminders_db):
        from core.agents.usage.service import get_usage_summary
        _insert_event(reminders_db, agent="a", model="claude-opus-4-8",
                      provider="anthropic", input_tokens=1_000_000, output_tokens=0)
        s = get_usage_summary(days=7, tz="UTC")
        assert s["totals"]["cost"] == pytest.approx(5.0)
        assert s["unknown_pricing_models"] == []
        assert s["agents"][0]["has_unknown_pricing"] is False

    def test_empty_model_not_flagged(self, reminders_db):
        # A paid-provider row with no model id can't be priced OR flagged.
        from core.agents.usage.service import get_usage_summary
        _insert_event(reminders_db, agent="t", model="", provider="together",
                      input_tokens=1_000_000, output_tokens=0)
        s = get_usage_summary(days=7, tz="UTC")
        assert s["unknown_pricing_models"] == []
        assert s["agents"][0]["has_unknown_pricing"] is False

    def test_explicit_anthropic_provider_priced(self, reminders_db):
        # Exercises the provider column read on the priced path (not just NULL rows).
        from core.agents.usage.service import get_usage_summary
        _insert_event(reminders_db, agent="a", model="claude-opus-4-8",
                      provider="anthropic", input_tokens=1_000_000, output_tokens=0)
        s = get_usage_summary(days=7, tz="UTC")
        assert s["totals"]["cost"] == pytest.approx(5.0)
        assert s["agents"][0]["has_unknown_pricing"] is False

    def test_legacy_null_provider_unpriced_flagged_not_free(self, reminders_db):
        # Pre-migration rows have provider=NULL; an unpriced model must be
        # flagged (conservative), never silently treated as free $0.
        from core.agents.usage.service import get_usage_summary
        _insert_event(reminders_db, agent="legacy", model="mystery-model-x",
                      provider=None, input_tokens=1_000_000, output_tokens=0)
        s = get_usage_summary(days=7, tz="UTC")
        assert "mystery-model-x" in s["unknown_pricing_models"]
        assert s["agents"][0]["has_unknown_pricing"] is True


# ── Aggregation ───────────────────────────────────────────────────────────────


class TestUsageSummary:
    def test_totals_and_chat_background_split(self, reminders_db):
        from core.agents import activity_log
        from core.agents.usage.service import get_usage_summary

        activity_log.log_chat_event(
            "alpha", model_used="claude-sonnet-4-6",
            input_tokens=1_000_000, output_tokens=0,
        )
        activity_log.log_chat_event(
            "alpha", model_used="claude-sonnet-4-6",
            input_tokens=0, output_tokens=1_000_000,
        )
        _insert_event(
            reminders_db, agent="beta", event_type="scheduled_action",
            model="claude-haiku-4-5-20251001",
            input_tokens=1_000_000, output_tokens=0,
        )

        summary = get_usage_summary(days=7, tz="UTC")

        assert summary["estimated"] is True
        assert summary["days"] == 7
        assert summary["totals"]["events"] == 3
        assert summary["totals"]["input_tokens"] == 2_000_000
        assert summary["totals"]["output_tokens"] == 1_000_000
        # $3 (sonnet in) + $15 (sonnet out) + $1 (haiku in)
        assert summary["totals"]["cost"] == pytest.approx(19.0)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day = next(d for d in summary["daily"] if d["date"] == today)
        assert day["chat_cost"] == pytest.approx(18.0)
        assert day["background_cost"] == pytest.approx(1.0)
        assert day["chat_tokens"] == 2_000_000
        assert day["background_tokens"] == 1_000_000
        assert day["events"] == 3

        # 7-day window zero-fills to exactly 7 days
        assert len(summary["daily"]) == 7
        assert summary["daily"][-1]["date"] == today

    def test_per_agent_breakdown_and_primary_model(self, reminders_db):
        from core.agents import activity_log
        from core.agents.usage.service import get_usage_summary

        activity_log.log_chat_event(
            "alpha", model_used="claude-sonnet-4-6",
            input_tokens=1_000_000, output_tokens=0,
        )
        activity_log.log_chat_event(
            "alpha", model_used="claude-sonnet-4-6",
            input_tokens=1_000_000, output_tokens=0,
        )
        activity_log.log_chat_event(
            "alpha", model_used="claude-haiku-4-5-20251001",
            input_tokens=1_000_000, output_tokens=0,
        )
        _insert_event(
            reminders_db, agent="beta", event_type="scheduled_action",
            model="claude-haiku-4-5-20251001", input_tokens=500_000,
        )

        summary = get_usage_summary(days=7, tz="UTC")
        assert [a["slug"] for a in summary["agents"]] == ["alpha", "beta"]

        alpha = summary["agents"][0]
        assert alpha["name"] == "alpha"  # registry unavailable → slug fallback
        assert alpha["primary_model"] == "claude-sonnet-4-6"
        assert alpha["input_tokens"] == 3_000_000
        assert alpha["events"] == 3
        assert alpha["chat_events"] == 3
        assert alpha["background_events"] == 0
        assert alpha["cost"] == pytest.approx(7.0)  # 3 + 3 + 1

        beta = summary["agents"][1]
        assert beta["primary_model"] == "claude-haiku-4-5-20251001"
        assert beta["chat_events"] == 0
        assert beta["background_events"] == 1
        assert beta["cost"] == pytest.approx(0.5)

    def test_running_rows_excluded(self, reminders_db):
        from core.agents.usage.service import get_usage_summary

        _insert_event(
            reminders_db, event_type="scheduled_action", status="running",
            model="claude-sonnet-4-6", input_tokens=1_000_000,
        )
        summary = get_usage_summary(days=7, tz="UTC")
        assert summary["totals"]["events"] == 0
        assert summary["totals"]["cost"] == 0.0

    def test_days_filtering(self, reminders_db):
        from core.agents.usage.service import get_usage_summary

        old = datetime.now(timezone.utc) - timedelta(days=30)
        _insert_event(
            reminders_db, started_at=_iso(old),
            model="claude-sonnet-4-6", input_tokens=1_000_000,
        )
        _insert_event(
            reminders_db, model="claude-sonnet-4-6", input_tokens=1_000_000,
        )

        recent = get_usage_summary(days=7, tz="UTC")
        assert recent["totals"]["events"] == 1

        all_time = get_usage_summary(days=0, tz="UTC")
        assert all_time["totals"]["events"] == 2
        assert all_time["days"] == 0

    def test_timezone_bucketing(self, reminders_db):
        from core.agents.usage.service import get_usage_summary

        # 03:00 UTC = previous evening in Chicago (UTC-5/-6)
        utc_day = datetime.now(timezone.utc).date()
        _insert_event(
            reminders_db,
            started_at=f"{utc_day.isoformat()}T03:00:00",
            model="claude-sonnet-4-6", input_tokens=1_000_000,
        )

        utc_summary = get_usage_summary(days=7, tz="UTC")
        utc_buckets = [d["date"] for d in utc_summary["daily"] if d["events"]]
        assert utc_buckets == [utc_day.isoformat()]

        chi_summary = get_usage_summary(days=7, tz="America/Chicago")
        assert chi_summary["timezone"] == "America/Chicago"
        chi_buckets = [d["date"] for d in chi_summary["daily"] if d["events"]]
        assert chi_buckets == [(utc_day - timedelta(days=1)).isoformat()]

    def test_invalid_timezone_falls_back_to_utc(self, reminders_db):
        from core.agents.usage.service import get_usage_summary

        summary = get_usage_summary(days=7, tz="Not/AZone")
        assert summary["timezone"] == "UTC"

    def test_empty_db(self, reminders_db):
        from core.agents.usage.service import get_usage_summary

        summary = get_usage_summary(days=7, tz="UTC")
        assert summary["totals"] == {
            "cost": 0.0, "input_tokens": 0, "output_tokens": 0, "events": 0,
        }
        assert len(summary["daily"]) == 7
        assert summary["agents"] == []

        all_time = get_usage_summary(days=0, tz="UTC")
        assert all_time["daily"] == []

    def test_all_time_zero_fill_spans_earliest_to_today(self, reminders_db):
        from core.agents.usage.service import get_usage_summary

        old = datetime.now(timezone.utc) - timedelta(days=30)
        _insert_event(
            reminders_db, started_at=_iso(old),
            model="claude-sonnet-4-6", input_tokens=1_000_000,
        )
        _insert_event(
            reminders_db, model="claude-sonnet-4-6", input_tokens=1_000_000,
        )

        summary = get_usage_summary(days=0, tz="UTC")
        assert summary["totals"]["events"] == 2
        assert len(summary["daily"]) >= 30
        dates = [d["date"] for d in summary["daily"]]
        assert old.strftime("%Y-%m-%d") in dates
        assert datetime.now(timezone.utc).strftime("%Y-%m-%d") in dates


# ── Retention ─────────────────────────────────────────────────────────────────


class TestRetention:
    def test_cleanup_retention_and_payload_trim(self, reminders_db):
        from core.agents.scheduled_actions.history import cleanup_old

        now = datetime.now(timezone.utc)

        chat_100d = _insert_event(
            reminders_db, event_type="chat",
            started_at=_iso(now - timedelta(days=100)),
        )
        chat_400d = _insert_event(
            reminders_db, event_type="chat",
            started_at=_iso(now - timedelta(days=400)),
        )
        sa_3d = _insert_event(
            reminders_db, event_type="scheduled_action",
            started_at=_iso(now - timedelta(days=3)),
            result_full="full result", tool_calls='[{"tool": "x"}]',
        )
        sa_60d = _insert_event(
            reminders_db, event_type="scheduled_action",
            started_at=_iso(now - timedelta(days=60)),
            result_full="full result", tool_calls='[{"tool": "x"}]',
        )
        sa_100d = _insert_event(
            reminders_db, event_type="scheduled_action",
            started_at=_iso(now - timedelta(days=100)),
        )

        deleted = cleanup_old()
        assert deleted == 2  # chat_400d + sa_100d

        rows = {
            r["id"]: r
            for r in reminders_db.execute(
                "SELECT id, result_full, tool_calls FROM execution_history"
            ).fetchall()
        }
        assert chat_100d in rows
        assert chat_400d not in rows
        assert sa_100d not in rows

        # Recent SA keeps payloads; 60-day SA survives but is trimmed
        assert rows[sa_3d]["result_full"] == "full result"
        assert rows[sa_3d]["tool_calls"] == '[{"tool": "x"}]'
        assert sa_60d in rows
        assert rows[sa_60d]["result_full"] is None
        assert rows[sa_60d]["tool_calls"] is None

        # Idempotency: second call should not delete or trim anything
        deleted2 = cleanup_old()
        assert deleted2 == 0
