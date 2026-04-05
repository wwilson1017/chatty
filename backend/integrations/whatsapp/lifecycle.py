"""Chatty — WhatsApp session lifecycle management.

Handles session creation/deletion on the Baileys sidecar, QR retrieval,
and the time-limited auto-registration window that lets a user self-onboard
by messaging the agent's WhatsApp within 10 minutes of connection.

Ported from CAKE OS messaging/whatsapp_lifecycle.py.
Adapted: agent_email → agent_slug, session IDs use wa-{slug} format.
"""

import logging

from agents.db import get_agent_by_slug, list_agents, update_agent

from . import state
from . import client as whatsapp_client

logger = logging.getLogger(__name__)


def _session_id_for(agent_slug: str) -> str:
    """Generate the sidecar session ID for an agent."""
    return f"wa-{agent_slug}"


def session_id_to_agent_slug(session_id: str) -> str | None:
    """Resolve a sidecar session ID back to the agent slug.

    Session IDs have the format "wa-{slug}".
    Returns the slug if the agent exists, None otherwise.
    """
    if not session_id.startswith("wa-"):
        return None
    slug = session_id[3:]  # strip "wa-" prefix
    agent = get_agent_by_slug(slug)
    return slug if agent else None


def start_session(agent_slug: str) -> dict:
    """Start a WhatsApp session for an agent.

    Creates the session on the sidecar, saves the session ID to the agent
    registry, and opens a 10-minute registration window.

    Returns dict with session_id, status, and registration window info.
    """
    agent = get_agent_by_slug(agent_slug)
    if not agent:
        raise ValueError(f"Agent not found: {agent_slug}")

    session_id = _session_id_for(agent_slug)

    result = whatsapp_client.create_session(session_id)
    if "error" in result:
        raise ValueError(f"Failed to create session: {result['error']}")

    # Save session ID to agent DB
    update_agent(agent["id"], whatsapp_session_id=session_id)

    # Open registration window
    window = state.open_registration_window(agent_slug)

    return {
        "session_id": session_id,
        "status": result.get("status", "starting"),
        "registration_expires_at": window["expires_at"],
    }


def stop_session(agent_slug: str) -> None:
    """Disconnect WhatsApp for an agent.

    Deletes the session from the sidecar and clears the session ID from the DB.
    """
    agent = get_agent_by_slug(agent_slug)
    if not agent:
        return

    session_id = agent.get("whatsapp_session_id", "")
    if session_id:
        whatsapp_client.delete_session(session_id)

    update_agent(agent["id"], whatsapp_session_id="")


def get_session_status(agent_slug: str) -> dict:
    """Get WhatsApp session status for an agent."""
    agent = get_agent_by_slug(agent_slug)
    if not agent:
        return {"status": "not_found"}

    session_id = agent.get("whatsapp_session_id", "")
    if not session_id:
        return {"status": "disconnected"}

    return whatsapp_client.get_status(session_id)


def get_session_qr(agent_slug: str) -> bytes | None:
    """Get QR code PNG for an agent's WhatsApp session."""
    agent = get_agent_by_slug(agent_slug)
    if not agent:
        return None

    session_id = agent.get("whatsapp_session_id", "")
    if not session_id:
        return None

    return whatsapp_client.get_qr(session_id)


def reset_registration_window(agent_slug: str) -> dict:
    """Reset (re-open) the WhatsApp registration window for an agent.

    Returns the new window info.
    Raises ValueError if the agent has no active WhatsApp session.
    """
    agent = get_agent_by_slug(agent_slug)
    if not agent or not agent.get("whatsapp_session_id"):
        raise ValueError("Agent has no WhatsApp session configured")

    return state.open_registration_window(agent_slug)


def reconnect_all_sessions() -> None:
    """Log the status of all agents with WhatsApp sessions.

    Sessions with saved credentials auto-reconnect on sidecar startup,
    so this function just checks and logs their status.
    """
    agents = list_agents()
    count = 0
    for agent in agents:
        session_id = agent.get("whatsapp_session_id", "")
        if not session_id:
            continue

        try:
            status = whatsapp_client.get_status(session_id)
            session_status = status.get("status", "unknown")
            if session_status in ("connected", "scan_qr", "connecting"):
                count += 1
            logger.info(
                "WhatsApp session %s (%s): %s",
                session_id, agent["agent_name"], session_status,
            )
        except Exception as e:
            logger.warning(
                "WhatsApp status check failed for %s: %s",
                agent["agent_name"], e,
            )

    if count:
        logger.info("Found %d active WhatsApp session(s)", count)


def try_auto_register(
    agent_slug: str, phone: str, sender_name: str,
) -> bool:
    """Try to auto-register a WhatsApp user during the registration window.

    Returns True if registration succeeded, False if the window is closed.
    """
    if not state.is_registration_open(agent_slug):
        return False

    state.create_mapping("whatsapp", phone, agent_slug, sender_name)
    state.close_registration_window(agent_slug, phone)
    return True
