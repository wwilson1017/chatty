import json
import stat
import sys
from argparse import Namespace
from pathlib import Path

import pytest
import tomllib
from chatty_connector.cli import EX_CONFIG, cmd_doctor, cmd_install_service, cmd_pair, cmd_run, cmd_setup
from chatty_connector.runner import Paths, load_profile
from conftest import TOKEN


@pytest.fixture(autouse=True)
def no_real_service(tmp_path, monkeypatch):
    """Never let a test see (or restart) the real service unit on this machine."""
    from chatty_connector import cli
    monkeypatch.setattr(cli, "service_file", lambda: tmp_path / "no-service.unit")
    monkeypatch.setattr(cli, "cmd_install_service", lambda *a: pytest.fail("service restarted"))


def answers(monkeypatch, *replies):
    it = iter(replies)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: print(q + (r := next(it))) or r)


def test_pair_writes_private_config_and_setup_files(fake, tmp_path):
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    assert cmd_pair(Namespace(url=fake.url + "/", code="000000"), paths) == 1
    assert cmd_pair(Namespace(url=fake.url + "/", code="123456"), paths) == 0
    config = paths.config_dir / "config.toml"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert tomllib.loads(config.read_text()) == {"url": fake.url, "token": TOKEN}
    profile = load_profile(paths)
    assert profile["ceiling"] == "sandbox" and profile["claude"]["resume"] is True
    settings = json.loads((paths.config_dir / "sandbox-settings.json").read_text())
    assert f"Read(/{Path.home()}/.ssh/**)" in settings["permissions"]["deny"]
    assert f"Read(/{paths.config_dir}/**)" in settings["permissions"]["deny"]
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    look = json.loads((paths.config_dir / "look-settings.json").read_text())
    assert {"Edit", "Write", f"Read(/{Path.home()}/.ssh/**)"} <= set(look["permissions"]["deny"])
    # look drops git log/show/diff (--output=<file> writes files)
    assert set(look["permissions"]["allow"]) < set(settings["permissions"]["allow"])
    assert not {"Bash(git log:*)", "Bash(git show:*)", "Bash(git diff:*)"} & set(look["permissions"]["allow"])
    assert look["sandbox"]["autoAllowBashIfSandboxed"] is False

    cmd_setup(Namespace(yes=True, ceiling="look"), paths)
    cmd_pair(Namespace(url=fake.url, code="123456"), paths)
    assert load_profile(paths)["ceiling"] == "look"  # re-pairing keeps the setup


@pytest.mark.parametrize("ceiling", ["look", "sandbox", "full"])
def test_setup_writes_each_ceiling_and_extras(tmp_path, ceiling):
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    assert cmd_setup(Namespace(yes=True, ceiling=ceiling, browser=True), paths) == 0
    profile = load_profile(paths)
    assert profile["ceiling"] == ceiling
    assert profile["claude"]["look"] == ["--permission-mode", "default", "--settings",
                                         "{config_dir}/look-settings.json"]
    assert profile["claude"]["full"] == ["--dangerously-skip-permissions"]
    if "codex" in profile:
        assert profile["codex"]["look"] == ["--sandbox", "read-only"]
    allow = json.loads((paths.config_dir / "sandbox-settings.json").read_text())["permissions"]["allow"]
    assert "Bash(playwright-cli:*)" in allow
    cmd_setup(Namespace(yes=True, browser=False), paths)
    allow = json.loads((paths.config_dir / "sandbox-settings.json").read_text())["permissions"]["allow"]
    assert "Bash(playwright-cli:*)" not in allow and load_profile(paths)["ceiling"] == ceiling


