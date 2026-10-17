"""
Chatty — the computer card's actions (called from the authed integrations
router) and the per-agent policy every later PR re-checks.

Creds file `computer.json`: enabled, disabled_agents, idle_minutes, and — when
the Railway env vars aren't set — url + api_key (PR 8 writes those).
"""

import re

from fastapi import HTTPException

from core.config import settings
from integrations.registry import get_credentials, save_credentials

from .client import ComputerError, api_version_error, get_client

IDLE_MINUTES_DEFAULT = 30  # "Close when idle"; 0 is "Always on"
# The helper loop's model. An explicit constant: the mid-tier fallback is Sonnet 4.6, and a
# helper model needs an exact pricing.py entry or the budget can't be reserved from it.
DEFAULT_HELPER_MODEL = "claude-sonnet-5-5"
_PROVIDER_PREFIXES = (("claude-", "anthropic"), ("gpt-", "openai"), ("o1", "openai"), ("o3", "openai"),
                      ("o4", "openai"), ("gemini-", "google"))
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")  # the computer's own rule for agent slugs
DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})*$")  # hostname labels: no bare/leading/double dots, so "." or ".." can never walk the computer's path


def creds() -> dict:
    return get_credentials("computer")


def policy_error(agent_slug: str) -> str | None:
    """Why this agent may not use the computer right now, or None."""
    c = creds()
    if not (c.get("enabled") and settings.computer.is_configured):
        return "The computer is not set up or is turned off."
    if agent_slug in (c.get("disabled_agents") or []):
        return "The computer is turned off for this agent."
    return None


def set_disabled_agents(slugs: list[str]) -> dict:
    c = creds()
    c["disabled_agents"] = sorted(set(slugs))
    save_credentials("computer", c)
    return {"ok": True, "disabled_agents": c["disabled_agents"]}


def provider_for_model(model: str) -> str:
    """Which provider serves a model id ("" when unknown). Together ids carry an org prefix."""
    for prefix, provider in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return provider
    return "together" if "/" in model else ""


def helper_model() -> str:
    return creds().get("helper_model") or DEFAULT_HELPER_MODEL


def helper_model_error(model: str) -> str | None:
    """Why `model` can't run the helper loop, or None. The budget is priced from pricing.py, so
    the model needs an EXACT entry there (a dated snapshot of a priced model doesn't count)."""
    from core.providers.pricing import MODEL_PRICING
    if model not in MODEL_PRICING:
        return (f"The helper model '{model}' has no exact price in pricing.py, so its spend can't be "
                "budgeted. Pick a priced model on the Computer card.")
    if not provider_for_model(model):
        return f"Chatty can't tell which provider serves '{model}'."
    return None


def helper_models() -> list[dict]:
    """The models the card may offer: every exactly priced model with a known provider."""
    from core.providers.pricing import MODEL_PRICING
    return [{"model": m, "provider": provider_for_model(m), "input": p[0], "output": p[1]}
            for m, p in MODEL_PRICING.items() if provider_for_model(m)]


def set_helper_model(model: str) -> dict:
    err = helper_model_error(model)
    if err:
        raise HTTPException(status_code=400, detail=err)
    c = creds()
    c["helper_model"] = model
    save_credentials("computer", c)
    return {"ok": True, "helper_model": model}


def _check(pattern: re.Pattern, value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {what}")
    return value


def _http_error(e: ComputerError) -> HTTPException:
    # Never forward the computer's 401: the frontend treats any 401 as its own login expiring.
    return HTTPException(status_code=e.status if e.status in (404, 409) else 502, detail=e.detail)


async def _call(coro):
    try:
        return await coro
    except ComputerError as e:
        raise _http_error(e) from e


def _client():
    """get_client() for a card action: "not configured" becomes a readable 502, not a 500."""
    try:
        return get_client()
    except ComputerError as e:
        raise _http_error(e) from e


async def status() -> dict:
    from . import viewer
    c = creds()
    out = {
        "configured": settings.computer.is_configured,
        "enabled": bool(c.get("enabled")),
        "url": settings.computer.url,
        "idle_minutes": c.get("idle_minutes", IDLE_MINUTES_DEFAULT),
        "disabled_agents": c.get("disabled_agents", []),
        "online": False,
        "health": None,
        "error": None,
        "viewers": viewer.open_count(),
        "control": viewer.current_control(),
        "helper_model": helper_model(),
        "helper_models": helper_models(),
    }
    if out["configured"]:
        client = get_client()
        try:
            out["health"] = await client.health()
            out["online"] = True
            out["idle_minutes"] = out["health"].get("idle_minutes", out["idle_minutes"])  # the computer persists it
            out["error"] = api_version_error(out["health"])
        except ComputerError as e:
            out["error"] = e.detail
        finally:
            await client.aclose()
    return out


async def check_enable() -> None:
    """Enabling needs a reachable computer speaking our API major (400 otherwise)."""
    try:
        client = get_client()
    except ComputerError as e:
        raise HTTPException(status_code=400, detail=e.detail) from e
    try:
        health = await client.health()
    except ComputerError as e:
        raise HTTPException(status_code=400, detail=e.detail) from e
    finally:
        await client.aclose()
    err = api_version_error(health)
    if err:
        raise HTTPException(status_code=400, detail=err)


async def set_keep_running(always_on: bool) -> dict:
    idle = 0 if always_on else IDLE_MINUTES_DEFAULT
    client = _client()
    try:
        await _call(client.set_settings(idle))
    finally:
        await client.aclose()
    c = creds()
    c["idle_minutes"] = idle
    save_credentials("computer", c)
    return {"ok": True, "idle_minutes": idle}


async def list_sites(agent: str) -> dict:
    _check(SLUG_RE, agent, "agent slug")
    client = _client()
    try:
        return {"sites": await _call(client.list_sites(agent))}
    finally:
        await client.aclose()


async def clear_site(agent: str, domain: str) -> dict:
    _check(SLUG_RE, agent, "agent slug")
    _check(DOMAIN_RE, domain, "domain")
    client = _client()
    try:
        await _call(client.clear_site(agent, domain))
    finally:
        await client.aclose()
    return {"ok": True}


async def reset_browser(agent: str) -> dict:
    _check(SLUG_RE, agent, "agent slug")
    client = _client()
    try:
        await _call(client.reset_profile(agent))
    finally:
        await client.aclose()
    return {"ok": True}
