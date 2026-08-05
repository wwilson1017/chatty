"""
Chatty — public quick-capture endpoints.

GET  /capture[/{token}]      — self-contained, mobile-first HTML page
POST /api/capture[/{token}]  — {"text": ...} → inbox todo (deterministic, no AI)

No JWT by design: this is the phone-bookmark capture path. An optional
secret (admin setting todo_capture_token) switches the URLs from public
/capture to /capture/{token}; while a token is set, the bare paths 404.
Per-IP rate limiting guards the POST endpoints (login-limiter pattern).
"""

import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from core.admin_settings import load_admin_settings
from core.todo import service
from core.todo.ratelimit import IPRateLimiter

logger = logging.getLogger(__name__)
router = APIRouter()

capture_limiter = IPRateLimiter(window=300, max_hits=30)


def _configured_token() -> str:
    return load_admin_settings().get("todo_capture_token", "") or ""


_CAPTURE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Capture</title>
<link rel="manifest" href="__BASE_PATH__/manifest.webmanifest">
<link rel="apple-touch-icon" href="/capture-apple-touch-icon.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Capture">
<meta name="theme-color" content="#0A0C0F">
<style>
  * { box-sizing: border-box; margin: 0; }
  body {
    background: #0A0C0F; color: #EDF0F4; min-height: 100dvh;
    font-family: 'Inter Tight', 'Inter', system-ui, sans-serif;
    display: flex; flex-direction: column; align-items: center;
    padding: max(24px, env(safe-area-inset-top)) 16px 24px;
  }
  main { width: 100%; max-width: 560px; display: flex; flex-direction: column; gap: 12px; }
  h1 { font-size: 18px; font-weight: 600; letter-spacing: 0.3px; }
  h1 span { color: #6B7280; font-weight: 400; font-size: 13px; margin-left: 8px; }
  textarea {
    width: 100%; min-height: 140px; resize: vertical;
    background: #12151B; color: #EDF0F4; border: 1px solid #262B36;
    border-radius: 10px; padding: 14px; font: inherit; font-size: 16px;
  }
  textarea:focus { outline: none; border-color: #4B5563; }
  button {
    background: #EDF0F4; color: #0A0C0F; border: 0; border-radius: 10px;
    padding: 14px; font: inherit; font-size: 16px; font-weight: 600; cursor: pointer;
  }
  button:disabled { opacity: 0.5; }
  #msg { min-height: 22px; font-size: 14px; text-align: center; }
  #msg.ok { color: #7BC47F; }
  #msg.err { color: #E9806E; }
</style>
</head>
<body>
<main>
  <h1>Capture<span>straight to your inbox</span></h1>
  <textarea id="t" autofocus placeholder="What's on your mind?"></textarea>
  <button id="b">Send</button>
  <div id="msg"></div>
</main>
<script>
  var t = document.getElementById('t'), b = document.getElementById('b'), m = document.getElementById('msg');
  function send() {
    var text = t.value.trim();
    if (!text) { t.focus(); return; }
    b.disabled = true;
    fetch('__POST_PATH__', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    }).then(function (r) {
      if (r.ok) {
        t.value = '';
        m.className = 'ok';
        m.textContent = 'captured \\u2713';
        setTimeout(function () { m.textContent = ''; }, 2500);
      } else {
        return r.json().catch(function () { return {}; }).then(function (d) {
          m.className = 'err';
          m.textContent = d.detail || ('failed (' + r.status + ') \\u2014 try again');
        });
      }
    }).catch(function () {
      m.className = 'err';
      m.textContent = 'network error \\u2014 try again';
    }).finally(function () {
      b.disabled = false;
      t.focus();
    });
  }
  b.addEventListener('click', send);
  t.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') send();
  });
</script>
</body>
</html>"""


def _page(post_path: str, base_path: str) -> HTMLResponse:
    html = _CAPTURE_HTML.replace("__POST_PATH__", post_path).replace("__BASE_PATH__", base_path)
    return HTMLResponse(html)


def _manifest(base_path: str) -> Response:
    """Web app manifest so Add to Home Screen installs Capture as a
    standalone app. start_url carries the secret path when one is set —
    which is also why the response is no-store (see core/todo/web.py)."""
    manifest = {
        "name": "Capture",
        "short_name": "Capture",
        "description": "Quick capture to your Chatty todo inbox",
        "start_url": base_path,
        "scope": base_path,
        "display": "standalone",
        "background_color": "#0A0C0F",
        "theme_color": "#0A0C0F",
        "icons": [
            {"src": "/capture-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/capture-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    return Response(
        json.dumps(manifest),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


# Bounds request processing before JSON parsing (the 20k-char cap in the
# service runs only after the body is materialized). 64 KiB fits any legal
# capture with UTF-8 + JSON-escaping headroom.
_MAX_BODY_BYTES = 64 * 1024


def _rate_or_429(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    if not capture_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Too many captures — try again in a few minutes")


async def _read_capture_text(request: Request) -> str:
    """Parse {"text": ...} manually so the size cap applies before parsing."""
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if declared > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Capture body too large")
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Capture body too large")
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    text = data.get("text", "") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string")
    return text


def _do_capture(text: str) -> dict:
    try:
        todo = service.capture(text, source="capture_web")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "id": todo["id"]}


# ── Public mode (no token configured) ────────────────────────────────────────

@router.get("/capture", response_class=HTMLResponse)
async def capture_page():
    if _configured_token():
        raise HTTPException(status_code=404, detail="Not found")
    return _page("/api/capture", "/capture")


# Registered before /capture/{token} so this path is never read as a token
# guess. No ambiguity either way: the token clamp strips dots, so a token can
# never literally be "manifest.webmanifest".
@router.get("/capture/manifest.webmanifest")
async def capture_manifest():
    if _configured_token():
        raise HTTPException(status_code=404, detail="Not found")
    return _manifest("/capture")


@router.post("/api/capture")
async def capture_post(request: Request):
    if _configured_token():
        raise HTTPException(status_code=404, detail="Not found")
    _rate_or_429(request)
    return _do_capture(await _read_capture_text(request))


# ── Token mode ────────────────────────────────────────────────────────────────

def _require_token(token: str) -> str:
    configured = _configured_token()
    # Compare as bytes: compare_digest raises TypeError on non-ASCII str
    # input, which would turn a scanner's /capture/ü guess into a 500.
    if not configured or not hmac.compare_digest(token.encode(), configured.encode()):
        raise HTTPException(status_code=404, detail="Not found")
    return configured


@router.get("/capture/{token}", response_class=HTMLResponse)
async def capture_page_token(token: str, request: Request):
    # Rate-check BEFORE the token comparison: failed guesses must burn the
    # same per-IP budget as captures, or the secret is brute-forceable at
    # line speed (the 404 itself reveals nothing).
    _rate_or_429(request)
    configured = _require_token(token)
    return _page(f"/api/capture/{configured}", f"/capture/{configured}")


@router.get("/capture/{token}/manifest.webmanifest")
async def capture_manifest_token(token: str, request: Request):
    # Same order as the page: burn the rate budget before the comparison so
    # manifest probes can't brute-force the token any faster than page loads.
    _rate_or_429(request)
    configured = _require_token(token)
    return _manifest(f"/capture/{configured}")


@router.post("/api/capture/{token}")
async def capture_post_token(token: str, request: Request):
    _rate_or_429(request)
    _require_token(token)
    return _do_capture(await _read_capture_text(request))
