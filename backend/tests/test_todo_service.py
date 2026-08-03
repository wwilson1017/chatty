"""Tests for core.todo.service — CRUD, filters, projects, capture."""

import pytest

import core.todo.db as tododb
from core.todo import service


@pytest.fixture()
def todo_db(tmp_path, monkeypatch):
    """Point the todo DB at a temp directory with a live connection."""
    monkeypatch.setattr(tododb, "DATA_DIR", tmp_path / "todo")
    monkeypatch.setattr(tododb, "DB_PATH", tmp_path / "todo" / "todo.db")
    (tmp_path / "todo").mkdir()
    tododb.close_db()
    tododb._setup_connection()
    yield
    tododb.close_db()


class TestCreateTodo:
    def test_defaults(self, todo_db):
        todo = service.create_todo("Call the bank")
        assert todo["title"] == "Call the bank"
        assert todo["status"] == "inbox"
        assert todo["source"] == "agent"
        assert todo["tags"] == []
        assert todo["star"] is False
        assert todo["project_id"] is None
        assert todo["project_name"] is None
        assert todo["due_date"] is None
        assert todo["completed_at"] is None
        assert todo["created_at"] and todo["updated_at"]

    def test_title_required(self, todo_db):
        with pytest.raises(ValueError, match="title is required"):
            service.create_todo("   ")

    def test_invalid_status_rejected(self, todo_db):
        with pytest.raises(ValueError, match="Invalid status"):
            service.create_todo("x", status="doing")

    def test_invalid_due_date_rejected(self, todo_db):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            service.create_todo("x", due_date="tomorrow")

    def test_invalid_source_rejected(self, todo_db):
        with pytest.raises(ValueError, match="Invalid source"):
            service.create_todo("x", source="carrier_pigeon")

    def test_tags_normalized(self, todo_db):
        todo = service.create_todo("x", tags=["  home ", "", "energy:low"])
        assert todo["tags"] == ["home", "energy:low"]

    def test_tags_must_be_string_list(self, todo_db):
        with pytest.raises(ValueError, match="list of strings"):
            service.create_todo("x", tags="home")

    def test_project_auto_created_by_name(self, todo_db):
        todo = service.create_todo("x", project="Renovation")
        assert todo["project_name"] == "Renovation"
        projects = service.list_projects()
        assert [p["name"] for p in projects] == ["Renovation"]
        assert projects[0]["status"] == "active"

    def test_project_name_case_insensitive_dedupe(self, todo_db):
        a = service.create_todo("x", project="Renovation")
        b = service.create_todo("y", project="renovation")
        assert a["project_id"] == b["project_id"]
        assert len(service.list_projects()) == 1

    def test_created_done_gets_completed_at(self, todo_db):
        todo = service.create_todo("x", status="done")
        assert todo["completed_at"] is not None

    def test_unknown_project_id_rejected(self, todo_db):
        with pytest.raises(ValueError, match="Project id not found"):
            service.create_todo("x", project_id=999)


class TestUpdateTodo:
    def test_done_sets_completed_at_and_undone_clears(self, todo_db):
        todo = service.create_todo("x")
        done = service.update_todo(todo["id"], {"status": "done"})
        assert done["completed_at"] is not None
        back = service.update_todo(todo["id"], {"status": "next_action"})
        assert back["completed_at"] is None
        assert back["status"] == "next_action"

    def test_unknown_field_rejected(self, todo_db):
        todo = service.create_todo("x")
        with pytest.raises(ValueError, match="Unknown fields: priority"):
            service.update_todo(todo["id"], {"priority": "high"})

    def test_missing_todo_returns_none(self, todo_db):
        assert service.update_todo(12345, {"title": "y"}) is None

    def test_clear_project_with_empty_name(self, todo_db):
        todo = service.create_todo("x", project="P1")
        cleared = service.update_todo(todo["id"], {"project": ""})
        assert cleared["project_id"] is None

    def test_update_bumps_updated_at(self, todo_db):
        todo = service.create_todo("x")
        conn = tododb.get_db()
        conn.execute(
            "UPDATE todos SET updated_at = '2020-01-01 00:00:00' WHERE id = ?", (todo["id"],)
        )
        conn.commit()
        updated = service.update_todo(todo["id"], {"notes": "hi"})
        assert updated["updated_at"] != "2020-01-01 00:00:00"


