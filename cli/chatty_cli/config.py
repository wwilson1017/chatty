"""The one Chatty server this terminal talks to, its device token, and the remembered choices."""

import json
import os
from pathlib import Path


def config_path() -> Path:
    # A second server gets its own file (CHATTY_CONFIG), so a token only ever goes to the server that issued it.
    if os.environ.get("CHATTY_CONFIG"):
        return Path(os.environ["CHATTY_CONFIG"]).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "chatty" / "config.json"


def load() -> dict:
    try:
        return json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(path, 0o600)


def history_path() -> Path:
    path = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "chatty" / "history"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.touch(mode=0o600)
    return path
