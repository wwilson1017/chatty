"""Installed-CLI store: per-CLI metadata, manifest snapshot, and encrypted creds.

Layout (under ``data/clis/<slug>/``)::

    install.json         # lean install record (see Install)
    tools-manifest.json  # snapshot of the built CLI's tool surface (full manifest)
    creds.json           # {"env": {ENV_VAR: "enc:v1:..."}}  — values encrypted
    bin/<slug>-pp-cli    # the built binary
    work/                # per-CLI runtime cwd (the CLI owns its device token here)

Credentials are encrypted **value-by-value** with ``encrypt_value`` rather than
``encrypt_dict``: a CLI's secrets live under arbitrary env-var names
(``OPENALEX_API_KEY``, ``KIT_API_KEY``, …) that the fixed ``SENSITIVE_FIELDS``
allowlist can't enumerate, so relying on it would leak plaintext at rest (plan
Risk #5). Encrypting each value directly is correct for any var name or count.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.encryption import decrypt_value, encrypt_value
from core.storage import atomic_write_json

from . import paths

logger = logging.getLogger(__name__)

INSTALL_FILENAME = "install.json"
MANIFEST_FILENAME = "tools-manifest.json"
CREDS_FILENAME = "creds.json"

# Per-CLI tool-confirmation ceiling. Printed CLIs default to "normal" so writes
# require confirmation; never inherit a "power" default (plan R4).
TOOL_MODE_NORMAL = "normal"
TOOL_MODE_POWER = "power"
# Hyphenated to match the engine's mode ranking (ai_service._MODE_RANK) and
# integrations.registry.get_tool_mode; a non-matching spelling would rank as "normal".
TOOL_MODE_READONLY = "read-only"
VALID_TOOL_MODES = (TOOL_MODE_NORMAL, TOOL_MODE_POWER, TOOL_MODE_READONLY)

# Build lifecycle.
BUILD_PENDING = "pending"
BUILD_BUILDING = "building"
BUILD_READY = "ready"
BUILD_ERROR = "error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Install:
    """Lean install record persisted as install.json (the full tool surface lives
    in the sibling tools-manifest.json)."""

    slug: str
    category: str
    ref: str                       # requested ref (branch/tag/sha)
    sha: str                       # resolved immutable commit SHA
    api_name: str = ""
    description: str = ""
    base_url: str = ""
    auth: dict[str, Any] = field(default_factory=dict)  # {type, env_vars:[...], key_url?}
    tool_count: int = 0
    enabled: bool = True
    tool_mode: str = TOOL_MODE_NORMAL
    build_status: str = BUILD_PENDING
    build_error: str | None = None
    binary: str | None = None
    installed_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Install":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# ── install.json ──────────────────────────────────────────────────────────

def _install_path(slug: str) -> Path:
    return paths.cli_dir(slug) / INSTALL_FILENAME


def get_install(slug: str) -> Install | None:
    try:
        slug = paths.validate_slug(slug)
    except paths.InvalidIdentifier:
        return None
    path = _install_path(slug)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return Install.from_dict(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("unreadable install.json for %s: %s", slug, exc)
        return None


def list_installed() -> list[Install]:
    if not paths.CLIS_DIR.exists():
        return []
    out: list[Install] = []
    for child in sorted(paths.CLIS_DIR.iterdir()):
        if not child.is_dir():
            continue
        rec = get_install(child.name)
        if rec is not None:
            out.append(rec)
    return out


def save_install(install: Install) -> Install:
    paths.validate_slug(install.slug)
    if install.tool_mode not in VALID_TOOL_MODES:
        install.tool_mode = TOOL_MODE_NORMAL
    now = _now()
    if not install.installed_at:
        install.installed_at = now
    install.updated_at = now
    paths.cli_dir(install.slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(_install_path(install.slug), install.to_dict())
    return install


def update_install(slug: str, **changes: Any) -> Install | None:
    """Patch fields on an existing install record. Returns the updated record."""
    rec = get_install(slug)
    if rec is None:
        return None
    for k, v in changes.items():
        if hasattr(rec, k):
            setattr(rec, k, v)
    return save_install(rec)


def is_enabled(slug: str) -> bool:
    rec = get_install(slug)
    return bool(rec and rec.enabled and rec.build_status == BUILD_READY)


def remove_install(slug: str) -> bool:
    """Delete the per-CLI dir (binary, manifest, creds, install) + staged sources."""
    import shutil

    slug = paths.validate_slug(slug)
    d = paths.cli_dir(slug)
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    # Prune any staged source trees for this slug (src/<slug>@<sha>).
    if paths.SRC_DIR.exists():
        for staged in paths.SRC_DIR.glob(f"{slug}@*"):
            shutil.rmtree(staged, ignore_errors=True)
    return True


# ── manifest snapshot ─────────────────────────────────────────────────────

def _manifest_path(slug: str) -> Path:
    return paths.cli_dir(slug) / MANIFEST_FILENAME


def save_manifest(slug: str, manifest: dict[str, Any]) -> None:
    paths.cli_dir(slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(_manifest_path(slug), manifest)


def get_manifest(slug: str) -> dict[str, Any] | None:
    path = _manifest_path(paths.validate_slug(slug))
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unreadable manifest for %s: %s", slug, exc)
        return None


# ── credentials (encrypted at rest) ───────────────────────────────────────

def _creds_path(slug: str) -> Path:
    return paths.cli_dir(slug) / CREDS_FILENAME


def save_cli_credentials(slug: str, env: dict[str, str]) -> None:
    """Persist credential env vars, encrypting each value. Replaces prior creds."""
    slug = paths.validate_slug(slug)
    enc = {name: encrypt_value(str(value)) for name, value in env.items() if value != ""}
    paths.cli_dir(slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(_creds_path(slug), {"env": enc, "updated_at": _now()})


def get_cli_credentials(slug: str) -> dict[str, str]:
    """Return decrypted credential env vars (empty dict if none stored)."""
    path = _creds_path(paths.validate_slug(slug))
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unreadable creds for %s: %s", slug, exc)
        return {}
    env = data.get("env", {})
    return {name: decrypt_value(value) for name, value in env.items()}


def has_credentials(slug: str) -> bool:
    return _creds_path(paths.validate_slug(slug)).exists()


def delete_cli_credentials(slug: str) -> bool:
    path = _creds_path(paths.validate_slug(slug))
    if path.exists():
        path.unlink()
        return True
    return False