class TestBulkUpdate:
    def test_reports_updated_and_not_found(self, todo_db):
        a = service.create_todo("a")
        b = service.create_todo("b")
        result = service.bulk_update([a["id"], b["id"], 999], {"status": "next_action"})
        assert result["updated"] == [a["id"], b["id"]]
        assert result["not_found"] == [999]
        assert service.get_todo(a["id"])["status"] == "next_action"

    def test_done_transition_only_stamps_fresh_completions(self, todo_db):
        a = service.create_todo("a")
        b = service.create_todo("b", status="done")
        first_completed = service.get_todo(b["id"])["completed_at"]
        result = service.bulk_update([a["id"], b["id"]], {"status": "done"})
        assert result["updated"] == [a["id"], b["id"]]
        assert service.get_todo(a["id"])["completed_at"] is not None
        assert service.get_todo(b["id"])["completed_at"] == first_completed

    def test_validation_error_rolls_back_everything(self, todo_db):
        a = service.create_todo("a")
        with pytest.raises(ValueError):
            service.bulk_update([a["id"]], {"status": "bogus"})
        assert service.get_todo(a["id"])["status"] == "inbox"


class TestListTodos:
    def test_filter_by_status(self, todo_db):
        service.create_todo("a")
        service.create_todo("b", status="next_action")
        assert [t["title"] for t in service.list_todos(status="next_action")] == ["b"]

    def test_filter_by_project_name_and_id(self, todo_db):
        t = service.create_todo("a", project="Ops")
        service.create_todo("b")
        assert [x["title"] for x in service.list_todos(project="Ops")] == ["a"]
        assert [x["title"] for x in service.list_todos(project=t["project_id"])] == ["a"]
        assert service.list_todos(project="NoSuch") == []

    def test_filter_by_context_case_insensitive(self, todo_db):
        service.create_todo("a", context="@Home")
        service.create_todo("b", context="@office")
        assert [t["title"] for t in service.list_todos(context="@home")] == ["a"]

    def test_filter_by_tag_exact_json_match(self, todo_db):
        service.create_todo("a", tags=["home"])
        service.create_todo("b", tags=["homework"])
        assert [t["title"] for t in service.list_todos(tag="home")] == ["a"]

    def test_filter_by_starred(self, todo_db):
        service.create_todo("a", star=1)
        service.create_todo("b")
        assert [t["title"] for t in service.list_todos(starred=True)] == ["a"]
        assert [t["title"] for t in service.list_todos(starred=False)] == ["b"]

    def test_due_ranges_exclude_undated(self, todo_db):
        service.create_todo("early", due_date="2026-01-05")
        service.create_todo("late", due_date="2026-03-05")
        service.create_todo("undated")
        assert [t["title"] for t in service.list_todos(due_before="2026-02-01")] == ["early"]
        assert [t["title"] for t in service.list_todos(due_after="2026-02-01")] == ["late"]

    def test_search_title_and_notes_with_wildcards_escaped(self, todo_db):
        service.create_todo("Buy 100% juice")
        service.create_todo("other", notes="contains juice too")
        service.create_todo("unrelated")
        assert len(service.list_todos(search="juice")) == 2
        assert [t["title"] for t in service.list_todos(search="100%")] == ["Buy 100% juice"]

    def test_next_due_arithmetic(self, todo_db):
        # Future base dates (never clamped to today) exercise the raw math.
        assert service._next_due("daily", "2099-03-15") == "2099-03-16"
        assert service._next_due("weekly", "2099-03-15") == "2099-03-22"
        assert service._next_due("monthly", "2099-01-31") == "2099-02-28"  # clamped
        assert service._next_due("monthly", "2099-12-15") == "2100-01-15"  # year rollover
        assert service._next_due("yearly", "2096-02-29") == "2097-02-28"   # leap clamp

    def test_next_due_invalid_repeat_raises(self, todo_db):
        # Empty/unknown values must never silently fall through to yearly math.
        with pytest.raises(ValueError, match="Invalid repeat"):
            service._next_due("", "2099-01-01")
        with pytest.raises(ValueError, match="Invalid repeat"):
            service._next_due("bogus", "2099-01-01")

    def test_next_due_never_spawns_overdue(self, todo_db):
        import datetime
        today = datetime.date.today()
        # Overdue and missing due dates both advance from today.
        assert service._next_due("daily", "2020-01-01") == (today + datetime.timedelta(days=1)).isoformat()
        assert service._next_due("weekly", None) == (today + datetime.timedelta(days=7)).isoformat()

    def test_completing_repeating_todo_spawns_next_occurrence(self, todo_db):
        a = service.create_todo(
            "Water the plants", status="next_action", context="@home",
            tags=["chore"], due_date="2099-06-01", repeat="weekly", star=1,
        )
        service.update_todo(a["id"], {"status": "done"})
        todos = service.list_todos(status="next_action")
        assert len(todos) == 1
        nxt = todos[0]
        assert nxt["id"] != a["id"]
        assert nxt["title"] == "Water the plants"
        assert nxt["due_date"] == "2099-06-08"
        assert nxt["repeat"] == "weekly"
        assert nxt["context"] == "@home"
        assert nxt["tags"] == ["chore"]
        assert nxt["star"] is False          # today's priority doesn't carry over
        done = service.list_todos(status="done")
        assert [t["id"] for t in done] == [a["id"]]

    def test_spawn_preserves_prior_inbox_status(self, todo_db):
        a = service.create_todo("repeating inbox", status="inbox", repeat="daily")
        service.update_todo(a["id"], {"status": "done"})
        spawned = service.list_todos(status="inbox")
        assert [t["title"] for t in spawned] == ["repeating inbox"]
        assert spawned[0]["id"] != a["id"]

    def test_spawn_from_dropped_falls_back_to_next_action(self, todo_db):
        a = service.create_todo("was dropped", status="dropped", repeat="weekly")
        service.update_todo(a["id"], {"status": "done"})
        spawned = service.list_todos(status="next_action")
        assert [t["title"] for t in spawned] == ["was dropped"]

    def test_non_repeating_and_reopen_do_not_spawn(self, todo_db):
        a = service.create_todo("one-off", status="next_action")
        service.update_todo(a["id"], {"status": "done"})
        assert service.list_todos(status="next_action") == []
        b = service.create_todo("weekly thing", status="next_action", repeat="weekly")
        service.update_todo(b["id"], {"status": "done"})
        # Editing an already-done repeating todo must not spawn again.
        service.update_todo(b["id"], {"notes": "edited after done", "status": "done"})
        assert len(service.list_todos(status="next_action")) == 1

    def test_bulk_complete_spawns_each_repeating_todo(self, todo_db):
        a = service.create_todo("water", status="next_action", repeat="daily")
        b = service.create_todo("stretch", status="next_action", repeat="weekly")
        c = service.create_todo("one-off", status="next_action")
        service.bulk_update([a["id"], b["id"], c["id"]], {"status": "done"})
        spawned = service.list_todos(status="next_action")
        assert sorted(t["title"] for t in spawned) == ["stretch", "water"]

    def test_clearing_repeat_while_completing_does_not_spawn(self, todo_db):
        a = service.create_todo("was repeating", status="next_action", repeat="weekly")
        service.update_todo(a["id"], {"repeat": "", "status": "done"})
        assert service.list_todos(status="next_action") == []

    def test_invalid_repeat_rejected(self, todo_db):
        import pytest
        with pytest.raises(ValueError, match="repeat"):
            service.create_todo("x", repeat="fortnightly")
        a = service.create_todo("y")
        with pytest.raises(ValueError, match="repeat"):
            service.update_todo(a["id"], {"repeat": "hourly"})
        # "none" and case variants normalize to no-repeat
        b = service.create_todo("z", repeat="None")
        assert b["repeat"] == ""

    def test_search_matches_context_tags_and_project_name(self, todo_db):
        service.create_todo("a", context="@calls")
        service.create_todo("b", tags=["errands"])
        service.create_todo("c", project="Garage Sale")
        service.create_todo("unrelated")
        assert [t["title"] for t in service.list_todos(search="calls")] == ["a"]
        assert [t["title"] for t in service.list_todos(search="errand")] == ["b"]
        assert [t["title"] for t in service.list_todos(search="garage")] == ["c"]

    def test_ordering_is_fifo(self, todo_db):
        service.create_todo("first")
        service.create_todo("second")
        titles = [t["title"] for t in service.list_todos()]
        assert titles == ["first", "second"]

    def test_done_list_is_newest_finished_first(self, todo_db):
        a = service.create_todo("finished early")
        b = service.create_todo("finished late")
        conn = tododb.get_db()
        conn.execute("UPDATE todos SET status='done', completed_at='2026-01-01 10:00:00' WHERE id=?", (a["id"],))
        conn.execute("UPDATE todos SET status='done', completed_at='2026-06-01 10:00:00' WHERE id=?", (b["id"],))
        conn.commit()
        titles = [t["title"] for t in service.list_todos(status="done")]
        assert titles == ["finished late", "finished early"]

    def test_bulk_non_string_title_rejected_not_crash(self, todo_db):
        a = service.create_todo("a")
        with pytest.raises(ValueError, match="title must be a string"):
            service.bulk_update([a["id"]], {"title": 123})


