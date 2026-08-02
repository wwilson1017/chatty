"""HTTP tests for /api/todo — CRUD, bulk, projects, filters.

Auth coverage comes from the 401 sweep in test_http_misc.py.
"""


class TestTodoCrud:
    def test_create_defaults_to_inbox_with_ui_source(self, client):
        r = client.post("/api/todo/todos", json={"title": "Call the bank"})
        assert r.status_code == 200
        todo = r.json()
        assert todo["status"] == "inbox"
        assert todo["source"] == "ui"
        assert todo["star"] is False

    def test_create_requires_title(self, client):
        r = client.post("/api/todo/todos", json={"title": "   "})
        assert r.status_code == 400

    def test_get_update_delete_roundtrip(self, client):
        todo = client.post("/api/todo/todos", json={"title": "x"}).json()
        tid = todo["id"]

        r = client.get(f"/api/todo/todos/{tid}")
        assert r.status_code == 200

        r = client.put(f"/api/todo/todos/{tid}", json={"status": "done"})
        assert r.status_code == 200
        assert r.json()["completed_at"] is not None

        r = client.delete(f"/api/todo/todos/{tid}")
        assert r.status_code == 200
        assert client.get(f"/api/todo/todos/{tid}").status_code == 404

    def test_partial_update_preserves_other_fields(self, client):
        todo = client.post(
            "/api/todo/todos",
            json={"title": "x", "notes": "keep me", "context": "@home"},
        ).json()
        r = client.put(f"/api/todo/todos/{todo['id']}", json={"star": True})
        assert r.status_code == 200
        updated = r.json()
        assert updated["star"] is True
        assert updated["notes"] == "keep me"
        assert updated["context"] == "@home"

    def test_update_missing_404(self, client):
        assert client.put("/api/todo/todos/9999", json={"title": "y"}).status_code == 404

    def test_invalid_status_400(self, client):
        r = client.post("/api/todo/todos", json={"title": "x", "status": "bogus"})
        assert r.status_code == 400

    def test_list_filters_by_status(self, client):
        client.post("/api/todo/todos", json={"title": "a"})
        client.post("/api/todo/todos", json={"title": "b", "status": "next_action"})
        r = client.get("/api/todo/todos", params={"status": "next_action"})
        assert r.status_code == 200
        todos = r.json()["todos"]
        assert [t["title"] for t in todos] == ["b"]

    def test_bulk_update(self, client):
        a = client.post("/api/todo/todos", json={"title": "a"}).json()
        b = client.post("/api/todo/todos", json={"title": "b"}).json()
        r = client.post(
            "/api/todo/todos/bulk",
            json={"ids": [a["id"], b["id"], 777], "fields": {"status": "someday_maybe"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == [a["id"], b["id"]]
        assert body["not_found"] == [777]

    def test_bulk_bad_field_400(self, client):
        a = client.post("/api/todo/todos", json={"title": "a"}).json()
        r = client.post("/api/todo/todos/bulk", json={"ids": [a["id"]], "fields": {"nope": 1}})
        assert r.status_code == 400


class TestTodoProjects:
    def test_create_by_name_via_todo(self, client):
        todo = client.post("/api/todo/todos", json={"title": "x", "project": "Ops"}).json()
        assert todo["project_name"] == "Ops"
        projects = client.get("/api/todo/projects").json()["projects"]
        assert [p["name"] for p in projects] == ["Ops"]
        assert projects[0]["open_count"] == 1

    def test_duplicate_400(self, client):
        client.post("/api/todo/projects", json={"name": "Ops"})
        assert client.post("/api/todo/projects", json={"name": "ops"}).status_code == 400

    def test_delete_orphans_todos(self, client):
        todo = client.post("/api/todo/todos", json={"title": "x", "project": "Doomed"}).json()
        r = client.delete(f"/api/todo/projects/{todo['project_id']}")
        assert r.status_code == 200
        survivor = client.get(f"/api/todo/todos/{todo['id']}").json()
        assert survivor["project_id"] is None

    def test_update_project(self, client):
        p = client.post("/api/todo/projects", json={"name": "Old"}).json()
        r = client.put(f"/api/todo/projects/{p['id']}", json={"name": "New", "status": "someday"})
        assert r.status_code == 200
        assert r.json()["name"] == "New"
        assert r.json()["status"] == "someday"

    def test_project_404s(self, client):
        assert client.put("/api/todo/projects/999", json={"name": "x"}).status_code == 404
        assert client.delete("/api/todo/projects/999").status_code == 404


class TestTodoFilters:
    def test_filters_shape(self, client):
        client.post("/api/todo/todos", json={"title": "a", "context": "@home", "tags": ["deep"]})
        r = client.get("/api/todo/filters")
        assert r.status_code == 200
        body = r.json()
        assert body["contexts"] == ["@home"]
        assert body["tags"] == ["deep"]
        assert body["status_counts"]["inbox"] == 1
        assert body["status_counts"]["done"] == 0
        assert len(body["status_counts"]) == 7
