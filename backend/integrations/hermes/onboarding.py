"""
Chatty — Hermes connection setup.

One connection per install (default Hermes profile). Credentials live in
data/integrations/hermes.json via the integration registry (encrypted at rest):

  {base_url, api_key, allow_insecure, connection_id, capabilities, toolsets, enabled}

`connection_id` is kept when base_url + api_key are unchanged so existing
conversations keep their Hermes sessions; it changes when the connection
points at a different server, which orphans those sessions on purpose.
"""

from __future__ import annotations

import logging
import uuid

from integrations.registry import get_credentials, save_credentials, enable

from .client import HermesClient, HermesConnectionError, HermesRequestError, REQUIRED_FEATURES

logger = logging.getLogger(__name__)

NAME = "hermes"


def get_connection() -> dict:
    return get_credentials(NAME)


def connection_enabled() -> bool:
    creds = get_connection()
    return bool(creds.get("enabled") and creds.get("base_url"))


def make_client(creds: dict | None = None) -> HermesClient:
    creds = creds or get_connection()
    if not creds.get("base_url"):
        raise HermesConnectionError("Hermes is not connected")
    return HermesClient(creds["base_url"], creds.get("api_key", ""),
                        allow_insecure=bool(creds.get("allow_insecure")))


def supports(feature: str, creds: dict | None = None) -> bool:
    creds = creds or get_connection()
    return bool(((creds.get("capabilities") or {}).get("features") or {}).get(feature))


def toolset_enabled(name: str, creds: dict | None = None) -> bool | None:
    """True/False from the cached /v1/toolsets payload, None when unknown."""
    creds = creds or get_connection()
    data = creds.get("toolsets") or {}
    entries = data.get("data") if isinstance(data, dict) else data
    if isinstance(entries, dict):
        entry = entries.get(name)
    elif isinstance(entries, list):
        entry = next((t for t in entries if isinstance(t, dict) and t.get("name") == name), None)
    else:
        entry = None
    if not isinstance(entry, dict):
        return None
    return bool(entry.get("enabled", True))


async def setup(base_url: str, api_key: str, allow_insecure: bool = False) -> dict:
    """Verify the capability gate, cache discovery payloads, persist + enable."""
    existing = get_connection()
    try:
        client = make_client({"base_url": base_url, "api_key": api_key,
                              "allow_insecure": allow_insecure})
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        caps = await client.capabilities()
        features = caps.get("features") or {}
        missing = [f for f in REQUIRED_FEATURES if not features.get(f)]
        if missing:
            return {"ok": False, "error": f"This Hermes lacks required API features: {', '.join(missing)}"}
        try:
            toolsets = await client.toolsets()
        except HermesRequestError:
            toolsets = {}
    except HermesConnectionError as e:
        return {"ok": False, "error": f"Could not reach Hermes: {e}"}
    except HermesRequestError as e:
        if e.status in (401, 403):
            return {"ok": False, "error": "Hermes rejected the API key"}
        return {"ok": False, "error": f"Hermes error: {e}"}
    finally:
        await client.aclose()

    same = (existing.get("base_url") == client.base_url and existing.get("api_key") == api_key)
    connection_id = existing.get("connection_id") if same and existing.get("connection_id") else uuid.uuid4().hex
    save_credentials(NAME, {
        **existing,
        "base_url": client.base_url,
        "api_key": api_key,
        "allow_insecure": bool(allow_insecure),
        "connection_id": connection_id,
        "capabilities": caps,
        "toolsets": toolsets,
    })
    enable(NAME)
    return {"ok": True, "connection_id": connection_id,
            "model": caps.get("model"), "features": features}


async def status() -> dict:
    """Health + model + skills + toolset flags for the UI. Never raises."""
    creds = get_connection()
    if not creds.get("base_url"):
        return {"connected": False}
    out = {
        "connected": bool(creds.get("enabled")),
        "base_url": creds["base_url"],
        "connection_id": creds.get("connection_id"),
        "healthy": False,
        "model": (creds.get("capabilities") or {}).get("model"),
        "approval_request_id": supports("approval_request_id", creds),
        "memory_toolset": toolset_enabled("memory", creds),
        "skills_toolset": toolset_enabled("skills", creds),
        "skills_count": None,
        "error": None,
    }
    try:
        client = make_client(creds)
    except (ValueError, HermesConnectionError) as e:
        out["error"] = str(e)
        return out
    try:
        await client.health()
        out["healthy"] = True
        try:
            opts = await client.model_options()
            model = opts.get("current") or opts.get("model")
            if isinstance(model, dict):
                model = model.get("model") or model.get("id")
            if model:
                out["model"] = model
        except HermesRequestError:
            pass
        try:
            out["skills_count"] = len(await client.list_skills())
        except HermesRequestError:
            pass
    except (HermesConnectionError, HermesRequestError) as e:
        out["error"] = str(e)
    finally:
        await client.aclose()
    return out
