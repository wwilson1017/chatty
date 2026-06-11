"""Chatty — Usage summary aggregation.

Aggregates token usage and estimated cost from the unified activity log
(execution_history). Costs are estimates based on the static pricing
table in core.providers.pricing; unknown/local models count as $0.00.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.agents.reminders import db
from core.providers.pricing import estimate_cost

logger = logging.getLogger(__name__)


def get_usage_summary(days: int = 7, tz: str = "UTC") -> dict:
    """Aggregate usage over the last `days` days (0 = all time).

    Day bucketing happens in the user's timezone; timestamps in the DB
    are naive UTC.
    """
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc

    now_local = datetime.now(timezone.utc).astimezone(zone)
    cutoff_utc: str | None = None
    start_day = None
    if days > 0:
        start_day = (now_local - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff_utc = start_day.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    query = """SELECT started_at, agent, event_type, model_used, input_tokens, output_tokens
               FROM execution_history
               WHERE status != 'running'"""
    params: tuple = ()
    if cutoff_utc:
        query += " AND started_at >= ?"
        params = (cutoff_utc,)

    conn = db.get_db()
    rows = conn.execute(query, params).fetchall()

    totals = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "events": 0}
    daily: dict[str, dict] = {}
    agents: dict[str, dict] = {}
    agent_models: dict[str, Counter] = {}
    earliest_day = None

    for row in rows:
        try:
            ts = datetime.fromisoformat(row["started_at"]).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        local_ts = ts.astimezone(zone)
        day_key = local_ts.strftime("%Y-%m-%d")
        if earliest_day is None or day_key < earliest_day:
            earliest_day = day_key

        in_tok = row["input_tokens"] or 0
        out_tok = row["output_tokens"] or 0
        model = row["model_used"] or ""
        cost = estimate_cost(model, in_tok, out_tok)
        kind = "chat" if row["event_type"] == "chat" else "background"

        totals["cost"] += cost
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["events"] += 1

        day = daily.setdefault(day_key, {
            "date": day_key,
            "chat_cost": 0.0, "background_cost": 0.0,
            "chat_tokens": 0, "background_tokens": 0,
            "events": 0,
        })
        day[f"{kind}_cost"] += cost
        day[f"{kind}_tokens"] += in_tok + out_tok
        day["events"] += 1

        slug = row["agent"]
        agent = agents.setdefault(slug, {
            "slug": slug, "name": slug, "primary_model": "",
            "input_tokens": 0, "output_tokens": 0, "events": 0,
            "chat_events": 0, "background_events": 0, "cost": 0.0,
        })
        agent["input_tokens"] += in_tok
        agent["output_tokens"] += out_tok
        agent["events"] += 1
        agent[f"{kind}_events"] += 1
        agent["cost"] += cost
        if model:
            agent_models.setdefault(slug, Counter())[model] += 1

    # Zero-fill missing days from the range start (or earliest seen) to today
    today_key = now_local.strftime("%Y-%m-%d")
    if start_day is not None:
        fill_from = start_day
    elif earliest_day:
        y, m, d = (int(p) for p in earliest_day.split("-"))
        fill_from = datetime(y, m, d, tzinfo=zone)
    else:
        fill_from = None
    if fill_from is not None:
        cursor = fill_from
        while cursor.strftime("%Y-%m-%d") <= today_key:
            key = cursor.strftime("%Y-%m-%d")
            daily.setdefault(key, {
                "date": key,
                "chat_cost": 0.0, "background_cost": 0.0,
                "chat_tokens": 0, "background_tokens": 0,
                "events": 0,
            })
            cursor += timedelta(days=1)

    # Primary model = most frequent model per agent
    for slug, counter in agent_models.items():
        agents[slug]["primary_model"] = counter.most_common(1)[0][0]

    # Enrich display names from the agent registry
    try:
        from agents.db import list_agents
        names = {a["slug"]: a.get("agent_name") or a["slug"] for a in list_agents()}
        for slug, agent in agents.items():
            agent["name"] = names.get(slug, slug)
    except Exception as e:
        logger.debug("Agent name enrichment skipped: %s", e)

    return {
        "days": days,
        "timezone": str(zone),
        "estimated": True,
        "totals": totals,
        "daily": sorted(daily.values(), key=lambda d: d["date"]),
        "agents": sorted(agents.values(), key=lambda a: a["cost"], reverse=True),
    }
