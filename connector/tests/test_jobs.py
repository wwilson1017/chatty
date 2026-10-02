import json
import subprocess

from chatty_connector.runner import Scopes
from conftest import (
    growing,
    make_connector,
    needs_systemd,
    pump,
    unit_active,
    wait_for,
    write_profile,
)


def test_job_runs_in_its_workdir_and_posts_result(fake, paths, containment, tmp_path):
    started = tmp_path / "started.json"
    fake.add_job(1, {"started": str(started), "result": "all done", "sid": "s-1"})
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: "1" in fake.results)
    assert fake.results["1"] == {"status": "done", "result_text": "all done", "session_id": "s-1",
                                 "usage": fake.results["1"]["usage"], "error": None}
    info = json.loads(started.read_text())
    assert info["cwd"] == str(paths.workdirs / "1")
    assert info["argv"][1:] == ["-p", "--output-format", "stream-json", "--verbose", "--safe-flag"]
    pump(conn, lambda: not list(paths.job_states.glob("*.json")))
    assert fake.polls[-1]["running"] == []


def test_output_past_cap_is_drained(fake, paths, containment):
    fake.add_job(1, {"big": 3000, "result": "fine"})  # ~3 MB on stdout
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: "1" in fake.results)
    assert fake.results["1"]["status"] == "done" and fake.results["1"]["result_text"] == "fine"


def test_truncated_stream_fails_with_partial_text(fake, paths, containment):
    fake.add_job(1, {"big": 2, "truncate": True, "exit": 1})
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: "1" in fake.results)
    r = fake.results["1"]
    assert r["status"] == "failed" and r["session_id"] == "sess-1" and r["result_text"].startswith("x" * 1000)


def test_follow_up_resumes_in_same_dir_or_fails_if_missing(fake, paths, containment, tmp_path):
    started = tmp_path / "started.json"
    fake.add_job(2, {}, workdir_key="gone", resume="s-9")
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: "2" in fake.results)
    assert fake.results["2"]["status"] == "failed" and fake.results["2"]["error"] == "workspace missing"
    assert not (paths.workdirs / "gone").exists()

    (paths.workdirs / "root").mkdir()
    fake.add_job(3, {"started": str(started)}, workdir_key="root", resume="s-9")
    pump(conn, lambda: "3" in fake.results)
    info = json.loads(started.read_text())
    assert info["argv"][-2:] == ["--resume", "s-9"] and info["cwd"] == str(paths.workdirs / "root")


def test_timeout_posts_failed_with_session(fake, paths, containment):
    fake.add_job(1, {"sleep": 30, "sid": "s-t"})
    conn = make_connector(fake, paths, containment)
    conn.profile["claude"]["timeout"]["safe"] = 1
    pump(conn, lambda: "1" in fake.results)
    assert fake.results["1"]["status"] == "failed" and fake.results["1"]["error"] == "timeout"
    assert fake.results["1"]["session_id"] == "s-t"


def test_outbox_retries_while_polls_keep_listing_the_job(fake, paths, containment):
    # Server-side lost-job detection fires when a claimed job is missing from `running`;
    # every poll until the result is accepted must list it.
    fake.result_codes = [500, 500, 500, 500]
    fake.add_job(1, {})
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: "1" in fake.results)
    claimed = fake.claimed_at["1"]
    accepted = fake.result_times["1"]
    between = [p for p in fake.polls if claimed < p["t"] < accepted]
    assert len(between) >= 4
    assert all(1 in p["running"] for p in between)
    assert fake.result_codes == []


def test_result_401_drops_entry(fake, paths, containment):
    fake.result_codes = [401]
    fake.add_job(1, {})
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: fake.result_codes == [] and not list(paths.job_states.glob("*.json")))
    conn.step()
    assert fake.results == {} and fake.polls[-1]["running"] == []


def test_free_counts_locally_waiting_jobs(fake, paths, containment, fake_cli):
    write_profile(paths, fake_cli, max_concurrent=2)
    fake.add_job(1, {"sleep": 30}, workdir_key="k")
    fake.add_job(2, {"sleep": 30}, workdir_key="k")
    conn = make_connector(fake, paths, containment)
    conn.step()
    assert fake.polls[-1]["free"]["claude"] == 2
    conn.step()
    assert fake.polls[-1]["free"]["claude"] == 0 and sorted(fake.polls[-1]["running"]) == [1, 2]
    fake.cancel = [1, 2]
    pump(conn, lambda: {"1", "2"} <= set(fake.results))


