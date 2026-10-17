"""core.security.ssrf — public hosts only, https, and connections pinned to the validated address."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from core.security import ssrf

PUBLIC = "93.184.216.34"


def _stub_resolver(monkeypatch, answers: dict[str, list]):
    """answers: host -> addresses, or host -> [addresses per call, ...] (last answer repeats)."""
    calls: dict[str, int] = {}

    def resolve(host):
        a = answers[host]
        if a and isinstance(a[0], list):
            i = calls.get(host, 0)
            calls[host] = i + 1
            return a[min(i, len(a) - 1)]
        return a
    monkeypatch.setattr(ssrf, "resolve", resolve)
    return calls


class TestValidateUrl:
    @pytest.mark.parametrize("ip", [
        "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1",
        "0.0.0.0", "240.0.0.1", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
        "64:ff9b::7f00:1", "64:ff9b::a00:1", "::127.0.0.1", "2002:7f00:1::1",
    ])
    def test_internal_addresses_refused(self, monkeypatch, ip):
        _stub_resolver(monkeypatch, {"h.test": [ip]})
        assert ssrf.validate_url("https://h.test/mcp") == ssrf.INTERNAL_ADDRESS

    @pytest.mark.parametrize("ip", [PUBLIC, "2606:2800:220:1:248:1893:25c8:1946", "::ffff:8.8.8.8", "64:ff9b::808:808"])
    def test_public_forms_pass(self, monkeypatch, ip):
        _stub_resolver(monkeypatch, {"h.test": [ip]})
        assert ssrf.validate_url("https://h.test/mcp") is None

    def test_one_private_answer_among_public_refused(self, monkeypatch):
        _stub_resolver(monkeypatch, {"h.test": [PUBLIC, "10.0.0.1"]})
        assert ssrf.validate_url("https://h.test/") == ssrf.INTERNAL_ADDRESS

    def test_public_https_passes(self, monkeypatch):
        _stub_resolver(monkeypatch, {"h.test": [PUBLIC, "2606:2800:220:1:248:1893:25c8:1946"]})
        assert ssrf.validate_url("https://h.test:8443/mcp") is None

    def test_http_refused_without_resolving(self, monkeypatch):
        monkeypatch.setattr(ssrf, "resolve", lambda h: pytest.fail("resolved"))
        assert ssrf.validate_url("http://h.test/") == "URL must use https"

    def test_unresolvable_and_invalid(self, monkeypatch):
        import socket
        def resolve(host):
            raise socket.gaierror
        monkeypatch.setattr(ssrf, "resolve", resolve)
        assert ssrf.validate_url("https://nope.test/") == "Cannot resolve host: nope.test"
        assert ssrf.validate_url("not a url") == "Invalid URL"
        assert ssrf.validate_url("https://") == "Invalid URL"

    def test_allowed_origin_is_exact_host_and_port(self, monkeypatch):
        monkeypatch.setattr(ssrf, "resolve", lambda h: ["10.0.0.5"])
        allow = ["http://computer.railway.internal:8080"]
        assert ssrf.validate_url("http://computer.railway.internal:8080/mcp/x", allow_origins=allow) is None
        assert ssrf.validate_url("http://computer.railway.internal:8081/", allow_origins=allow) == "URL must use https"
        assert ssrf.validate_url("https://computer.railway.internal/", allow_origins=allow) == ssrf.INTERNAL_ADDRESS

    def test_odoo_discovery_uses_the_shared_check(self):
        from integrations.odoo.discovery import _validate_host
        assert _validate_host is ssrf.validate_host


@pytest.fixture
def local_server():
    """A loopback HTTP server recording the Host header of every request."""
    hosts: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hosts.append(self.headers.get("Host"))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1], hosts
    finally:
        srv.shutdown()
        srv.server_close()


class TestPinnedClient:
    """Through the real httpcore backend; only the resolver is stubbed."""

    async def test_rebinding_refused_at_connect(self, monkeypatch, local_server):
        port, hosts = local_server
        calls = _stub_resolver(monkeypatch, {"rebind.test": [[PUBLIC], ["127.0.0.1"]]})
        assert ssrf.validate_url("https://rebind.test/") is None  # the check saw the public answer
        async with ssrf.pinned_client() as http:
            with pytest.raises(httpx.ConnectError, match="internal addresses"):
                await http.get(f"http://rebind.test:{port}/")  # the connect saw the private one
        assert hosts == [] and calls["rebind.test"] == 2

    async def test_connects_to_the_resolved_address_with_the_original_host(self, monkeypatch, local_server):
        port, hosts = local_server
        _stub_resolver(monkeypatch, {"pinned.test": ["127.0.0.1"]})
        monkeypatch.setattr(ssrf, "_public", lambda ip: True)  # loopback stands in for a public address
        async with ssrf.pinned_client() as http:
            r = await http.get(f"http://pinned.test:{port}/")
        assert r.status_code == 200 and hosts == [f"pinned.test:{port}"]

    async def test_allowed_origin_skips_validation_and_redirects_stay_off(self, monkeypatch, local_server):
        port, hosts = local_server
        monkeypatch.setattr(ssrf, "resolve", lambda h: pytest.fail("resolved"))
        async with ssrf.pinned_client(allow_origins=[f"http://127.0.0.1:{port}"]) as http:
            assert (await http.get(f"http://127.0.0.1:{port}/")).status_code == 200
            assert (await http.get(f"http://127.0.0.1:{port}/redirect")).status_code == 302
        assert hosts == [f"127.0.0.1:{port}"] * 2
