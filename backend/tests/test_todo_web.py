"""Tests for the no-login todo web app (/todo page + /api/todo-web API)."""

import pytest
from fastapi.routing import APIRoute

import core.admin_settings as admin
import core.todo.web as web_mod
import main


@pytest.fixture(autouse=True)
def clean_rate_buckets():
    """Per-IP buckets are module-global and TestClient always presents the
    same IP, so leftover state would bleed 429s across tests."""
    web_mod.web_limiter.clear()
    web_mod.guess_limiter.clear()
    yield
    web_mod.web_limiter.clear()
    web_mod.guess_limiter.clear()


@pytest.fixture
def shell(monkeypatch):
    """Stand in for frontend/dist/index.html, which tests don't build."""
    monkeypatch.setattr(
        web_mod, "_index_html",
        lambda: "<html><head><title>Chatty</title></head><body></body></html>",
    )


def _enable(token: str = "") -> None:
    admin.set_admin_setting("todo_web_enabled", True)
    admin.set_admin_setting("todo_web_token", token)


def _todo_web_paths():
    """Every registered /todo* or /api/todo-web* route, as (method, url)."""
    cases = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(("/todo", "/api/todo-web")):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            cases.append((method, route.path.replace("{rest:path}", "x")
                                            .replace("{token}", "x")
                                            .replace("{todo_id}", "1")
                                            .replace("{project_id}", "1")))
    return cases


class TestDisabledByDefault:
    def test_every_route_404s(self, anon_client):
        paths = _todo_web_paths()
        assert paths, "no todo-web routes registered"
        for method, url in paths:
            resp = anon_client.request(method, url, json={})
            assert resp.status_code == 404, f"{method} {url} returned {resp.status_code}"

    def test_dashboard_api_unaffected(self, client):
        assert client.get("/api/todo/filters").status_code == 200


class TestPublicMode:
    def test_page_served_with_base_injected(self, anon_client, shell):
        _enable()
        r = anon_client.get("/todo")
        assert r.status_code == 200
        assert 'window.__CHATTY_TODO_BASE__ = "/todo"' in r.text
        assert r.headers["cache-control"] == "no-store"

    def test_deep_link_serves_same_shell(self, anon_client, shell):
        _enable()
        assert anon_client.get("/todo/projects/12").status_code == 200

    def test_api_reads_and_writes(self, anon_client, client):
        _enable()
        created = anon_client.post("/api/todo-web/todos", json={"title": "mow the lawn"})
        assert created.status_code == 200
        todo_id = created.json()["id"]

        listed = anon_client.get("/api/todo-web/todos?status=inbox")
        assert listed.status_code == 200
        assert any(t["id"] == todo_id for t in listed.json()["todos"])

        assert anon_client.put(
            f"/api/todo-web/todos/{todo_id}", json={"status": "next_action"},
        ).status_code == 200
        # Same store the logged-in dashboard sees.
        assert client.get(f"/api/todo/todos/{todo_id}").json()["status"] == "next_action"

        assert anon_client.get("/api/todo-web/filters").status_code == 200
        assert anon_client.delete(f"/api/todo-web/todos/{todo_id}").status_code == 200

    def test_token_paths_404_while_public(self, anon_client, shell):
        _enable()
        assert anon_client.get("/api/todo-web/whatever/todos").status_code == 404


class TestTokenMode:
    def test_bare_paths_404(self, anon_client, shell):
        _enable("s3cret-token")
        assert anon_client.get("/todo").status_code == 404
        assert anon_client.get("/api/todo-web/todos").status_code == 404

    def test_wrong_token_404(self, anon_client, shell):
        _enable("s3cret-token")
        assert anon_client.get("/todo/nope").status_code == 404
        assert anon_client.get("/api/todo-web/nope/todos").status_code == 404

    def test_right_token_works(self, anon_client, shell):
        _enable("s3cret-token")
        page = anon_client.get("/todo/s3cret-token")
        assert page.status_code == 200
        assert 'window.__CHATTY_TODO_BASE__ = "/todo/s3cret-token"' in page.text
        assert anon_client.get("/todo/s3cret-token/next").status_code == 200
        assert anon_client.get("/api/todo-web/s3cret-token/todos").status_code == 200

    def test_non_ascii_guess_404s_not_500(self, anon_client, shell):
        _enable("s3cret-token")
        assert anon_client.get("/todo/ü").status_code == 404

    def test_guessing_is_rate_limited(self, anon_client, shell):
        _enable("s3cret-token")
        for _ in range(web_mod.guess_limiter.max_hits):
            assert anon_client.get("/todo/nope").status_code == 404
        assert anon_client.get("/todo/nope").status_code == 429
        # ...while the real link still works: valid requests never touch the
        # guess budget (the generous web_limiter is what bounds them).
        assert anon_client.get("/todo/s3cret-token").status_code == 200


class TestSettingsRoundTrip:
    """What the Settings → Todos toggles actually send.

    anon_client is requested first on purpose: it asserts no auth override is
    installed, and the `client` fixture installs one for the whole app.
    """

    def test_enable_with_secret(self, anon_client, client, shell):
        saved = client.put(
            "/api/setup/admin-settings",
            json={"todo_web_enabled": True, "todo_web_token": "from-settings"},
        ).json()
        assert saved["todo_web_enabled"] is True
        assert saved["todo_web_token"] == "from-settings"
        assert anon_client.get("/todo/from-settings").status_code == 200

    def test_disable_closes_the_door(self, anon_client, client, shell):
        client.put("/api/setup/admin-settings",
                   json={"todo_web_enabled": True, "todo_web_token": "x1"})
        client.put("/api/setup/admin-settings", json={"todo_web_enabled": False})
        assert anon_client.get("/todo/x1").status_code == 404
        assert anon_client.get("/api/todo-web/x1/todos").status_code == 404

    def test_truthy_non_bool_coerced(self, client):
        saved = client.put("/api/setup/admin-settings", json={"todo_web_enabled": "yes"}).json()
        assert saved["todo_web_enabled"] is True


class TestTokenClamping:
    def test_url_unsafe_characters_stripped(self):
        settings = admin.set_admin_setting("todo_web_token", "abc/../?&$" + "x" * 200)
        assert settings["todo_web_token"] == ("abcx" + "x" * 199)[:128]

    def test_reserved_page_slug_rejected(self):
        # /todo/next must stay the "next actions" page, never a secret link.
        assert admin.set_admin_setting("todo_web_token", "next")["todo_web_token"] == ""

    def test_non_string_becomes_empty(self):
        assert admin.set_admin_setting("todo_web_token", 12345)["todo_web_token"] == ""
