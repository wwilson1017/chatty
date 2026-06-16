"""HTTP tests for the Printing Press routes (catalog, install, manage, build SSE).

Network (library fetch) and the real Go build are mocked — these test the API
surface + install lifecycle, not the toolchain (covered by the M0 spike).
"""

from tests.conftest import parse_sse

_FAKE_REGISTRY = {
    "schema_version": 2,
    "entries": [{
        "name": "openalex", "category": "other", "api": "OpenAlex",
        "description": "Scholarly works API.", "path": "library/other/openalex",
        "search_terms": ["a"] * 50,  # dropped by the slimmed catalog
        "mcp": {"tool_count": 43, "auth_type": "api_key", "env_vars": ["OPENALEX_API_KEY"]},
    }],
}


def _make_install(slug="demo", **kw):
    from integrations.printing_press import store
    base = dict(slug=slug, category="x", ref="main", sha="a" * 40, api_name=slug.upper(),
                tool_count=2, build_status=store.BUILD_READY)
    base.update(kw)
    return store.save_install(store.Install(**base))


def test_catalog_is_slimmed(client, monkeypatch):
    from integrations.printing_press import library_client
    monkeypatch.setattr(library_client, "fetch_registry", lambda ref="main": _FAKE_REGISTRY)
    resp = client.get("/api/printing-press/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    entry = data["entries"][0]
    assert entry["slug"] == "openalex" and entry["tool_count"] == 43
    assert entry["auth_type"] == "api_key"
    assert "search_terms" not in entry  # slimmed out


def test_catalog_library_unreachable_502(client, monkeypatch):
    from integrations.printing_press import library_client

    def boom(ref="main"):
        raise RuntimeError("network down")

    monkeypatch.setattr(library_client, "fetch_registry", boom)
    assert client.get("/api/printing-press/catalog").status_code == 502


def test_installed_lists_records(client):
    _make_install("demo", auth={"type": "api_key", "env_vars": ["DEMO_KEY"]})
    resp = client.get("/api/printing-press/installed")
    assert resp.status_code == 200
    items = resp.json()["installed"]
    assert len(items) == 1
    item = items[0]
    assert item["slug"] == "demo" and item["build_status"] == "ready"
    assert item["needs_auth"] is True  # declares env_vars, no creds saved


def test_install_creates_building_record_and_queues(client, monkeypatch):
    from integrations.printing_press import build_jobs, store
    monkeypatch.setattr(build_jobs, "submit_build", lambda slug, category, ref="main": "bid123")
    resp = client.post("/api/printing-press/install",
                       json={"slug": "openalex", "category": "other", "ref": "main"})
    assert resp.status_code == 200
    assert resp.json() == {"build_id": "bid123", "slug": "openalex"}
    rec = store.get_install("openalex")
    assert rec is not None and rec.build_status == store.BUILD_BUILDING


def test_install_rejects_bad_slug(client):
    resp = client.post("/api/printing-press/install",
                       json={"slug": "../evil", "category": "other"})
    assert resp.status_code == 400


def test_enable_disable_mode_delete(client):
    _make_install("demo")
    assert client.post("/api/printing-press/demo/disable").status_code == 200
    from integrations.printing_press import store
    assert store.get_install("demo").enabled is False
    assert client.post("/api/printing-press/demo/enable").status_code == 200
    assert client.post("/api/printing-press/demo/mode", json={"tool_mode": "power"}).status_code == 200
    assert store.get_install("demo").tool_mode == "power"
    assert client.post("/api/printing-press/demo/mode", json={"tool_mode": "bogus"}).status_code == 400
    assert client.delete("/api/printing-press/demo").status_code == 200
    assert store.get_install("demo") is None
    assert client.post("/api/printing-press/demo/enable").status_code == 404


def test_build_stream_emits_progress_then_done(client):
    from integrations.printing_press import build_jobs
    job = build_jobs.BuildJob(build_id="b1", slug="demo", category="x", ref="main")
    job.log = [{"phase": "fetch", "msg": "fetching"}, {"phase": "build", "msg": "built"}]
    job.status = build_jobs.SUCCESS
    job.finished_at = 1.0
    build_jobs._jobs["b1"] = job
    try:
        resp = client.get("/api/printing-press/install/b1/stream")
        assert resp.status_code == 200
        events = parse_sse(resp)
        phases = [e.get("phase") for e in events if e.get("type") == "progress"]
        assert phases == ["fetch", "build"]
        done = [e for e in events if e.get("type") == "done"]
        assert done and done[0]["status"] == "success"
    finally:
        build_jobs._jobs.pop("b1", None)


def test_build_stream_unknown_404(client):
    assert client.get("/api/printing-press/install/nope/stream").status_code == 404


# ── auth ──────────────────────────────────────────────────────────────────

def _install_with_auth(slug="demo"):
    from integrations.printing_press import store
    store.save_install(store.Install(
        slug=slug, category="x", ref="main", sha="a" * 40, api_name=slug.upper(),
        tool_count=1, build_status=store.BUILD_READY,
        auth={"type": "api_key", "env_vars": ["DEMO_API_KEY"]}))
    store.save_manifest(slug, {"api_name": slug.upper(), "tools": [], "auth": {
        "type": "api_key", "env_vars": ["DEMO_API_KEY"],
        "env_var_specs": [{"name": "DEMO_API_KEY", "description": "Your Demo key",
                           "sensitive": True, "required": True}]}})


def test_auth_requirements(client):
    _install_with_auth()
    r = client.get("/api/printing-press/demo/auth").json()
    assert r["auth_type"] == "api_key"
    assert r["env_vars"][0] == {"name": "DEMO_API_KEY", "description": "Your Demo key", "sensitive": True}
    assert r["has_credentials"] is False
    assert r["supports_device"] is False  # no built binary → no device flow


def test_save_and_clear_auth(client):
    from integrations.printing_press import store
    _install_with_auth()
    assert client.post("/api/printing-press/demo/auth", json={"env": {"DEMO_API_KEY": "sk-123"}}).status_code == 200
    assert store.get_cli_credentials("demo") == {"DEMO_API_KEY": "sk-123"}
    items = client.get("/api/printing-press/installed").json()["installed"]
    assert next(i for i in items if i["slug"] == "demo")["needs_auth"] is False
    assert client.delete("/api/printing-press/demo/auth").status_code == 200
    assert store.get_cli_credentials("demo") == {}


def test_save_auth_empty_400(client):
    _install_with_auth()
    assert client.post("/api/printing-press/demo/auth", json={"env": {"DEMO_API_KEY": ""}}).status_code == 400


def test_auth_requirements_unknown_404(client):
    assert client.get("/api/printing-press/ghost/auth").status_code == 404


def test_device_flow_unsupported_400(client):
    _install_with_auth()  # synthetic install has no binary → device unsupported
    assert client.post("/api/printing-press/demo/auth/device").status_code == 400
