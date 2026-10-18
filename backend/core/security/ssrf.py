"""Chatty — outbound-request guard against SSRF.

validate_host() is the check Odoo discovery used to carry, widened so every address a
name resolves to must be public: ipaddress.is_global rejects private, loopback,
link-local, CGNAT (100.64/10), reserved and unspecified ranges; IPv4-mapped IPv6
addresses are unwrapped first and multicast is refused too. validate_url() adds the
https requirement.

Checking before a request still leaves a DNS-rebinding window (the name resolves to a
public address for the check and a private one for the connect), so pinned_client()
returns an httpx client whose httpcore network backend resolves and validates on every
connect and opens the socket to the address that passed. TLS SNI, certificate checks
and the Host header keep the original hostname; redirects are off.

allow_origins: "scheme://host[:port]" origins exempt from both checks (matched on host and
port), for a service on a private network the operator configured themselves (the
computer, PR 11).
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpcore
import httpx

INTERNAL_ADDRESS = "Requests to internal addresses are not allowed"


def resolve(host: str) -> list[str]:
    """Addresses `host` resolves to right now, in resolver order. Tests stub this."""
    return list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, None)))


# IPv6 forms that carry an IPv4 address in their low 32 bits: mapped (::ffff:a.b.c.d),
# NAT64 (64:ff9b::/96) and IPv4-compatible (::a.b.c.d). Judge the embedded address.
_V4_IN_V6 = (ipaddress.ip_network("::ffff:0:0/96"), ipaddress.ip_network("64:ff9b::/96"),
             ipaddress.ip_network("::/96"))


def _public(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if ip.version == 6 and any(ip in n for n in _V4_IN_V6):
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def resolve_public(host: str) -> tuple[list[str], str | None]:
    """(addresses, None) when every address `host` resolves to is public, else ([], why)."""
    try:
        addrs = resolve(host)
    except socket.gaierror:
        return [], f"Cannot resolve host: {host}"
    if not addrs or not all(_public(a) for a in addrs):
        return [], INTERNAL_ADDRESS
    return addrs, None


def validate_host(host: str) -> str | None:
    """Resolve host and reject private/internal IPs. Returns error or None."""
    return resolve_public(host)[1]


def _origin(url: str) -> tuple[str, str, int] | None:
    p = urlsplit(url)
    if not p.scheme or not p.hostname:
        return None
    try:
        port = p.port
    except ValueError:
        return None
    return p.scheme, p.hostname, port or (443 if p.scheme == "https" else 80)


def _allowed(allow_origins) -> set[tuple[str, int]]:
    return {(o[1], o[2]) for o in map(_origin, allow_origins) if o}


def validate_url(url: str, *, allow_origins=()) -> str | None:
    """Why `url` may not be requested (not https, or not a public host), or None."""
    origin = _origin(url)
    if not origin:
        return "Invalid URL"
    scheme, host, port = origin
    if (host, port) in _allowed(allow_origins):
        return None
    if scheme != "https":
        return "URL must use https"
    return validate_host(host)


class PinnedBackend(httpcore.AsyncNetworkBackend):
    """Resolves and validates on every connect, then connects to the validated address."""

    def __init__(self, allow: set[tuple[str, int]] = frozenset()):
        self._inner = httpcore.AnyIOBackend()
        self._allow = allow

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host, port) not in self._allow:
            addrs, err = await asyncio.to_thread(resolve_public, host)
            if err:
                raise httpcore.ConnectError(err)
            host = addrs[0]
        return await self._inner.connect_tcp(host, port, timeout, local_address, socket_options)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are not allowed")

    async def sleep(self, seconds):
        await self._inner.sleep(seconds)


def pinned_client(*, allow_origins=(), timeout: float = 30.0) -> httpx.AsyncClient:
    """An httpx client that only connects to validated public addresses and never follows redirects."""
    transport = httpx.AsyncHTTPTransport()
    # httpx exposes no hook for the network backend, so replace the pool it just built.
    # simplification: private attribute; upgrade: a full AsyncBaseTransport if httpx renames _pool.
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(),
        network_backend=PinnedBackend(_allowed(allow_origins)),
    )
    return httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=timeout)
