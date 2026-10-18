"""Computer integration (PR 8): "Add computer to this Railway project" against a fake
Railway GraphQL API (httpx MockTransport). The pasted token is used for those calls only:
never saved, never logged, never echoed."""

import json
import logging

import httpx
import pytest

from integrations import registry
from integrations.computer import railway
from integrations.registry import get_credentials, save_credentials

TOKEN = "rw-account-token-SECRET-0123456789abcdef"


class FakeRailway:
    def __init__(self):
        self.ops: list[tuple[str, dict]] = []  # (mutation name, variables) in call order
        self.fail: dict[str, httpx.Response] = {}  # mutation name -> canned reply
        self.unreachable = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("refused", request=request)
        assert request.url == railway.RAILWAY_API
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        body = json.loads(request.content)
        op = body["query"].split("{", 1)[1].split("(", 1)[0].strip()
        self.ops.append((op, body["variables"]))
        if op in self.fail:
            return self.fail[op]
        if op == "serviceCreate":
            return httpx.Response(200, json={"data": {"serviceCreate": {"id": "svc-1", "name": "computer"}}})
        if op == "volumeCreate":
            return httpx.Response(200, json={"data": {"volumeCreate": {"id": "vol-1"}}})
        if op == "serviceInstanceDeployV2":
            return httpx.Response(200, json={"data": {"serviceInstanceDeployV2": "dep-1"}})
        return httpx.Response(400, json={"errors": [{"message": f"unknown mutation {op}"}]})


def _gql_error(message: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"data": None, "errors": [{"message": message}]})


@pytest.fixture
def rw(client, monkeypatch):
    from core.config import settings
    fr = FakeRailway()
    monkeypatch.setattr(railway, "transport", httpx.MockTransport(fr.handle))
    monkeypatch.setattr(settings, "is_railway", True)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj-1")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env-1")
    monkeypatch.delenv("COMPUTER_URL", raising=False)
    monkeypatch.delenv("COMPUTER_SECRET", raising=False)
    fr.client = client
    return fr


def _setup(rw, token=TOKEN):
    return rw.client.post("/api/integrations/computer/railway-setup", json={"token": token})


def test_happy_path_creates_service_volume_deploy_and_saves_creds(rw, caplog):
    caplog.set_level(logging.DEBUG)
    r = _setup(rw)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "service_id": "svc-1", "url": "http://computer.railway.internal:8080"}

    assert [op for op, _ in rw.ops] == ["serviceCreate", "volumeCreate", "serviceInstanceDeployV2"]
    create = rw.ops[0][1]["input"]
    assert create["projectId"] == "proj-1" and create["environmentId"] == "env-1" and create["name"] == "computer"
    assert create["source"] == {"image": railway.IMAGE}
    secret = create["variables"]["COMPUTER_SECRET"]
    assert len(secret) >= 32 and create["variables"]["PORT"] == "8080"
    assert rw.ops[1][1]["input"] == {"projectId": "proj-1", "environmentId": "env-1", "serviceId": "svc-1", "mountPath": "/data"}
    assert rw.ops[2][1] == {"serviceId": "svc-1", "environmentId": "env-1"}

    # Chatty points at the new service without a redeploy, with the very secret the service got.
    creds = get_credentials("computer")
    assert creds["url"] == "http://computer.railway.internal:8080" and creds["api_key"] == secret
    assert creds["enabled"] is True and creds["setup_at"] > 0
    s = rw.client.get("/api/integrations/computer/status").json()
    assert s["configured"] and s["enabled"] and s["is_railway"] is True and s["setup_at"] == creds["setup_at"]

    # The token went into the Authorization header and nowhere else.
    assert TOKEN not in registry._creds_path("computer").read_text(encoding="utf-8")
    assert TOKEN not in json.dumps(creds)
    assert TOKEN not in caplog.text
    assert TOKEN not in r.text


@pytest.mark.parametrize("reply", [
    httpx.Response(401, json={"errors": [{"message": "Not Authorized"}]}),
    httpx.Response(403, text="forbidden"),  # a project token
    _gql_error("Not Authorized"),  # authorization failures also arrive as a 200 with `errors`
    _gql_error("Authentication required"),
])
def test_bad_token_is_a_readable_400_and_saves_nothing(rw, reply, caplog):
    caplog.set_level(logging.DEBUG)
    rw.fail["serviceCreate"] = reply
    r = _setup(rw)
    assert r.status_code == 400 and "rejected the token" in r.json()["detail"], r.text
    assert "project tokens" in r.json()["detail"]
    assert get_credentials("computer") == {}
    assert [op for op, _ in rw.ops] == ["serviceCreate"]
    assert TOKEN not in r.text and TOKEN not in caplog.text


def test_refused_off_railway(rw, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "is_railway", False)
    r = _setup(rw)
    assert r.status_code == 400 and "isn't running on Railway" in r.json()["detail"]
    assert rw.ops == [] and get_credentials("computer") == {}


def test_refused_when_already_configured(rw, monkeypatch):
    save_credentials("computer", {"url": "http://elsewhere:8080", "api_key": "k" * 40})
    r = _setup(rw)
    assert r.status_code == 409 and "already configured" in r.json()["detail"]
    # Env vars (even half a pair) win over saved credentials, so a saved pair would be ignored.
    save_credentials("computer", {})
    monkeypatch.setenv("COMPUTER_URL", "http://env:8080")
    r = _setup(rw)
    assert r.status_code == 409 and "set on the chatty service" in r.json()["detail"]
    assert rw.ops == []


def test_refused_without_railway_ids_or_token(rw, monkeypatch):
    assert _setup(rw, "   ").status_code == 400
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID")
    r = _setup(rw)
    assert r.status_code == 400 and "RAILWAY_PROJECT_ID" in r.json()["detail"]
    assert rw.ops == []


def test_railway_refusals_pass_the_message_through(rw):
    rw.fail["serviceCreate"] = _gql_error("A service with the name computer already exists in this environment")
    r = _setup(rw)
    assert r.status_code == 502 and "already exists" in r.json()["detail"] and "creating the service" in r.json()["detail"]
    assert get_credentials("computer") == {}  # nothing was created, so nothing is saved

    rw.fail.clear()
    rw.fail["serviceCreate"] = httpx.Response(429, text="slow down")
    assert "rate limit" in _setup(rw).json()["detail"]

    rw.fail.clear()
    rw.unreachable = True
    r = _setup(rw)
    assert r.status_code == 502 and "Couldn't reach Railway" in r.json()["detail"]


def test_failure_after_the_service_exists_keeps_the_creds(rw):
    rw.fail["volumeCreate"] = _gql_error("Volume limit reached for this plan")
    r = _setup(rw)
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert detail.startswith("The computer service was created, but railway refused attaching the volume: Volume limit reached")
    assert "volume at /data" in detail
    assert [op for op, _ in rw.ops] == ["serviceCreate", "volumeCreate"]  # no deploy after a failed step
    creds = get_credentials("computer")
    assert creds["url"] == railway.INTERNAL_URL and len(creds["api_key"]) >= 32 and creds["enabled"] is True
    # ...and a second press is refused rather than creating a second service.
    assert _setup(rw).status_code == 409


def test_empty_reply_is_an_error_not_a_crash(rw):
    rw.fail["serviceCreate"] = httpx.Response(200, json={"data": {"serviceCreate": None}})
    r = _setup(rw)
    assert r.status_code == 502 and "empty reply" in r.json()["detail"]
    assert get_credentials("computer") == {}
