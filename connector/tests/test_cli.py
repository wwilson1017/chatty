import json
import stat
import sys
from argparse import Namespace
from pathlib import Path

import tomllib
from chatty_connector.cli import cmd_doctor, cmd_install_service, cmd_pair
from chatty_connector.runner import Paths
from conftest import TOKEN


def test_pair_writes_private_config_and_starter_files(fake, tmp_path):
    paths = Paths(tmp_path / "cfg", tmp_path / "s", tmp_path / "d")
    assert cmd_pair(Namespace(url=fake.url + "/", code="000000"), paths) == 1
    assert cmd_pair(Namespace(url=fake.url + "/", code="123456"), paths) == 0
    config = paths.config_dir / "config.toml"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert tomllib.loads(config.read_text()) == {"url": fake.url, "token": TOKEN}
    assert tomllib.loads((paths.config_dir / "profiles.toml").read_text())["claude"]["resume"] is True
    settings = json.loads((paths.config_dir / "safe-settings.json").read_text())
    assert f"Read(/{Path.home()}/.ssh/**)" in settings["permissions"]["deny"]
    assert f"Read(/{paths.config_dir}/**)" in settings["permissions"]["deny"]
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False

    (paths.config_dir / "profiles.toml").write_text("# mine")
    cmd_pair(Namespace(url=fake.url, code="123456"), paths)
    assert (paths.config_dir / "profiles.toml").read_text() == "# mine"  # never overwritten


def test_doctor_against_fake(fake, paths, capsys):
    (paths.config_dir / "config.toml").write_text(f'url = "{fake.url}"\ntoken = "{TOKEN}"\n')
    (paths.config_dir / "safe-settings.json").write_text(
        json.dumps({"sandbox": {"enabled": True, "allowUnsandboxedCommands": False}}))
    assert cmd_doctor(Namespace(), paths) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert '"generation": 1' in out and "claude ping (safe profile): answered" in out
    assert "sandbox: available" in out or "safe profile = deny rules only" in out
    assert fake.polls == []  # doctor never claims


def test_doctor_fails_when_not_paired(paths, capsys):
    assert cmd_doctor(Namespace(), paths) == 1
    assert "not paired" in capsys.readouterr().out


def test_install_service_writes_systemd_unit(tmp_path, monkeypatch, fake_cli):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    assert cmd_install_service(Namespace(), None) == 0
    unit = (tmp_path / "systemd/user/chatty-connector.service").read_text()
    assert f"ExecStart={sys.executable} -m chatty_connector.cli run" in unit
    assert "RestartPreventExitStatus=78" in unit and "WantedBy=default.target" in unit
