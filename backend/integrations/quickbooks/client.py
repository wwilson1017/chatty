"""
Chatty — QuickBooks Online OAuth2 client.

Uses the QBO v3 REST API. Credentials stored in data/integrations/quickbooks.json.
Token refresh handled automatically. Logs intuit_tid on every response for debugging.
"""

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

QBO_BASE_URL = os.getenv(
    "QUICKBOOKS_API_BASE_URL",
    "https://quickbooks.api.intuit.com/v3/company",
)
QBO_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_SCOPES = "com.intuit.quickbooks.accounting"
QBO_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"

MAX_RETRIES = 3


class QuickBooksAuthError(Exception):
    """Raised when QBO auth is irrecoverably broken (refresh token expired/revoked)."""


class QuickBooksClient:
    """Client for QuickBooks Online v3 REST API."""

    def __init__(self, company_id: str, access_token: str, refresh_token: str,
                 client_id: str, client_secret: str, token_expires_at: float = 0):
        self.company_id = company_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_expires_at = token_expires_at

    def _headers(self) -> dict:
        self._maybe_refresh()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _maybe_refresh(self) -> None:
        """Refresh access token if expired or close to expiry."""
        if self.token_expires_at and time.time() > self.token_expires_at - 60:
            try:
                resp = httpx.post(
                    QBO_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    },
                    auth=(self.client_id, self.client_secret),
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data["access_token"]
                self.refresh_token = data.get("refresh_token", self.refresh_token)
                self.token_expires_at = time.time() + data.get("expires_in", 3600)
                self._persist_tokens()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (400, 401):
                    logger.error("QBO token refresh rejected (status %d) — marking connection broken", e.response.status_code)
                    self._mark_broken()
                    raise QuickBooksAuthError("QuickBooks connection expired. Please reconnect.")
                logger.warning("QBO token refresh failed: %s", e)
            except Exception as e:
                logger.warning("QBO token refresh failed: %s", e)

    def _persist_tokens(self) -> None:
        from integrations.registry import get_credentials, save_credentials
        creds = get_credentials("quickbooks")
        creds.update({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.token_expires_at,
        })
        save_credentials("quickbooks", creds)

    def _mark_broken(self) -> None:
        """Mark the QuickBooks connection as broken in stored credentials."""
        from integrations.registry import get_credentials, save_credentials
        creds = get_credentials("quickbooks")
        creds["connection_status"] = "broken"
        save_credentials("quickbooks", creds)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute an HTTP request with intuit_tid logging, rate-limit retry, and 401 detection."""
        kwargs.setdefault("timeout", 15)
        kwargs.setdefault("headers", self._headers())

        for attempt in range(MAX_RETRIES + 1):
            resp = httpx.request(method, url, **kwargs)
            tid = resp.headers.get("intuit_tid", "none")

            if resp.status_code == 429 and attempt < MAX_RETRIES:
                retry_after = int(resp.headers.get("Retry-After", str(2 ** attempt)))
                logger.warning("QBO 429 rate limited (intuit_tid=%s), retrying in %ds", tid, retry_after)
                time.sleep(retry_after)
                continue

            logger.info("QBO %s %s → %d (intuit_tid=%s)", method, url.split("/v3/")[-1], resp.status_code, tid)

            if resp.status_code == 401:
                logger.error("QBO 401 Unauthorized (intuit_tid=%s) — marking connection broken", tid)
                self._mark_broken()
                raise QuickBooksAuthError("QuickBooks connection expired. Please reconnect.")

            resp.raise_for_status()
            return resp

        # Final attempt exhausted (all 429s)
        resp.raise_for_status()
        return resp

    def query(self, sql: str) -> list[dict]:
        """Run a QBO SQL-style query."""
        try:
            resp = self._request(
                "GET",
                f"{QBO_BASE_URL}/{self.company_id}/query",
                params={"query": sql, "minorversion": "65"},
            )
            data = resp.json()
            query_resp = data.get("QueryResponse", {})
            for key, val in query_resp.items():
                if isinstance(val, list):
                    return val
            return []
        except QuickBooksAuthError:
            return [{"error": "QuickBooks connection needs to be reconnected", "needs_reconnect": True}]
        except Exception as e:
            logger.error("QBO query error: %s", e)
            return [{"error": str(e)}]

    def get_profit_and_loss(self, start_date: str, end_date: str) -> dict:
        """Fetch P&L report."""
        try:
            resp = self._request(
                "GET",
                f"{QBO_BASE_URL}/{self.company_id}/reports/ProfitAndLoss",
                params={"start_date": start_date, "end_date": end_date, "minorversion": "65"},
            )
            return resp.json()
        except QuickBooksAuthError:
            return {"error": "QuickBooks connection needs to be reconnected", "needs_reconnect": True}
        except Exception as e:
            logger.error("QBO P&L error: %s", e)
            return {"error": str(e)}

    def get_balance_sheet(self, start_date: str, end_date: str) -> dict:
        """Fetch Balance Sheet report."""
        try:
            resp = httpx.get(
                f"{QBO_BASE_URL}/{self.company_id}/reports/BalanceSheet",
                headers=self._headers(),
                params={"start_date": start_date, "end_date": end_date, "minorversion": "65"},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("QBO Balance Sheet error: %s", e)
            return {"error": str(e)}

    # ── Entity CRUD methods ──────────────────────────────────────────────────

    def _entity_url(self, entity_type: str, entity_id: str = "") -> str:
        """Build QBO API URL for an entity type."""
        path = entity_type.lower()
        base = f"{QBO_BASE_URL}/{self.company_id}/{path}"
        if entity_id:
            base = f"{base}/{entity_id}"
        return base

    def get_entity(self, entity_type: str, entity_id: str) -> dict:
        """Fetch a single entity by type and ID."""
        try:
            resp = httpx.get(
                self._entity_url(entity_type, entity_id),
                headers=self._headers(),
                params={"minorversion": "65"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            # QBO nests the entity under its PascalCase type name
            return data.get(entity_type, data)
        except Exception as e:
            logger.error("QBO get %s/%s error: %s", entity_type, entity_id, e)
            return {"error": str(e)}

    def create_entity(self, entity_type: str, data: dict) -> dict:
        """Create a new entity. Returns the created entity dict."""
        try:
            resp = httpx.post(
                self._entity_url(entity_type),
                headers=self._headers(),
                params={"minorversion": "65"},
                json=data,
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get(entity_type, result)
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error("QBO create %s failed (%s): %s", entity_type, e.response.status_code, body)
            return {"error": f"QBO API error {e.response.status_code}: {body}"}
        except Exception as e:
            logger.error("QBO create %s error: %s", entity_type, e)
            return {"error": str(e)}

    def update_entity(self, entity_type: str, data: dict) -> dict:
        """Update an existing entity. data must include Id and SyncToken."""
        try:
            resp = httpx.post(
                self._entity_url(entity_type),
                headers=self._headers(),
                params={"minorversion": "65"},
                json=data,
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get(entity_type, result)
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error("QBO update %s failed (%s): %s", entity_type, e.response.status_code, body)
            return {"error": f"QBO API error {e.response.status_code}: {body}"}
        except Exception as e:
            logger.error("QBO update %s error: %s", entity_type, e)
            return {"error": str(e)}

    def void_entity(self, entity_type: str, entity_id: str, sync_token: str) -> dict:
        """Void an entity (e.g. Invoice). Sets balance to zero without deleting."""
        try:
            resp = httpx.post(
                self._entity_url(entity_type),
                headers=self._headers(),
                params={"operation": "void", "minorversion": "65"},
                json={"Id": entity_id, "SyncToken": sync_token, "sparse": True},
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get(entity_type, result)
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error("QBO void %s/%s failed (%s): %s", entity_type, entity_id, e.response.status_code, body)
            return {"error": f"QBO API error {e.response.status_code}: {body}"}
        except Exception as e:
            logger.error("QBO void %s/%s error: %s", entity_type, entity_id, e)
            return {"error": str(e)}

    def send_entity(self, entity_type: str, entity_id: str, email: str | None = None) -> dict:
        """Email an entity (Invoice or Estimate) to the customer."""
        try:
            params: dict[str, str] = {"minorversion": "65"}
            if email:
                params["sendTo"] = email
            resp = httpx.post(
                f"{self._entity_url(entity_type, entity_id)}/send",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get(entity_type, result)
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error("QBO send %s/%s failed (%s): %s", entity_type, entity_id, e.response.status_code, body)
            return {"error": f"QBO API error {e.response.status_code}: {body}"}
        except Exception as e:
            logger.error("QBO send %s/%s error: %s", entity_type, entity_id, e)
            return {"error": str(e)}

    def _fetch_sync_token(self, entity_type: str, entity_id: str) -> tuple[dict, str] | None:
        """Fetch an entity and return (full_entity, sync_token), or None if not found."""
        entity = self.get_entity(entity_type, entity_id)
        if not entity or "error" in entity:
            return None
        sync_token = entity.get("SyncToken", "0")
        return entity, sync_token


def get_client() -> QuickBooksClient | None:
    """Return a configured QBO client from stored credentials, or None."""
    from integrations.registry import get_credentials, is_enabled
    from core.config import settings
    if not is_enabled("quickbooks"):
        return None
    creds = get_credentials("quickbooks")
    return QuickBooksClient(
        company_id=creds.get("company_id", ""),
        access_token=creds.get("access_token", ""),
        refresh_token=creds.get("refresh_token", ""),
        client_id=settings.quickbooks_oauth.client_id,
        client_secret=settings.quickbooks_oauth.client_secret,
        token_expires_at=float(creds.get("token_expires_at", 0)),
    )
