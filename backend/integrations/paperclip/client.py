"""Chatty — Paperclip REST API client.

Wraps Paperclip's REST API for issue management, agent listing, and
company validation.  Credentials stored in data/integrations/paperclip.json.

Auth: Paperclip uses Better Auth session cookies. The client logs in with
email/password, gets a session token, and sends it as a cookie on all requests.
"""

import logging
from contextvars import ContextVar
from typing import Any

import httpx

logger = logging.getLogger(__name__)

paperclip_run_ctx: ContextVar[dict] = ContextVar("paperclip_run_ctx", default={})

TIMEOUT = 30


def login(base_url: str, email: str, password: str) -> dict:
    """Login to Paperclip via Better Auth. Returns session info or error."""
    base_url = base_url.rstrip("/")
    try:
        resp = httpx.post(
            f"{base_url}/api/auth/sign-in/email",
            json={"email": email, "password": password},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        session_cookie = None
        for name, value in resp.cookies.items():
            if "session_token" in name:
                session_cookie = f"{name}={value}"
                break

        if not session_cookie:
            cookie_header = resp.headers.get("set-cookie", "")
            for part in cookie_header.split(","):
                part = part.strip()
                if "session_token" in part:
                    session_cookie = part.split(";")[0]
                    break

        if not session_cookie:
            return {"error": "Login succeeded but no session cookie returned"}

        companies = httpx.get(
            f"{base_url}/api/companies",
            headers={"Cookie": session_cookie},
            timeout=TIMEOUT,
        )
        company_list = companies.json() if companies.status_code == 200 else []
        if isinstance(company_list, dict):
            company_list = company_list.get("companies", [])

        return {
            "ok": True,
            "session_cookie": session_cookie,
            "user": data.get("user", {}),
            "companies": company_list,
        }
    except httpx.HTTPStatusError as e:
        body = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        msg = body.get("message", e.response.text[:200])
        return {"error": f"Login failed: {msg}"}
    except Exception as e:
        return {"error": f"Cannot reach Paperclip: {e}"}


class PaperclipClient:
    """Client for Paperclip's REST API."""

    def __init__(self, base_url: str, company_id: str, session_cookie: str = ""):
        self.base_url = base_url.rstrip("/")
        self.company_id = company_id
        self.session_cookie = session_cookie

    def _headers(self, mutating: bool = False) -> dict:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
        if mutating:
            headers["Content-Type"] = "application/json"
            ctx = paperclip_run_ctx.get()
            if ctx.get("run_id"):
                headers["X-Paperclip-Run-Id"] = ctx["run_id"]
        return headers

    # ── Company ──────────────────────────────────────────────────────────

    def get_company(self) -> dict:
        try:
            resp = httpx.get(
                f"{self.base_url}/api/companies/{self.company_id}",
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Issues ───────────────────────────────────────────────────────────

    def list_issues(
        self,
        status: str | None = None,
        assignee_agent_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if assignee_agent_id:
            params["assigneeAgentId"] = assignee_agent_id
        try:
            resp = httpx.get(
                f"{self.base_url}/api/companies/{self.company_id}/issues",
                headers=self._headers(),
                params=params,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            issues = data if isinstance(data, list) else data.get("issues", data)
            return {"ok": True, "issues": issues}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_issue(self, issue_id: str) -> dict:
        try:
            resp = httpx.get(
                f"{self.base_url}/api/issues/{issue_id}",
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            issue = resp.json()

            comments_resp = httpx.get(
                f"{self.base_url}/api/issues/{issue_id}/comments",
                headers=self._headers(),
                params={"limit": 20, "order": "desc"},
                timeout=TIMEOUT,
            )
            comments = []
            if comments_resp.status_code == 200:
                cdata = comments_resp.json()
                comments = cdata if isinstance(cdata, list) else cdata.get("comments", [])

            return {"ok": True, "issue": issue, "comments": comments}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def checkout_issue(
        self,
        issue_id: str,
        agent_id: str,
        expected_statuses: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"agentId": agent_id}
        if expected_statuses:
            body["expectedStatuses"] = expected_statuses
        else:
            body["expectedStatuses"] = ["backlog", "todo"]
        try:
            resp = httpx.post(
                f"{self.base_url}/api/issues/{issue_id}/checkout",
                headers=self._headers(mutating=True),
                json=body,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return {"ok": True, "issue": resp.json()}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def update_issue(self, issue_id: str, updates: dict) -> dict:
        try:
            resp = httpx.patch(
                f"{self.base_url}/api/issues/{issue_id}",
                headers=self._headers(mutating=True),
                json=updates,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return {"ok": True, "issue": resp.json()}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def add_comment(self, issue_id: str, body: str) -> dict:
        try:
            resp = httpx.post(
                f"{self.base_url}/api/issues/{issue_id}/comments",
                headers=self._headers(mutating=True),
                json={"body": body},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return {"ok": True, "comment": resp.json()}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Agents ───────────────────────────────────────────────────────────

    def list_agents(self) -> dict:
        try:
            resp = httpx.get(
                f"{self.base_url}/api/companies/{self.company_id}/agents",
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            agents = data if isinstance(data, list) else data.get("agents", data)
            return {"ok": True, "agents": agents}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def update_agent(self, agent_id: str, updates: dict) -> dict:
        headers = self._headers(mutating=True)
        headers["Origin"] = self.base_url
        headers["Referer"] = f"{self.base_url}/"
        try:
            resp = httpx.patch(
                f"{self.base_url}/api/agents/{agent_id}",
                headers=headers,
                json=updates,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return {"ok": True, "agent": resp.json()}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def configure_agent_webhook(self, agent_id: str, webhook_url: str, webhook_secret: str) -> dict:
        """Switch an agent to HTTP adapter with the Chatty webhook URL and secret."""
        return self.update_agent(agent_id, {
            "adapterType": "http",
            "adapterConfig": {
                "url": webhook_url,
                "method": "POST",
                "timeoutMs": 120000,
                "headers": {"X-Webhook-Secret": webhook_secret},
            },
        })


def get_client() -> PaperclipClient | None:
    """Return a configured client from stored credentials, or None."""
    from integrations.registry import get_credentials, is_enabled

    if not is_enabled("paperclip"):
        return None
    creds = get_credentials("paperclip")
    if not creds.get("url") or not creds.get("company_id"):
        return None
    return PaperclipClient(
        base_url=creds["url"],
        company_id=creds["company_id"],
        session_cookie=creds.get("session_cookie", ""),
    )
