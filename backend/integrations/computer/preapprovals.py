"""Chatty — pre-approved gates for scheduled actions.

A cron scheduled action may carry {host, button_text} pairs its computer tasks
cross without asking ("submit the timesheet every Friday"). They are read here,
on the server, from the task's `action_id` (stamped from the server-built `_ctx`,
never from model input), re-checked against the prompt they were bound to, and
matched deterministically against the element the classifier just gated. Only
`match()` decides; the runner then records an already-approved gate and sends the
one activation through its normal dispatch path, so the computer re-checks the
same binding it would for an owner's approval.

Never pre-approved: purchases (kind "buy"), a send or post whose composer has no
fingerprint (the recipients and text can't be pinned to the click — it asks, as
a takeover card, like an owner approval would), anything that isn't a single
click or Enter/Space (`gates.dispatch_for`), targets that couldn't be identified,
and any task without a cron action behind it (heartbeats and reminders carry none).
"""

from core.agents.scheduled_actions import service as actions

from . import gates


def match(action_id: str | None, kind: str, label: str, element: dict | None) -> dict | None:
    """The pre-approval covering this gated action, or None → the normal gate."""
    if not action_id or kind == "buy" or not element or not element.get("found") or gates.dispatch_for(label) is None:
        return None
    if kind in ("send", "post") and not element.get("context_fp"):
        return None
    host = actions.normalize_host((element.get("page") or {}).get("host"))
    name = actions.normalize_text(element.get("name")).lower()
    if not host or not name:
        return None
    for item in actions.preapproved_for(actions.get_action(action_id)):
        if actions.normalize_host(item["host"]) == host and actions.normalize_text(item["button_text"]).lower() == name:
            return item
    return None
