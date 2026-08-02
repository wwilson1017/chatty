"""Tests for the public /capture page and POST /api/capture endpoints."""

import pytest

import core.admin_settings as admin
import core.todo.capture as capture_mod


@pytest.fixture(autouse=True)
def clean_rate_buckets():
    """The per-IP rate buckets are module-global; TestClient always presents
    the same IP, so leftover state would bleed 429s across tests."""
    capture_mod._capture_posts.clear()
    yield
    capture_mod._capture_posts.clear()


def _set_token(token: str) -> None:
    admin.set_admin_setting("todo_capture_token", token)


class TestPublicMode:
    def test_page_served(self, anon_client):
        r = anon_client.get("/capture")
        assert r.status_code == 200
        assert "<textarea" in r.text
        assert "'/api/capture'" in r.text

    def test_token_paths_404(self, anon_client):
        assert anon_client.get("/capture/whatever").status_code == 404
        assert anon_client.post("/api/capture/whatever", json={"text": "x"}).status_code == 404

    def test_post_lands_in_inbox(self, anon_client, client):
        r = anon_client.post("/api/capture", json={"text": "  buy milk  "})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        todo = client.get(f"/api/todo/todos/{body['id']}").json()
        assert todo["title"] == "buy milk"
        assert todo["status"] == "inbox"
        assert todo["source"] == "capture_web"

    def test_empty_400(self, anon_client):
        assert anon_client.post("/api/capture", json={"text": "   "}).status_code == 400

    def test_oversize_400(self, anon_client):
        assert anon_client.post("/api/capture", json={"text": "x" * 20_001}).status_code == 400

    def test_huge_body_413_before_parsing(self, anon_client):
        r = anon_client.post("/api/capture", json={"text": "x" * 70_000})
        assert r.status_code == 413

    def test_non_string_text_400(self, anon_client):
        assert anon_client.post("/api/capture", json={"text": 123}).status_code == 400
        assert anon_client.post("/api/capture", json=["not", "a", "dict"]).status_code == 400


class TestTokenMode:
    def test_matrix(self, anon_client):
        _set_token("s3cret-token")
        # Bare paths go dark
        assert anon_client.get("/capture").status_code == 404
        assert anon_client.post("/api/capture", json={"text": "x"}).status_code == 404
        # Wrong token 404s
        assert anon_client.get("/capture/wrong").status_code == 404
        assert anon_client.post("/api/capture/wrong", json={"text": "x"}).status_code == 404
        # Right token works
        page = anon_client.get("/capture/s3cret-token")
        assert page.status_code == 200
        assert "'/api/capture/s3cret-token'" in page.text
        assert anon_client.post("/api/capture/s3cret-token", json={"text": "x"}).status_code == 200

    def test_untokenize_restores_public(self, anon_client):
        _set_token("s3cret-token")
        _set_token("")
        assert anon_client.get("/capture").status_code == 200
        assert anon_client.get("/capture/s3cret-token").status_code == 404


class TestRateLimit:
    def test_429_after_limit(self, anon_client, monkeypatch):
        monkeypatch.setattr(capture_mod, "_RATE_MAX_POSTS", 3)
        for i in range(3):
            assert anon_client.post("/api/capture", json={"text": f"item {i}"}).status_code == 200
        assert anon_client.post("/api/capture", json={"text": "over"}).status_code == 429

    def test_wrong_token_guesses_burn_the_rate_budget(self, anon_client, monkeypatch):
        # Brute-forcing the secret must be throttled: failed guesses hit the
        # same per-IP budget as captures (404s until the cap, then 429).
        monkeypatch.setattr(capture_mod, "_RATE_MAX_POSTS", 3)
        _set_token("s3cret-token")
        for i in range(3):
            assert anon_client.post(f"/api/capture/guess{i}", json={"text": "x"}).status_code == 404
        assert anon_client.post("/api/capture/guess3", json={"text": "x"}).status_code == 429
        assert anon_client.get("/capture/guess4").status_code == 429
