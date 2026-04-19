"""Telegram Bot API client.

Handles outbound messages and webhook registration.  Every function requires
an explicit ``bot_token`` — there is no global fallback.  Telegram's Bot API
is HTTP/webhook-based so no persistent connections are needed.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

MAX_CHUNK_LENGTH = 4096  # Telegram's message limit


def _base_url(bot_token: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}"


def send_message(chat_id: int | str, text: str, bot_token: str) -> list[dict]:
    """Send a text message to a Telegram chat.

    Long messages are chunked.  Returns a list of Telegram response dicts.
    """
    if not bot_token:
        logger.warning("No Telegram bot token — cannot send message")
        return []

    chunks = _chunk_text(text, MAX_CHUNK_LENGTH)
    results = []
    for chunk in chunks:
        try:
            resp = httpx.post(
                f"{_base_url(bot_token)}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "Markdown",
                },
                timeout=30,
            )
            # If Markdown parse fails, retry without parse_mode
            if resp.status_code == 400 and "parse" in resp.text.lower():
                resp = httpx.post(
                    f"{_base_url(bot_token)}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                    timeout=30,
                )
            resp.raise_for_status()
            results.append(resp.json())
        except httpx.HTTPError as e:
            logger.error("Telegram send failed: %s", e)
            results.append({"error": str(e)})

    return results


def set_webhook(url: str, bot_token: str, secret_token: str | None = None) -> dict:
    """Register a webhook URL with Telegram.

    Telegram will POST updates to this URL.  The optional ``secret_token``
    is sent in the ``X-Telegram-Bot-Api-Secret-Token`` header on every
    webhook delivery so we can verify authenticity.
    """
    if not bot_token:
        return {"ok": False, "error": "No bot token provided"}

    payload: dict = {"url": url}
    if secret_token:
        payload["secret_token"] = secret_token

    try:
        resp = httpx.post(
            f"{_base_url(bot_token)}/setWebhook",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Telegram setWebhook failed: %s", e)
        return {"ok": False, "error": str(e)}


def delete_webhook(bot_token: str) -> dict:
    """Remove the webhook for this bot token."""
    if not bot_token:
        return {"ok": False, "error": "No bot token provided"}

    try:
        resp = httpx.post(
            f"{_base_url(bot_token)}/deleteWebhook",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Telegram deleteWebhook failed: %s", e)
        return {"ok": False, "error": str(e)}


def get_me(bot_token: str) -> dict:
    """Get bot info (username, name) for status display."""
    if not bot_token:
        return {"ok": False, "error": "No bot token provided"}

    try:
        resp = httpx.get(f"{_base_url(bot_token)}/getMe", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning("Telegram getMe failed: %s", e)
        return {"ok": False, "error": str(e)}


def validate_token(bot_token: str) -> dict | None:
    """Validate a bot token by calling getMe.

    Returns the ``result`` dict (with ``id``, ``username``, ``first_name``, etc.)
    on success, or ``None`` if the token is invalid or the call fails.
    """
    if not bot_token:
        return None

    result = get_me(bot_token)
    if result.get("ok") and "result" in result:
        return result["result"]
    return None


def get_updates(bot_token: str, offset: int | None = None, timeout: int = 30) -> list[dict]:
    """Long-poll for new updates from Telegram (alternative to webhooks)."""
    if not bot_token:
        return []

    params: dict = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset

    try:
        resp = httpx.get(
            f"{_base_url(bot_token)}/getUpdates",
            params=params,
            timeout=timeout + 10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])
    except httpx.HTTPError as e:
        logger.warning("Telegram getUpdates failed: %s", e)
        return []


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

        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1:
            split_at = max_length

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks
