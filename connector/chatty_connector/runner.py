"""Job execution: durable state files, per-job containment and the poll loop."""

import ctypes
import fcntl
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import tomllib

from . import __version__

log = logging.getLogger("chatty_connector")

RUNNERS = ("claude", "codex")
LEVELS = ("look", "sandbox", "full")  # lowest to highest
RESULT_CAP = 100_000
LINE_LIMIT = 4 * 1024 * 1024
STDERR_TAIL = 2000
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class Revoked(Exception):
    """Chatty rejected the token (disconnected or re-paired)."""


@dataclass
class Paths:
    config_dir: Path
    state_dir: Path
    data_dir: Path

    @classmethod
    def default(cls) -> "Paths":
        home = Path.home()
        env = os.environ.get
        return cls(
            Path(env("XDG_CONFIG_HOME") or home / ".config") / "chatty-connector",
            Path(env("XDG_STATE_HOME") or home / ".local/state") / "chatty-connector",
            Path(env("XDG_DATA_HOME") or home / ".local/share") / "chatty-connector",
        )

    @property
    def job_states(self) -> Path:
        return self.state_dir / "jobs"

    @property
    def workdirs(self) -> Path:
        return self.data_dir / "jobs"


# --- profiles and argv ------------------------------------------------------

def load_profile(paths: Paths) -> dict:
    with open(paths.config_dir / "profiles.toml", "rb") as f:
        profile = tomllib.load(f)
    if "ceiling" not in profile or any("safe" in profile.get(r, {}) for r in RUNNERS):
        raise ValueError("profiles.toml is from connector 0.1.0. Run `chatty-connector setup` to update it.")
    if profile["ceiling"] not in LEVELS:
        raise ValueError(f"ceiling must be one of {', '.join(LEVELS)}")
    if "claude" not in profile and "codex" not in profile:
        raise ValueError("profiles.toml has neither a [claude] nor a [codex] section")
    for runner in RUNNERS:
        p = profile.get(runner)
        if p is None:
            continue
        for mode in LEVELS:
            if not isinstance(p.get(mode), list) or not all(isinstance(a, str) for a in p[mode]):
                raise ValueError(f"[{runner}] {mode} must be a list of strings")
            if not isinstance(p.get("timeout", {}).get(mode), int):
                raise ValueError(f"[{runner}] timeout.{mode} must be an integer (seconds)")
    return profile


def runner_command(profile: dict, runner: str) -> str:
    return profile[runner].get("command", runner)


def available_runners(profile: dict) -> dict:
    return {
        r: {"resume": bool(profile[r].get("resume", r == "claude"))}
        for r in RUNNERS
        if r in profile and shutil.which(runner_command(profile, r))
    }


def _extra(profile: dict, runner: str, mode: str, config_dir: Path) -> list[str]:
    return [a.replace("{config_dir}", str(config_dir)) for a in profile[runner][mode]]


def build_claude_argv(profile: dict, mode: str, resume_session_id: str | None, config_dir: Path) -> list[str]:
    argv = [runner_command(profile, "claude"), "-p", "--output-format", "stream-json", "--verbose"]
    argv += _extra(profile, "claude", mode, config_dir)
    if resume_session_id:
        argv += ["--resume", resume_session_id]
    return argv


def build_codex_argv(profile: dict, mode: str, resume_session_id: str | None, config_dir: Path) -> list[str]:
    argv = [runner_command(profile, "codex"), "exec"]
    if resume_session_id:
        argv += ["resume", resume_session_id]
    argv += ["--json", "--skip-git-repo-check", *_extra(profile, "codex", mode, config_dir), "-"]
    return argv


BUILDERS = {"claude": build_claude_argv, "codex": build_codex_argv}


# --- output parsing ---------------------------------------------------------