def test_setup_interactive_then_yes_keeps_values(tmp_path, monkeypatch, capsys):
    from chatty_connector import cli
    monkeypatch.setattr(cli.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    answers(monkeypatch, "9", "3", "maybe", "y", "n", "2", "y", "")  # bad inputs are asked again
    assert cmd_setup(Namespace(), paths) == 0
    assert capsys.readouterr().out.count("Choose 1-3") >= 2  # the bad answer "9" was asked again

    def check():
        profile = load_profile(paths)
        settings = json.loads((paths.config_dir / "sandbox-settings.json").read_text())
        assert profile["ceiling"] == "full" and profile["max_concurrent"] == 2 and "codex" not in profile
        assert settings["sandbox"]["failIfUnavailable"] is True
        look = json.loads((paths.config_dir / "look-settings.json").read_text())
        assert look["sandbox"]["failIfUnavailable"] is True
        assert "Bash(git diff:*)" not in look["permissions"]["allow"]
        assert "Bash(playwright-cli:*)" in settings["permissions"]["allow"]
    check()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cmd_setup(Namespace(), paths) == 0  # no terminal: keep everything
    check()
    assert cmd_setup(Namespace(yes=True), paths) == 0
    check()


def test_setup_declined_writes_nothing(tmp_path, monkeypatch):
    from chatty_connector import cli
    monkeypatch.setattr(cli.shutil, "which", lambda cmd: None)  # no codex: no codex question
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    answers(monkeypatch, "1", "", "", "n")
    assert cmd_setup(Namespace(), paths) == 1
    assert not paths.config_dir.exists()


def test_migrates_0_1_0_profile_and_run_refuses_it(tmp_path, capsys):
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    paths.config_dir.mkdir()
    (paths.config_dir / "config.toml").write_text('url = "http://x"\ntoken = "t"\n')
    (paths.config_dir / "profiles.toml").write_text(
        'max_concurrent = 2\nmax_codex = 2\n[claude]\ncommand = "my-claude"\nsafe = []\nfull = []\n'
        "timeout = { safe = 1, full = 1 }\nresume = false\n")
    (paths.config_dir / "safe-settings.json").write_text("{}")
    with pytest.raises(ValueError, match="0.1.0"):
        load_profile(paths)
    assert cmd_run(Namespace(no_containment=True), paths) == EX_CONFIG
    assert "chatty-connector setup" in capsys.readouterr().err

    assert cmd_setup(Namespace(yes=True), paths) == 0
    profile = load_profile(paths)
    assert profile["ceiling"] == "sandbox" and profile["max_concurrent"] == 2
    assert profile["max_codex"] == 2
    assert profile["claude"]["command"] == "my-claude" and profile["claude"]["resume"] is False
    assert not (paths.config_dir / "safe-settings.json").exists()
    assert (paths.config_dir / "safe-settings.json.bak").read_text() == "{}"
    assert (paths.config_dir / "sandbox-settings.json").exists()


def test_setup_restarts_the_service_only_if_installed(tmp_path, monkeypatch):
    from chatty_connector import cli
    restarted = []
    monkeypatch.setattr(cli, "cmd_install_service", lambda *a: restarted.append(1) or 0)
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    cmd_setup(Namespace(yes=True), paths)
    assert restarted == []
    cli.service_file().write_text("")
    cmd_setup(Namespace(yes=True), paths)
    assert restarted == [1]


def test_doctor_against_fake(fake, paths, capsys):
    (paths.config_dir / "config.toml").write_text(f'url = "{fake.url}"\ntoken = "{TOKEN}"\n')
    (paths.config_dir / "sandbox-settings.json").write_text(
        json.dumps({"sandbox": {"enabled": True, "allowUnsandboxedCommands": False}}))
    assert cmd_doctor(Namespace(), paths) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert '"generation": 1' in out and "claude ping (sandbox profile): answered" in out
    assert "ceiling: full; browser in Sandbox jobs: off" in out
    assert "sandbox: available" in out or "sandbox level = deny rules only" in out
    assert fake.polls == []  # doctor never claims


def test_doctor_fails_when_not_paired(paths, capsys):
    assert cmd_doctor(Namespace(), paths) == 1
    assert "not paired" in capsys.readouterr().out


def test_install_service_writes_unit_and_starts_it(tmp_path, monkeypatch, fake_cli):
    from chatty_connector import cli
    monkeypatch.undo()  # the real cmd_install_service and service_file, with systemctl stubbed below
    calls = []
    monkeypatch.setattr(cli, "_sh", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Namespace(stdout="Linger=yes", returncode=0))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    assert cmd_install_service(Namespace(), None) == 0
    assert ("systemctl", "--user", "restart", "chatty-connector") in calls  # restart: re-pair leaves it stopped
    assert not any(c[0] == "loginctl" for c in calls)  # linger already on
    unit = (tmp_path / "systemd/user/chatty-connector.service").read_text()
    assert f"ExecStart={sys.executable} -m chatty_connector.cli run" in unit
    assert "RestartPreventExitStatus=78" in unit and "WantedBy=default.target" in unit


def test_pair_without_a_terminal_only_pairs(fake, tmp_path, monkeypatch, capsys):
    from chatty_connector import cli
    monkeypatch.setattr(cli, "cmd_doctor", lambda *a: pytest.fail("doctor ran"))
    monkeypatch.setattr(cli, "cmd_install_service", lambda *a: pytest.fail("service installed"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    assert cmd_pair(Namespace(url=fake.url, code="123456"), paths) == 0
    assert "Later: chatty-connector doctor" in capsys.readouterr().out


def test_pair_wizard_runs_setup_then_doctor_then_service(fake, tmp_path, monkeypatch):
    from chatty_connector import cli
    ran = []
    real_setup = cli.cmd_setup
    monkeypatch.setattr(cli, "cmd_setup", lambda *a, **k: ran.append("setup") or real_setup(*a, **k))
    monkeypatch.setattr(cli, "cmd_doctor", lambda *a: ran.append("doctor") or 0)
    monkeypatch.setattr(cli, "cmd_install_service", lambda *a: ran.append("service") or 0)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: "")  # Enter = the default everywhere
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    assert cmd_pair(Namespace(url=fake.url, code="123456"), paths) == 0
    assert ran == ["setup", "doctor", "service"]
    assert load_profile(paths)["ceiling"] == "sandbox"


def test_setup_keeps_hand_set_resume(tmp_path, monkeypatch):
    from chatty_connector import cli
    monkeypatch.setattr(cli.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")  # codex installed
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    cmd_setup(Namespace(yes=True), paths)
    profile = load_profile(paths)
    assert profile["claude"]["resume"] is True and profile["codex"]["resume"] is False  # defaults
    text = (paths.config_dir / "profiles.toml").read_text()
    (paths.config_dir / "profiles.toml").write_text(text.replace("resume = false", "resume = true"))
    cmd_setup(Namespace(yes=True, ceiling="full"), paths)
    profile = load_profile(paths)
    assert profile["codex"]["resume"] is True and profile["ceiling"] == "full"
