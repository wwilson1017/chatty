"""
Chatty — Credential store for AI provider profiles.

Reads and writes data/auth-profiles.json.

Schema:
{
    "active_provider": "anthropic" | "openai" | "google",
    "active_model": "claude-opus-4-6",
    "profiles": {
        "anthropic:default": {"type": "api_key", "key": "sk-ant-..."}
                           | {"type": "setup_token", "token": "..."},
        "openai:default":    {"type": "api_key", "key": "sk-..."}
                           | {"type": "oauth", "access": "...", "refresh": "...", "expires": 1234567890},
        "google:default":    {"type": "oauth", "access": "...", "refresh": "...", "expires": 1234567890}
    }
}
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROFILES_PATH = DATA_DIR / "auth-profiles.json"

PROVIDER_DEFAULTS = {
    "anthropic": "claude-opus-4-6",
    "openai": "gpt-5.4",
    "google": "gemini-2.0-flash-exp",
}


class CredentialStore:
    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        if PROFILES_PATH.exists():
            try:
                return json.loads(PROFILES_PATH.read_text())
            except Exception as e:
                logger.error("Failed to load auth-profiles.json: %s", e)
        return {"active_provider": "", "active_model": "", "profiles": {}}

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_PATH.write_text(json.dumps(self.data, indent=2))

    def get_active_profile(self, provider_override: str | None = None) -> tuple[str, dict | None]:
        """Return (profile_name, profile_dict) for the active (or overridden) provider."""
        provider = provider_override or self.data.get("active_provider", "")
        if not provider:
            return ("", None)

        profile_name = f"{provider}:default"
        profile = self.data.get("profiles", {}).get(profile_name)
        return (profile_name, profile)

    def get_google_token(self) -> str:
        """Return the current Google OAuth access token (no refresh logic here)."""
        profile = self.data.get("profiles", {}).get("google:default", {})
        return profile.get("access", "")

    def is_configured(self) -> bool:
        """Return True if at least one provider has valid credentials."""
        profiles = self.data.get("profiles", {})
        for name, p in profiles.items():
            if p.get("type") == "api_key" and p.get("key"):
                return True
            if p.get("type") == "oauth" and p.get("access"):
                return True
            if p.get("type") == "setup_token" and p.get("token"):
                return True
            if p.get("type") == "chatgpt_oauth" and p.get("access"):
                return True
        return False

    def set_chatgpt_oauth(
        self,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        model: str | None = None,
    ):
        """Store ChatGPT OAuth tokens (from Codex CLI) and set OpenAI as active."""
        if "profiles" not in self.data:
            self.data["profiles"] = {}
        self.data["profiles"]["openai:default"] = {
            "type": "chatgpt_oauth",
            "access": access_token,
            "refresh": refresh_token,
            "expires": int(time.time()) + expires_in,
        }
        self.data["active_provider"] = "openai"
        self.data["active_model"] = model or PROVIDER_DEFAULTS.get("openai", "")
        self._save()

    def set_setup_token(self, provider: str, token: str, model: str | None = None):
        """Store a setup-token (e.g. from `claude setup-token`) and set as active."""
        profile_name = f"{provider}:default"
        if "profiles" not in self.data:
            self.data["profiles"] = {}
        self.data["profiles"][profile_name] = {"type": "setup_token", "token": token}
        self.data["active_provider"] = provider
        self.data["active_model"] = model or PROVIDER_DEFAULTS.get(provider, "")
        self._save()

    def set_api_key(self, provider: str, key: str, model: str | None = None):
        """Store an API key for the given provider and set it as active."""
        profile_name = f"{provider}:default"
        if "profiles" not in self.data:
            self.data["profiles"] = {}
        self.data["profiles"][profile_name] = {"type": "api_key", "key": key}
        self.data["active_provider"] = provider
        self.data["active_model"] = model or PROVIDER_DEFAULTS.get(provider, "")
        self._save()

    def set_oauth_tokens(
        self,
        provider: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        model: str | None = None,
    ):
        """Store OAuth tokens for the given provider and set it as active."""
        profile_name = f"{provider}:default"
        if "profiles" not in self.data:
            self.data["profiles"] = {}
        self.data["profiles"][profile_name] = {
            "type": "oauth",
            "access": access_token,
            "refresh": refresh_token,
            "expires": int(time.time()) + expires_in,
        }
        self.data["active_provider"] = provider
        self.data["active_model"] = model or PROVIDER_DEFAULTS.get(provider, "")
        self._save()

    def set_active_model(self, model: str):
        """Update the active model."""
        if model and model != "default":
            self.data["active_model"] = model
        else:
            provider = self.data.get("active_provider", "")
            self.data["active_model"] = PROVIDER_DEFAULTS.get(provider, "")
        self._save()

    def set_active_provider(self, provider: str):
        """Switch active provider (must already have credentials stored)."""
        self.data["active_provider"] = provider
        if not self.data.get("active_model"):
            self.data["active_model"] = PROVIDER_DEFAULTS.get(provider, "")
        self._save()

    def remove_provider(self, provider: str):
        """Remove credentials for a provider."""
        profile_name = f"{provider}:default"
        self.data.get("profiles", {}).pop(profile_name, None)
        if self.data.get("active_provider") == provider:
            self.data["active_provider"] = ""
            self.data["active_model"] = ""
        self._save()

    def is_token_expired(self, provider: str) -> bool:
        """Return True if the OAuth token is expired (or within 60s of expiry)."""
        profile = self.data.get("profiles", {}).get(f"{provider}:default", {})
        expires = profile.get("expires", 0)
        return time.time() >= (expires - 60)

    def to_dict(self) -> dict:
        """Return a sanitized summary (no raw keys) for the frontend."""
        profiles = {}
        for name, p in self.data.get("profiles", {}).items():
            provider = name.split(":")[0]
            if p.get("type") == "api_key":
                key = p.get("key", "")
                profiles[provider] = {
                    "type": "api_key",
                    "configured": bool(key),
                    "key_preview": f"...{key[-4:]}" if len(key) > 4 else "",
                }
            elif p.get("type") == "oauth":
                profiles[provider] = {
                    "type": "oauth",
                    "configured": bool(p.get("access")),
                    "expired": self.is_token_expired(provider),
                }
            elif p.get("type") == "setup_token":
                profiles[provider] = {
                    "type": "setup_token",
                    "configured": bool(p.get("token")),
                }
            elif p.get("type") == "chatgpt_oauth":
                profiles[provider] = {
                    "type": "chatgpt_oauth",
                    "configured": bool(p.get("access")),
                    "expired": self.is_token_expired(provider),
                }

        return {
            "active_provider": self.data.get("active_provider", ""),
            "active_model": self.data.get("active_model", ""),
            "profiles": profiles,
        }
