"""Chatty — WhatsApp connector availability check."""

from core.config import settings


def is_available() -> bool:
    """Check if the WhatsApp bridge sidecar is configured."""
    return settings.whatsapp.is_configured
