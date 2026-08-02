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
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.admin_settings import load_admin_settings
from core.todo import service

logger = logging.getLogger(__name__)
router = APIRouter()

_RATE_WINDOW_SECONDS = 300
_RATE_MAX_POSTS = 30
_capture_posts: dict[str, list[float]] = defaultdict(list)


def _check_capture_rate(ip: str) -> bool:
    now = time.time()
    _capture_posts[ip] = [t for t in _capture_posts[ip] if now - t < _RATE_WINDOW_SECONDS]
    if len(_capture_posts[ip]) >= _RATE_MAX_POSTS:
        return False
    _capture_posts[ip].append(now)
    return True


def _configured_token() -> str:
    return load_admin_settings().get("todo_capture_token", "") or ""


_CAPTURE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Capture</title>
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


def _page(post_path: str) -> HTMLResponse:
    return HTMLResponse(_CAPTURE_HTML.replace("__POST_PATH__", post_path))


class CaptureBody(BaseModel):
    text: str = ""


def _do_capture(body: CaptureBody, request: Request) -> dict:
    ip = request.client.host if request.client else "unknown"
    if not _check_capture_rate(ip):
        raise HTTPException(status_code=429, detail="Too many captures — try again in a few minutes")
    try:
        todo = service.capture(body.text, source="capture_web")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "id": todo["id"]}


# ── Public mode (no token configured) ────────────────────────────────────────

@router.get("/capture", response_class=HTMLResponse)
async def capture_page():
    if _configured_token():
        raise HTTPException(status_code=404, detail="Not found")
    return _page("/api/capture")


@router.post("/api/capture")
async def capture_post(body: CaptureBody, request: Request):
    if _configured_token():
        raise HTTPException(status_code=404, detail="Not found")
    return _do_capture(body, request)


# ── Token mode ────────────────────────────────────────────────────────────────

def _require_token(token: str) -> str:
    configured = _configured_token()
    if not configured or not hmac.compare_digest(token, configured):
        raise HTTPException(status_code=404, detail="Not found")
    return configured


@router.get("/capture/{token}", response_class=HTMLResponse)
async def capture_page_token(token: str):
    configured = _require_token(token)
    return _page(f"/api/capture/{configured}")


@router.post("/api/capture/{token}")
async def capture_post_token(token: str, body: CaptureBody, request: Request):
    _require_token(token)
    return _do_capture(body, request)
