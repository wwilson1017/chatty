"""
Chatty — ChatGPT OAuth token refresh.

Refreshes expired ChatGPT OAuth tokens using the Codex CLI's registered
client ID at auth.openai.com/oauth/token.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# Codex CLI's registered OAuth client ID (public, embedded in the CLI)
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"


async def refresh_chatgpt_token(refresh_token: str) -> dict:
    """
    Exchange a ChatGPT refresh token for a new access token.

    Returns:
        {"access_token": str, "refresh_token": str, "expires_in": int}

    Raises:
        ValueError on failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_CLIENT_ID,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            logger.error("ChatGPT token refresh failed: %s %s", resp.status_code, resp.text[:200])
            raise ValueError(f"Token refresh failed (HTTP {resp.status_code})")

        data = resp.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", refresh_token),
            "expires_in": data.get("expires_in", 864000),
        }
