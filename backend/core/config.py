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
    # Scopes: Gemini AI + Gmail + Google Calendar in one OAuth flow
    scopes: list[str] = [
        "https://www.googleapis.com/auth/generative-language",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar",
        "openid",
        "email",
        "profile",
    ]


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


class Settings:
    auth = AuthSettings()
    jwt = JWTSettings()
    google_oauth = GoogleOAuthSettings()
    openai_oauth = OpenAIOAuthSettings()
    quickbooks_oauth = QuickBooksOAuthSettings()
    webby = WebbySettings()
    whatsapp = WhatsAppSettings()

    # GCS bucket for Phase 2 cloud deployment (no-ops if empty)
    gcs_bucket: str = os.getenv("CONFIG_BUCKET", "")

    # CORS
    allowed_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        ).split(",")
        if o.strip()
    ]
    # Auto-add Railway domain to CORS origins
    if RAILWAY_PUBLIC_URL:
        allowed_origins.append(RAILWAY_PUBLIC_URL)

    # Feature flags
    multi_user_enabled: bool = os.getenv("MULTI_USER_ENABLED", "false").lower() in ("1", "true", "yes")

    # URLs — auto-detect from Railway if not explicitly set
    frontend_url: str = os.getenv("FRONTEND_URL", "") or RAILWAY_PUBLIC_URL or "http://localhost:5173"
    backend_url: str = os.getenv("BACKEND_URL", "") or RAILWAY_PUBLIC_URL or "http://localhost:8000"

    # Railway environment detection
    is_railway: bool = bool(RAILWAY_PUBLIC_DOMAIN)
    jwt_secret_is_auto: bool = _jwt_secret_is_auto


settings = Settings()
