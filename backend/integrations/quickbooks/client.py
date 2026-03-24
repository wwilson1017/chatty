"""
Chatty — QuickBooks Online OAuth2 client.

Uses the QBO v3 REST API. Credentials stored in data/integrations/quickbooks.json.
Token refresh handled automatically.
"""

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

QBO_BASE_URL = "https://quickbooks.api.intuit.com/v3/company"
QBO_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth2.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_SCOPES = "com.intuit.quickbooks.accounting"


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

    def query(self, sql: str) -> list[dict]:
        """Run a QBO SQL-style query."""
        try:
            resp = httpx.get(
                f"{QBO_BASE_URL}/{self.company_id}/query",
                headers=self._headers(),
                params={"query": sql, "minorversion": "65"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            query_resp = data.get("QueryResponse", {})
            # Return the first non-empty list in the response
            for key, val in query_resp.items():
                if isinstance(val, list):
                    return val
            return []
        except Exception as e:
            logger.error("QBO query error: %s", e)
            return []

    def get_profit_and_loss(self, start_date: str, end_date: str) -> dict:
        """Fetch P&L report."""
        try:
            resp = httpx.get(
                f"{QBO_BASE_URL}/{self.company_id}/reports/ProfitAndLoss",
                headers=self._headers(),
                params={"start_date": start_date, "end_date": end_date, "minorversion": "65"},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("QBO P&L error: %s", e)
            return {"error": str(e)}


def get_client() -> QuickBooksClient | None:
    """Return a configured QBO client from stored credentials, or None."""
    from integrations.registry import get_credentials, is_enabled
    if not is_enabled("quickbooks"):
        return None
    creds = get_credentials("quickbooks")
    return QuickBooksClient(
        company_id=creds.get("company_id", ""),
        access_token=creds.get("access_token", ""),
        refresh_token=creds.get("refresh_token", ""),
        client_id=creds.get("client_id", ""),
        client_secret=creds.get("client_secret", ""),
        token_expires_at=float(creds.get("token_expires_at", 0)),
    )
