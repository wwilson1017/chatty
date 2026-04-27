from .client import StripeClient
from integrations.registry import save_credentials


def setup(api_key: str) -> dict:
    client = StripeClient(api_key=api_key)
    if not client.test_connection():
        return {"ok": False, "error": "Invalid API key. Find yours at dashboard.stripe.com/apikeys"}
    save_credentials("stripe", {
        "api_key": api_key,
        "mode": client.mode,
        "account_name": client.account_name,
        "enabled": True,
    })
    return {"ok": True, "mode": client.mode, "account_name": client.account_name}
