"""Chatty — WhatsApp messaging router.

Handles inbound webhooks from the Baileys sidecar plus JWT-protected
admin endpoints for managing per-agent WhatsApp sessions.

Ported from CAKE OS messaging/router.py (WhatsApp endpoints only).
"""

import hmac
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from core.auth import get_current_user
from core.config import settings

from . import state, service, lifecycle
from . import client as whatsapp_client
from .models import StartSessionRequest, ResetRegistrationRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wa-webhook")


# ---------------------------------------------------------------------------
# WhatsApp webhook (Baileys sidecar) — no JWT, token-verified
# ---------------------------------------------------------------------------

_wa_token_warned = False


def _verify_webhook(request: Request) -> None:
    """Verify the webhook secret from the sidecar's X-Api-Key header."""
    global _wa_token_warned
    expected = settings.whatsapp.webhook_secret
    if not expected:
        if not _wa_token_warned:
            logger.warning(
                "WHATSAPP_WEBHOOK_SECRET is not set — WhatsApp webhook is open. "
                "Set the secret in production."
            )
            _wa_token_warned = True
        return

    token = request.headers.get("X-Api-Key", "")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook token")


@router.post("/webhook", status_code=200)
async def whatsapp_webhook(request: Request):
    """Receive inbound messages from the Baileys sidecar.

    Payload: { session, phone, text, sender_name, message_id }
    Returns 200 immediately; processes message and sends reply in background.
    """
    _verify_webhook(request)

    try:
        raw = await request.json()
    except Exception:
        logger.warning("WhatsApp webhook: unparseable body")
        return {"status": "ok"}

    session = raw.get("session", "")
    phone = raw.get("phone", "")
    text = raw.get("text", "")
    sender_name = raw.get("sender_name", "")

    if not phone or not text:
        return {"status": "ok"}

    logger.info(
        "WhatsApp message: session=%s from=%s name=%s msg=%s",
        session, phone, sender_name, text[:100],
    )

    _executor.submit(_safe_process_whatsapp, session, phone, sender_name, text)
    return {"status": "ok"}


def _try_auto_register(
    agent_slug: str | None, phone: str, sender_name: str,
) -> bool:
    """Try to auto-register a WhatsApp user, checking agent-specific window first,
    then falling back to any open window. Returns True if registered."""
    if agent_slug and lifecycle.try_auto_register(agent_slug, phone, sender_name):
        logger.info("Auto-registered WhatsApp user %s for agent %s", phone, agent_slug)
        return True
    # Fall back to any open window
    window = state.get_any_open_window()
    if window and lifecycle.try_auto_register(window["agent_slug"], phone, sender_name):
        logger.info(
            "Auto-registered WhatsApp user %s for agent %s (via open window)",
            phone, window["agent_slug"],
        )
        return True
    return False


def _safe_process_whatsapp(
    session: str, phone: str, sender_name: str, message: str,
) -> None:
    """Process WhatsApp message and send reply. Catches exceptions."""
    try:
        # Resolve session → agent slug
        agent_slug = lifecycle.session_id_to_agent_slug(session)

        # Check if sender has a mapping
        mapping = state.get_mapping_by_sender("whatsapp", phone)
        if not mapping:
            if not _try_auto_register(agent_slug, phone, sender_name):
                logger.debug(
                    "WhatsApp: ignoring unregistered phone %s (no open window)", phone,
                )
                return
            # Re-fetch the mapping after registration
            mapping = state.get_mapping_by_sender("whatsapp", phone)
            if not mapping:
                return

        target_slug = mapping["agent_slug"]
        response = service.process_message(target_slug, phone, sender_name, message)
        whatsapp_client.send_message(phone, response, session=session)
    except Exception:
        logger.exception("WhatsApp processing failed (phone=%s)", phone)
        try:
            whatsapp_client.send_message(
                phone, "I had trouble processing that. Please try again.",
                session=session,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Admin endpoints — JWT protected
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_whatsapp_status(user=Depends(get_current_user)):
    """Check if WhatsApp bridge is configured and healthy."""
    if not settings.whatsapp.is_configured:
        return {"configured": False, "status": "not_configured"}

    sessions = whatsapp_client.list_sessions()
    return {
        "configured": True,
        "bridge_url": settings.whatsapp.bridge_url,
        "sessions": sessions,
    }


@router.post("/session")
async def start_session(
    req: StartSessionRequest, user=Depends(get_current_user),
):
    """Start a WhatsApp session for an agent.

    Creates the Baileys session on the sidecar and opens a 10-minute
    registration window.
    """
    try:
        result = lifecycle.start_session(req.agent_slug)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/session/{agent_slug}")
async def stop_session(
    agent_slug: str, user=Depends(get_current_user),
):
    """Disconnect WhatsApp for an agent."""
    lifecycle.stop_session(agent_slug)
    return {"ok": True}


@router.get("/session/status/{agent_slug}")
async def get_session_status(
    agent_slug: str, user=Depends(get_current_user),
):
    """Get the WhatsApp session status for an agent."""
    return lifecycle.get_session_status(agent_slug)


@router.get("/session/qr/{agent_slug}")
async def get_session_qr(
    agent_slug: str, user=Depends(get_current_user),
):
    """Get the QR code PNG for an agent's WhatsApp session."""
    data = lifecycle.get_session_qr(agent_slug)
    if data is None:
        raise HTTPException(status_code=404, detail="QR not available")
    return Response(content=data, media_type="image/png")


@router.post("/session/reset-registration")
async def reset_registration(
    req: ResetRegistrationRequest, user=Depends(get_current_user),
):
    """Reset (re-open) the WhatsApp registration window for an agent."""
    try:
        window = lifecycle.reset_registration_window(req.agent_slug)
        return window
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/registration-window/{agent_slug}")
async def get_registration_window(
    agent_slug: str, user=Depends(get_current_user),
):
    """Get the WhatsApp registration window status for an agent."""
    window = state.get_registration_window(agent_slug)
    if not window:
        return {"open": False, "window": None}
    return {
        "open": state.is_registration_open(agent_slug),
        "window": window,
    }
