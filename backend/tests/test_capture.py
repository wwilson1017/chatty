"""Tests for the public /capture page and POST /api/capture endpoints."""

import pytest

import core.admin_settings as admin
import core.todo.capture as capture_mod


@pytest.fixture(autouse=True)
def clean_rate_buckets():
    """The per-IP rate buckets are module-global; TestClient always presents
    the same IP, so leftover state would bleed 429s across tests."""
    capture_mod.capture_limiter.clear()
    yield
    capture_mod.capture_limiter.clear()


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

    def test_non_ascii_token_guess_is_404_not_500(self, anon_client):
        # compare_digest raises TypeError on non-ASCII str input — must not 500.
        _set_token("s3cret-token")
        assert anon_client.get("/capture/%C3%BC").status_code == 404
        assert anon_client.post("/api/capture/%C3%BC", json={"text": "x"}).status_code == 404


class TestManifest:
    def test_public_manifest(self, anon_client):
        r = anon_client.get("/capture/manifest.webmanifest")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/manifest+json")
        assert r.headers["cache-control"] == "no-store"
        m = r.json()
        assert m["start_url"] == "/capture"
        assert m["display"] == "standalone"
        assert all(i["src"].startswith("/capture-icon-") for i in m["icons"])

    def test_token_matrix(self, anon_client):
        _set_token("s3cret-token")
        # Bare and wrong-token manifest paths go dark like the page
        assert anon_client.get("/capture/manifest.webmanifest").status_code == 404
        assert anon_client.get("/capture/wrong/manifest.webmanifest").status_code == 404
        r = anon_client.get("/capture/s3cret-token/manifest.webmanifest")
        assert r.status_code == 200
        assert r.json()["start_url"] == "/capture/s3cret-token"
        assert r.json()["scope"] == "/capture/s3cret-token"

    def test_page_declares_manifest(self, anon_client):
        r = anon_client.get("/capture")
        # The tokened variant embeds the secret POST path, so the page must
        # carry the same no-store/noindex headers as the todo web app.
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-robots-tag"] == "noindex, nofollow"
        html = r.text
        assert 'rel="manifest" href="/capture/manifest.webmanifest"' in html
        assert "apple-mobile-web-app-capable" in html
        assert "capture-apple-touch-icon.png" in html
        _set_token("s3cret-token")
        html = anon_client.get("/capture/s3cret-token").text
        assert 'rel="manifest" href="/capture/s3cret-token/manifest.webmanifest"' in html

    def test_wrong_manifest_guess_burns_rate_budget(self, anon_client, monkeypatch):
        _set_token("s3cret-token")
        monkeypatch.setattr(capture_mod.capture_limiter, "max_hits", 3)
        for _ in range(3):
            assert anon_client.get("/capture/wrong/manifest.webmanifest").status_code == 404
        assert anon_client.get("/capture/wrong/manifest.webmanifest").status_code == 429


class TestRateLimit:
    def test_429_after_limit(self, anon_client, monkeypatch):
        monkeypatch.setattr(capture_mod.capture_limiter, "max_hits", 3)
        for i in range(3):
            assert anon_client.post("/api/capture", json={"text": f"item {i}"}).status_code == 200
        assert anon_client.post("/api/capture", json={"text": "over"}).status_code == 429

    def test_wrong_token_guesses_burn_the_rate_budget(self, anon_client, monkeypatch):
        # Brute-forcing the secret must be throttled: failed guesses hit the
        # same per-IP budget as captures (404s until the cap, then 429).
        monkeypatch.setattr(capture_mod.capture_limiter, "max_hits", 3)
        _set_token("s3cret-token")
        for i in range(3):
            assert anon_client.post(f"/api/capture/guess{i}", json={"text": "x"}).status_code == 404
        assert anon_client.post("/api/capture/guess3", json={"text": "x"}).status_code == 429
        assert anon_client.get("/capture/guess4").status_code == 429
