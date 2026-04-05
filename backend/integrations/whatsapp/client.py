"""Chatty — WhatsApp messaging client via Baileys sidecar.

The sidecar is a small Node.js Express server that manages Baileys sessions
and exposes a REST API for session CRUD, QR retrieval, and message sending.
This module wraps those HTTP calls.

Ported from CAKE OS messaging/whatsapp_client.py.
"""

import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

# WhatsApp text messages are limited to ~65536 chars, but readability
# drops sharply past 4096.  Chunk on paragraph boundaries.
MAX_CHUNK_LENGTH = 4000


def _headers() -> dict[str, str]:
    h: dict[str, str] = {}
    if settings.whatsapp.bridge_api_key:
        h["X-Api-Key"] = settings.whatsapp.bridge_api_key
    return h


def _base_url() -> str:
    return settings.whatsapp.bridge_url.rstrip("/")


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(session_id: str) -> dict:
    """Create and start a new Baileys session on the sidecar."""
    if not settings.whatsapp.is_configured:
        return {"error": "WhatsApp bridge not configured"}
    try:
        resp = httpx.post(
            f"{_base_url()}/sessions",
            json={"session": session_id},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Failed to create WhatsApp session %s: %s", session_id, e)
        return {"error": str(e)}


def delete_session(session_id: str) -> dict:
    """Logout and delete a Baileys session."""
    if not settings.whatsapp.is_configured:
        return {"error": "WhatsApp bridge not configured"}
    try:
        resp = httpx.delete(
            f"{_base_url()}/sessions/{session_id}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Failed to delete WhatsApp session %s: %s", session_id, e)
        return {"error": str(e)}


def get_status(session_id: str) -> dict:
    """Get the status of a Baileys session.

    Returns dict with ``status`` key: "scan_qr", "connecting", "connected",
    "disconnected", or "not_configured".
    """
    if not settings.whatsapp.is_configured:
        return {"status": "not_configured"}
    try:
        resp = httpx.get(
            f"{_base_url()}/sessions/{session_id}",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 404:
            return {"status": "disconnected"}
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning("WhatsApp status check failed for %s: %s", session_id, e)
        return {"status": "disconnected", "error": str(e)}


def get_qr(session_id: str) -> bytes | None:
    """Fetch the QR code PNG for a session.

    Returns raw PNG bytes when QR is available, or None otherwise.
    """
    if not settings.whatsapp.is_configured:
        return None
    try:
        resp = httpx.get(
            f"{_base_url()}/sessions/{session_id}/qr",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.content
        return None
    except httpx.HTTPError:
        return None


def list_sessions() -> list[dict]:
    """List all sessions on the sidecar with their status."""
    if not settings.whatsapp.is_configured:
        return []
    try:
        resp = httpx.get(
            f"{_base_url()}/sessions",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning("Failed to list WhatsApp sessions: %s", e)
        return []


# ---------------------------------------------------------------------------
# Message sending
# ---------------------------------------------------------------------------

def send_message(phone: str, text: str, session: str = "default") -> list[dict]:
    """Send a text message via the sidecar.

    Long messages are chunked into multiple sends.
    Returns a list of response dicts (one per chunk).
    """
    if not settings.whatsapp.is_configured:
        logger.warning("WhatsApp not configured — cannot send message")
        return []

    phone = phone.lstrip("+")
    chunks = _chunk_text(text, MAX_CHUNK_LENGTH)
    results = []
    for chunk in chunks:
        try:
            resp = httpx.post(
                f"{_base_url()}/sessions/{session}/send",
                json={"phone": phone, "text": chunk},
                headers=_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            results.append(resp.json())
        except httpx.HTTPError as e:
            logger.error("WhatsApp send failed: %s", e)
            results.append({"error": str(e)})

    return results


# ---------------------------------------------------------------------------
# Text chunking helper
# ---------------------------------------------------------------------------

def _chunk_text(text: str, max_length: int) -> list[str]:
    """Split text into chunks on paragraph boundaries."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Find the last paragraph break before the limit
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at == -1:
            # No paragraph break — try single newline
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            # No newline — try space
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1:
            # No good break point — hard cut
            split_at = max_length

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks
