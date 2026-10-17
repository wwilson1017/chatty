"""
Chatty — async httpx client for the computer's control API (see computer/ in
the repo root for the server). Every call carries `Authorization: Bearer
<COMPUTER_SECRET>`; failures surface as ComputerError(status, detail), status 0
when the computer can't be reached at all.
"""

from urllib.parse import quote

import httpx

from core.config import settings

API_MAJOR = "1"  # the control-API major this client speaks; another major is refused
DEFAULT_TIMEOUT = 10.0


class ComputerError(Exception):
    """A control-API call failed. `status` is the HTTP status (0: unreachable), `detail` the
    computer's sentence, `code` its machine-readable error (`busy`, `human_in_control`, …) if any."""

    def __init__(self, status: int, detail: str, code: str = "", body: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code
        self.body = body or {}  # the computer's extra fields (`holder`, `epoch`, `mismatches`, …)


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

    async def raw(self, method: str, path: str, **kw) -> httpx.Response:
        """One control-API call, errors raised, response returned (for non-JSON bodies)."""
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ComputerError(0, f"Can't reach the computer at {self.base_url}: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = None
            # The computer answers {"error": "<code>", "detail": "<sentence>"}; FastAPI's own 422 has only `detail`.
            code = str(body.get("error") or "") if isinstance(body, dict) else ""
            detail = (body.get("detail") if isinstance(body, dict) else None) or code or r.text or f"HTTP {r.status_code}"
            raise ComputerError(r.status_code, str(detail)[:500], code, body if isinstance(body, dict) else None)
        return r

    async def request(self, method: str, path: str, **kw) -> dict | list:
        """One control-API call; JSON body or {} back. Later PRs add their own wrappers on top of this."""
        r = await self.raw(method, path, **kw)
        if not r.content:
            return {}
        return r.json()

    # ── files (no lease needed) ──────────────────────────────────────────────

    async def get_file(self, agent: str, path: str) -> tuple[bytes, str]:
        """(bytes, file name) of a file under /workspace/<agent> or /workspace/shared."""
        r = await self.raw("GET", "/files/content", params={"agent": agent, "path": path}, timeout=60.0)
        return r.content, r.headers.get("X-File-Name") or path.rsplit("/", 1)[-1]

    async def put_file(self, agent: str, path: str, data: bytes) -> dict:
        return await self.request("PUT", "/files/content", params={"agent": agent, "path": path}, content=data,
                                  timeout=60.0)

    # ── PR 2 surface ─────────────────────────────────────────────────────────

    async def health(self) -> dict:
        return await self.request("GET", "/health")

    async def set_settings(self, idle_minutes: int) -> dict:
        return await self.request("PUT", "/settings", json={"idle_minutes": idle_minutes})

    async def control_start(self, agent: str, task_id: str | None = None) -> dict:
        return await self.request("POST", "/control/start", json={"agent": agent, "task_id": task_id})

    async def control_end(self, control_session_id: str) -> dict:
        return await self.request("POST", "/control/end", json={"control_session_id": control_session_id})

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
            url += f"&control_session_id={quote(control_session_id, safe='')}"
        return url


def get_client() -> ComputerClient:
    """Client for the configured computer, or ComputerError(0) when nothing is configured.
    Callers own the client: `async with closing(...)` isn't needed for one-shot card calls,
    but long-lived holders (PR 3's runner) should aclose()."""
    if not settings.computer.is_configured:
        raise ComputerError(0, "No computer is configured. Set COMPUTER_URL and COMPUTER_SECRET.")
    return ComputerClient(settings.computer.url, settings.computer.secret)
