"""Unit tests for the printed-CLI runner (arg serialization, env scoping, errors).

Uses a hermetic fake CLI script (no network, no Go build) that echoes its argv /
env or simulates failures, so serialization and process handling are tested
deterministically. A separate skipped-if-absent live test exercises the real
openalex binary when it has been built locally.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from integrations.printing_press import runner

# A fake CLI: dispatches on the first arg, emits JSON / errors / hangs so we can
# assert exactly how the runner builds argv and scopes the environment.
_FAKE_CLI = f"""#!{sys.executable}
import json, os, sys, time
argv = sys.argv[1:]
cmd = argv[0] if argv else ""
if cmd == "echo":
    print(json.dumps({{"received": argv}}))
elif cmd == "env":
    print(json.dumps({{
        "home": os.environ.get("HOME"),
        "has_secret": os.environ.get("MY_SECRET"),
        "host_leak": os.environ.get("PP_HOST_ONLY"),
        "path": os.environ.get("PATH"),
    }}))
elif cmd == "fail":
    sys.stderr.write("boom on stderr\\n")
    sys.exit(2)
elif cmd == "failjson":
    print(json.dumps({{"error": "upstream 500"}}))
    sys.exit(1)
elif cmd == "nojson":
    print("this is not json")
elif cmd == "listout":
    print(json.dumps([1, 2, 3]))
elif cmd == "leak":
    sys.stderr.write("token=topsecret leaked\\n")
    sys.exit(1)
elif cmd == "hang":
    time.sleep(30)
else:
    print(json.dumps({{"ok": True, "cmd": cmd, "received": argv}}))
"""


@pytest.fixture
def fake_cli(tmp_path):
    p = tmp_path / "fake-pp-cli"
    p.write_text(_FAKE_CLI)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR | stat.S_IWUSR)
    return p


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


def run(fake_cli, work_dir, command, args=None, **kw):
    return runner.run_command(fake_cli, command, args or {}, work_dir=work_dir, **kw)


# ── serialization ─────────────────────────────────────────────────────────

def test_path_param_is_positional_query_params_are_flags(fake_cli, work_dir):
    specs = [
        {"name": "id", "location": "path", "required": True, "type": "string"},
        {"name": "per_page", "location": "query", "type": "integer"},
        {"name": "all", "location": "query", "type": "boolean"},
    ]
    out = run(fake_cli, work_dir, "echo", {"id": "A123", "per_page": 2, "all": True}, param_specs=specs)
    received = out["received"]
    # command, positional id, --json, then flags
    assert received[0] == "echo"
    assert received[1] == "A123"          # path param → positional, right after command
    assert "--json" in received
    assert "--per-page" in received and "2" in received
    assert "--all" in received            # bool True → presence flag
    # kebab conversion + no value for the bool
    assert received.index("--per-page") + 1 < len(received)
    assert received[received.index("--per-page") + 1] == "2"


def test_bool_false_and_empty_values_omitted(fake_cli, work_dir):
    specs = [
        {"name": "all", "location": "query", "type": "boolean"},
        {"name": "filter", "location": "query", "type": "string"},
    ]
    out = run(fake_cli, work_dir, "echo", {"all": False, "filter": ""}, param_specs=specs)
    assert "--all" not in out["received"]
    assert "--filter" not in out["received"]


def test_list_value_becomes_repeated_flags(fake_cli, work_dir):
    specs = [{"name": "ids", "location": "query", "type": "array"}]
    out = run(fake_cli, work_dir, "echo", {"ids": ["a", "b"]}, param_specs=specs)
    received = out["received"]
    assert received.count("--ids") == 2
    assert "a" in received and "b" in received


def test_multi_segment_command(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "authors list", {}, param_specs=[])
    assert out["received"][:2] == ["authors", "list"]


# ── validation ────────────────────────────────────────────────────────────

def test_unknown_argument_rejected(fake_cli, work_dir):
    specs = [{"name": "id", "location": "path", "required": True}]
    out = run(fake_cli, work_dir, "echo", {"id": "x", "bogus": 1}, param_specs=specs)
    assert "unknown argument" in out["error"]


def test_missing_required_rejected(fake_cli, work_dir):
    specs = [{"name": "id", "location": "path", "required": True}]
    out = run(fake_cli, work_dir, "echo", {}, param_specs=specs)
    assert "missing required" in out["error"]


def test_invalid_command_segment_rejected(fake_cli, work_dir):
    out = run(fake_cli, work_dir, ["authors", "--sneaky"], {})
    assert "invalid command segment" in out["error"]


# ── env scoping ───────────────────────────────────────────────────────────

def test_env_is_scoped_not_inherited(fake_cli, work_dir, monkeypatch):
    monkeypatch.setenv("PP_HOST_ONLY", "should-not-leak")
    out = run(fake_cli, work_dir, "env", {}, env_vars={"MY_SECRET": "sek"})
    assert out["home"] == str(work_dir)        # HOME points at the work dir
    assert out["has_secret"] == "sek"          # declared auth env injected
    assert out["host_leak"] is None            # host env NOT inherited
    assert "/usr/bin" in out["path"]


def test_scoped_env_drops_marker_keys(work_dir):
    env = runner._scoped_env(work_dir, {"REAL": "v", "_device_authorized": "1"})
    assert env["REAL"] == "v"
    assert "_device_authorized" not in env  # internal markers never reach the CLI


# ── result + error handling ───────────────────────────────────────────────

def test_nonzero_exit_returns_structured_error(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "fail", {})
    assert out["error"] == "command failed"
    assert out["exit_code"] == 2
    assert "boom" in out["stderr"]


def test_nonzero_with_json_keeps_detail(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "failjson", {})
    assert out["error"] == "command failed"
    assert out["exit_code"] == 1
    assert out["detail"] == {"error": "upstream 500"}


def test_non_json_output_is_error(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "nojson", {})
    assert "no JSON output" in out["error"]


def test_list_json_is_wrapped(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "listout", {})
    assert out == {"result": [1, 2, 3]}


def test_secret_redacted_from_stderr(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "leak", {}, env_vars={"TOKEN": "topsecret"})
    assert "topsecret" not in json.dumps(out)
    assert "***" in out["stderr"]


def test_timeout_kills_and_returns_error(fake_cli, work_dir):
    out = run(fake_cli, work_dir, "hang", {}, timeout=1)
    assert "timed out" in out["error"]


# ── live integration (skipped unless the real binary was built locally) ────

def _openalex_ready():
    try:
        from integrations.printing_press import store
        return store.is_enabled("openalex") and Path(store.paths.cli_bin("openalex")).exists()
    except Exception:
        return False


@pytest.mark.skipif(not _openalex_ready(), reason="openalex CLI not built/installed locally")
def test_live_openalex_authors_list():
    from integrations.printing_press import store

    manifest = store.get_manifest("openalex") or {}
    specs = next(
        (t["params"] for t in manifest.get("tools", []) if t["name"] == "authors_list"),
        [],
    )
    out = runner.run_cli("openalex", "authors list", {"per_page": 2}, param_specs=specs)
    assert "results" in out or "meta" in out
