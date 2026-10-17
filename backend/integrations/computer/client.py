"""
Chatty — async httpx client for the computer's control API (see computer/ in
the repo root for the server). Every call carries `Authorization: Bearer
<COMPUTER_SECRET>`; failures surface as ComputerError(status, detail), status 0
when the computer can't be reached at all.
"""

import httpx

from core.config import settings

API_MAJOR = "1"  # the control-API major this client speaks; another major is refused
DEFAULT_TIMEOUT = 10.0


class ComputerError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def api_version_error(health: dict) -> str | None:
    """Why this computer can't be used, or None. The major is compared; "1", "1.0" and "1.2.3" all match."""
    major = str(health.get("api_version", "")).split(".")[0]
    if major != API_MAJOR:
        return (f"The computer speaks control API v{health.get('api_version') or '?'}; this Chatty needs "
                f"v{API_MAJOR}.x. Update whichever is older.")
    return None


class ComputerClient:
    def __init__(self, base_url: str, secret: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport,
                                       headers={"Authorization": f"Bearer {secret}"})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, **kw) -> dict | list:
        """One control-API call; JSON body or {} back. Later PRs add their own wrappers on top of this."""
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ComputerError(0, f"Can't reach the computer at {self.base_url}: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = None
            detail = (body.get("detail") if isinstance(body, dict) else None) or r.text or f"HTTP {r.status_code}"
            raise ComputerError(r.status_code, str(detail)[:500])
        if not r.content:
            return {}
        return r.json()

    # ── PR 2 surface ─────────────────────────────────────────────────────────

    async def health(self) -> dict:
        return await self.request("GET", "/health")

    async def set_settings(self, idle_minutes: int) -> dict:
        return await self.request("PUT", "/settings", json={"idle_minutes": idle_minutes})

    async def control_start(self, agent: str, task_id: str | None = None) -> dict:
        return await self.request("POST", "/control/start", json={"agent": agent, "task_id": task_id})

    async def control_end(self, control_session_id: str) -> dict:
        return await self.request("POST", "/control/end", json={"control_session_id": control_session_id})

    async def control_status(self) -> dict:
        return await self.request("GET", "/control/status")

    async def list_sites(self, agent: str) -> list[dict]:
        data = await self.request("GET", f"/profiles/{agent}/sites")
        return data.get("sites", []) if isinstance(data, dict) else data

    async def clear_site(self, agent: str, domain: str) -> dict:
        return await self.request("DELETE", f"/profiles/{agent}/sites/{domain}")

    async def reset_profile(self, agent: str) -> dict:
        return await self.request("DELETE", f"/profiles/{agent}")

    def vnc_url(self, mode: str, control_session_id: str | None = None) -> str:
        """ws(s) URL of the computer's viewer stream; the relay adds the bearer header itself."""
        url = "ws" + self.base_url[4:] if self.base_url.startswith("http") else self.base_url
        url += f"/vnc?mode={mode}"
        if control_session_id:
            url += f"&control_session_id={control_session_id}"
        return url


def get_client() -> ComputerClient:
    """Client for the configured computer, or ComputerError(0) when nothing is configured.
    Callers own the client: `async with closing(...)` isn't needed for one-shot card calls,
    but long-lived holders (PR 3's runner) should aclose()."""
    if not settings.computer.is_configured:
        raise ComputerError(0, "No computer is configured. Set COMPUTER_URL and COMPUTER_SECRET.")
    return ComputerClient(settings.computer.url, settings.computer.secret)
