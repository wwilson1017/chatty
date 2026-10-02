import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from chatty_connector.runner import Connector, Paths, ProcessGroups, Scopes

TOKEN = "test-token"
FIXTURES = Path(__file__).parent / "fixtures"

# A stand-in for `claude`: the prompt (stdin) is a JSON spec of what to do.
FAKE_CLI = r'''
import json, os, subprocess, sys, time
try:
    spec = json.loads(sys.stdin.read())
except ValueError:
    spec = {}
sid = spec.get("sid", "sess-1")
if spec.get("started"):
    with open(spec["started"], "w") as f:
        json.dump({"t": time.time(), "argv": sys.argv, "cwd": os.getcwd()}, f)
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
if spec.get("writer"):
    code = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('x\\n')\n    time.sleep(0.2)"
    subprocess.Popen([sys.executable, "-c", code, spec["writer"]], start_new_session=spec.get("setsid", False),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(spec.get("big", 0)):
    sys.stdout.write(json.dumps({"type": "assistant", "session_id": sid,
                                 "message": {"content": [{"type": "text", "text": "x" * 1000}]}}) + "\n")
sys.stdout.flush()
time.sleep(spec.get("sleep", 0))
if not spec.get("truncate"):
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
                      "result": spec.get("result", "ok"), "total_cost_usd": 0.01, "usage": {}}), flush=True)
sys.exit(spec.get("exit", 0))
'''

HAVE_SYSTEMD = bool(shutil.which("systemd-run")) and Scopes().works()
# Reconciliation stops every chatty-job-*.scope, so never run these next to a live connector.
LIVE_CONNECTOR = HAVE_SYSTEMD and subprocess.run(
    ["systemctl", "--user", "is-active", "--quiet", "chatty-connector"]).returncode == 0
needs_systemd = pytest.mark.skipif(not HAVE_SYSTEMD or LIVE_CONNECTOR,
                                   reason="systemd-run --user unavailable, or a live chatty-connector is running")


class FakeChatty:
    """Just enough of /api/connector to drive the connector, recording everything it sees."""

    def __init__(self):
        self.queue: list[dict] = []
        self.cancel: list = []
        self.polls: list[dict] = []
        self.claimed_at: dict = {}
        self.results: dict = {}
        self.result_times: dict = {}
        self.result_codes: list[int] = []
        self.poll_code = 200
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/connector/health" and self.headers.get("Authorization") == f"Bearer {TOKEN}":
                    return self._send(200, {"ok": True, "generation": 1})
                self._send(401, {"detail": "unauthorized"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/api/connector/pair":
                    return self._send(200, {"token": TOKEN}) if body.get("code") == "123456" else self._send(400, {})
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"detail": "unauthorized"})
                with fake.lock:
                    if self.path == "/api/connector/poll":
                        return self._send(*fake._poll(body))
                    m = re.fullmatch(r"/api/connector/jobs/([^/]+)/result", self.path)
                    if m:
                        code = fake.result_codes.pop(0) if fake.result_codes else 200
                        if code == 200:
                            fake.results.setdefault(m.group(1), body)
                            fake.result_times.setdefault(m.group(1), time.time())
                        return self._send(code, {})
                self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def _poll(self, body):
        self.polls.append({**body, "t": time.time()})
        if self.poll_code != 200:
            return self.poll_code, {"detail": "nope"}
        free = dict(body["free"])
        jobs = []
        for job in list(self.queue):
            if free.get(job["runner"], 0) > 0:
                free[job["runner"]] -= 1
                self.queue.remove(job)
                self.claimed_at[str(job["id"])] = time.time()
                jobs.append(job)
        cancel, self.cancel = self.cancel, []
        return 200, {"jobs": jobs, "cancel": cancel}

    def add_job(self, job_id, spec: dict, runner="claude", mode="safe", workdir_key=None, resume=None):
        with self.lock:
            self.queue.append({"id": job_id, "runner": runner, "mode": mode, "prompt": json.dumps(spec),
                               "resume_session_id": resume, "workdir_key": workdir_key or str(job_id)})


@pytest.fixture
def fake():
    f = FakeChatty()
    yield f
    f.server.shutdown()


@pytest.fixture
def fake_cli(tmp_path):
    path = tmp_path / "fake-claude"
    path.write_text(f"#!{sys.executable}\n{FAKE_CLI}")
    path.chmod(0o755)
    return path


def write_profile(paths: Paths, cli: Path, **top):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    head = "".join(f"{k} = {v}\n" for k, v in {"max_concurrent": 1, "max_codex": 1, **top}.items())
    (paths.config_dir / "profiles.toml").write_text(
        head + f'[claude]\ncommand = "{cli}"\nsafe = ["--safe-flag"]\nfull = ["--full-flag"]\n'
        "timeout = { safe = 60, full = 60 }\n")


@pytest.fixture
def paths(tmp_path, fake_cli):
    p = Paths(tmp_path / "config", tmp_path / "state", tmp_path / "data")
    write_profile(p, fake_cli)
    return p


@pytest.fixture(params=["groups", pytest.param("scopes", marks=needs_systemd)])
def containment(request):
    return ProcessGroups() if request.param == "groups" else Scopes()


def make_connector(fake, paths, containment, token=TOKEN, **kw):
    from chatty_connector.runner import load_profile
    client = httpx.Client(base_url=fake.url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    return Connector(client, load_profile(paths), paths, containment, **kw)


def pump(conn, until, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not until():
        assert time.monotonic() < deadline, "timed out"
        conn.step()
        time.sleep(0.1)


def wait_for(cond, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


def growing(path: Path, window=1.0) -> bool:
    before = path.stat().st_size if path.exists() else 0
    time.sleep(window)
    return (path.stat().st_size if path.exists() else 0) > before


def unit_active(unit: str) -> bool:
    out = subprocess.run(["systemctl", "--user", "show", unit, "-p", "ActiveState", "--value"],
                         capture_output=True, text=True).stdout.strip()
    return out in ("active", "activating", "deactivating")


def connector_process(paths: Paths, extra_path: str | None = None):
    """Run the real CLI (`run`) as a separate process so tests can SIGKILL it."""
    env = {**os.environ,
           "XDG_CONFIG_HOME": str(paths.config_dir.parent),
           "XDG_STATE_HOME": str(paths.state_dir.parent),
           "XDG_DATA_HOME": str(paths.data_dir.parent)}
    if extra_path:
        env["PATH"] = f"{extra_path}:{env['PATH']}"
    return subprocess.Popen([sys.executable, "-m", "chatty_connector.cli", "run", "--interval", "0.2"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def process_paths(tmp_path, fake, fake_cli) -> Paths:
    """Paths as the CLI computes them from the XDG vars connector_process() sets."""
    p = Paths(tmp_path / "xdg-config" / "chatty-connector", tmp_path / "xdg-state" / "chatty-connector",
              tmp_path / "xdg-data" / "chatty-connector")
    write_profile(p, fake_cli)
    (p.config_dir / "config.toml").write_text(f'url = "{fake.url}"\ntoken = "{TOKEN}"\n')
    return p
