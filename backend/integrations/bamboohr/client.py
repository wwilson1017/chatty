"""
Chatty — BambooHR REST API client.

Adapted from CAKE OS core/bamboohr.py.
Credentials loaded from data/integrations/bamboohr.json.
"""

import logging
import re

import httpx

logger = logging.getLogger(__name__)


class BambooHRClient:
    """Client for BambooHR REST API."""

    def __init__(self, api_key: str, subdomain: str):
        self.api_key = api_key
        self.subdomain = subdomain
        self.base_url = f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1"
        self._auth = (api_key, "x")

    def test_connection(self) -> bool:
        try:
            resp = httpx.get(
                f"{self.base_url}/employees/directory",
                auth=self._auth,
                headers={"Accept": "application/json"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("BambooHR connection error: %s", e)
            return False

    def get_employee_directory(self) -> list[dict]:
        """Get the full employee directory."""
        try:
            resp = httpx.get(
                f"{self.base_url}/employees/directory",
                auth=self._auth,
                headers={"Accept": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("employees", [])
            return []
        except Exception as e:
            logger.error("BambooHR employee directory error: %s", e)
            return []

    def get_employee(self, employee_id: str, fields: list[str] | None = None) -> dict:
        """Get an employee record."""
        fields = fields or ["firstName", "lastName", "jobTitle", "department", "workEmail", "mobilePhone"]
        try:
            resp = httpx.get(
                f"{self.base_url}/employees/{employee_id}",
                auth=self._auth,
                headers={"Accept": "application/json"},
                params={"fields": ",".join(fields)},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error("BambooHR get_employee error: %s", e)
            return {"error": str(e)}

    def api_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        timeout: int = 30,
    ) -> dict:
        """Execute an arbitrary BambooHR API request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: API path (e.g. "/api/v1/time_off/whos_out").
                  The /api/v1 prefix is mapped to the client's base URL.
            params: Query parameters.
            body: JSON request body (for POST/PUT/PATCH).
            timeout: Request timeout in seconds.

        Returns:
            Dict with 'ok' (bool), 'status_code' (int), and 'data' (parsed JSON or raw text).
        """
        method = method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            return {"ok": False, "status_code": 0, "data": f"Invalid HTTP method: {method}"}

        # Map OpenAPI spec paths (/api/v1/...) to the client's base URL
        stripped = re.sub(r"^/api/v1(?:_\d+)?", "", path)
        url = f"{self.base_url}{stripped}"

        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"

        try:
            resp = httpx.request(
                method,
                url,
                auth=self._auth,
                headers=headers,
                params=params,
                json=body if body is not None else None,
                timeout=timeout,
            )
            ok = 200 <= resp.status_code < 300
            try:
                data = resp.json()
            except Exception:
                data = resp.text
            if not ok:
                logger.warning(
                    "BambooHR API %s %s returned %s", method, path, resp.status_code
                )
            return {"ok": ok, "status_code": resp.status_code, "data": data}
        except Exception as e:
            logger.error("BambooHR API request failed: %s %s — %s", method, path, e)
            return {"ok": False, "status_code": 0, "data": str(e)}

    def get_time_off_requests(
        self, start_date: str, end_date: str, status: str = "approved"
    ) -> list[dict]:
        """Get time-off requests for a date range."""
        try:
            resp = httpx.get(
                f"{self.base_url}/time_off/requests/",
                auth=self._auth,
                headers={"Accept": "application/json"},
                params={"start": start_date, "end": end_date, "status": status},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json() if isinstance(resp.json(), list) else []
            return []
        except Exception as e:
            logger.error("BambooHR time_off error: %s", e)
            return []


def get_client() -> BambooHRClient | None:
    """Return a configured BambooHRClient from stored credentials, or None."""
    from integrations.registry import get_credentials, is_enabled
    if not is_enabled("bamboohr"):
        return None
    creds = get_credentials("bamboohr")
    return BambooHRClient(
        api_key=creds.get("api_key", ""),
        subdomain=creds.get("subdomain", ""),
    )
