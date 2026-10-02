"""
Chatty — Claude Code connector API (/api/connector/*) and the card's actions.

The external `chatty-connector` polls OUTBOUND, so nothing on the user's
network is exposed. Auth: a one-time pair code (10 min, rate-limited, stored
hashed) is exchanged for a bearer token, of which only the sha256 is stored.
Every pairing bumps `pair_generation`; jobs are stamped with the generation
that claimed them, so a re-paired or disconnected connector can't post into
jobs it no longer owns.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from core.todo.ratelimit import IPRateLimiter
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from integrations.registry import save_credentials

from . import db
from .tools import build_prompt

logger = logging.getLogger(__name__)

router = APIRouter()

PAIR_CODE_TTL = timedelta(minutes=10)
LOST_AFTER_S = 120
RESULT_MAX_CHARS = 100_000
ERROR_MAX_CHARS = 4000
USAGE_MAX_CHARS = 10_000
CAPABILITIES_TASK = (
    "Describe this environment for the assistant that will delegate work here, in under 300 "
    "words: OS and host, which CLIs and logins are available (git, gh, browsers, cloud CLIs), "
    "which MCP servers and tools you have, and anything you cannot do. Don't change anything."
)

# Burned before the compare, so guessing a pair code costs 10 tries / 5 min / IP.
pair_limiter = IPRateLimiter(window=300, max_hits=10)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _queue_system_job() -> str:
    return db.insert_job(agent_slug="", origin="system", runner="claude", mode="look",
                         task=CAPABILITIES_TASK, prompt=build_prompt("look", CAPABILITIES_TASK))


# ── Card actions (called from the authed integrations router) ────────────────

def create_pair_code() -> dict:
    code = secrets.token_hex(5)
    expires = datetime.now(timezone.utc) + PAIR_CODE_TTL
    with db.write_lock():
        c = db.creds()
        c.update(pair_code_hash=_sha256(code), pair_code_expires_at=expires.isoformat())
        save_credentials("claude_code", c)
    return {"code": code, "expires_at": db.iso_z(expires.isoformat())}


def disconnect() -> dict:
    """Owner disconnect: revoke the token, stop everything. No completion turns."""
    conn = db.get_db()
    with db.write_lock():
        db.set_state("pair_generation", db.generation() + 1, commit=False)
        for key in ("last_seen", "version", "runners", "ceiling"):
            conn.execute("DELETE FROM connector_state WHERE key = ?", (key,))
        conn.commit()
        rows = conn.execute("SELECT id, status FROM jobs WHERE status IN ('queued','pending_approval','running')").fetchall()
        for r in rows:
            if r["status"] == "running":
                db.finish_job(r["id"], "failed", "connector disconnected", notify=False)
            else:
                db.finish_job(r["id"], "cancelled", "connector disconnected", notify=False)
        # The owner's choices survive a disconnect; everything about the pairing goes.
        save_credentials("claude_code", {k: v for k, v in db.creds().items()
                                         if k in ("disabled_agents", "access_level") and v})
    return {"ok": True, "stopped": len(rows)}


def status() -> dict:
    c = db.creds()
    return {
        "paired": bool(c.get("token_hash")),
        "enabled": bool(c.get("enabled")),
        "online": db.is_online(),
        "host": c.get("host", ""),
        "paired_at": db.iso_z(c.get("paired_at")),
        "last_seen": db.iso_z(db.get_state("last_seen")),
        "version": db.get_state("version"),
        "runners": db.get_state("runners", {}),
        "capabilities": db.get_state("capabilities"),
        "disabled_agents": c.get("disabled_agents", []),
        "pair_code_expires_at": db.iso_z(c.get("pair_code_expires_at")),
        "ceiling": db.ceiling(),
        "access_level": db.access_level(),
        "approvals": pending_approvals(),
    }


def pending_approvals() -> list[dict]:
    from .approvals import parent_excerpt
    rows = db.query("SELECT * FROM jobs WHERE status = 'pending_approval' ORDER BY created_at, rowid")
    return [{
        "id": r["id"], "agent_slug": r["agent_slug"], "runner": r["runner"], "task": r["task"],
        "parent_job_id": r["parent_job_id"], "parent_excerpt": parent_excerpt(dict(r)),
        "expires_at": db.iso_z(r["approval_expires_at"]),
    } for r in rows]


def list_jobs(limit: int) -> dict:
    limit = max(1, min(limit, 100))
    rows = db.query("SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
    return {"jobs": [db.job_view(dict(r)) for r in rows]}


def cancel_job(job_id: str) -> dict:
    if not db.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    cancelled = db.finish_job(job_id, "cancelled", "cancelled by owner", notify=False, cancel_requested=1)
    return {"ok": True, "cancelled": cancelled}


def refresh_capabilities() -> dict:
    if not db.creds().get("token_hash"):
        raise HTTPException(status_code=400, detail="Connector is not paired")
    with db.write_lock():
        row = db.get_db().execute(
            "SELECT id FROM jobs WHERE origin = 'system' AND status IN ('queued','running')"
        ).fetchone()
        job_id = row["id"] if row else _queue_system_job()
    return {"ok": True, "job_id": job_id}


def set_disabled_agents(slugs: list[str]) -> dict:
    with db.write_lock():
        c = db.creds()
        c["disabled_agents"] = sorted(set(slugs))
        save_credentials("claude_code", c)
    return {"ok": True, "disabled_agents": c["disabled_agents"]}


def set_access_level(level: str) -> dict:
    with db.write_lock():
        c = db.creds()
        c["access_level"] = level
        save_credentials("claude_code", c)
    return {"ok": True, "access_level": level}


def decide_job(job_id: str, decision: str) -> dict:
    from .approvals import decide
    result = decide(job_id, decision, via="card", decided_by="owner")
    if "error" in result:
        raise HTTPException(status_code=404 if result.get("not_found") else 409, detail=result["error"])
    return result


# ── Connector API ────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def connector_auth(authorization: str = Header("")) -> int:
    """Bearer-token guard. Returns the current pair_generation."""
    token = authorization[7:].strip() if authorization[:7].lower() == "bearer " else ""
    with db.write_lock():  # read hash + generation together so a concurrent /pair can't split them
        stored = db.creds().get("token_hash", "")
        gen = db.generation()
    if not stored or not token or not hmac.compare_digest(_sha256(token), stored):
        raise HTTPException(status_code=401, detail="Invalid connector token")
    return gen


class PairRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    host: str = Field("", max_length=200)


@router.post("/pair")
def pair(body: PairRequest, request: Request):
    if not pair_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many attempts — try again in a few minutes")
    token = secrets.token_urlsafe(32)
    with db.write_lock():
        c = db.creds()
        expires = c.get("pair_code_expires_at")
        live = bool(expires) and datetime.fromisoformat(expires) > datetime.now(timezone.utc)
        if not (live and c.get("pair_code_hash")
                and hmac.compare_digest(_sha256(body.code.strip()), c["pair_code_hash"])):
            raise HTTPException(status_code=401, detail="Invalid or expired pair code")

        gen = db.generation() + 1
        db.set_state("pair_generation", gen)
        for r in db.get_db().execute("SELECT id FROM jobs WHERE status = 'running'").fetchall():
            db.finish_job(r["id"], "failed", "connector re-paired", notify=True)
        c.pop("pair_code_hash", None)
        c.pop("pair_code_expires_at", None)
        c.update(enabled=True, token_hash=_sha256(token), host=body.host,
                 paired_at=datetime.now(timezone.utc).isoformat())
        save_credentials("claude_code", c)
        _queue_system_job()
    logger.info("Claude Code connector paired (host=%s, generation=%d)", body.host, gen)
    return {"token": token, "generation": gen}


@router.get("/health")
def health(gen: int = Depends(connector_auth)):
    return {"ok": True, "generation": gen}


class PollRequest(BaseModel):
    version: str = Field("", max_length=100)
    runners: dict[str, dict] = Field(default_factory=dict)
    free: dict[str, int] = Field(default_factory=dict)
    running: list[str] = Field(default_factory=list, max_length=1000)
    ceiling: Literal["look", "sandbox", "full"] | None = None  # None: a 0.1.x connector — it claims nothing


def _cancel_at_claim(job: dict, reason: str) -> None:
    db.finish_job(job["id"], "cancelled", reason, notify=job["origin"] != "system")


@router.post("/poll")
def poll(body: PollRequest, gen: int = Depends(connector_auth)):
    conn = db.get_db()
    owned = set(body.running)
    claimed: list[dict] = []
    with db.write_lock():
        if gen != db.generation():  # re-paired after this request authenticated
            raise HTTPException(status_code=401, detail="Invalid connector token")
        db.set_state("last_seen", time.time(), commit=False)
        db.set_state("version", body.version, commit=False)
        db.set_state("ceiling", body.ceiling, commit=False)
        db.set_state("runners", {k: {"resume": bool(v.get("resume"))} for k, v in list(body.runners.items())[:10]},
                     commit=False)
        if owned:
            marks = ",".join("?" * len(owned))
            conn.execute(
                f"UPDATE jobs SET last_reported_at = datetime('now') WHERE status = 'running' "
                f"AND pair_generation = ? AND id IN ({marks})",
                (gen, *owned),
            )
        conn.commit()

        # Lost: claimed by this pairing, no longer owned by the connector. Never re-run — it may have acted.
        for r in conn.execute(
            "SELECT id FROM jobs WHERE status = 'running' AND pair_generation = ? "
            "AND claimed_at < datetime('now', ?)",
            (gen, f"-{LOST_AFTER_S} seconds"),
        ).fetchall():
            if r["id"] not in owned:
                db.finish_job(r["id"], "failed", "lost by connector", notify=True)

        # Ids the connector still owns that the server no longer considers running → stop them.
        cancel = []
        for jid in owned:
            row = conn.execute("SELECT status, pair_generation FROM jobs WHERE id = ?", (jid,)).fetchone()
            if not row or row["status"] != "running" or row["pair_generation"] != gen:
                cancel.append(jid)

        free = {k: max(0, int(v)) for k, v in body.free.items()}
        enabled = bool(db.creds().get("enabled"))
        disabled_agents = set(db.creds().get("disabled_agents") or [])
        access = db.level_rank(db.access_level())
        top = db.level_rank(body.ceiling)
        for row in conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at, rowid"
        ).fetchall() if body.ceiling else ():
            job = dict(row)
            if free.get(job["runner"], 0) <= 0:
                continue
            # 1. Policy re-checked at claim time.
            if not enabled or (job["origin"] != "system" and job["agent_slug"] in disabled_agents):
                _cancel_at_claim(job, "Claude Code was disabled for this agent")
                continue
            # 2. Follow-ups resume a session that only exists on the pairing that ran the parent.
            parent = db.get_job(job["parent_job_id"]) if job["parent_job_id"] else None
            if job["parent_job_id"] and (not parent or parent["pair_generation"] != gen):
                _cancel_at_claim(job, "that workspace is on a previous connector")
                continue
            # 3. Levels re-checked at claim: the machine's ceiling, then the owner's access level.
            if db.level_rank(job["mode"]) > top:
                _cancel_at_claim(job, "above this machine's ceiling")
                continue
            if db.level_rank(job["mode"]) > access:
                _cancel_at_claim(job, "access level lowered")
                continue
            # 4. Full jobs run only with an approval bound to this exact prompt.
            if job["mode"] == "full" and not (
                job["decision"] == "full"
                and job["approved_prompt_sha256"]
                and hmac.compare_digest(_sha256(job["prompt"]), job["approved_prompt_sha256"])
            ):
                _cancel_at_claim(job, "full access was not approved")
                continue
            # 5. One job at a time per chain (same session + working directory).
            if conn.execute(
                "SELECT 1 FROM jobs WHERE root_job_id = ? AND status = 'running'", (job["root_job_id"],)
            ).fetchone():
                continue
            conn.execute(
                "UPDATE jobs SET status = 'running', claimed_at = datetime('now'), pair_generation = ? "
                "WHERE id = ? AND status = 'queued'",
                (gen, job["id"]),
            )
            conn.commit()
            free[job["runner"]] -= 1
            claimed.append({
                "id": job["id"],
                "runner": job["runner"],
                "mode": job["mode"],
                "prompt": job["prompt"],
                "resume_session_id": parent["session_id"] if parent else None,
                "workdir_key": job["root_job_id"],
            })
    return {"jobs": claimed, "cancel": cancel}


class ResultRequest(BaseModel):
    status: Literal["done", "failed", "cancelled"]
    result_text: str = ""
    session_id: str | None = Field(None, max_length=200)
    usage: dict | None = None
    error: str | None = None


@router.post("/jobs/{job_id}/result")
def post_result(job_id: str, body: ResultRequest, gen: int = Depends(connector_auth)):
    with db.write_lock():
        job = db.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] in db.TERMINAL_STATUSES:
            return {"ok": True, "accepted": False}  # first terminal write wins; retries are no-ops
        if job["status"] != "running" or job["pair_generation"] != gen:
            raise HTTPException(status_code=409, detail="Job is not running on this connector")

        usage = json.dumps(body.usage) if body.usage else None
        fields = {
            "result_text": body.result_text[:RESULT_MAX_CHARS],
            "session_id": body.session_id or None,
            "usage_json": usage if usage and len(usage) <= USAGE_MAX_CHARS else None,
            "error": (body.error or "")[:ERROR_MAX_CHARS] or None,
        }
        reason = body.error[:200] if body.error else body.status
        if job["origin"] == "system":
            accepted = db.finish_job(job_id, body.status, reason, notify=False,
                                     running_generation=gen, commit=False, **fields)
            if accepted and body.status == "done":
                db.set_state("capabilities", fields["result_text"][:20000], commit=False)
            db.get_db().commit()
        else:
            accepted = db.finish_job(job_id, body.status, reason, notify=True,
                                     running_generation=gen, **fields)
    return {"ok": True, "accepted": accepted}
