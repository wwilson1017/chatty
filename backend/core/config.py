"""
Chatty — Central configuration loader.
Reads settings from the .env file in the backend directory.
"""

import os
from dotenv import load_dotenv

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_backend_dir, ".env"))


class AuthSettings:
    # Plaintext password for single-user login
    password: str = os.getenv("AUTH_PASSWORD", "changeme")


class JWTSettings:
    secret_key: str = os.getenv("JWT_SECRET", "change-me-in-production")
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


class Settings:
    auth = AuthSettings()
    jwt = JWTSettings()
    google_oauth = GoogleOAuthSettings()
    openai_oauth = OpenAIOAuthSettings()
    quickbooks_oauth = QuickBooksOAuthSettings()
    webby = WebbySettings()

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

    # Feature flags
    multi_user_enabled: bool = os.getenv("MULTI_USER_ENABLED", "false").lower() in ("1", "true", "yes")

    # URLs
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    backend_url: str = os.getenv("BACKEND_URL", "http://localhost:8000")


settings = Settings()
