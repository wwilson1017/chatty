"""run.py's virtual-computer step: Docker missing, and a fake `docker` on PATH (no real container)."""

import importlib.util
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def run_mod(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("chatty_run", ROOT / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("AUTH_PASSWORD='pw'\nJWT_SECRET=abc\n", encoding="utf-8")
    return mod


@pytest.fixture
def docker_log(tmp_path, monkeypatch):
    """A `docker` script first on PATH that logs its argv; `start` fails until a `run` has happened."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log, started = tmp_path / "docker.log", tmp_path / "started"
    script = bin_dir / "docker"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\ncase "$1" in\n  info) exit 0;;\n  start) [ -e "{started}" ];;\n'
                      f'  run) touch "{started}"; exit 0;;\n  rm) rm -f "{started}"; exit 0;;\nesac\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log.write_text("", encoding="utf-8")
    return log  # its sibling `started` file is the container; touch it to simulate a leftover one


def _answers(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))  # StopIteration = an unexpected prompt


def test_no_docker_prints_the_pointer_and_changes_nothing(run_mod, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    _answers(monkeypatch)
    before = run_mod.ENV_FILE.read_text(encoding="utf-8")
    run_mod.setup_computer()
    assert "docs/computer.md" in capsys.readouterr().out
    assert run_mod.ENV_FILE.read_text(encoding="utf-8") == before


def test_yes_writes_env_runs_the_container_then_only_starts_it(run_mod, docker_log, monkeypatch, capsys):
    _answers(monkeypatch, "y")
    run_mod.setup_computer()
    env = run_mod._read_env()
    assert env["AUTH_PASSWORD"] == "pw"  # quotes stripped, earlier lines kept
    assert env["COMPUTER_URL"] == "http://127.0.0.1:8765" and len(env["COMPUTER_SECRET"]) >= 32
    calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert calls[:3] == ["info", "rm -f chatty-computer", "start chatty-computer"]
    run_cmd = calls[3]
    assert run_cmd.startswith("run -d --name chatty-computer --restart unless-stopped -p 127.0.0.1:8765:8080 -v chatty-computer:/data")
    assert f"-e COMPUTER_SECRET={env['COMPUTER_SECRET']}" in run_cmd  # the very secret .env holds
    assert "-e HOST=0.0.0.0 --shm-size=1g ghcr.io/wwilson1017/chatty-computer:latest" in run_cmd
    assert "running at http://127.0.0.1:8765" in capsys.readouterr().out

    # Next start: no question, `docker start` is enough.
    docker_log.write_text("", encoding="utf-8")
    _answers(monkeypatch)
    run_mod.setup_computer()
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["info", "start chatty-computer"]
    assert run_mod._read_env()["COMPUTER_SECRET"] == env["COMPUTER_SECRET"]


def test_yes_recreates_a_leftover_container_so_it_gets_the_new_secret(run_mod, docker_log, monkeypatch):
    (docker_log.parent / "started").touch()  # a chatty-computer container exists, but .env has no COMPUTER_* lines
    _answers(monkeypatch, "y")
    run_mod.setup_computer()
    calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert calls[:3] == ["info", "rm -f chatty-computer", "start chatty-computer"]
    assert calls[3].startswith("run -d") and f"COMPUTER_SECRET={run_mod._read_env()['COMPUTER_SECRET']}" in calls[3]


def test_no_is_remembered(run_mod, docker_log, monkeypatch, capsys):
    _answers(monkeypatch, "n")
    run_mod.setup_computer()
    assert run_mod._read_env()["COMPUTER_URL"] == "" and "COMPUTER_SECRET" not in run_mod._read_env()
    assert "run" not in docker_log.read_text(encoding="utf-8")
    assert "Skipped" in capsys.readouterr().out
    docker_log.write_text("", encoding="utf-8")
    _answers(monkeypatch)
    run_mod.setup_computer()
    assert docker_log.read_text(encoding="utf-8") == ""  # not even `docker info`


def test_a_computer_run_py_does_not_manage_is_left_alone(run_mod, docker_log, monkeypatch):
    with run_mod.ENV_FILE.open("a") as f:
        f.write("COMPUTER_URL=http://computer.lan:8080\nCOMPUTER_SECRET=" + "k" * 40 + "\n")
    _answers(monkeypatch)
    run_mod.setup_computer()
    assert docker_log.read_text(encoding="utf-8") == ""