class TestProjects:
    def test_duplicate_name_rejected(self, todo_db):
        service.create_project("Ops")
        with pytest.raises(ValueError, match="already exists"):
            service.create_project("ops")

    def test_delete_orphans_todos(self, todo_db):
        todo = service.create_todo("x", project="Doomed")
        assert service.delete_project(todo["project_id"]) is True
        survivor = service.get_todo(todo["id"])
        assert survivor is not None
        assert survivor["project_id"] is None

    def test_open_count_excludes_done_and_dropped(self, todo_db):
        service.create_todo("a", project="P")
        service.create_todo("b", project="P", status="done")
        service.create_todo("c", project="P", status="dropped")
        project = service.list_projects()[0]
        assert project["open_count"] == 1

    def test_update_project_rename_dup_rejected(self, todo_db):
        service.create_project("A")
        p = service.create_project("B")
        with pytest.raises(ValueError, match="already exists"):
            service.update_project(p["id"], {"name": "a"})

    def test_update_missing_returns_none(self, todo_db):
        assert service.update_project(999, {"name": "x"}) is None


class TestFilters:
    def test_counts_include_all_statuses_with_zeros(self, todo_db):
        service.create_todo("a")
        filters = service.get_filters()
        assert filters["status_counts"]["inbox"] == 1
        assert set(filters["status_counts"]) == set(tododb.TODO_STATUSES)
        assert filters["status_counts"]["done"] == 0

    def test_contexts_and_tags_deduped(self, todo_db):
        service.create_todo("a", context="@home", tags=["deep", "quick"])
        service.create_todo("b", context="@home", tags=["quick"])
        service.create_todo("c")
        filters = service.get_filters()
        assert filters["contexts"] == ["@home"]
        assert filters["tags"] == ["deep", "quick"]


