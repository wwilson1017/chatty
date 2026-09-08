"""
Chatty — Hermes API-server client.

Talks to a Hermes gateway's `api_server` platform (aiohttp, bearer auth) as an
external UI:

  GET  /v1/capabilities            feature flags — the compatibility gate
  GET  /v1/toolsets                which toolsets the api_server agent has
  GET  /health                     liveness
  GET  /api/model/options          model label for the header line
  GET  /v1/skills                  read-only skills list
  POST /api/sessions               create the Hermes session a conversation maps to
  GET  /api/sessions/{id}/messages
  POST /v1/runs                    submit one turn (202 → run_id)
  GET  /v1/runs/{id}               pollable status (+ output when completed)
  GET  /v1/runs/{id}/events        SSE: message.delta / tool.* / approval.* / run.*
  POST /v1/runs/{id}/approval      answer an approval request
  POST /v1/runs/{id}/stop          request interruption (returns "stopping")

Hermes runs do NOT hydrate history from `session_id`; the caller supplies
`conversation_history` on every run. `instructions` is an additive, ephemeral
system prompt for that run only.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Feature flags Chatty depends on (all advertised by /v1/capabilities).
REQUIRED_FEATURES = (
    "run_submission",
    "run_events_sse",
    "run_status",
    "run_approval_response",
    "approval_events",
    "run_stop",
    "session_resources",
)

# Finite read timeout for every request except the events stream, which is
# silent for up to 30 s between Hermes keepalives and unbounded while an
# approval waits on a human.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)


class HermesConnectionError(Exception):
    """Connection never established (nothing reached Hermes)."""


class HermesRequestError(Exception):
    """Hermes answered, or the request failed after it was sent."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _is_private_host(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def validate_base_url(url: str, allow_insecure: bool = False) -> str:
    """Return a normalised base URL or raise ValueError.

    http/https only, no userinfo, no query/fragment, no path traversal; https
    required unless the host is loopback/private (or the operator opted in).
    """
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Hermes URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("Hermes URL has no host")
    if parsed.username or parsed.password:
        raise ValueError("Hermes URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Hermes URL must not contain a query string or fragment")
    if ".." in parsed.path.split("/"):
        raise ValueError("Hermes URL path is invalid")
    if parsed.scheme == "http" and not allow_insecure and not _is_private_host(parsed.hostname):
        raise ValueError("Hermes URL must use https unless it is a local/private address")
    return raw.rstrip("/")


def _parse_sse_lines(lines: AsyncIterator[str]):
    """Turn an SSE line stream into dicts; comment lines (keepalives) yield None."""
    async def gen():
        event_name: str | None = None
        data_parts: list[str] = []
        async for line in lines:
            line = line.rstrip("\r")
            if line == "":
                if data_parts:
                    raw = "\n".join(data_parts)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"event": event_name or "unknown", "raw": raw}
                    if isinstance(payload, dict) and event_name and "event" not in payload:
                        payload["event"] = event_name
                    yield payload
                event_name, data_parts = None, []
                continue
            if line.startswith(":"):
                yield None  # keepalive / comment
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].lstrip())
        if data_parts:  # unterminated final frame
            try:
                yield json.loads("\n".join(data_parts))
            except json.JSONDecodeError:
                pass
    return gen()


class HermesClient:
    def __init__(self, base_url: str, api_key: str, *, allow_insecure: bool = False,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = validate_base_url(base_url, allow_insecure)
        self._api_key = api_key or ""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── plumbing ──────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, *, json_body: dict | None = None,
                       headers: dict | None = None) -> Any:
        try:
            resp = await self._client.request(method, path, json=json_body, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise HermesConnectionError(str(e)) from e
        except httpx.HTTPError as e:
            raise HermesRequestError(f"{method} {path}: {e}") from e
        if resp.status_code >= 400:
            code = None
            try:
                err = resp.json().get("error") or {}
                code = err.get("code")
                msg = err.get("message") or resp.text[:200]
            except Exception:
                msg = resp.text[:200]
            raise HermesRequestError(f"{method} {path} → {resp.status_code}: {msg}",
                                     status=resp.status_code, code=code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as e:
            raise HermesRequestError(f"{method} {path}: unparseable body") from e

    # ── discovery ─────────────────────────────────────────────────────────

    async def capabilities(self) -> dict:
        return await self._request("GET", "/v1/capabilities")

    async def toolsets(self) -> dict:
        return await self._request("GET", "/v1/toolsets")

    async def health(self) -> dict:
        return await self._request("GET", "/health")

    async def model_options(self) -> dict:
        return await self._request("GET", "/api/model/options")

    async def list_skills(self) -> list[dict]:
        data = await self._request("GET", "/v1/skills")
        return data.get("data") or []

    # ── sessions ──────────────────────────────────────────────────────────

    async def create_session(self, title: str | None = None,
                             system_prompt: str | None = None) -> dict:
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        if system_prompt:
            body["system_prompt"] = system_prompt
        data = await self._request("POST", "/api/sessions", json_body=body)
        return data.get("session") or data

    async def session_messages(self, session_id: str) -> list[dict]:
        data = await self._request("GET", f"/api/sessions/{session_id}/messages")
        return data.get("messages") or data.get("data") or []

    # ── runs ──────────────────────────────────────────────────────────────

    async def create_run(self, *, input: str, session_id: str | None,
                         instructions: str | None,
                         conversation_history: list[dict],
                         session_key: str | None = None) -> str:
        body: dict[str, Any] = {"input": input, "conversation_history": conversation_history}
        if session_id:
            body["session_id"] = session_id
        if instructions:
            body["instructions"] = instructions
        headers = {"X-Hermes-Session-Key": session_key} if session_key else None
        data = await self._request("POST", "/v1/runs", json_body=body, headers=headers)
        run_id = data.get("run_id")
        if not run_id:
            raise HermesRequestError("POST /v1/runs: no run_id in response")
        return run_id

    async def get_run(self, run_id: str) -> dict | None:
        """Run status, or None when Hermes no longer knows the run (404)."""
        try:
            return await self._request("GET", f"/v1/runs/{run_id}")
        except HermesRequestError as e:
            if e.status == 404:
                return None
            raise

    async def respond_approval(self, run_id: str, choice: str,
                               request_id: str | None = None) -> dict:
        body: dict[str, Any] = {"choice": choice}
        if request_id:
            body["request_id"] = request_id
        return await self._request("POST", f"/v1/runs/{run_id}/approval", json_body=body)

    async def stop_run(self, run_id: str) -> dict:
        return await self._request("POST", f"/v1/runs/{run_id}/stop")

    async def iter_run_events(self, run_id: str):
        """Yield event dicts from the run's SSE stream; None for keepalives.

        Single-consumer on the Hermes side: a dropped stream cannot be resumed,
        the caller must fall back to polling get_run().
        """
        try:
            async with self._client.stream(
                "GET", f"/v1/runs/{run_id}/events", timeout=_STREAM_TIMEOUT,
            ) as resp:
                if resp.status_code >= 400:
                    raise HermesRequestError(
                        f"GET /v1/runs/{run_id}/events → {resp.status_code}",
                        status=resp.status_code)
                async for item in _parse_sse_lines(resp.aiter_lines()):
                    yield item
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise HermesConnectionError(str(e)) from e
        except httpx.HTTPError as e:
            raise HermesRequestError(f"events stream: {e}") from e
