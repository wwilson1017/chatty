"""Skill packs CRUD operations using the agent's MemoryDB connection."""

import json
import logging
import re

from core.agents.memory.db import get_instance

logger = logging.getLogger(__name__)

_MAX_TRIGGER_PATTERN_LEN = 200
_NESTED_QUANTIFIER_RE = re.compile(r"(\.\*){2,}|\(\.\*\)\*|\(\.\+\)\+")


def list_skills(data_dir: str, category: str | None = None) -> list[dict]:
    """List available skill packs."""
    db = get_instance(data_dir)
    if not db:
        return []

    conn = db.get_db()
    sql = "SELECT id, name, description, category, usage_count FROM skill_packs"
    params: list = []
    if category:
        sql += " WHERE category = ?"
        params.append(category)
    sql += " ORDER BY usage_count DESC, name"

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_skill(data_dir: str, name: str) -> dict | None:
    """Get a skill by name."""
    db = get_instance(data_dir)
    if not db:
        return None

    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM skill_packs WHERE name = ?", (name,)
    ).fetchone()
    return dict(row) if row else None


def save_skill(
    data_dir: str,
    name: str,
    prompt: str,
    description: str = "",
    category: str | None = None,
    tags: list[str] | None = None,
    trigger_pattern: str | None = None,
) -> dict:
    """Save a new skill pack."""
    if not name or not name.strip():
        return {"error": "name is required"}
    if not prompt or not prompt.strip():
        return {"error": "prompt is required"}

    # Validate trigger_pattern if provided
    if trigger_pattern:
        if len(trigger_pattern) > _MAX_TRIGGER_PATTERN_LEN:
            return {"error": f"trigger_pattern too long (max {_MAX_TRIGGER_PATTERN_LEN} chars)"}
        if _NESTED_QUANTIFIER_RE.search(trigger_pattern):
            return {"error": "trigger_pattern contains unsafe nested quantifiers"}
        try:
            re.compile(trigger_pattern)
        except re.error as e:
            return {"error": f"trigger_pattern is invalid regex: {e}"}

    db = get_instance(data_dir)
    if not db:
        return {"error": "memory database not available"}

    conn = db.get_db()
    tags_json = json.dumps(tags) if tags else None

    with db.write_lock:
        try:
            conn.execute(
                """INSERT INTO skill_packs (name, description, prompt, category, tags, trigger_pattern)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       description=excluded.description,
                       prompt=excluded.prompt,
                       category=excluded.category,
                       tags=excluded.tags,
                       trigger_pattern=excluded.trigger_pattern,
                       updated_at=datetime('now')""",
                (name.strip(), description, prompt.strip(), category, tags_json, trigger_pattern),
            )
            conn.commit()
        except Exception as e:
            return {"error": str(e)}

    return {"name": name.strip(), "ok": True}


def run_skill(data_dir: str, name: str, params: dict | None = None) -> dict:
    """Execute a skill by name, expanding {{param}} placeholders."""
    skill = get_skill(data_dir, name)
    if not skill:
        return {"error": f"Skill '{name}' not found"}

    prompt = skill["prompt"]

    # Substitute parameters
    if params:
        for key, value in params.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

    # Increment usage count
    db = get_instance(data_dir)
    if db:
        conn = db.get_db()
        with db.write_lock:
            conn.execute(
                "UPDATE skill_packs SET usage_count = usage_count + 1, updated_at = datetime('now') WHERE name = ?",
                (name,),
            )
            conn.commit()

    return {"name": name, "prompt": prompt, "ok": True}


def delete_skill(data_dir: str, name: str) -> dict:
    """Delete a skill pack."""
    db = get_instance(data_dir)
    if not db:
        return {"error": "memory database not available"}

    conn = db.get_db()
    with db.write_lock:
        cursor = conn.execute("DELETE FROM skill_packs WHERE name = ?", (name,))
        conn.commit()
        if cursor.rowcount == 0:
            return {"error": f"Skill '{name}' not found"}

    return {"name": name, "deleted": True}