class TestMigration:
    def test_repeat_column_added_to_pre_migration_db(self, tmp_path, monkeypatch):
        """A DB created before the repeat column existed gets it via the
        ALTER TABLE migration in _setup_connection, preserving existing rows."""
        import sqlite3

        monkeypatch.setattr(tododb, "DATA_DIR", tmp_path / "todo")
        monkeypatch.setattr(tododb, "DB_PATH", tmp_path / "todo" / "todo.db")
        (tmp_path / "todo").mkdir()
        tododb.close_db()

        # Pre-migration schema: current CREATE TABLE minus the repeat column.
        conn = sqlite3.connect(str(tmp_path / "todo" / "todo.db"))
        conn.executescript("""
            CREATE TABLE projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL COLLATE NOCASE UNIQUE,
                notes       TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','someday','completed','dropped')),
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE todos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT NOT NULL,
                notes        TEXT NOT NULL DEFAULT '',
                project_id   INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                context      TEXT NOT NULL DEFAULT '',
                tags         TEXT NOT NULL DEFAULT '[]',
                status       TEXT NOT NULL DEFAULT 'inbox'
                             CHECK(status IN ('inbox','next_action','waiting_for','delegated',
                                              'someday_maybe','done','dropped')),
                star         INTEGER NOT NULL DEFAULT 0,
                due_date     TEXT,
                source       TEXT NOT NULL DEFAULT 'agent',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            );
        """)
        conn.execute("INSERT INTO todos (title) VALUES ('legacy row')")
        conn.commit()
        conn.close()

        tododb._setup_connection()
        try:
            cols = {r[1] for r in tododb.get_db().execute("PRAGMA table_info(todos)")}
            assert "repeat" in cols
            legacy = service.list_todos(search="legacy")
            assert len(legacy) == 1
            assert legacy[0]["repeat"] == ""
            fresh = service.create_todo("new repeating", repeat="weekly")
            assert fresh["repeat"] == "weekly"
        finally:
            tododb.close_db()


class TestCapture:
    def test_capture_trims_and_lands_in_inbox(self, todo_db):
        todo = service.capture("  buy milk  ", source="telegram")
        assert todo["title"] == "buy milk"
        assert todo["status"] == "inbox"
        assert todo["source"] == "telegram"

    def test_capture_empty_rejected(self, todo_db):
        with pytest.raises(ValueError, match="Nothing to capture"):
            service.capture("   ")

    def test_capture_oversize_rejected(self, todo_db):
        with pytest.raises(ValueError, match="too long"):
            service.capture("x" * 20_001)
