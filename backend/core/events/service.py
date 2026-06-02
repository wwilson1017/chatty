"""Chatty -- Event log service helpers.

Convenience wrappers that combine event logging with alert creation
and external notifications (Telegram/WhatsApp).
"""

import logging

from core.events.db import log_event

logger = logging.getLogger(__name__)


def log_security_event(
    event_type: str,
    summary: str,
    *,
    severity: str = "warning",
    agent_slug: str | None = None,
    source: str | None = None,
    details: dict | str | None = None,
) -> str | None:
    """Log a security event and create a persistent alert for the user.

    For warning/error/critical severity: creates an in-app alert (golden banner)
    and pushes to Telegram/WhatsApp if connected.
    """
    try:
        event_id = log_event(
            "security", event_type, summary,
            severity=severity, agent_slug=agent_slug,
            source=source, details=details,
        )
    except Exception:
        logger.exception("Failed to log security event: %s", event_type)
        return None

    if severity in ("warning", "error", "critical") and agent_slug:
        try:
            from core.agents.alerts.service import create_alert
            create_alert(
                agent_slug,
                f"Security: {event_type.replace('_', ' ').title()}",
                summary[:500],
                source="security",
                source_id=f"security_{event_type}_{event_id}",
            )
        except Exception:
            logger.warning("Failed to create alert for security event %s", event_id)

        try:
            from core.agents.scheduled_actions.notifications import send_external_for_agent
            send_external_for_agent(
                agent_slug,
                f"[Security] {summary[:500]}",
                title=event_type.replace("_", " ").title(),
            )
        except Exception:
            logger.debug("Failed to push external notification for security event %s", event_id)

    return event_id
