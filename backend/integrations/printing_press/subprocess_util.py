"""Shared subprocess execution: hard timeout, process-group kill, output caps.

Used by both ``builder`` (the ``go build`` invocation) and ``runner`` (per-CLI
command calls). Both must (a) bound wall-clock with a timeout, (b) kill the whole
process *group* on timeout — ``go`` and the printed CLIs spawn children — and
(c) cap captured output so a runaway process can't exhaust memory/logs.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


def truncate(text: str, cap: int) -> str:
    """Truncate ``text`` to at most ``cap`` bytes (UTF-8 safe)."""
    if not text:
        return text or ""
    data = text.encode("utf-8", "replace")
    if len(data) <= cap:
        return text
    return data[:cap].decode("utf-8", "replace") + "\n…(truncated)"


def kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the process group of ``proc`` (best-effort, then the proc itself)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def run_capture(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout: float,
    stdout_cap: int = 4 * 1024 * 1024,
    stderr_cap: int = 64 * 1024,
    merge_stderr: bool = False,
) -> ProcResult:
    """Run ``argv`` to completion (or timeout) in its own process group.

    Returns a :class:`ProcResult`. On timeout, the group is killed and
    ``timed_out`` is True with ``returncode`` = -1. Output is captured and
    truncated to the given caps. Never raises for non-zero exits.
    """
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        text=True,
        start_new_session=True,  # own process group → killpg on timeout
    )
    started = time.monotonic()
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        out, err = proc.communicate()
        timed_out = True
    duration = time.monotonic() - started
    return ProcResult(
        returncode=proc.returncode if not timed_out else -1,
        stdout=truncate(out or "", stdout_cap),
        stderr=truncate(err or "", stderr_cap),
        timed_out=timed_out,
        duration_s=duration,
    )
