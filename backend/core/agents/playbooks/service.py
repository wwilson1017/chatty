"""Playbook file storage — parse/serialize, CRUD, archival, manifest, telemetry.

File format: hand-rolled single-line `key: value` frontmatter between ---
delimiters, followed by a free-form markdown body (no PyYAML dependency;
same approach as core/agents/tools/real_tools.py).
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from core.storage import atomic_write, atomic_write_json, upload_config, delete_config

logger = logging.getLogger(__name__)

PLAYBOOKS_SUBDIR = "playbooks"
ARCHIVE_SUBDIR = "archive"
USAGE_FILENAME = "_usage.json"

MAX_NAME_CHARS = 80
MAX_DESCRIPTION_CHARS = 200
MAX_BODY_CHARS = 20_000
MAX_ACTIVE_PLAYBOOKS = 200
MAX_SLUG_CHARS = 64

VALID_ORIGINS = ("user", "agent", "review", "migration")

# gmail/calendar/drive are natural names agents will use; they all ride on
# the single "google" integration credential.
_INTEGRATION_ALIASES = {"gmail": "google", "calendar": "google", "drive": "google"}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_FRONTMATTER_LINE_RE = re.compile(r"^([a-z_]+):\s*(.*)$")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _agents_data_dir() -> Path:
    # Deferred import: agents.engine imports core.agents modules at load time.
    from agents.engine import DATA_DIR
    return DATA_DIR


def playbooks_dir(agent_slug: str) -> Path:
    return _agents_data_dir() / agent_slug / PLAYBOOKS_SUBDIR


def archive_dir(agent_slug: str) -> Path:
    return playbooks_dir(agent_slug) / ARCHIVE_SUBDIR


def gcs_prefix(agent_slug: str) -> str:
    return f"agents/{agent_slug}/{PLAYBOOKS_SUBDIR}/"


def _safe_slug(slug: str) -> bool:
    return bool(slug) and len(slug) <= MAX_SLUG_CHARS and bool(_SLUG_RE.match(slug))


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:MAX_SLUG_CHARS].strip("-")


# ---------------------------------------------------------------------------
# Parse / serialize
# ---------------------------------------------------------------------------

_META_FIELDS = ("name", "description", "integrations", "chip",
                "created_by", "created_at", "updated_at")


def parse_playbook(text: str) -> dict:
    """Parse playbook file text into {"meta": {...}, "body": str}.

    Raises ValueError on missing/malformed frontmatter or required fields.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("playbook must start with --- frontmatter")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("unterminated frontmatter (missing closing ---)")

    meta: dict = {}
    for raw in lines[1:end]:
        line = raw.strip()
        if not line:
            continue
        m = _FRONTMATTER_LINE_RE.match(line)
        if not m:
            raise ValueError(f"invalid frontmatter line: {line[:80]!r}")
        key, value = m.group(1), m.group(2).strip()
        if key in _META_FIELDS:
            meta[key] = value

    if not meta.get("name"):
        raise ValueError("frontmatter missing required field: name")
    if not meta.get("description"):
        raise ValueError("frontmatter missing required field: description")

    meta["chip"] = str(meta.get("chip", "")).lower() in ("true", "yes", "1")
    meta["integrations"] = [
        s.strip() for s in meta.get("integrations", "").split(",") if s.strip()
    ]
    meta.setdefault("created_by", "user")
    body = "\n".join(lines[end + 1:]).strip("\n")
    return {"meta": meta, "body": body}


def serialize_playbook(meta: dict, body: str) -> str:
    integrations = meta.get("integrations") or []
    if isinstance(integrations, str):
        integrations = [s.strip() for s in integrations.split(",") if s.strip()]
    parts = [
        "---",
        f"name: {meta['name']}",
        f"description: {meta['description']}",
    ]
    if integrations:
        parts.append(f"integrations: {', '.join(integrations)}")
    parts.append(f"chip: {'true' if meta.get('chip') else 'false'}")
    parts.append(f"created_by: {meta.get('created_by', 'user')}")
    if meta.get("created_at"):
        parts.append(f"created_at: {meta['created_at']}")
    if meta.get("updated_at"):
        parts.append(f"updated_at: {meta['updated_at']}")
    parts.append("---")
    parts.append(body.strip("\n"))
    return "\n".join(parts) + "\n"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _validate_integrations(integrations: list[str]) -> str | None:
    """Return an error string for unknown integration ids, else None."""
    from integrations.registry import AVAILABLE_INTEGRATIONS
    valid = set(AVAILABLE_INTEGRATIONS) | set(_INTEGRATION_ALIASES)
    unknown = [i for i in integrations if i not in valid]
    if unknown:
        return f"unknown integrations: {', '.join(unknown)} (valid: {', '.join(sorted(valid))})"
    return None


