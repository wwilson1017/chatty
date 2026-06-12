"""One-time migration: legacy skill_packs rows → playbook files.

The proto skill-packs system (single prompt-template strings in the per-agent
memory.db) was superseded by playbooks. On startup, any agent with skill_packs
rows and no migration marker gets each row converted into a playbook file so
no user data is lost. The old table is left in place as a safety net.
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATION_MARKER = ".skills-migrated"


def migrate_all_agents() -> dict:
    """Migrate skill_packs → playbooks for every agent. Idempotent.

    Known limitation: scans local agent dirs only. On a GCS-backed deployment
    whose memory DBs are lazily restored after boot, a fresh instance can skip
    legacy rows. Accepted: skill packs were a UI-less proto feature, and the
    skill_packs table is left in place as the recovery source.
    """
    from agents.engine import DATA_DIR

    if not DATA_DIR.exists():
        return {"status": "ok", "migrated": 0}

    total = 0
    for agent_dir in sorted(DATA_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        try:
            total += migrate_agent(agent_dir)
        except Exception:
            logger.warning("skill-pack migration failed for %s", agent_dir.name, exc_info=True)
    return {"status": "ok", "migrated": total}


def migrate_agent(agent_dir: Path) -> int:
    """Convert one agent's skill_packs rows into playbook files. Returns count."""
    from . import service

    slug = agent_dir.name
    pb_dir = agent_dir / service.PLAYBOOKS_SUBDIR
    marker = pb_dir / MIGRATION_MARKER
    if marker.exists():
        return 0

    db_path = agent_dir / "context" / "memory.db"
    rows: list[dict] = []
    if db_path.exists():
        # Read-only plain sqlite3 — deliberately NOT ensure_memory_db(), which
        # would force FTS reindexing of every agent at boot.
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                rows = [dict(r) for r in conn.execute(
                    "SELECT name, description, prompt, category, usage_count FROM skill_packs"
                ).fetchall()]
            except sqlite3.OperationalError:
                rows = []  # fresh DB — table never existed
            finally:
                conn.close()
        except sqlite3.Error:
            logger.warning("could not open memory.db for %s", slug, exc_info=True)
            rows = []

    migrated = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        prompt = (row.get("prompt") or "").strip()
        if not name or not prompt:
            continue
        description = (row.get("description") or "").strip() or f"Migrated skill pack: {name}"
        body_parts = ["*(Migrated from a skill pack.)*", ""]
        if row.get("category"):
            body_parts.append(f"Category: {row['category']}")
            body_parts.append("")
        body_parts.append("## Procedure")
        body_parts.append("")
        body_parts.append(prompt)
        result = service.save_playbook(
            slug,
            name=name[:service.MAX_NAME_CHARS],
            description=description.replace("\n", " ")[:service.MAX_DESCRIPTION_CHARS],
            content="\n".join(body_parts)[:service.MAX_BODY_CHARS],
            origin="migration",
        )
        if result.get("ok"):
            migrated += 1
            usage_count = int(row.get("usage_count") or 0)
            if usage_count:
                service.seed_usage(slug, result["slug"], usage_count)
        else:
            logger.warning("skipped skill pack %r for %s: %s", name, slug, result.get("error"))

    pb_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("done\n", encoding="utf-8")
    if migrated:
        logger.info("migrated %d skill pack(s) → playbooks for %s", migrated, slug)
    return migrated
