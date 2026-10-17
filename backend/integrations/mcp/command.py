"""Chatty — command MCP servers (`npx …`, `uvx …`) run on the computer, never here.

The computer's MCP bridge (computer/README.md) starts one `mcp-proxy` per server:
`PUT /mcp/servers/{name} {command, env}` starts or restarts it with the environment
kept in memory, `DELETE` stops it, and `ANY /mcp/{name}/…` proxies to it. To the MCP
client a command server is therefore one more streamable-HTTP URL,
`<computer origin>/mcp/<id>/mcp`, built here from the server id (validated against
the computer's own name rule) and the configured computer origin — the one SSRF
exemption, and only for that exact origin. Both calls carry the computer's bearer.

Processes vanish when the computer restarts; the proxy then answers 404. The server
is started again, and the request retried only when it was not the tool call itself.
"""

import logging
import re

import httpx

from core.config import settings
from integrations.computer.client import ComputerClient, ComputerError

from . import store
from .client import McpClient, McpError

logger = logging.getLogger(__name__)
NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")  # the computer's rule; store.slug() always satisfies it
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_ENV = 20
START_TIMEOUT = 45.0  # the computer waits up to 20 s for mcp-proxy, after npx/uvx may fetch the package
MAX_ERROR = 600
_transport: httpx.AsyncBaseTransport | None = None  # tests only: the fake computer


def _check_name(server_id: str) -> str:
    if not NAME_RE.fullmatch(server_id):
        raise McpError(f"Invalid server id {server_id!r}")
    return server_id


def url(server_id: str) -> str:
    """The server's endpoint behind the computer's bridge. Built, never accepted from a user."""
    return f"{settings.computer.url}/mcp/{_check_name(server_id)}/mcp"


def client(server_id: str) -> McpClient:
    origin = settings.computer.url
    return McpClient(url(server_id), f"Bearer {settings.computer.secret}", allow_origins=(origin,),
                     transport=_transport)


def _computer(timeout: float) -> ComputerClient:
    return ComputerClient(settings.computer.url, settings.computer.secret, transport=_transport, timeout=timeout)


def redact(text: str, values) -> str:
    """`text` with every env value replaced: a server that prints its environment must not leak it into
    an error on the card or in mcp.json."""
    for v in values:
        if v:
            text = text.replace(v, "[redacted]")
    return text[:MAX_ERROR]


def validate_env(env) -> dict[str, str]:
    """Checked here, not by the request model: a pydantic 422 echoes the input, values included."""
    out = {}
    env = env or {}
    if not isinstance(env, dict):
        raise ValueError("env must be an object of NAME: value")
    if len(env) > MAX_ENV:
        raise ValueError(f"At most {MAX_ENV} environment variables")
    for k, v in env.items():
        if not isinstance(k, str) or not ENV_NAME_RE.fullmatch(k):
            raise ValueError(f"Invalid environment variable name {k!r}")
        if not isinstance(v, str) or not v.isprintable():
            raise ValueError(f"The value of {k} contains control characters")
        out[k] = v
    return out


async def put(server_id: str, cmd: str, env: dict[str, str]) -> None:
    """Start (or restart) the process on the computer. The env travels only here, and never appears
    in a log or an error."""
    _check_name(server_id)
    c = _computer(START_TIMEOUT)
    try:
        await c.request("PUT", f"/mcp/servers/{server_id}", json={"command": cmd, "env": env})
    except ComputerError as e:
        # The untruncated body: ComputerError.detail is cut at 500 chars, which could split a value so
        # that redact() no longer matches it. redact() truncates after replacing.
        detail = f"Start failed on the computer: {e.body.get('detail') or e.detail}"
        if log := e.body.get("log"):
            detail += f"\n{str(log).strip()}"
        raise McpError(redact(detail, env.values())) from e
    finally:
        await c.aclose()


async def start(server_id: str) -> None:
    s = store.servers().get(server_id)
    if not s or not store.is_command(s):
        raise KeyError(server_id)
    await put(server_id, s["command"], store.env_values(s))


async def delete(server_id: str) -> None:
    """DELETE the process by name. Best effort: with the computer off or unreachable there is nothing to stop."""
    if not NAME_RE.fullmatch(server_id) or store.computer_error():
        return
    c = _computer(10.0)
    try:
        await c.request("DELETE", f"/mcp/servers/{server_id}")
    except ComputerError as e:
        logger.info("Could not stop MCP server %s on the computer: %s", server_id, e.detail)
    finally:
        await c.aclose()


async def stop(server_id: str) -> None:
    """Stop a command server's process; a no-op for a remote or unknown server."""
    s = store.servers().get(server_id)
    if s and store.is_command(s):
        await delete(server_id)


async def stop_all() -> None:
    """Disabling the MCP integration or the computer stops every command server."""
    for sid, s in store.servers().items():
        if store.is_command(s):
            await stop(sid)


async def run(server_id: str, op):
    """await op(client) through the computer's bridge. A 404 from the proxy means the process is gone
    (the computer restarted): start it again, then retry only a request that was not the tool call —
    a tool call's outcome is reported as unknown, never replayed. Every error is redacted: a server
    that echoes its environment must not put a value in last_error, on the card or in a tool result."""
    if err := store.computer_error():
        raise McpError(err)
    values = store.env_values(store.servers()[server_id]).values()
    try:
        return await _run(server_id, op)
    except McpError as e:
        raise McpError(redact(str(e), values), status=e.status, retry_safe=e.retry_safe) from e


async def _run(server_id: str, op):
    try:
        return await op(client(server_id))
    except McpError as e:
        if isinstance(e.__cause__, httpx.TransportError):
            raise McpError(f"Can't reach the computer at {settings.computer.url} ({type(e.__cause__).__name__}). "
                           "Is it running?") from e
        if e.status != 404:
            raise
        await start(server_id)
        if not e.retry_safe:
            raise McpError("The server was not running on the computer when the call arrived (did the computer "
                           "restart?). It has been started again; the call was not replayed, so treat its outcome "
                           "as unknown and ask again.") from e
        return await op(client(server_id))


async def overview() -> dict:
    """For the card: why command servers can't run right now, and which are running on the computer."""
    out = {"error": store.computer_error(), "running": []}
    if out["error"] or not any(store.is_command(s) for s in store.servers().values()):
        return out
    c = _computer(10.0)
    try:
        data = await c.request("GET", "/mcp/servers")
        out["running"] = [x["name"] for x in (data.get("servers") or []) if isinstance(x, dict) and x.get("running")]
    except ComputerError as e:
        out["error"] = e.detail
    finally:
        await c.aclose()
    return out
