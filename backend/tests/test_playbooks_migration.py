"""Tests for the skill_packs → playbooks startup migration."""

import sqlite3

import pytest

import core.agents.playbooks.migration as mig
import core.agents.playbooks.service as svc

LEGACY_DDL = """
CREATE TABLE skill_packs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    description     TEXT    NOT NULL DEFAULT '',
    prompt          TEXT    NOT NULL,
    category        TEXT,
    tags            TEXT,
    trigger_pattern TEXT,
    usage_count     INTEGER NOT NULL DEFAULT 0,
    auto_generated  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


@pytest.fixture
def migration_env(monkeypatch, tmp_path):
    import agents.engine as engine_mod
    agents_dir = tmp_path / "agents"
    monkeypatch.setattr(engine_mod, "DATA_DIR", agents_dir)
    monkeypatch.setattr(svc, "upload_config", lambda *a, **k: None)
    monkeypatch.setattr(svc, "delete_config", lambda *a, **k: None)
    return agents_dir


def _make_agent_with_skills(agents_dir, slug, rows):
    ctx = agents_dir / slug / "context"
    ctx.mkdir(parents=True)
    conn = sqlite3.connect(ctx / "memory.db")
    conn.executescript(LEGACY_DDL)
    for name, description, prompt, category, usage in rows:
        conn.execute(
            "INSERT INTO skill_packs (name, description, prompt, category, usage_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, description, prompt, category, usage),
        )
    conn.commit()
    conn.close()


def test_migrates_rows_to_files(migration_env):
    _make_agent_with_skills(migration_env, "test-agent", [
        ("Weekly Report", "Builds the weekly report", "Summarize the week's sales.", "analysis", 7),
        ("Email Draft", "", "Draft an email about {{topic}}.", None, 0),
    ])

    result = mig.migrate_all_agents()
    assert result == {"status": "ok", "migrated": 2}

    rows = svc.list_playbooks("test-agent")
    slugs = {r["slug"] for r in rows}
    assert slugs == {"weekly-report", "email-draft"}

    weekly = svc.read_playbook("test-agent", "weekly-report")
    assert weekly["meta"]["created_by"] == "migration"
    assert "Summarize the week's sales." in weekly["body"]
    assert "## Procedure" in weekly["body"]
    assert "analysis" in weekly["body"]

    # usage_count seeded into telemetry
    by_slug = {r["slug"]: r for r in rows}
    assert by_slug["weekly-report"]["use_count"] == 7
    assert by_slug["email-draft"]["use_count"] == 0

    marker = migration_env / "test-agent" / "playbooks" / mig.MIGRATION_MARKER
    assert marker.exists()


def test_idempotent(migration_env):
    _make_agent_with_skills(migration_env, "test-agent", [
        ("Only One", "d", "prompt body", None, 1),
    ])
    assert mig.migrate_all_agents()["migrated"] == 1
    assert mig.migrate_all_agents()["migrated"] == 0
    assert len(svc.list_playbooks("test-agent")) == 1


def test_missing_table_tolerated(migration_env):
    ctx = migration_env / "fresh-agent" / "context"
    ctx.mkdir(parents=True)
    sqlite3.connect(ctx / "memory.db").close()  # empty DB, no skill_packs table

    result = mig.migrate_all_agents()
    assert result["status"] == "ok"
    assert result["migrated"] == 0
    assert (migration_env / "fresh-agent" / "playbooks" / mig.MIGRATION_MARKER).exists()


def test_missing_db_tolerated(migration_env):
    (migration_env / "no-db-agent").mkdir(parents=True)
    result = mig.migrate_all_agents()
    assert result["status"] == "ok"


def test_no_agents_dir(monkeypatch, tmp_path):
    import agents.engine as engine_mod
    monkeypatch.setattr(engine_mod, "DATA_DIR", tmp_path / "nonexistent")
    assert mig.migrate_all_agents() == {"status": "ok", "migrated": 0}
