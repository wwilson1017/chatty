"""
Chatty — Odoo XML-RPC client.

Adapted from CAKE OS core/odoo_client.py.
Credentials loaded from data/integrations/odoo.json instead of env vars.
"""

import logging
import xmlrpc.client

logger = logging.getLogger(__name__)


class OdooClient:
    """Handles connection and operations with Odoo via XML-RPC."""

    def __init__(self, url: str, database: str, username: str, api_key: str):
        self.url = url.rstrip("/")
        self.database = database
        self.username = username
        self.api_key = api_key
        self.uid: int | None = None

        try:
            self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
            self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        except Exception as e:
            logger.error("Failed to create Odoo XML-RPC proxies: %s", e)
            self.common = None
            self.models = None

    def test_connection(self) -> dict | None:
        """Test connection by fetching Odoo version info."""
        if not self.common:
            return None
        try:
            return self.common.version()
        except Exception as e:
            logger.error("Odoo connection test failed: %s", e)
            return None

    def authenticate(self) -> bool:
        """Authenticate and store user ID."""
        if not self.common:
            return False
        try:
            self.uid = self.common.authenticate(self.database, self.username, self.api_key, {})
            return bool(self.uid)
        except Exception as e:
            logger.error("Odoo auth error: %s", e)
            return False

    def execute(self, model: str, method: str, *args, **kwargs):
        """Execute a method on an Odoo model."""
        if not self.models or not self.uid:
            return None
        try:
            return self.models.execute_kw(
                self.database, self.uid, self.api_key, model, method, args, kwargs
            )
        except Exception as e:
            logger.error("Odoo execute %s.%s failed: %s", model, method, e)
            return None

    def search_read(self, model: str, domain=None, fields=None, limit=None, order="") -> list:
        """Search and read records."""
        domain = domain or []
        fields = fields or []
        kwargs: dict = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", domain, **kwargs) or []

    def search_count(self, model: str, domain=None) -> int:
        """Count matching records."""
        return self.execute(model, "search_count", domain or []) or 0

    def read(self, model: str, ids: list[int], fields=None) -> list:
        """Read specific records by ID."""
        return self.execute(model, "read", ids, {"fields": fields or []}) or []

    def write(self, model: str, ids: list[int], vals: dict):
        """Write field values to records. Raises on failure."""
        if not self.models or not self.uid:
            raise RuntimeError(f"Odoo not connected — cannot write to {model}")
        return self.models.execute_kw(
            self.database, self.uid, self.api_key,
            model, "write", [ids, vals],
        )

    def create(self, model: str, vals: dict) -> int:
        """Create a record. Returns the new record ID. Raises on failure."""
        if not self.models or not self.uid:
            raise RuntimeError(f"Odoo not connected — cannot create {model}")
        return self.models.execute_kw(
            self.database, self.uid, self.api_key,
            model, "create", [vals],
        )


def get_client() -> OdooClient | None:
    """Return a configured OdooClient from stored credentials, or None."""
    from integrations.registry import get_credentials, is_enabled
    if not is_enabled("odoo"):
        return None
    creds = get_credentials("odoo")
    client = OdooClient(
        url=creds.get("url", ""),
        database=creds.get("database", ""),
        username=creds.get("username", ""),
        api_key=creds.get("api_key", ""),
    )
    if client.authenticate():
        return client
    return None
