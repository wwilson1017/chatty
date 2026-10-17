"""
Chatty — Central configuration loader.
Reads settings from the .env file in the backend directory.
Auto-detects Railway environment via RAILWAY_PUBLIC_DOMAIN.
"""

import os
import secrets
from dotenv import load_dotenv

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_backend_dir, ".env"))
load_dotenv(os.path.join(os.path.dirname(_backend_dir), ".env"))  # the repo-root .env that run.py writes

# Railway injects RAILWAY_PUBLIC_DOMAIN (e.g. "chatty-production.up.railway.app")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
RAILWAY_PUBLIC_URL = f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else ""

# Track whether JWT_SECRET was explicitly provided or auto-generated
_jwt_secret_from_env = os.getenv("JWT_SECRET", "")
_jwt_secret_is_auto = not _jwt_secret_from_env or _jwt_secret_from_env == "change-me-in-production"


class AuthSettings:
    # Plaintext password for single-user login
    password: str = os.getenv("AUTH_PASSWORD", "changeme")


class JWTSettings:
    secret_key: str = _jwt_secret_from_env if not _jwt_secret_is_auto else secrets.token_hex(32)
    algorithm: str = "HS256"
    expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))


class GoogleOAuthSettings:
    client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # Default scopes for Gemini-AI-only connect (from /providers/google/connect).
    # The Gmail/Calendar/Drive integration computes scopes dynamically based on
    # the user's chosen access levels — see build_google_scopes().
    scopes: list[str] = [
        "https://www.googleapis.com/auth/generative-language",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar",
        "openid",
        "email",
        "profile",
    ]


# ── Google scope builder (for Gmail/Calendar/Drive integration) ───────────────

GMAIL_SCOPE_LEVELS = {
    "none": [],
    "read": ["https://www.googleapis.com/auth/gmail.readonly"],
    "send": [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose",
    ],
}

CALENDAR_SCOPE_LEVELS = {
    "none": [],
    "read": ["https://www.googleapis.com/auth/calendar.readonly"],
    "full": ["https://www.googleapis.com/auth/calendar"],
}

DRIVE_SCOPE_LEVELS = {
    "none": [],
    "file": ["https://www.googleapis.com/auth/drive.file"],
    "readonly": ["https://www.googleapis.com/auth/drive.readonly"],
    "full": ["https://www.googleapis.com/auth/drive"],
}


def build_google_scopes(
    gmail_level: str = "none",
    calendar_level: str = "none",
    drive_level: str = "none",
    include_ai: bool = False,
) -> list[str]:
    """Build the Google OAuth scope list for a user-chosen access profile.

    Always includes openid/email/profile for identity resolution.
    Set include_ai=True to also request the Gemini generative-language scope.
    """
    scopes = ["openid", "email", "profile"]
    if include_ai:
        scopes.append("https://www.googleapis.com/auth/generative-language")
    scopes.extend(GMAIL_SCOPE_LEVELS.get(gmail_level, []))
    scopes.extend(CALENDAR_SCOPE_LEVELS.get(calendar_level, []))
    scopes.extend(DRIVE_SCOPE_LEVELS.get(drive_level, []))
    # De-duplicate while preserving order
    seen: set[str] = set()
    deduped = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


class OpenAIOAuthSettings:
    client_id: str = os.getenv("OPENAI_CLIENT_ID", "")
    client_secret: str = os.getenv("OPENAI_CLIENT_SECRET", "")


class QuickBooksOAuthSettings:
    client_id: str = os.getenv("QUICKBOOKS_CLIENT_ID", "")
    client_secret: str = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")


class WebbySettings:
    github_token: str = os.getenv("WEBBY_GITHUB_TOKEN", "")
    github_repo: str = os.getenv("WEBBY_GITHUB_REPO", "")  # e.g. "owner/repo"


class WhatsAppSettings:
    def __init__(self):
        self.bridge_url: str = os.getenv("WHATSAPP_BRIDGE_URL", "")
        self.bridge_api_key: str = os.getenv("WHATSAPP_BRIDGE_API_KEY", "")
        self.webhook_secret: str = os.getenv("WHATSAPP_WEBHOOK_SECRET", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.bridge_url)


class ComputerSettings:
    """The virtual computer (integrations/computer). COMPUTER_URL/COMPUTER_SECRET
    from env win (the Railway template sets them); otherwise the card's saved
    credentials (`url`, `api_key`). Read on every access: the card can save
    credentials while the server runs."""

    @staticmethod
    def _source() -> dict:
        """The one pair in use: both env vars, else the saved pair. One env var alone counts as
        nothing (not a mix), so a saved secret is never sent to an env-named host or the reverse."""
        url, secret = os.getenv("COMPUTER_URL", ""), os.getenv("COMPUTER_SECRET", "")
        if url or secret:
            return {"url": url, "api_key": secret} if url and secret else {}
        from integrations.registry import get_credentials
        return get_credentials("computer")

    @property
    def url(self) -> str:
        return self._source().get("url", "").rstrip("/")

    @property
    def secret(self) -> str:
        return self._source().get("api_key", "")

    @property
    def is_configured(self) -> bool:
        src = self._source()
        return bool(src.get("url") and src.get("api_key"))


class Settings:
    auth = AuthSettings()
    jwt = JWTSettings()
    google_oauth = GoogleOAuthSettings()
    openai_oauth = OpenAIOAuthSettings()
    quickbooks_oauth = QuickBooksOAuthSettings()
    webby = WebbySettings()
    whatsapp = WhatsAppSettings()
    computer = ComputerSettings()

    # GCS bucket for Phase 2 cloud deployment (no-ops if empty)
    gcs_bucket: str = os.getenv("CONFIG_BUCKET", "")

    # CORS — parse from env + auto-add Railway domain if detected
    allowed_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        ).split(",")
        if o.strip()
    ] + ([RAILWAY_PUBLIC_URL] if RAILWAY_PUBLIC_URL else [])

    # Feature flags
    multi_user_enabled: bool = os.getenv("MULTI_USER_ENABLED", "false").lower() in ("1", "true", "yes")

    # URLs — auto-detect from Railway if not explicitly set
    frontend_url: str = os.getenv("FRONTEND_URL", "") or RAILWAY_PUBLIC_URL or "http://localhost:5173"
    backend_url: str = os.getenv("BACKEND_URL", "") or RAILWAY_PUBLIC_URL or "http://localhost:8000"

    # Railway environment detection
    is_railway: bool = bool(RAILWAY_PUBLIC_DOMAIN)
    jwt_secret_is_auto: bool = _jwt_secret_is_auto


settings = Settings()
