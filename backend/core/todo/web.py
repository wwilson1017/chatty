"""
Chatty — the no-login todo web app.

  GET /todo[/{token}][/...]        — serves the SPA shell in todo-only mode
  /api/todo-web[/{token}]/...      — the /api/todo endpoints, token-gated

Same trust model as /capture (core/todo/capture.py): no JWT by design, an
optional secret path token (admin setting todo_web_token) instead. The whole
surface is off until todo_web_enabled is turned on in Settings → Todos.
While a token is set, the bare /todo and /api/todo-web paths 404.

Unlike capture — which is write-only into the inbox — this exposes the full
todo store for reading and editing, so the settings UI defaults it to the
token'd URL and says plainly what the tokenless mode means.
"""

import hmac
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from core.admin_settings import load_admin_settings
from core.todo.ratelimit import IPRateLimiter
from core.todo.router import build_router

logger = logging.getLogger(__name__)
router = APIRouter()

# Generous: one todo page view is several API calls, and this is the owner's
# own phone hitting it. It only exists to cap outright flooding.
web_limiter = IPRateLimiter(window=300, max_hits=600)
# Strict, and burned only by *wrong* tokens, so guessing the secret costs 30
# tries per 5 minutes per IP while normal use never touches this budget.
guess_limiter = IPRateLimiter(window=300, max_hits=30)

# backend/core/todo/web.py → repo root → frontend/dist (same build main.py mounts).
_FRONTEND_INDEX = Path(__file__).resolve().parents[3] / "frontend" / "dist" / "index.html"

_UNBUILT_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Todos</title></head><body style="font-family:system-ui;background:#0A0C0F;color:#EDF0F4;padding:32px">
<p>Frontend build not found. Run <code>python run.py</code> (or <code>npm run build</code>
in <code>frontend/</code>) and reload.</p></body></html>"""

_index_cache: tuple[float, str] | None = None


def _settings() -> dict:
    return load_admin_settings()


def _enabled() -> bool:
    return bool(_settings().get("todo_web_enabled"))


def _configured_token() -> str:
    return _settings().get("todo_web_token", "") or ""


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_or_429(request: Request) -> None:
    if not web_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests — try again in a few minutes")


def _not_found() -> HTTPException:
    # Always 404, never 403: an unauthorized caller learns nothing about
    # whether the todo web app exists or what the token looks like.
    return HTTPException(status_code=404, detail="Not found")


def _match_token(token: str, request: Request) -> None:
    configured = _configured_token()
    # Compare as bytes: compare_digest raises TypeError on non-ASCII str,
    # which would turn a scanner's /todo/ü guess into a 500.
    if configured and hmac.compare_digest(token.encode(), configured.encode()):
        return
    if not guess_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests — try again in a few minutes")
    raise _not_found()


def _index_html() -> str:
    """Read the built SPA shell, cached on mtime."""
    global _index_cache
    try:
        mtime = _FRONTEND_INDEX.stat().st_mtime
    except OSError:
        return ""
    if _index_cache and _index_cache[0] == mtime:
        return _index_cache[1]
    html = _FRONTEND_INDEX.read_text(encoding="utf-8")
    _index_cache = (mtime, html)
    return html


def _page(base_path: str) -> HTMLResponse:
    """Serve the SPA with the todo-only mode and its router basename injected."""
    html = _index_html()
    if not html:
        return HTMLResponse(_UNBUILT_HTML, status_code=503)
    # base_path is either "/todo" or "/todo/<token>", both already restricted
    # to URL-safe characters, so it is safe inside a JSON string literal.
    inject = f'<script>window.__CHATTY_TODO_BASE__ = "{base_path}";</script>'
    if "</head>" in html:
        html = html.replace("</head>", f"  {inject}\n  </head>", 1)
    else:
        html = inject + html
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


# ── Page ──────────────────────────────────────────────────────────────────────

@router.get("/todo", response_class=HTMLResponse)
@router.get("/todo/{rest:path}", response_class=HTMLResponse)
async def todo_web_page(request: Request, rest: str = ""):
    """One handler for every in-app path so deep links and reloads work.

    In token mode the first path segment is the secret; everything after it
    is a client-side route the SPA resolves itself.
    """
    if not _enabled():
        raise _not_found()
    _rate_or_429(request)
    configured = _configured_token()
    if not configured:
        return _page("/todo")
    first = rest.split("/", 1)[0]
    _match_token(first, request)
    return _page(f"/todo/{configured}")


# ── API ───────────────────────────────────────────────────────────────────────

async def _public_api_guard(request: Request):
    if not _enabled() or _configured_token():
        raise _not_found()
    _rate_or_429(request)


async def _token_api_guard(token: str, request: Request):
    if not _enabled():
        raise _not_found()
    _rate_or_429(request)
    _match_token(token, request)


public_api_router = build_router(_public_api_guard)
token_api_router = build_router(_token_api_guard)
