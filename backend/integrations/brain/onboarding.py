"""Chatty — second-brain integration onboarding (validate the server, save credentials)."""

import httpx

from integrations.registry import save_credentials


def setup(base_url: str, api_key: str = "") -> dict:
    """GET /health on the brain server, then store the URL + key encrypted."""
    base_url = base_url.strip().rstrip("/")
    headers = {"X-Api-Key": api_key} if api_key else {}
    try:
        resp = httpx.get(f"{base_url}/health", headers=headers, timeout=10)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Connection failed — {e}"}
    if resp.status_code in (401, 403):
        return {"ok": False, "error": "Connection failed — check the API key"}
    if resp.status_code != 200 or not resp.json().get("ok"):
        return {"ok": False, "error": f"Connection failed — /health returned {resp.status_code}"}
    save_credentials("brain", {"base_url": base_url, "api_key": api_key, "enabled": True})
    return {"ok": True, "home": resp.json().get("home", "")}
