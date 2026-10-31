"""Chatty — second-brain integration onboarding (check the Common Brain key, save credentials)."""

import httpx

from integrations.registry import get_credentials, save_credentials


def setup(base_url: str, api_key: str = "") -> dict:
    """GET /api/v1 on Common Brain with the program key, then store the URL + key encrypted.

    A blank key on reconfigure keeps the stored one (the UI never sees it).
    """
    base_url = base_url.strip().rstrip("/").removesuffix("/api/v1")
    api_key = api_key.strip() or get_credentials("brain").get("api_key", "")
    if not api_key:
        return {"ok": False, "error": "Paste a Common Brain program key (cb_…, from Connect → For programs)"}
    try:
        resp = httpx.get(f"{base_url}/api/v1", headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Connection failed — {e}"}
    if resp.status_code == 403:
        return {"ok": False, "error": "Connection failed — check the program key"}
    try:
        about = resp.json()
    except ValueError:
        return {"ok": False, "error": f"Connection failed — /api/v1 returned non-JSON ({resp.status_code})"}
    if resp.status_code != 200 or not isinstance(about, dict):
        return {"ok": False, "error": f"Connection failed — /api/v1 returned {resp.status_code}"}
    if not any(t.get("name") == "brain_start" for t in about.get("tools") or []):
        return {"ok": False, "error": "This key reaches no Common Brain — turn Brain on for the account "
                                      "and make the key for Common Brain"}
    save_credentials("brain", {"base_url": base_url, "api_key": api_key, "enabled": True})
    key = about.get("key") or {}
    return {"ok": True, "account_no": about.get("account_no"), "key": key.get("name"), "access": key.get("access")}