def integrations_available(required: list[str]) -> tuple[bool, list[str]]:
    """Check required integration ids against the registry. Returns (all_ok, missing)."""
    from integrations.registry import is_enabled
    missing = []
    for ident in required:
        resolved = _INTEGRATION_ALIASES.get(ident, ident)
        if not is_enabled(resolved):
            missing.append(ident)
    return (not missing, missing)


# ---------------------------------------------------------------------------
# Usage telemetry (_usage.json)
# ---------------------------------------------------------------------------

def _load_usage(agent_slug: str) -> dict:
    path = playbooks_dir(agent_slug) / USAGE_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_usage(agent_slug: str, usage: dict) -> None:
    pb_dir = playbooks_dir(agent_slug)
    pb_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pb_dir / USAGE_FILENAME, usage)


def bump_usage(agent_slug: str, slug: str) -> None:
    try:
        usage = _load_usage(agent_slug)
        entry = usage.setdefault(slug, {"use_count": 0, "last_used_at": None})
        entry["use_count"] = int(entry.get("use_count", 0)) + 1
        entry["last_used_at"] = _now_iso()
        _save_usage(agent_slug, usage)
    except Exception:
        logger.warning("usage bump failed for %s/%s", agent_slug, slug, exc_info=True)


def seed_usage(agent_slug: str, slug: str, use_count: int) -> None:
    """Seed telemetry for a migrated playbook."""
    usage = _load_usage(agent_slug)
    usage[slug] = {"use_count": int(use_count), "last_used_at": None}
    _save_usage(agent_slug, usage)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _read_file(path: Path) -> dict | None:
    try:
        parsed = parse_playbook(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("skipping unreadable playbook %s: %s", path, e)
        return None
    return parsed


def _row(agent_slug: str, path: Path, parsed: dict, usage: dict, archived: bool) -> dict:
    meta = parsed["meta"]
    available, missing = integrations_available(meta["integrations"])
    u = usage.get(path.stem, {})
    return {
        "slug": path.stem,
        "name": meta["name"],
        "description": meta["description"],
        "integrations": meta["integrations"],
        "chip": meta["chip"],
        "created_by": meta.get("created_by", "user"),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "archived": archived,
        "available": available,
        "missing_integrations": missing,
        "use_count": int(u.get("use_count", 0)),
        "last_used_at": u.get("last_used_at"),
        "size_bytes": path.stat().st_size,
    }


def list_playbooks(agent_slug: str, include_archived: bool = False) -> list[dict]:
    pb_dir = playbooks_dir(agent_slug)
    if not pb_dir.exists():
        return []
    usage = _load_usage(agent_slug)
    rows = []
    for path in sorted(pb_dir.glob("*.md")):
        parsed = _read_file(path)
        if parsed:
            rows.append(_row(agent_slug, path, parsed, usage, archived=False))
    if include_archived:
        arch = archive_dir(agent_slug)
        if arch.exists():
            for path in sorted(arch.glob("*.md")):
                parsed = _read_file(path)
                if parsed:
                    rows.append(_row(agent_slug, path, parsed, usage, archived=True))
    return rows


def read_playbook(agent_slug: str, slug: str, bump: bool = False) -> dict | None:
    """Read a playbook. Returns {slug, meta, body, archived} or None."""
    if not _safe_slug(slug):
        return None
    path = playbooks_dir(agent_slug) / f"{slug}.md"
    archived = False
    if not path.exists():
        path = archive_dir(agent_slug) / f"{slug}.md"
        archived = True
        if not path.exists():
            return None
    parsed = _read_file(path)
    if not parsed:
        return None
    if bump and not archived:
        bump_usage(agent_slug, slug)
    return {"slug": slug, "meta": parsed["meta"], "body": parsed["body"], "archived": archived}


def _scan_learned_write(agent_slug: str, slug: str, text: str, origin: str,
                        conversation_id: str | None) -> dict | None:
    """Injection policy for playbook writes. Returns an error dict to block, else None.

    Learned writes (agent/review) are ALWAYS scanned and blocked on findings —
    autonomous learning is a prompt-injection persistence vector. User writes
    honor the admin injection_scanning setting (off/flag/block), matching imports.
    """
    from core.agents.security.scanner import scan_content

    if origin in ("agent", "review"):
        result = scan_content(text)
        if result.clean:
            return None
        _log_injection(agent_slug, slug, origin, result, conversation_id)
        return {
            "error": "content failed safety scan and was not saved",
            "finding_count": len(result.findings),
            "pattern_names": [f["pattern_name"] for f in result.findings[:5]],
        }

    if origin == "migration":
        # Pre-existing local data: flag (log) but never block.
        result = scan_content(text)
        if not result.clean:
            _log_injection(agent_slug, slug, origin, result, conversation_id)
        return None

    from core.admin_settings import load_admin_settings
    mode = load_admin_settings().get("injection_scanning", "flag")
    if mode == "off":
        return None
    result = scan_content(text)
    if result.clean:
        return None
    _log_injection(agent_slug, slug, origin, result, conversation_id)
    if mode == "block":
        return {
            "error": "content failed safety scan and was not saved",
            "finding_count": len(result.findings),
            "pattern_names": [f["pattern_name"] for f in result.findings[:5]],
        }
    return None


def _log_injection(agent_slug, slug, origin, result, conversation_id) -> None:
    try:
        from core.events.service import log_security_event
        log_security_event(
            "injection_detected",
            f"Injection patterns in playbook write '{slug}': {len(result.findings)} match(es)",
            agent_slug=agent_slug,
            source=f"playbook_{origin}",
            details={"slug": slug, "findings": result.findings[:10]},
        )
    except Exception:
        logger.warning("security event log failed", exc_info=True)
    if origin in ("agent", "review"):
        try:
            from . import learning_log
            learning_log.log_event(
                agent_slug,
                event_type="blocked_injection",
                source=origin,
                target=slug,
                title=f"Blocked an unsafe update to “{slug}”",
                conversation_id=conversation_id,
            )
        except Exception:
            logger.warning("learning event log failed", exc_info=True)


def save_playbook(
    agent_slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    content: str | None = None,
    integrations: list[str] | None = None,
    chip: bool | None = None,
    origin: str = "user",
    slug: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Create or update a playbook. Merge semantics: None fields keep existing values.

    Learned writes (origin agent/review) are injection-scanned and logged to the
    learning events feed with before/after content for one-click revert.
    """
    if origin not in VALID_ORIGINS:
        return {"error": f"invalid origin: {origin}"}

    existing = None
    if slug:
        if not _safe_slug(slug):
            return {"error": f"invalid slug: {slug!r}"}
        existing = read_playbook(agent_slug, slug)
        if existing and existing["archived"]:
            return {"error": f"playbook '{slug}' is archived — restore it first"}

    if existing:
        meta = dict(existing["meta"])
        body = existing["body"]
        if name is not None:
            meta["name"] = name.strip()
        if description is not None:
            meta["description"] = description.strip()
        if integrations is not None:
            meta["integrations"] = integrations
        if chip is not None:
            meta["chip"] = bool(chip)
        if content is not None:
            body = content
    else:
        if not name or not name.strip():
            return {"error": "name is required"}
        if not description or not description.strip():
            return {"error": "description is required"}
        if not content or not content.strip():
            return {"error": "content is required"}
        slug = slug or slugify(name)
        if not _safe_slug(slug):
            return {"error": f"could not derive a valid slug from name {name!r}"}
        if (archive_dir(agent_slug) / f"{slug}.md").exists():
            return {"error": f"an archived playbook '{slug}' exists — restore it instead"}
        active_count = len(list(playbooks_dir(agent_slug).glob("*.md"))) if playbooks_dir(agent_slug).exists() else 0
        if active_count >= MAX_ACTIVE_PLAYBOOKS:
            return {"error": f"playbook limit reached ({MAX_ACTIVE_PLAYBOOKS})"}
        meta = {
            "name": name.strip(),
            "description": description.strip(),
            "integrations": integrations or [],
            "chip": bool(chip),
            "created_by": origin,
            "created_at": _now_iso(),
        }
        body = content

    if len(meta["name"]) > MAX_NAME_CHARS:
        return {"error": f"name too long (max {MAX_NAME_CHARS} chars)"}
    if len(meta["description"]) > MAX_DESCRIPTION_CHARS:
        return {"error": f"description too long (max {MAX_DESCRIPTION_CHARS} chars)"}
    if "\n" in meta["name"] or "\n" in meta["description"]:
        return {"error": "name and description must be single-line"}
    if not body or not body.strip():
        return {"error": "content is required"}
    if len(body) > MAX_BODY_CHARS:
        return {"error": f"content too long (max {MAX_BODY_CHARS} chars)"}
    err = _validate_integrations(meta["integrations"])
    if err:
        return {"error": err}

    blocked = _scan_learned_write(
        agent_slug, slug, f"{meta['name']}\n{meta['description']}\n{body}",
        origin, conversation_id,
    )
    if blocked:
        return blocked

    meta["updated_at"] = _now_iso()
    text = serialize_playbook(meta, body)

    pb_dir = playbooks_dir(agent_slug)
    pb_dir.mkdir(parents=True, exist_ok=True)
    path = pb_dir / f"{slug}.md"
    before_text = None
    if existing:
        try:
            before_text = path.read_text(encoding="utf-8")
        except OSError:
            before_text = None
    atomic_write(path, text)
    try:
        upload_config(path, f"{slug}.md", prefix=gcs_prefix(agent_slug))
    except Exception:
        logger.warning("GCS upload failed for playbook %s/%s", agent_slug, slug, exc_info=True)

    if origin in ("agent", "review"):
        try:
            from . import learning_log
            learning_log.log_event(
                agent_slug,
                event_type="playbook_updated" if existing else "playbook_created",
                source=origin,
                target=slug,
                title=(f"Updated playbook “{meta['name']}”" if existing
                       else f"New playbook “{meta['name']}”"),
                before_content=before_text,
                after_content=text,
                conversation_id=conversation_id,
            )
        except Exception:
            logger.warning("learning event log failed for %s/%s", agent_slug, slug, exc_info=True)

    return {"slug": slug, "name": meta["name"], "ok": True}


def archive_playbook(agent_slug: str, slug: str, origin: str = "user",
                     conversation_id: str | None = None) -> dict:
    """Move a playbook to the archive (recoverable; agents never hard-delete)."""
    if not _safe_slug(slug):
        return {"error": f"invalid slug: {slug!r}"}
    src = playbooks_dir(agent_slug) / f"{slug}.md"
    if not src.exists():
        return {"error": f"playbook '{slug}' not found"}
    arch = archive_dir(agent_slug)
    arch.mkdir(parents=True, exist_ok=True)
    before_text = src.read_text(encoding="utf-8")
    src.rename(arch / f"{slug}.md")
    try:
        delete_config(f"{slug}.md", prefix=gcs_prefix(agent_slug))
        upload_config(arch / f"{slug}.md", f"{ARCHIVE_SUBDIR}/{slug}.md", prefix=gcs_prefix(agent_slug))
    except Exception:
        logger.warning("GCS sync failed archiving %s/%s", agent_slug, slug, exc_info=True)

    if origin in ("agent", "review"):
        try:
            from . import learning_log
            name = parse_playbook(before_text)["meta"].get("name", slug)
            learning_log.log_event(
                agent_slug,
                event_type="playbook_archived",
                source=origin,
                target=slug,
                title=f"Archived playbook “{name}”",
                before_content=before_text,
                conversation_id=conversation_id,
            )
        except Exception:
            logger.warning("learning event log failed for %s/%s", agent_slug, slug, exc_info=True)

    return {"slug": slug, "archived": True}


def restore_playbook(agent_slug: str, slug: str) -> dict:
    if not _safe_slug(slug):
        return {"error": f"invalid slug: {slug!r}"}
    src = archive_dir(agent_slug) / f"{slug}.md"
    if not src.exists():
        return {"error": f"archived playbook '{slug}' not found"}
    if (playbooks_dir(agent_slug) / f"{slug}.md").exists():
        return {"error": f"an active playbook '{slug}' already exists"}
    dst = playbooks_dir(agent_slug) / f"{slug}.md"
    src.rename(dst)
    try:
        delete_config(f"{ARCHIVE_SUBDIR}/{slug}.md", prefix=gcs_prefix(agent_slug))
        upload_config(dst, f"{slug}.md", prefix=gcs_prefix(agent_slug))
    except Exception:
        logger.warning("GCS sync failed restoring %s/%s", agent_slug, slug, exc_info=True)
    return {"slug": slug, "restored": True}


def delete_playbook(agent_slug: str, slug: str) -> dict:
    """Hard delete (REST/UI only — agents archive instead)."""
    if not _safe_slug(slug):
        return {"error": f"invalid slug: {slug!r}"}
    deleted = False
    for sub, gcs_name in ((playbooks_dir(agent_slug), f"{slug}.md"),
                          (archive_dir(agent_slug), f"{ARCHIVE_SUBDIR}/{slug}.md")):
        path = sub / f"{slug}.md"
        if path.exists():
            path.unlink()
            deleted = True
            try:
                delete_config(gcs_name, prefix=gcs_prefix(agent_slug))
            except Exception:
                logger.warning("GCS delete failed for %s/%s", agent_slug, slug, exc_info=True)
    if not deleted:
        return {"error": f"playbook '{slug}' not found"}
    usage = _load_usage(agent_slug)
    if slug in usage:
        usage.pop(slug)
        _save_usage(agent_slug, usage)
    return {"slug": slug, "deleted": True}


def write_raw(agent_slug: str, slug: str, text: str) -> dict:
    """Write raw file text (used by learning-event revert). Validates by parsing."""
    if not _safe_slug(slug):
        return {"error": f"invalid slug: {slug!r}"}
    try:
        parse_playbook(text)
    except ValueError as e:
        return {"error": f"invalid playbook content: {e}"}
    pb_dir = playbooks_dir(agent_slug)
    pb_dir.mkdir(parents=True, exist_ok=True)
    path = pb_dir / f"{slug}.md"
    atomic_write(path, text)
    try:
        upload_config(path, f"{slug}.md", prefix=gcs_prefix(agent_slug))
    except Exception:
        logger.warning("GCS upload failed for playbook %s/%s", agent_slug, slug, exc_info=True)
    return {"slug": slug, "ok": True}


# ---------------------------------------------------------------------------
# Prompt manifest + chat activation
# ---------------------------------------------------------------------------

def get_playbook_manifest(agent_slug: str, include_unavailable: bool = False) -> str:
    """Compact index for the system prompt: one line per active playbook.

    Integration-gated playbooks are omitted unless include_unavailable
    (the review fork sees everything; the live agent only what's runnable).
    """
    from core.agents.security.scanner import sanitize_memory_content

    lines = []
    for row in list_playbooks(agent_slug):
        if not row["available"] and not include_unavailable:
            continue
        name = sanitize_memory_content(row["name"])
        desc = sanitize_memory_content(row["description"])
        suffix = ""
        if not row["available"]:
            suffix = f"  (needs: {', '.join(row['missing_integrations'])})"
        lines.append(f"- {row['slug']} · {name} · {desc}{suffix}")
    return "\n".join(lines)


def build_activation_message(agent_slug: str, slug: str, user_text: str) -> str | None:
    """Expand a playbook invocation (chip / slash command) into the provider-bound
    user message, Hermes-style. Returns None if the playbook is missing/archived."""
    from core.agents.security.scanner import sanitize_memory_content

    pb = read_playbook(agent_slug, slug, bump=True)
    if not pb or pb["archived"]:
        return None
    name = pb["meta"]["name"]
    body = sanitize_memory_content(pb["body"])
    return (
        f"[Playbook activated: {name}]\n\n"
        f"The user invoked this playbook — follow its procedure now.\n\n"
        f'<playbook slug="{slug}" name="{name}">\n'
        f"{body}\n"
        f"</playbook>\n\n"
        f"User request: {user_text.strip() or 'Run this playbook.'}"
    )
