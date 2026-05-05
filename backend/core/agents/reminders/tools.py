"""Chatty — Reminder tool handler functions.

Called by ToolRegistry when agents use reminder tools.
agent_name is injected by the registry dispatcher.
"""

import json
import re

from . import service


_WEEKDAY_MAP = {
    "mon": 1, "monday": 1,
    "tue": 2, "tuesday": 2,
    "wed": 3, "wednesday": 3,
    "thu": 4, "thursday": 4,
    "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6,
    "sun": 7, "sunday": 7,
}

_RECURRENCE_DESCRIPTIONS = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "interval": "Interval",
    "cron": "Cron",
}


def parse_recurrence(raw: str) -> dict | None:
    """Parse a natural-language recurrence string into a structured rule.

    Accepted formats:
      'daily'
      'weekly:mon,wed,fri' or 'weekly:1,3,5'
      'monthly:15'
      'every 4 hours' or 'every 30 minutes'
      'cron:0 9 * * MON-FRI'
    """
    if not raw:
        return None
    raw = raw.strip().lower()

    if raw == "daily":
        return {"type": "daily"}

    if raw.startswith("weekly"):
        parts = raw.split(":", 1)
        if len(parts) < 2:
            return {"type": "weekly", "days": [1, 2, 3, 4, 5]}
        day_strs = [d.strip() for d in parts[1].split(",")]
        days = []
        for d in day_strs:
            if d in _WEEKDAY_MAP:
                days.append(_WEEKDAY_MAP[d])
            elif d.isdigit() and 1 <= int(d) <= 7:
                days.append(int(d))
        if not days:
            return None
        return {"type": "weekly", "days": sorted(set(days))}

    if raw.startswith("monthly"):
        parts = raw.split(":", 1)
        if len(parts) < 2:
            return {"type": "monthly", "day": 1}
        try:
            day = int(parts[1].strip())
            return {"type": "monthly", "day": max(1, min(31, day))}
        except ValueError:
            return None

    m = re.match(r"every\s+(\d+)\s+(hour|hours|minute|minutes|min|mins)", raw)
    if m:
        n = int(m.group(1))
        if n < 1:
            return None
        unit = m.group(2)
        if unit.startswith("hour"):
            return {"type": "interval", "hours": n}
        return {"type": "interval", "minutes": n}

    if raw.startswith("cron:"):
        expression = raw[5:].strip()
        if expression:
            try:
                from croniter import croniter
                if croniter.is_valid(expression):
                    return {"type": "cron", "expression": expression}
            except Exception:
                pass
        return None

    return None


def _describe_recurrence(rule_json: str | None) -> str | None:
    """Return a human-readable description of a recurrence rule."""
    if not rule_json:
        return None
    try:
        rule = json.loads(rule_json)
    except (json.JSONDecodeError, TypeError):
        return None

    rtype = rule.get("type", "")

    if rtype == "daily":
        return "Daily"
    if rtype == "weekly":
        days = rule.get("days", [])
        day_names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
        names = [day_names.get(d, str(d)) for d in sorted(days)]
        return f"Weekly: {', '.join(names)}"
    if rtype == "monthly":
        return f"Monthly: day {rule.get('day', '?')}"
    if rtype == "interval":
        hours = rule.get("hours", 0)
        minutes = rule.get("minutes", 0)
        if hours and not minutes:
            return f"Every {hours}h"
        if minutes and not hours:
            return f"Every {minutes}m"
        return f"Every {hours}h {minutes}m"
    if rtype == "cron":
        return f"Cron: {rule.get('expression', '?')}"

    return None


def create_reminder_handler(agent_name: str, **kwargs) -> dict:
    recurrence_raw = kwargs.pop("recurrence", None)
    recurrence_rule = None
    if recurrence_raw:
        parsed = parse_recurrence(recurrence_raw)
        if parsed:
            recurrence_rule = json.dumps(parsed)
        else:
            return {"error": f"Could not parse recurrence: {recurrence_raw}"}

    return service.create_reminder(
        agent=agent_name,
        message=kwargs.get("message", ""),
        due_at=kwargs.get("due_at", ""),
        context=kwargs.get("context"),
        recurrence_rule=recurrence_rule,
    )


def list_reminders_handler(agent_name: str, **kwargs) -> dict:
    status = kwargs.get("status", "pending")
    reminders = service.list_reminders(agent=agent_name, status=status)
    enriched = []
    for r in reminders:
        r["is_recurring"] = bool(r.get("recurrence_rule"))
        desc = _describe_recurrence(r.get("recurrence_rule"))
        if desc:
            r["recurrence_description"] = desc
        enriched.append(r)
    return {"reminders": enriched, "count": len(enriched)}


def cancel_reminder_handler(agent_name: str = "", **kwargs) -> dict:
    reminder_id = kwargs.get("reminder_id", "")
    if not reminder_id:
        return {"error": "reminder_id is required"}
    return service.cancel_reminder(reminder_id)
