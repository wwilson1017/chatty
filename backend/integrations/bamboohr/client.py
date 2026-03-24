"""
Chatty — BambooHR REST API client.

Adapted from CAKE OS core/bamboohr.py.
Credentials loaded from data/integrations/bamboohr.json.
"""

import logging
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