class StreamParser:
    """Reads claude stream-json / codex JSONL events one line at a time."""

    def __init__(self, runner: str):
        self.runner = runner
        self.session_id = None
        self.result = None
        self.is_error = False
        self.error = None
        self.usage = None
        self._partial: list[str] = []
        self._partial_len = 0

    def feed(self, line: bytes | str) -> None:
        try:
            ev = json.loads(line)
        except ValueError:
            return  # blank, non-JSON, or a fragment of an over-long line
        if isinstance(ev, dict):
            (self._claude if self.runner == "claude" else self._codex)(ev)

    def _text(self, s: str) -> None:
        room = RESULT_CAP - self._partial_len
        if room > 0 and s:
            self._partial.append(s[:room])
            self._partial_len += min(len(s), room)

    def _claude(self, ev: dict) -> None:
        self.session_id = self.session_id or ev.get("session_id")
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    self._text(block.get("text") or "")
        elif ev.get("type") == "result":
            self.result = ev.get("result")
            self.is_error = bool(ev.get("is_error"))
            denials = ev.get("permission_denials") or []
            self.usage = {
                "total_cost_usd": ev.get("total_cost_usd"),
                "usage": ev.get("usage"),
                "num_turns": ev.get("num_turns"),
                "duration_ms": ev.get("duration_ms"),
                "permission_denials": [d.get("tool_name") for d in denials if isinstance(d, dict)][:50],
            }

    def _codex(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "thread.started":
            self.session_id = self.session_id or ev.get("thread_id")
        elif t == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message":
                self.result = item.get("text")
                self._text((item.get("text") or "") + "\n")
        elif t == "turn.completed":
            self.usage = {"usage": ev.get("usage")}
        elif t == "turn.failed":
            self.is_error = True
            self.error = str(ev.get("error"))[:STDERR_TAIL]

    @property
    def text(self) -> str:
        text = self.result if isinstance(self.result, str) else "".join(self._partial)
        return text[:RESULT_CAP]


def drain(stream, parser: StreamParser) -> None:
    """Read to EOF so the child never blocks on a full pipe; parsing is bounded by the parser."""
    while line := stream.readline(LINE_LIMIT):
        parser.feed(line)


# --- containment ------------------------------------------------------------

_libc = ctypes.CDLL(None, use_errno=True) if sys.platform.startswith("linux") else None


def _die_with_parent() -> None:
    # PR_SET_PDEATHSIG = 1. Fires when the spawning *thread* exits; job threads outlive their child.
    _libc.prctl(1, signal.SIGKILL)


def _wait_until(cond, timeout: float, step: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            return False
        time.sleep(step)
    return True


class Scopes:
    """Linux: each job is a transient systemd user scope; stopping it kills the whole cgroup."""

    def __init__(self, systemd_run: str = "systemd-run", systemctl: str = "systemctl"):
        self.systemd_run = systemd_run
        self.systemctl = systemctl

    def handle(self, job_id: str) -> str:
        return f"chatty-job-{job_id}.scope"

    def spawn(self, argv, handle, cwd, stderr) -> subprocess.Popen:
        cmd = [self.systemd_run, "--user", "--scope", "--quiet", "--collect", f"--unit={handle}",
               "-p", "TimeoutStopSec=10", "--", *argv]
        return subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=stderr, preexec_fn=_die_with_parent)

    def wait_started(self, handle, proc) -> bool:
        return _wait_until(lambda: proc.poll() is not None or self._state(handle) == "active", 15)

    def alive(self, handle) -> bool:
        return self._state(handle) in ("active", "activating", "deactivating", "reloading")

    def stop(self, handle, proc=None) -> None:
        subprocess.run([self.systemctl, "--user", "stop", handle], capture_output=True, timeout=60)
        if not _wait_until(lambda: not self.alive(handle), 30):
            raise RuntimeError(f"{handle} did not stop")

    def leftovers(self) -> list[str]:
        out = subprocess.run([self.systemctl, "--user", "list-units", "--all", "--plain", "--no-legend",
                              "chatty-job-*.scope"], capture_output=True, text=True).stdout
        return [line.split()[0] for line in out.splitlines() if line.strip()]

    def _state(self, handle) -> str:
        return subprocess.run([self.systemctl, "--user", "show", handle, "-p", "ActiveState", "--value"],
                              capture_output=True, text=True).stdout.strip()

    def works(self) -> bool:
        try:
            return subprocess.run([self.systemd_run, "--user", "--scope", "--quiet", "--collect", "true"],
                                  capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


class ProcessGroups:
    """macOS and --no-containment: one process group per job, killed with killpg.
    # simplification: grandchildren that call setsid() escape, and a recorded pgid could be
    # reused after a reboot; upgrade path is a launchd-per-job agent if a Mac user needs hard containment."""

    def handle(self, job_id: str):
        return None  # the pgid is only known after spawn

    def spawn(self, argv, handle, cwd, stderr) -> subprocess.Popen:
        return subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                start_new_session=True, preexec_fn=_die_with_parent if _libc else None)

    def wait_started(self, handle, proc) -> bool:
        return True

    def alive(self, pgid) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True

    def stop(self, pgid, proc=None) -> None:
        def gone():
            if proc is not None:
                proc.poll()  # reap the leader, or its zombie keeps the group alive
            return not self.alive(pgid)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return
            if _wait_until(gone, 10):
                return
        raise RuntimeError(f"process group {pgid} did not exit")

    def leftovers(self) -> list:
        return []


# --- jobs and the loop ------------------------------------------------------

@dataclass
class Job:
    data: dict  # exactly what is persisted in <state>/jobs/<id>.json
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def state(self) -> str:
        return self.data["state"]

    @property
    def busy(self) -> bool:
        """True from the moment it is started until its scope/group has fully exited."""
        return self.thread is not None and self.thread.is_alive()


def _failed(error: str, parser: StreamParser | None = None) -> dict:
    return {"status": "failed", "result_text": parser.text if parser else "",
            "session_id": parser.session_id if parser else None,
            "usage": parser.usage if parser else None, "error": error}


class Connector:
    def __init__(self, client: httpx.Client, profile: dict, paths: Paths, containment,
                 restart_recheck: float = 5.0):
        self.client = client
        self.profile = profile
        self.paths = paths
        self.containment = containment
        self.restart_recheck = restart_recheck
        self.jobs: dict[str, Job] = {}
        self._lock_fd = None
        paths.job_states.mkdir(parents=True, exist_ok=True)
        paths.workdirs.mkdir(parents=True, exist_ok=True)

    # durable state

    def lock(self) -> None:
        fd = os.open(self.paths.state_dir / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise RuntimeError(f"another chatty-connector is already running ({self.paths.state_dir})") from None
        self._lock_fd = fd

    def _state_path(self, job_id: str) -> Path:
        return self.paths.job_states / f"{job_id}.json"

    def _save(self, job: Job, **changes) -> None:
        job.data.update(changes)
        path = self._state_path(job.id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(job.data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _forget(self, job_id: str) -> None:
        self._state_path(job_id).unlink(missing_ok=True)
        (self.paths.job_states / f"{job_id}.stderr").unlink(missing_ok=True)
        self.jobs.pop(job_id, None)

    def owned_ids(self) -> list:
        return [json.loads(p.read_text())["id"] for p in sorted(self.paths.job_states.glob("*.json"))]

    def reconcile(self) -> None:
        """After a restart: stop every leftover job and report it failed before claiming anything new."""
        for unit in self.containment.leftovers():
            self.containment.stop(unit)
        jobs = [Job(json.loads(p.read_text())) for p in sorted(self.paths.job_states.glob("*.json"))]
        if any(j.state == "starting" for j in jobs):
            time.sleep(self.restart_recheck)  # a launcher racing its death signal has registered by now
        for job in jobs:
            self.jobs[job.id] = job
            if job.state == "result":
                continue
            handle = job.data.get("handle")
            if handle is not None and self.containment.alive(handle):
                self.containment.stop(handle)
            self._save(job, state="result", result=_failed("connector restarted"))

    # talking to Chatty

    def free(self) -> dict:
        active = [j for j in self.jobs.values() if j.state != "result"]
        runners = available_runners(self.profile)
        total = max(0, self.profile.get("max_concurrent", 1) - len(active))
        codex = max(0, self.profile.get("max_codex", 1) - sum(j.data["runner"] == "codex" for j in active))
        return {"claude": total if "claude" in runners else 0,
                "codex": min(total, codex) if "codex" in runners else 0}

    def poll(self) -> None:
        body = {"version": __version__, "ceiling": self.profile["ceiling"], "runners": available_runners(self.profile),
                "free": self.free(), "running": self.owned_ids()}
        r = self.client.post("/api/connector/poll", json=body)
        if r.status_code in (401, 403):
            raise Revoked()
        r.raise_for_status()
        data = r.json()
        for job_id in data.get("cancel") or []:
            self.cancel(str(job_id))
        for spec in data.get("jobs") or []:
            self.accept(spec)

    def accept(self, spec: dict) -> None:
        job_id, key = str(spec.get("id")), str(spec.get("workdir_key"))
        if not (ID_RE.fullmatch(job_id) and ID_RE.fullmatch(key) and spec.get("runner") in RUNNERS
                and spec.get("mode") in LEVELS and isinstance(spec.get("prompt"), str)):
            log.error("ignoring malformed job from Chatty: %r", {k: spec.get(k) for k in ("id", "runner", "mode")})
            return
        if job_id in self.jobs:
            return
        job = Job({"id": spec["id"], "runner": spec["runner"], "mode": spec["mode"], "prompt": spec["prompt"],
                   "resume_session_id": spec.get("resume_session_id") or None, "workdir_key": key,
                   "state": "waiting"})
        self.jobs[job_id] = job
        if LEVELS.index(spec["mode"]) > LEVELS.index(self.profile["ceiling"]):
            # Chatty should never send this; the machine's ceiling is enforced here regardless
            self._save(job, state="result", result=_failed("above this machine's ceiling"))
            log.warning("refused job %s: %s is above this machine's ceiling (%s)", job_id, spec["mode"],
                        self.profile["ceiling"])
            return
        self._save(job)
        log.info("claimed job %s (%s, %s)", job_id, job.data["runner"], job.data["mode"])

    def cancel(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None or job.state == "result":
            return
        log.info("cancelling job %s", job_id)
        if job.thread is None:
            self._save(job, state="result", result={**_failed("cancelled"), "status": "cancelled"})
        else:
            job.cancel.set()

    def flush_outbox(self) -> None:
        for job in [j for j in self.jobs.values() if j.state == "result" and not j.busy]:
            try:
                r = self.client.post(f"/api/connector/jobs/{job.id}/result", json=job.data["result"])
            except httpx.HTTPError as e:
                log.warning("result upload for job %s failed, will retry: %s", job.id, e)
                continue
            if r.is_success:
                self._forget(job.id)
            elif r.status_code < 500:  # 401/403 = token rotated; other 4xx won't succeed on retry
                log.error("Chatty refused the result for job %s (HTTP %s); dropping it", job.id, r.status_code)
                self._forget(job.id)
            else:
                log.warning("result upload for job %s got HTTP %s, will retry", job.id, r.status_code)

    def start_ready(self) -> None:
        running = [j for j in self.jobs.values() if j.busy]
        busy = {j.data["workdir_key"] for j in running}
        slots = self.profile.get("max_concurrent", 1) - len(running)
        codex_slots = self.profile.get("max_codex", 1) - sum(j.data["runner"] == "codex" for j in running)
        for job in list(self.jobs.values()):
            if job.state != "waiting" or job.thread is not None:
                continue
            if job.data["workdir_key"] in busy:
                continue  # an earlier job in this workspace has not fully exited yet
            # free() offers a slot per runner, so the server can hand us more than the cap; extras wait here
            if slots <= 0 or (job.data["runner"] == "codex" and codex_slots <= 0):
                continue
            slots -= 1
            codex_slots -= job.data["runner"] == "codex"
            busy.add(job.data["workdir_key"])
            job.thread = threading.Thread(target=self._execute, args=(job,), daemon=True)
            job.thread.start()

    def revoke(self) -> None:
        """Token rejected: stop everything we own, forget it, and let the caller halt."""
        for job in self.jobs.values():
            job.cancel.set()
        for job in self.jobs.values():
            if job.thread is not None:
                job.thread.join()
        for path in self.paths.job_states.glob("*"):
            path.unlink(missing_ok=True)
        self.jobs.clear()

    def step(self) -> None:
        self.flush_outbox()
        self.poll()
        self.start_ready()

    def run(self, interval: float = 5.0) -> None:
        self.lock()
        self.reconcile()
        delay = interval
        while True:
            try:
                self.step()
                delay = interval
            except Revoked:
                self.revoke()
                raise
            except (httpx.HTTPError, ValueError) as e:
                delay = min(delay * 2, 60)
                log.warning("poll failed (%s); retrying in %.0fs", e, delay)
                self.start_ready()
            time.sleep(delay)

    # one job

    def _execute(self, job: Job) -> None:
        try:
            result = self._run(job)
        except Exception as e:
            log.exception("job %s crashed", job.id)
            result = _failed(f"connector error: {e}")
        self._save(job, state="result", result=result)
        log.info("job %s finished: %s", job.id, result["status"])

    def _run(self, job: Job) -> dict:
        d = job.data
        workdir = self.paths.workdirs / d["workdir_key"]
        if d["resume_session_id"] and not workdir.is_dir():
            return _failed("workspace missing")
        workdir.mkdir(parents=True, exist_ok=True)
        argv = BUILDERS[d["runner"]](self.profile, d["mode"], d["resume_session_id"], self.paths.config_dir)
        timeout = self.profile[d["runner"]]["timeout"][d["mode"]]

        handle = self.containment.handle(job.id)
        self._save(job, state="starting", handle=handle)
        if job.cancel.is_set():
            return {**_failed("cancelled"), "status": "cancelled"}
        err_path = self.paths.job_states / f"{job.id}.stderr"
        with open(err_path, "wb") as err:
            proc = self.containment.spawn(argv, handle, workdir, err)
        if handle is None:
            handle = proc.pid
        if not self.containment.wait_started(handle, proc):
            self.containment.stop(handle, proc)
            proc.wait()
            return _failed("job did not start")
        self._save(job, state="running", handle=handle)

        parser = StreamParser(d["runner"])
        reader = threading.Thread(target=drain, args=(proc.stdout, parser), daemon=True)
        reader.start()
        try:
            proc.stdin.write(d["prompt"].encode())
            proc.stdin.close()
        except BrokenPipeError:
            pass

        deadline = time.monotonic() + timeout
        reason = None
        while proc.poll() is None:
            if job.cancel.is_set():
                reason = "cancelled"
                break
            if time.monotonic() > deadline:
                reason = "timeout"
                break
            job.cancel.wait(0.5)
        # Stop the scope even after a clean exit: it kills detached descendants still writing.
        self.containment.stop(handle, proc)
        proc.wait()
        reader.join()

        if reason == "cancelled":
            return {**_failed("cancelled", parser), "status": "cancelled"}
        if reason == "timeout":
            return _failed("timeout", parser)
        if proc.returncode == 0 and parser.result is not None and not parser.is_error:
            return {"status": "done", "result_text": parser.text, "session_id": parser.session_id,
                    "usage": parser.usage, "error": None}
        stderr = err_path.read_bytes()[-STDERR_TAIL:].decode(errors="replace").strip()
        error = parser.error or (parser.text if parser.is_error else "") or stderr or f"exit code {proc.returncode}"
        return _failed(error[:STDERR_TAIL], parser)
