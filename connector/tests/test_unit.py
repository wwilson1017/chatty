import json
import os
import shutil
import subprocess
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest
from chatty_connector.cli import cmd_clean, sandbox_status
from chatty_connector.runner import (
    RESULT_CAP,
    Connector,
    Paths,
    ProcessGroups,
    StreamParser,
    build_claude_argv,
    build_codex_argv,
)
from conftest import FIXTURES

PROFILE = {
    "ceiling": "full",
    "claude": {"sandbox": ["--settings", "{config_dir}/sandbox-settings.json"],
               "full": ["--dangerously-skip-permissions"]},
    "codex": {"command": "codex-isolated", "sandbox": ["--sandbox", "workspace-write"],
              "full": ["--dangerously-bypass-approvals-and-sandbox"]},
}
CFG = Path("/cfg")


def test_claude_argv():
    assert build_claude_argv(PROFILE, "sandbox", None, CFG) == [
        "claude", "-p", "--output-format", "stream-json", "--verbose", "--settings", "/cfg/sandbox-settings.json"]
    assert build_claude_argv(PROFILE, "full", "sid-1", CFG) == [
        "claude", "-p", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions",
        "--resume", "sid-1"]


def test_codex_argv():
    assert build_codex_argv(PROFILE, "sandbox", None, CFG) == [
        "codex-isolated", "exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write", "-"]
    assert build_codex_argv(PROFILE, "full", "t-1", CFG) == [
        "codex-isolated", "exec", "resume", "t-1", "--json", "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox", "-"]


def parse(runner, lines):
    p = StreamParser(runner)
    for line in lines:
        p.feed(line)
    return p


def fixture_lines(name):
    return (FIXTURES / name).read_text().splitlines()


def test_parse_claude_fixtures():
    p = parse("claude", fixture_lines("claude_stream.jsonl"))
    assert p.session_id == "bff6b20f-7c15-4f0f-bb10-cf237fff0f73"
    assert p.result.startswith("ok") and not p.is_error
    assert p.usage["total_cost_usd"] > 0 and p.usage["permission_denials"] == []
    assert parse("claude", fixture_lines("claude_resume.jsonl")).session_id == p.session_id
    denied = parse("claude", fixture_lines("claude_denied.jsonl"))
    assert denied.usage["permission_denials"] == ["Bash"] * 4


def test_parse_codex_fixture():
    p = parse("codex", fixture_lines("codex_stream.jsonl"))
    assert p.session_id == "01a0faaa-58cc-7640-a729-431c57ce5bd1"
    assert p.result == "ok" and not p.is_error  # the deprecation "error" item is not a failure
    assert p.usage["usage"]["output_tokens"] == 5


def test_parse_truncated_stream_keeps_partial_text():
    p = parse("claude", fixture_lines("claude_stream.jsonl")[:-1] + ['{"type": "assistant", "mess'])
    assert p.result is None and p.session_id
    assert p.text.startswith("ok")  # the assistant text seen so far
    c = parse("codex", fixture_lines("codex_stream.jsonl")[:-1])
    assert c.result == "ok" and c.usage is None


def test_parse_past_capture_cap():
    big = json.dumps({"type": "assistant", "session_id": "s",
                      "message": {"content": [{"type": "text", "text": "x" * 60_000}]}})
    p = parse("claude", [big] * 5 + [json.dumps({"type": "result", "result": "final", "session_id": "s"})])
    assert len("".join(p._partial)) == RESULT_CAP
    assert p.result == "final" and p.text == "final"


def test_second_instance_refused(tmp_path):
    paths = Paths(tmp_path / "c", tmp_path / "s", tmp_path / "d")
    a = Connector(None, PROFILE, paths, ProcessGroups())
    b = Connector(None, PROFILE, paths, ProcessGroups())
    a.lock()
    with pytest.raises(RuntimeError, match="already running"):
        b.lock()


def test_sandbox_status_checks_settings(tmp_path):
    s = tmp_path / "sandbox-settings.json"
    s.write_text(json.dumps({"sandbox": {"enabled": True}}))
    assert sandbox_status(s) == (False, "sandbox.allowUnsandboxedCommands is not false in sandbox-settings.json")
    s.write_text(json.dumps({"sandbox": {"enabled": True, "allowUnsandboxedCommands": False}}))
    good, reason = sandbox_status(s)
    assert good or reason  # either works here, or names why (bwrap/socat/AppArmor)


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


def test_clean_skips_dirty_unpushed_and_live(tmp_path):
    paths = Paths(tmp_path / "c", tmp_path / "s", tmp_path / "d")
    jobs = paths.workdirs
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    for name in ("dirty", "unpushed", "pushed"):
        git(tmp_path, "clone", "-q", str(remote), str(jobs / name / "repo"))
        git(jobs / name / "repo", "commit", "-q", "--allow-empty", "-m", "c")
        if name != "unpushed":
            git(jobs / name / "repo", "push", "-q", "origin", "HEAD")
    (jobs / "dirty" / "repo" / "new.txt").write_text("x")
    (jobs / "plain").mkdir()
    (jobs / "plain" / "notes.txt").write_text("x")
    (jobs / "live").mkdir()
    paths.job_states.mkdir(parents=True)
    (paths.job_states / "9.json").write_text(json.dumps({"id": 9, "workdir_key": "live", "state": "running"}))
    (jobs / "recent").mkdir()
    old = 1_000_000_000
    for p in [*jobs.rglob("*"), *jobs.iterdir()]:
        if p.name != "recent":
            os.utime(p, (old, old), follow_symlinks=False)

    cmd_clean(Namespace(older_than="30d", dry_run=True), paths)
    assert sorted(p.name for p in jobs.iterdir()) == ["dirty", "live", "plain", "pushed", "recent", "unpushed"]
    cmd_clean(Namespace(older_than="30d", dry_run=False), paths)
    assert sorted(p.name for p in jobs.iterdir()) == ["dirty", "live", "recent", "unpushed"]


@pytest.mark.skipif(not (shutil.which("uv") or shutil.which("pip")), reason="no wheel builder")
def test_wheel_contains_package_data(tmp_path):
    root = Path(__file__).parent.parent
    if shutil.which("uv"):
        cmd = ["uv", "build", "--wheel", "-q", "-o", str(tmp_path), str(root)]
    else:
        cmd = [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(tmp_path), str(root)]
    subprocess.run(cmd, check=True)
    (wheel,) = tmp_path.glob("chatty_connector-*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "chatty_connector/sandbox-settings.json" in names
    assert "chatty_connector/look-settings.json" in names
    assert "chatty_connector/runner.py" in names
