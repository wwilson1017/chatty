"""In-memory build-job registry — runs CLI builds off the request worker.

``POST /install`` returns in milliseconds with a ``build_id``; the actual
fetch→toolchain→build (tens of seconds) runs on a module-level
``ThreadPoolExecutor(max_workers=1)`` so it never holds the single gunicorn
worker (``--timeout 120``) and only one build runs at a time (bounds CPU/RAM).

State is in-memory and assumes a single worker (the deployment runs
``--workers 1``). In-flight builds are lost on restart — the *durable* outcome is
``install.json`` + the binary on the volume, so a lost build is simply
re-triggered; completed installs persist. Build logs have a TTL so the registry
doesn't grow without bound.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from . import builder, library_client, store

logger = logging.getLogger(__name__)

# Build lifecycle (job-level; the install record tracks its own build_status).
QUEUED = "queued"
RUNNING = "running"
SUCCESS = "success"
ERROR = "error"

_JOB_TTL_SECONDS = 3600  # prune finished jobs after an hour
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pp-build")
_jobs: dict[str, "BuildJob"] = {}
_lock = threading.Lock()


@dataclass
class BuildJob:
    build_id: str
    slug: str
    category: str
    ref: str
    status: str = QUEUED
    log: list[dict] = field(default_factory=list)   # [{phase, msg}]
    error: str | None = None
    created_at: float = 0.0
    finished_at: float | None = None

    @property
    def done(self) -> bool:
        return self.status in (SUCCESS, ERROR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id, "slug": self.slug, "category": self.category,
            "ref": self.ref, "status": self.status, "log": list(self.log),
            "error": self.error,
        }


def _prune_locked(now: float) -> None:
    stale = [
        bid for bid, j in _jobs.items()
        if j.finished_at and (now - j.finished_at) > _JOB_TTL_SECONDS
    ]
    for bid in stale:
        _jobs.pop(bid, None)


def get_job(build_id: str) -> BuildJob | None:
    return _jobs.get(build_id)


def submit_build(slug: str, category: str, ref: str = "main") -> str:
    """Queue a build on the single-worker pool. Returns the build_id immediately."""
    now = time.time()
    build_id = uuid.uuid4().hex
    job = BuildJob(build_id=build_id, slug=slug, category=category, ref=ref, created_at=now)
    with _lock:
        _prune_locked(now)
        _jobs[build_id] = job
    _executor.submit(_run_build, job)
    logger.info("queued printed-CLI build %s for %s@%s", build_id, slug, ref)
    return build_id


def _run_build(job: BuildJob) -> None:
    def progress(phase: str, msg: str) -> None:
        job.log.append({"phase": phase, "msg": msg})

    job.status = RUNNING
    try:
        info = library_client.fetch_source(job.slug, job.category, ref=job.ref, progress=progress)
        res = builder.go_build(job.slug, info["src"], progress=progress)
        manifest = library_client.read_manifest(info["src"])
        auth = manifest.get("auth", {}) or {}

        store.save_manifest(job.slug, manifest)
        existing = store.get_install(job.slug)
        record = existing or store.Install(slug=job.slug, category=job.category, ref=job.ref, sha=info["sha"])
        record.category = job.category
        record.ref = job.ref
        record.sha = info["sha"]
        record.api_name = manifest.get("api_name", job.slug)
        record.description = manifest.get("description", "")
        record.base_url = manifest.get("base_url", "")
        record.auth = {"type": auth.get("type"), "env_vars": auth.get("env_vars", []),
                       "key_url": auth.get("key_url", "")}
        record.tool_count = len(manifest.get("tools", []))
        record.binary = str(res["binary"])
        record.build_status = store.BUILD_READY
        record.build_error = None
        store.save_install(record)

        # Append the terminal log line BEFORE flipping status, so an SSE tail that
        # keys off `done` never misses the last entry.
        progress("done", f"installed {record.api_name} ({record.tool_count} commands)")
        job.status = SUCCESS
    except Exception as exc:  # noqa: BLE001 — surface any build failure to the user
        logger.warning("printed-CLI build %s failed: %s", job.build_id, exc)
        job.error = str(exc)
        progress("error", str(exc))
        job.status = ERROR
        try:
            store.update_install(job.slug, build_status=store.BUILD_ERROR, build_error=str(exc)[:2000])
        except Exception:
            logger.debug("could not mark install errored for %s", job.slug, exc_info=True)
    finally:
        job.finished_at = time.time()
