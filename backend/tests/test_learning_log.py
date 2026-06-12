"""Tests for the learning events log and one-click revert."""

import pytest

import core.agents.playbooks.learning_log as ll
import core.agents.playbooks.service as svc


@pytest.fixture
def learning_env(monkeypatch, tmp_path):
    """Real MemoryDB + playbooks dir in a temp tree."""
    import agents.engine as engine_mod
    from core.agents.memory.db import MemoryDB

    agents_dir = tmp_path / "agents"
    ctx_dir = agents_dir / "test-agent" / "context"
    ctx_dir.mkdir(parents=True)
    monkeypatch.setattr(engine_mod, "DATA_DIR", agents_dir)
    monkeypatch.setattr(svc, "upload_config", lambda *a, **k: None)
    monkeypatch.setattr(svc, "delete_config", lambda *a, **k: None)

    db = MemoryDB(ctx_dir, "agents/test-agent/context/")
    db._setup_connection()
    monkeypatch.setattr(ll, "_get_db", lambda slug: db)
    return db


def test_log_and_list(learning_env):
    eid = ll.log_event(
        "test-agent", event_type="playbook_created", source="review",
        target="daily-recap", title="New playbook “Daily Recap”",
        after_content="full file text",
    )
    assert eid
    events = ll.list_events("test-agent")
    assert len(events) == 1
    assert events[0]["event_type"] == "playbook_created"
    assert events[0]["reverted_at"] is None


def test_unknown_event_type_rejected(learning_env):
    assert ll.log_event("test-agent", event_type="nonsense", source="review",
                        target="x", title="t") is None


def test_revert_created_archives(learning_env):
    svc.save_playbook("test-agent", name="Daily Recap", description="D",
                      content="body", origin="user")
    eid = ll.log_event("test-agent", event_type="playbook_created", source="review",
                       target="daily-recap", title="t")
    result = ll.revert_event("test-agent", eid)
    assert result["reverted"]
    assert svc.read_playbook("test-agent", "daily-recap")["archived"]


def test_revert_updated_restores_before_content(learning_env):
    svc.save_playbook("test-agent", name="Recap", description="D",
                      content="original body", origin="user")
    pb_path = svc.playbooks_dir("test-agent") / "recap.md"
    before_text = pb_path.read_text(encoding="utf-8")

    svc.save_playbook("test-agent", slug="recap", content="mutated body", origin="user")
    eid = ll.log_event("test-agent", event_type="playbook_updated", source="review",
                       target="recap", title="t", before_content=before_text)

    assert ll.revert_event("test-agent", eid)["reverted"]
    assert pb_path.read_text(encoding="utf-8") == before_text


def test_revert_updated_blocked_while_archived(learning_env):
    """Reverting an update while the playbook is archived must not create a
    duplicate active copy alongside the archived one."""
    svc.save_playbook("test-agent", name="Recap", description="D",
                      content="original body", origin="user")
    pb_path = svc.playbooks_dir("test-agent") / "recap.md"
    before_text = pb_path.read_text(encoding="utf-8")

    svc.save_playbook("test-agent", slug="recap", content="mutated body", origin="user")
    eid = ll.log_event("test-agent", event_type="playbook_updated", source="review",
                       target="recap", title="t", before_content=before_text)

    svc.archive_playbook("test-agent", "recap")
    result = ll.revert_event("test-agent", eid)
    assert "error" in result
    assert not pb_path.exists()
    assert svc.read_playbook("test-agent", "recap")["archived"]


def test_revert_archived_restores(learning_env):
    svc.save_playbook("test-agent", name="Old", description="D", content="b", origin="user")
    svc.archive_playbook("test-agent", "old")
    eid = ll.log_event("test-agent", event_type="playbook_archived", source="review",
                       target="old", title="t")
    assert ll.revert_event("test-agent", eid)["reverted"]
    assert not svc.read_playbook("test-agent", "old")["archived"]


def test_revert_fact_deletes(learning_env):
    fact = learning_env.add_fact(subject="Acme", predicate="payment terms", object_="net-30")
    eid = ll.log_event("test-agent", event_type="fact_added", source="review",
                       target=f"fact:{fact['id']}", title="t")
    assert ll.revert_event("test-agent", eid)["reverted"]
    conn = learning_env.get_db()
    assert conn.execute("SELECT COUNT(*) FROM facts WHERE id = ?",
                        (fact["id"],)).fetchone()[0] == 0


def test_double_revert_guarded(learning_env):
    svc.save_playbook("test-agent", name="Once", description="D", content="b", origin="user")
    eid = ll.log_event("test-agent", event_type="playbook_created", source="review",
                       target="once", title="t")
    assert ll.revert_event("test-agent", eid)["reverted"]
    assert "error" in ll.revert_event("test-agent", eid)


def test_blocked_injection_not_revertible(learning_env):
    eid = ll.log_event("test-agent", event_type="blocked_injection", source="review",
                       target="x", title="t")
    assert "error" in ll.revert_event("test-agent", eid)


def test_revert_missing_event(learning_env):
    assert "error" in ll.revert_event("test-agent", 99999)
