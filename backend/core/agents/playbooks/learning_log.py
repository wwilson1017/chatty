"""Learning events — the "what I learned" feed with one-click revert.

Every autonomous write (review fork or foreground agent saving a playbook,
the review fork adding a fact) is logged here with before/after content so
the user can see what the agent taught itself and undo any of it.
"""

import logging

logger = logging.getLogger(__name__)

EVENT_TYPES = (
    "playbook_created",
    "playbook_updated",
    "playbook_archived",
    "fact_added",
    "blocked_injection",
)

# Feed payload truncation — full content stays in the DB for revert.
_PREVIEW_CHARS = 600


def _get_db(agent_slug: str):
    from agents.engine import ensure_memory_db
    return ensure_memory_db(agent_slug)


def log_event(
    agent_slug: str,
    *,
    event_type: str,
    source: str,
    target: str,
    title: str,
    before_content: str | None = None,
    after_content: str | None = None,
    conversation_id: str | None = None,
) -> int | None:
    """Record a learning event. Returns the event id, or None on failure."""
    if event_type not in EVENT_TYPES:
        logger.warning("unknown learning event type: %s", event_type)
        return None
    try:
        db = _get_db(agent_slug)
        conn = db.get_db()
        with db.write_lock:
            cursor = conn.execute(
                """INSERT INTO learning_events
                   (agent_slug, event_type, source, target, title,
                    before_content, after_content, conversation_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_slug, event_type, source, target, title,
                 before_content, after_content, conversation_id),
            )
            conn.commit()
        return cursor.lastrowid
    except Exception:
        logger.warning("failed to log learning event for %s", agent_slug, exc_info=True)
        return None


def list_events(agent_slug: str, limit: int = 50, offset: int = 0) -> list[dict]:
    db = _get_db(agent_slug)
    conn = db.get_db()
    rows = conn.execute(
        """SELECT id, event_type, source, target, title,
                  substr(before_content, 1, ?) AS before_preview,
                  substr(after_content, 1, ?) AS after_preview,
                  conversation_id, created_at, reverted_at
           FROM learning_events
           WHERE agent_slug = ?
           ORDER BY created_at DESC, id DESC
           LIMIT ? OFFSET ?""",
        (_PREVIEW_CHARS, _PREVIEW_CHARS, agent_slug, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def revert_event(agent_slug: str, event_id: int) -> dict:
    """Undo a learning event. Idempotence guard: refuses if already reverted."""
    from . import service

    db = _get_db(agent_slug)
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM learning_events WHERE id = ? AND agent_slug = ?",
        (event_id, agent_slug),
    ).fetchone()
    if not row:
        return {"error": "learning event not found"}
    event = dict(row)

    etype = event["event_type"]
    target = event["target"]
    if etype == "blocked_injection":
        return {"error": "nothing to revert — this write was already blocked"}
    if etype not in EVENT_TYPES:
        return {"error": f"cannot revert event type: {etype}"}

    # Claim the event atomically before acting so a double-click can't run
    # the revert action twice; released again below if the action fails.
    with db.write_lock:
        cursor = conn.execute(
            "UPDATE learning_events SET reverted_at = datetime('now') "
            "WHERE id = ? AND reverted_at IS NULL",
            (event_id,),
        )
        conn.commit()
    if cursor.rowcount == 0:
        return {"error": "event already reverted"}

    if etype == "playbook_created":
        result = service.archive_playbook(agent_slug, target, origin="user")
    elif etype == "playbook_updated":
        if not event["before_content"]:
            result = {"error": "no previous version stored for this event"}
        elif (service.archive_dir(agent_slug) / f"{target}.md").exists():
            result = {"error": "playbook is archived — restore it first, then revert"}
        else:
            result = service.write_raw(agent_slug, target, event["before_content"])
    elif etype == "playbook_archived":
        result = service.restore_playbook(agent_slug, target)
    else:  # fact_added
        result = _delete_fact(db, target)

    if result.get("error"):
        with db.write_lock:
            conn.execute(
                "UPDATE learning_events SET reverted_at = NULL WHERE id = ?",
                (event_id,),
            )
            conn.commit()
        return result

    return {"id": event_id, "reverted": True}


def _delete_fact(db, target: str) -> dict:
    """Delete a fact created by the review fork (target format: 'fact:{id}')."""
    if not target.startswith("fact:"):
        return {"error": f"invalid fact target: {target}"}
    try:
        fact_id = int(target.split(":", 1)[1])
    except ValueError:
        return {"error": f"invalid fact target: {target}"}
    conn = db.get_db()
    with db.write_lock:
        cursor = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        conn.commit()
    if cursor.rowcount == 0:
        return {"error": "fact no longer exists"}
    db.remove_document("fact", str(fact_id))
    return {"deleted": f"fact:{fact_id}"}
