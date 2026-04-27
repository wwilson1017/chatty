import logging

import stripe

logger = logging.getLogger(__name__)


class StripeClient:
    """Thin wrapper around the Stripe SDK holding a per-instance API key."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.mode = "test" if api_key.startswith("sk_test_") else "live"
        self.account_name = ""

    def test_connection(self) -> bool:
        try:
            acct = stripe.Account.retrieve(api_key=self.api_key)
            self.account_name = (
                (acct.get("settings") or {}).get("dashboard", {}).get("display_name", "")
                or (acct.get("business_profile") or {}).get("name", "")
                or ""
            )
            return True
        except stripe.error.AuthenticationError:
            return False
        except Exception as e:
            logger.error("Stripe connection test failed: %s", e)
            return False


def get_client() -> StripeClient | None:
    from integrations.registry import get_credentials, is_enabled

    if not is_enabled("stripe"):
        return None
    creds = get_credentials("stripe")
    api_key = creds.get("api_key", "")
    if not api_key:
        return None
    client = StripeClient(api_key=api_key)
    client.mode = creds.get("mode", client.mode)
    client.account_name = creds.get("account_name", "")
    return client
