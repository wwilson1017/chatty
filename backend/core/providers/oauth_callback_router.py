"""
Chatty — Shared OAuth callback endpoint.

Handles the browser redirect from Google / Intuit / OpenAI after the user
authorizes. Exchanges the authorization code for tokens server-side, then
stashes them on an OAuthFlow object keyed by state/flow_id. The frontend
polls `/api/oauth/flows/{flow_id}/status` to know when to proceed.

This replaces the old localhost:9876 HTTP server pattern so OAuth works
on cloud deployments (Railway) as well as local dev.
"""

import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from core.auth import get_current_user
from .oauth import complete_oauth_flow, get_flow_status

logger = logging.getLogger(__name__)
router = APIRouter()


# ── HTML shown in the popup after OAuth completes ────────────────────────────

_CALLBACK_OK_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Connected — Chatty</title>
  <style>
    html, body { margin: 0; height: 100%; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a; color: #f1f5f9;
      display: flex; align-items: center; justify-content: center;
    }
    .card { text-align: center; padding: 2rem; max-width: 420px; }
    h1 { color: #4ade80; font-weight: 600; font-size: 1.5rem; margin: 0 0 0.75rem; }
    p { color: #cbd5e1; font-size: 0.95rem; margin: 0.25rem 0; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Connected</h1>
    <p>You can close this window and return to Chatty.</p>
  </div>
  <script>setTimeout(function () { try { window.close(); } catch (e) {} }, 800);</script>
</body>
</html>
"""

_CALLBACK_ERROR_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Connection failed — Chatty</title>
  <style>
    html, body {{ margin: 0; height: 100%; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a; color: #f1f5f9;
      display: flex; align-items: center; justify-content: center;
    }}
    .card {{ text-align: center; padding: 2rem; max-width: 480px; }}
    h1 {{ color: #ef4444; font-weight: 600; font-size: 1.5rem; margin: 0 0 0.75rem; }}
    p {{ color: #cbd5e1; font-size: 0.95rem; margin: 0.25rem 0; }}
    code {{
      display: inline-block; background: #1e293b; padding: 0.25rem 0.5rem;
      border-radius: 0.25rem; font-size: 0.85rem; color: #fbbf24;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Connection failed</h1>
    <p>{error}</p>
    <p>You can close this window and try again in Chatty.</p>
  </div>
</body>
</html>
"""


def _render_error(message: str, status_code: int = 400) -> HTMLResponse:
    # Full HTML escape (incl. single-quote) — error_description is provider-controlled
    safe = html.escape(message, quote=True)
    return HTMLResponse(_CALLBACK_ERROR_HTML.format(error=safe), status_code=status_code)


# ── Callback endpoint (unauthenticated — providers redirect here) ────────────

@router.get("/callback")
async def oauth_callback(request: Request):
    """OAuth callback endpoint hit by Google / Intuit / OpenAI.

    This is intentionally unauthenticated — the user's browser is redirected
    here by the OAuth provider without any Chatty JWT.
    """
    params = dict(request.query_params)
    code = params.pop("code", "")
    state = params.pop("state", "")
    error = params.pop("error", "")
    error_description = params.pop("error_description", "")

    if error:
        logger.info("OAuth callback error: %s (%s)", error, error_description)
        return _render_error(error_description or error, status_code=400)

    if not code or not state:
        return _render_error("Missing code or state in OAuth callback", status_code=400)

    try:
        await complete_oauth_flow(code=code, state=state, callback_params=params)
    except ValueError as e:
        return _render_error(str(e), status_code=400)
    except Exception as e:
        logger.error("OAuth callback token exchange failed: %s", e)
        return _render_error("Token exchange failed. Please try again.", status_code=500)

    return HTMLResponse(_CALLBACK_OK_HTML)


# ── Status polling (authenticated — frontend polls this) ─────────────────────

@router.get("/flows/{flow_id}/status")
async def flow_status(flow_id: str, user=Depends(get_current_user)):
    """Poll the status of an in-flight OAuth flow.

    Returns one of:
      { status: "pending" } — waiting on user to authorize
      { status: "ok" } — callback completed; frontend should now call
          the integration-specific /setup/complete endpoint with {flow_id}
      { status: "error", error: "..." } — flow failed
      HTTP 404 — flow not found or expired
    """
    status = get_flow_status(flow_id)
    if status["status"] == "not_found":
        raise HTTPException(status_code=404, detail="OAuth flow not found or expired")
    return status