def test_cancel_a_then_b_waits_for_a_to_exit(fake, paths, containment, fake_cli, tmp_path):
    write_profile(paths, fake_cli, max_concurrent=2)
    writer = tmp_path / "a-writer"
    b_started = tmp_path / "b-started.json"
    fake.add_job("a", {"sleep": 60, "writer": str(writer)}, workdir_key="root")
    conn = make_connector(fake, paths, containment)
    pump(conn, lambda: conn.jobs.get("a") and conn.jobs["a"].state == "running" and writer.exists())

    fake.cancel = ["a"]
    fake.add_job("b", {"started": str(b_started)}, workdir_key="root")
    conn.step()
    assert "b" in conn.jobs and not b_started.exists()
    pump(conn, lambda: b_started.exists())
    assert writer.stat().st_mtime <= json.loads(b_started.read_text())["t"]
    assert not growing(writer)
    pump(conn, lambda: {"a", "b"} <= set(fake.results))
    assert fake.results["a"]["status"] == "cancelled" and fake.results["b"]["status"] == "done"


def write_state(paths, job_id, state, **extra):
    paths.job_states.mkdir(parents=True, exist_ok=True)
    data = {"id": job_id, "runner": "claude", "mode": "safe", "prompt": "{}", "resume_session_id": None,
            "workdir_key": str(job_id), "state": state, **extra}
    (paths.job_states / f"{job_id}.json").write_text(json.dumps(data))


def test_restart_reconciliation_each_crash_point(fake, paths, containment):
    write_state(paths, 1, "waiting")
    write_state(paths, 2, "starting", handle=containment.handle("2"))  # crashed before the spawn
    write_state(paths, 3, "result", result={"status": "done", "result_text": "kept", "session_id": "s",
                                            "usage": None, "error": None})
    fake.add_job(4, {})
    conn = make_connector(fake, paths, containment, restart_recheck=0.2)
    conn.reconcile()
    assert fake.polls == []  # nothing claimed during reconciliation
    pump(conn, lambda: {"1", "2", "3", "4"} <= set(fake.results))
    assert fake.results["1"]["error"] == fake.results["2"]["error"] == "connector restarted"
    assert fake.results["3"]["result_text"] == "kept"
    assert fake.claimed_at["4"] > max(fake.result_times[k] for k in ("1", "2", "3"))


@needs_systemd
def test_reconcile_stops_surviving_scope(fake, paths, tmp_path):
    scopes = Scopes()
    writer = tmp_path / "w"
    code = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('x')\n    time.sleep(0.2)"
    proc = subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", "--collect",
                             "--unit=chatty-job-77.scope", "--", "python3", "-c", code, str(writer)])
    wait_for(lambda: unit_active("chatty-job-77.scope") and writer.exists())
    write_state(paths, 77, "running", handle="chatty-job-77.scope")
    conn = make_connector(fake, paths, scopes)
    conn.reconcile()
    assert not unit_active("chatty-job-77.scope") and not growing(writer)
    proc.wait(timeout=10)
    pump(conn, lambda: "77" in fake.results)
    assert fake.results["77"]["error"] == "connector restarted"


@needs_systemd
def test_stop_command_against_real_scope():
    scopes = Scopes()
    unit = scopes.handle("stoptest")
    with open("/dev/null", "wb") as null:
        proc = scopes.spawn(["sleep", "60"], unit, "/", null)
    assert scopes.wait_started(unit, proc) and scopes.alive(unit)
    scopes.stop(unit, proc)
    assert not scopes.alive(unit)
    assert proc.wait(timeout=10) != 0


@needs_systemd
def test_detached_descendant_is_stopped_before_result(fake, paths, tmp_path):
    writer = tmp_path / "w"
    fake.add_job(1, {"writer": str(writer), "setsid": True, "sleep": 1})
    conn = make_connector(fake, paths, Scopes())
    pump(conn, lambda: "1" in fake.results)
    assert fake.results["1"]["status"] == "done"
    assert writer.exists() and writer.stat().st_mtime <= fake.result_times["1"]
    assert not growing(writer) and not unit_active("chatty-job-1.scope")
    assert not conn.jobs or not any(j.busy for j in conn.jobs.values())
