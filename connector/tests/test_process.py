"""The real `chatty-connector run` in a separate process, SIGKILLed at awkward moments (Linux, user systemd)."""

import json
import shutil
import subprocess
import time

import tomllib
from conftest import (
    connector_process,
    growing,
    needs_systemd,
    process_paths,
    unit_active,
    wait_for,
)

pytestmark = needs_systemd


def state_of(paths, job_id):
    path = paths.job_states / f"{job_id}.json"
    return json.loads(path.read_text())["state"] if path.exists() else None


def test_sigkilled_connector_restart_stops_job_before_new_work(fake, fake_cli, tmp_path):
    paths = process_paths(tmp_path, fake, fake_cli)
    writer = tmp_path / "w"
    fake.add_job(1, {"sleep": 120, "writer": str(writer)})
    proc = connector_process(paths)
    try:
        wait_for(lambda: writer.exists() and unit_active("chatty-job-1.scope"))
    finally:
        proc.kill()
        proc.wait()
    assert growing(writer)  # the job's scope outlives the connector

    fake.add_job(2, {})
    proc = connector_process(paths)
    try:
        wait_for(lambda: {"1", "2"} <= set(fake.results), timeout=40)
    finally:
        proc.kill()
        proc.wait()
    assert fake.results["1"]["status"] == "failed" and fake.results["1"]["error"] == "connector restarted"
    assert writer.stat().st_mtime <= fake.claimed_at["2"]
    assert not unit_active("chatty-job-1.scope") and not growing(writer)


def test_startup_race_launcher_dies_with_connector(fake, fake_cli, tmp_path):
    paths = process_paths(tmp_path, fake, fake_cli)
    started = tmp_path / "started.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    slow = bin_dir / "systemd-run"  # pauses after spawn, before the scope is registered
    slow.write_text(f'#!/bin/sh\nsleep 3\nexec {shutil.which("systemd-run")} "$@"\n')
    slow.chmod(0o755)
    fake.add_job(1, {"started": str(started)})
    proc = connector_process(paths, extra_path=str(bin_dir))
    try:
        wait_for(lambda: state_of(paths, 1) == "starting", timeout=30)
    finally:
        proc.kill()
        proc.wait()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        assert not unit_active("chatty-job-1.scope")
        time.sleep(0.2)
    launchers = subprocess.run(["pgrep", "-f", "unit=chatty-job-1.scope"], capture_output=True, text=True).stdout
    assert launchers.strip() == "" and not started.exists()

    proc = connector_process(paths)
    try:
        wait_for(lambda: "1" in fake.results, timeout=30)
    finally:
        proc.kill()
        proc.wait()
    assert fake.results["1"]["error"] == "connector restarted" and not started.exists()


def test_revoked_token_stops_jobs_and_halts(fake, fake_cli, tmp_path):
    paths = process_paths(tmp_path, fake, fake_cli)
    writer = tmp_path / "w"
    fake.add_job(1, {"sleep": 120, "writer": str(writer)})
    proc = connector_process(paths)
    try:
        wait_for(lambda: writer.exists() and unit_active("chatty-job-1.scope"))
        fake.poll_code = 401
        assert proc.wait(timeout=40) == 78
    finally:
        proc.kill()
        proc.wait()
    assert not unit_active("chatty-job-1.scope") and not growing(writer)
    polls = len(fake.polls)
    time.sleep(1)
    assert len(fake.polls) == polls  # claiming halted
    assert list(paths.job_states.glob("*")) == [] and fake.results == {}
    with open(paths.config_dir / "config.toml", "rb") as f:
        assert tomllib.load(f)["token"] == ""
