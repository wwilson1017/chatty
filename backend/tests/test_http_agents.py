"""HTTP tests: agent CRUD and per-agent context file CRUD."""


def make_agent(client, name="Helper", personality="friendly"):
    resp = client.post("/api/agents", json={"agent_name": name, "personality": personality})
    assert resp.status_code == 200
    return resp.json()


# ── Agent CRUD ────────────────────────────────────────────────────────────────

def test_list_agents_empty(client):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    assert resp.json() == {"agents": []}


def test_create_agent_seeds_context(client, tmp_path):
    agent = make_agent(client)
    assert agent["slug"] == "helper"
    assert agent["id"]
    # Seeding is synchronous and lands in the patched tmp tree — proves the
    # router-level DATA_DIR patch is effective.
    assert (tmp_path / "helper" / "context" / "soul.md").exists()


def test_create_agent_blank_name_400(client):
    resp = client.post("/api/agents", json={"agent_name": "   "})
    assert resp.status_code == 400


def test_get_agent(client):
    agent = make_agent(client)
    resp = client.get(f"/api/agents/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "helper"


def test_get_agent_unknown_404(client):
    assert client.get("/api/agents/no-such-id").status_code == 404


def test_rename_keeps_slug_and_context(client):
    agent = make_agent(client)
    files_before = client.get(f"/api/agents/{agent['id']}/context").json()["files"]
    names_before = sorted(f["name"] for f in files_before)
    assert names_before

    resp = client.put(f"/api/agents/{agent['id']}", json={"agent_name": "Renamed Agent"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["agent_name"] == "Renamed Agent"
    assert updated["slug"] == "helper"

    files_after = client.get(f"/api/agents/{agent['id']}/context").json()["files"]
    assert sorted(f["name"] for f in files_after) == names_before


def test_update_no_fields_400(client):
    agent = make_agent(client)
    resp = client.put(f"/api/agents/{agent['id']}", json={})
    assert resp.status_code == 400


def test_update_invalid_model_tier_400(client):
    agent = make_agent(client)
    resp = client.put(f"/api/agents/{agent['id']}", json={"model_tier": "ludicrous"})
    assert resp.status_code == 400


def test_delete_agent(client, tmp_path):
    agent = make_agent(client)
    assert (tmp_path / "helper").exists()

    resp = client.delete(f"/api/agents/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert client.get(f"/api/agents/{agent['id']}").status_code == 404
    assert not (tmp_path / "helper").exists()


# ── Context file CRUD ─────────────────────────────────────────────────────────

def test_context_list_seeded(client):
    agent = make_agent(client)
    files = client.get(f"/api/agents/{agent['id']}/context").json()["files"]
    assert "soul.md" in [f["name"] for f in files]


def test_context_put_get_roundtrip(client):
    agent = make_agent(client)
    put = client.put(
        f"/api/agents/{agent['id']}/context/notes.md", json={"content": "# Notes\nhello"}
    )
    assert put.status_code == 200
    assert put.json() == {"filename": "notes.md", "ok": True}

    got = client.get(f"/api/agents/{agent['id']}/context/notes.md")
    assert got.status_code == 200
    assert got.json()["content"] == "# Notes\nhello"


def test_context_get_missing_404(client):
    agent = make_agent(client)
    assert client.get(f"/api/agents/{agent['id']}/context/nope.md").status_code == 404


def test_context_delete_then_404(client):
    agent = make_agent(client)
    client.put(f"/api/agents/{agent['id']}/context/notes.md", json={"content": "x"})
    resp = client.delete(f"/api/agents/{agent['id']}/context/notes.md")
    assert resp.status_code == 200
    assert client.get(f"/api/agents/{agent['id']}/context/notes.md").status_code == 404


def test_context_rejects_bad_filenames(client):
    agent = make_agent(client)
    # Single-segment names that route but fail _safe_filename → 400, on all verbs.
    for bad in ("notes.txt", "noextension", "..sneaky.md", "back%5Cslash.md"):
        for method, kwargs in (
            ("GET", {}),
            ("PUT", {"json": {"content": "x"}}),
            ("DELETE", {}),
        ):
            resp = client.request(
                method, f"/api/agents/{agent['id']}/context/{bad}", **kwargs
            )
            assert resp.status_code == 400, (
                f"{method} {bad!r} returned {resp.status_code}"
            )


def test_context_encoded_traversal_blocked(client, tmp_path):
    agent = make_agent(client)
    # %2F decodes to a slash, which the single-segment path param can't match;
    # depending on routing this is a 404 (no route) or 400 (validator). The
    # property under test: never 200, and nothing written outside context/.
    resp = client.put(
        f"/api/agents/{agent['id']}/context/..%2Fevil.md", json={"content": "pwned"}
    )
    assert resp.status_code in (400, 404)
    assert not (tmp_path / "helper" / "evil.md").exists()
    assert not (tmp_path / "evil.md").exists()
