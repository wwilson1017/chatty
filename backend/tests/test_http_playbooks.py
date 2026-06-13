"""HTTP tests: playbook CRUD/archive/restore and the learning-events feed."""

import pytest

from core.agents.playbooks import learning_log

from tests.test_http_agents import make_agent

PLAYBOOK_BODY = {
    "name": "Morning Brief",
    "description": "Summarize overnight email and calendar",
    "content": "## Procedure\n1. Pull unread email.\n2. Summarize.",
    "integrations": [],
    "chip": True,
}


@pytest.fixture
def agent(client):
    return make_agent(client)


def put_playbook(client, agent, slug="morning-brief", **overrides):
    body = {**PLAYBOOK_BODY, **overrides}
    return client.put(f"/api/agents/{agent['id']}/playbooks/{slug}", json=body)


# ── Playbook CRUD ─────────────────────────────────────────────────────────────

def test_list_empty(client, agent):
    resp = client.get(f"/api/agents/{agent['id']}/playbooks")
    assert resp.status_code == 200
    assert resp.json() == {"playbooks": []}


def test_put_creates_and_get_roundtrip(client, agent):
    resp = put_playbook(client, agent)
    assert resp.status_code == 200
    assert resp.json()["slug"] == "morning-brief"

    got = client.get(f"/api/agents/{agent['id']}/playbooks/morning-brief")
    assert got.status_code == 200
    pb = got.json()
    assert pb["meta"]["name"] == "Morning Brief"
    assert pb["meta"]["chip"] is True
    assert "## Procedure" in pb["body"]
    assert pb["archived"] is False

    listed = client.get(f"/api/agents/{agent['id']}/playbooks").json()["playbooks"]
    assert [p["slug"] for p in listed] == ["morning-brief"]


def test_get_missing_404(client, agent):
    assert client.get(f"/api/agents/{agent['id']}/playbooks/nope").status_code == 404


def test_put_invalid_slug_400(client, agent):
    resp = put_playbook(client, agent, slug="Bad_Slug")
    assert resp.status_code == 400


def test_archive_restore_cycle(client, agent):
    put_playbook(client, agent)

    resp = client.post(f"/api/agents/{agent['id']}/playbooks/morning-brief/archive")
    assert resp.status_code == 200
    assert resp.json()["archived"] is True
    listed = client.get(f"/api/agents/{agent['id']}/playbooks").json()["playbooks"]
    assert [p["archived"] for p in listed] == [True]

    resp = client.post(f"/api/agents/{agent['id']}/playbooks/morning-brief/restore")
    assert resp.status_code == 200
    listed = client.get(f"/api/agents/{agent['id']}/playbooks").json()["playbooks"]
    assert [p["archived"] for p in listed] == [False]


def test_archive_missing_404(client, agent):
    resp = client.post(f"/api/agents/{agent['id']}/playbooks/nope/archive")
    assert resp.status_code == 404


def test_delete_playbook(client, agent):
    put_playbook(client, agent)
    resp = client.delete(f"/api/agents/{agent['id']}/playbooks/morning-brief")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert client.get(f"/api/agents/{agent['id']}/playbooks/morning-brief").status_code == 404


def test_delete_missing_404(client, agent):
    assert client.delete(f"/api/agents/{agent['id']}/playbooks/nope").status_code == 404


# ── Learning events ───────────────────────────────────────────────────────────

def test_learning_events_empty(client, agent):
    # Also verifies ensure_memory_db lazily creates the per-agent memory DB
    # under the patched tmp tree when reached over HTTP.
    resp = client.get(f"/api/agents/{agent['id']}/learning-events")
    assert resp.status_code == 200
    assert resp.json() == {"events": []}


def test_learning_events_list_after_seed(client, agent):
    eid = learning_log.log_event(
        agent["slug"], event_type="playbook_created", source="review",
        target="morning-brief", title="New playbook “Morning Brief”",
        after_content="full file text",
    )
    assert eid

    resp = client.get(f"/api/agents/{agent['id']}/learning-events")
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "playbook_created"
    assert events[0]["reverted_at"] is None

    paged = client.get(
        f"/api/agents/{agent['id']}/learning-events", params={"limit": 1, "offset": 1}
    )
    assert paged.json()["events"] == []


def test_revert_playbook_updated_restores_content(client, agent):
    put_playbook(client, agent)
    v1_path_resp = client.get(f"/api/agents/{agent['id']}/playbooks/morning-brief")
    v1_body = v1_path_resp.json()["body"]

    # Reconstruct the on-disk v1 text the way the service stores it, then
    # simulate an agent-learned update with before_content = v1.
    from core.agents.playbooks import service as pb_service
    v1_text = (pb_service.playbooks_dir(agent["slug"]) / "morning-brief.md").read_text()

    put_playbook(client, agent, content="## Procedure\nCOMPLETELY REWRITTEN")
    eid = learning_log.log_event(
        agent["slug"], event_type="playbook_updated", source="agent",
        target="morning-brief", title="Updated playbook",
        before_content=v1_text,
    )

    resp = client.post(f"/api/agents/{agent['id']}/learning-events/{eid}/revert")
    assert resp.status_code == 200
    assert resp.json()["reverted"] is True

    got = client.get(f"/api/agents/{agent['id']}/playbooks/morning-brief").json()
    assert got["body"] == v1_body
    assert "COMPLETELY REWRITTEN" not in got["body"]


def test_revert_playbook_created_archives(client, agent):
    put_playbook(client, agent)
    eid = learning_log.log_event(
        agent["slug"], event_type="playbook_created", source="review",
        target="morning-brief", title="New playbook",
    )

    resp = client.post(f"/api/agents/{agent['id']}/learning-events/{eid}/revert")
    assert resp.status_code == 200

    got = client.get(f"/api/agents/{agent['id']}/playbooks/morning-brief").json()
    assert got["archived"] is True


def test_revert_twice_400(client, agent):
    put_playbook(client, agent)
    eid = learning_log.log_event(
        agent["slug"], event_type="playbook_created", source="review",
        target="morning-brief", title="New playbook",
    )
    assert client.post(
        f"/api/agents/{agent['id']}/learning-events/{eid}/revert"
    ).status_code == 200

    resp = client.post(f"/api/agents/{agent['id']}/learning-events/{eid}/revert")
    assert resp.status_code == 400
    assert "already reverted" in resp.json()["detail"]


def test_revert_unknown_event_400(client, agent):
    resp = client.post(f"/api/agents/{agent['id']}/learning-events/9999/revert")
    assert resp.status_code == 400
