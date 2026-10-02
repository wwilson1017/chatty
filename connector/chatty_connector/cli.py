"""chatty-connector command line: pair, run, doctor, install-service, clean."""

import argparse
import json
import logging
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from importlib.resources import files
from pathlib import Path

import httpx
import tomllib

from . import __version__
from .runner import (
    BUILDERS,
    Connector,
    Paths,
    ProcessGroups,
    Revoked,
    Scopes,
    StreamParser,
    available_runners,
    load_profile,
    runner_command,
)

EX_CONFIG = 78  # the service unit doesn't restart on this; re-pairing is needed

log = logging.getLogger("chatty_connector")


# --- config -----------------------------------------------------------------

def read_config(paths: Paths) -> dict:
    path = paths.config_dir / "config.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def write_config(paths: Paths, url: str, token: str) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = paths.config_dir / "config.toml"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"url = {json.dumps(url)}\ntoken = {json.dumps(token)}\n")
    os.chmod(path, 0o600)


def install_starter_files(paths: Paths) -> None:
    pkg = files("chatty_connector")
    profiles = paths.config_dir / "profiles.toml"
    if not profiles.exists():
        profiles.write_text(pkg.joinpath("profiles.toml").read_text())
    settings = paths.config_dir / "safe-settings.json"
    if not settings.exists():
        text = pkg.joinpath("safe-settings.json").read_text()
        settings.write_text(text.replace("{home}", str(Path.home())).replace("{config_dir}", str(paths.config_dir)))


def make_client(cfg: dict) -> httpx.Client:
    return httpx.Client(base_url=cfg["url"].rstrip("/"), headers={"Authorization": f"Bearer {cfg['token']}"},
                        timeout=30)


# --- commands ---------------------------------------------------------------

def cmd_pair(args, paths: Paths) -> int:
    url = args.url.rstrip("/")
    r = httpx.post(f"{url}/api/connector/pair", json={"code": args.code, "host": socket.gethostname()}, timeout=30)
    if not r.is_success:
        print(f"Pairing failed (HTTP {r.status_code}): {r.text[:300]}", file=sys.stderr)
        return 1
    write_config(paths, url, r.json()["token"])
    install_starter_files(paths)
    print(f"Paired with {url}. Config: {paths.config_dir}\n")
    if _ask("Run the health check now?", args):
        print()
        cmd_doctor(args, paths)
        print()
    if _ask("Install and start the background service, so jobs run even when you're logged out?", args):
        return cmd_install_service(args, paths)
    print("Later: chatty-connector doctor, then chatty-connector install-service")
    return 0


def _ask(question: str, args) -> bool:
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")


def _sh(*argv: str) -> bool:
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode:
        print(f"  `{' '.join(argv)}` failed: {(r.stderr or r.stdout).strip()[:300]}", file=sys.stderr)
    return r.returncode == 0


def cmd_run(args, paths: Paths) -> int:
    cfg = read_config(paths)
    if not cfg.get("token"):
        print("Not paired. Run: chatty-connector pair <chatty-url> <code>", file=sys.stderr)
        return EX_CONFIG
    if sys.platform.startswith("linux") and not args.no_containment:
        containment = Scopes()
        if not containment.works():
            print("systemd-run --user is unavailable, so jobs can't be contained. Fix the user systemd "
                  "session (loginctl enable-linger $USER) or pass --no-containment.", file=sys.stderr)
            return 1
    else:
        if args.no_containment:
            log.warning("RUNNING WITHOUT CONTAINMENT: a cancelled or crashed job's background processes "
                        "may keep running.")
        containment = ProcessGroups()
    connector = Connector(make_client(cfg), load_profile(paths), paths, containment)
    try:
        connector.run(interval=args.interval)
    except Revoked:
        write_config(paths, cfg["url"], "")
        log.error("Chatty rejected the token (disconnected or re-paired). All jobs were stopped. "
                  "Run chatty-connector pair again.")
        return EX_CONFIG
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    return 0


def sandbox_status(settings_path: Path) -> tuple[bool, str]:
    """Deterministic checks only: the settings ask for a strict sandbox, and the OS can start one."""
    try:
        sandbox = json.loads(settings_path.read_text()).get("sandbox") or {}
    except (OSError, ValueError) as e:
        return False, f"can't read {settings_path}: {e}"
    if sandbox.get("enabled") is not True:
        return False, "sandbox.enabled is not true in safe-settings.json"
    if sandbox.get("allowUnsandboxedCommands") is not False:
        return False, "sandbox.allowUnsandboxedCommands is not false in safe-settings.json"
    if sys.platform == "darwin":
        return (True, "") if shutil.which("sandbox-exec") else (False, "sandbox-exec not found")
    reasons = [f"{b} not installed" for b in ("bwrap", "socat") if not shutil.which(b)]
    if shutil.which("bwrap"):
        probe = subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"], capture_output=True, text=True)
        if probe.returncode != 0:
            reason = f"bwrap can't start: {probe.stderr.strip()[:200]}"
            try:
                if Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text().strip() == "1":
                    reason += (" (AppArmor blocks unprivileged user namespaces: "
                               "kernel.apparmor_restrict_unprivileged_userns=1)")
            except OSError:
                pass
            reasons.append(reason)
    return not reasons, "; ".join(reasons)


def cmd_doctor(args, paths: Paths) -> int:
    ok = True

    def report(good: bool, msg: str, hard: bool = True) -> None:
        nonlocal ok
        print(f"{'ok  ' if good else ('FAIL' if hard else 'warn')}  {msg}")
        ok = ok and (good or not hard)

    cfg = read_config(paths)
    if not cfg.get("token"):
        report(False, "not paired (run chatty-connector pair <url> <code>)")
    else:
        try:
            r = make_client(cfg).get("/api/connector/health")
            report(r.is_success, f"Chatty {cfg['url']}: HTTP {r.status_code} {r.text[:200]}")
        except httpx.HTTPError as e:
            report(False, f"Chatty {cfg['url']}: {e}")

    try:
        profile = load_profile(paths)
        report(True, f"profiles.toml parsed ({', '.join(r for r in ('claude', 'codex') if r in profile)})")
    except (OSError, ValueError) as e:
        report(False, f"profiles.toml: {e}")
        return 1

    runners = available_runners(profile)
    for runner in ("claude", "codex"):
        if runner not in profile:
            continue
        cmd = runner_command(profile, runner)
        if runner not in runners:
            report(False, f"{runner}: command {cmd!r} not found on PATH")
            continue
        v = subprocess.run([cmd, "--version"], capture_output=True, text=True)
        report(v.returncode == 0, f"{runner}: {(v.stdout or v.stderr).strip()[:100]} (resume={runners[runner]['resume']})")
    if "claude" in runners:
        report(*_claude_ping(profile, paths))

    good, reason = sandbox_status(paths.config_dir / "safe-settings.json")
    report(good, "sandbox: available" if good else
           f"sandbox: unavailable ({reason}; safe profile = deny rules only, see README)", hard=False)

    if sys.platform.startswith("linux"):
        report(Scopes().works(), "containment: systemd-run --user --scope works")
    else:
        report(True, "containment: process groups (best effort on this platform, see README)", hard=False)
    return 0 if ok else 1


def _claude_ping(profile: dict, paths: Paths) -> tuple[bool, str]:
    argv = BUILDERS["claude"](profile, "safe", None, paths.config_dir)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = subprocess.run(argv, input="Reply with the word ok.", capture_output=True, text=True,
                               cwd=tmp, timeout=180)
        except subprocess.TimeoutExpired:
            return False, "claude ping: timed out after 180s"
    parser = StreamParser("claude")
    for line in p.stdout.splitlines():
        parser.feed(line)
    if p.returncode == 0 and parser.result is not None and not parser.is_error:
        return True, "claude ping (safe profile): answered"
    return False, f"claude ping (safe profile): {(parser.text or p.stderr).strip()[:300]}"


def cmd_install_service(args, paths: Paths) -> int:
    argv = [sys.executable, "-m", "chatty_connector.cli", "run"]
    path_env = os.environ.get("PATH", "")
    if sys.platform == "darwin":
        target = Path.home() / "Library/LaunchAgents/com.chatty.connector.plist"
        logfile = str(Path.home() / "Library/Logs/chatty-connector.log")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(plistlib.dumps({
            "Label": "com.chatty.connector", "ProgramArguments": argv, "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False}, "EnvironmentVariables": {"PATH": path_env},
            "StandardOutPath": logfile, "StandardErrorPath": logfile,
        }))
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{domain}/com.chatty.connector"], capture_output=True)  # if loaded
        if not _sh("launchctl", "bootstrap", domain, str(target)):
            return 1
        print(f"Service installed and running. Logs: {logfile}")
        return 0
    target = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user/chatty-connector.service"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "[Unit]\nDescription=Chatty connector (runs Chatty's Claude Code / Codex jobs)\n"
        "After=network-online.target\n\n"
        f"[Service]\nExecStart={' '.join(argv)}\nEnvironment=\"PATH={path_env}\"\n"
        f"Restart=always\nRestartSec=10\nRestartPreventExitStatus={EX_CONFIG}\n\n"
        "[Install]\nWantedBy=default.target\n"
    )
    # restart, not just enable --now: after a re-pair the old process has exited on the revoked token
    if not (_sh("systemctl", "--user", "daemon-reload") and _sh("systemctl", "--user", "enable", "chatty-connector")
            and _sh("systemctl", "--user", "restart", "chatty-connector")):
        return 1
    user = os.environ.get("USER", "")
    linger = subprocess.run(["loginctl", "show-user", user, "-p", "Linger"], capture_output=True, text=True)
    if "Linger=yes" not in linger.stdout and not _sh("loginctl", "enable-linger", user):
        print(f"  Run `sudo loginctl enable-linger {user}` so it keeps running while you're logged out.")
    print("Service installed and running. Logs: journalctl --user -u chatty-connector -f")
    return 0


def _git_unsafe(repo: Path) -> str | None:
    """Why a repo must be kept, or None. Anything we can't check counts as unsafe."""
    def git(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
    status = git("status", "--porcelain")
    if status.returncode != 0:
        return "git status failed"
    if status.stdout.strip():
        return "uncommitted changes"
    unpushed = git("log", "--branches", "--not", "--remotes", "--oneline")
    if unpushed.returncode != 0 or unpushed.stdout.strip():
        return "unpushed commits"
    return None


def cmd_clean(args, paths: Paths) -> int:
    if not args.older_than.endswith("d") or not args.older_than[:-1].isdigit():
        print("--older-than takes days, e.g. 30d", file=sys.stderr)
        return 2
    cutoff = time.time() - int(args.older_than[:-1]) * 86400
    live = set()
    for p in paths.job_states.glob("*.json"):
        live.add(json.loads(p.read_text()).get("workdir_key"))
    for d in sorted(paths.workdirs.glob("*")) if paths.workdirs.is_dir() else []:
        if not d.is_dir():
            continue
        reason = None
        if d.name in live:
            reason = "job still owned by the connector"
        newest = d.stat().st_mtime
        for root, dirs, names in os.walk(d):
            if (".git" in dirs or ".git" in names) and reason is None:
                why = _git_unsafe(Path(root))
                if why:
                    reason = f"{why} in {Path(root).relative_to(d)}"
            dirs[:] = [x for x in dirs if x != ".git"]
            for n in names + dirs:
                try:
                    newest = max(newest, os.lstat(os.path.join(root, n)).st_mtime)
                except OSError:
                    pass
        if reason is None and newest > cutoff:
            reason = "used recently"
        if reason:
            print(f"keep    {d.name}: {reason}")
        elif args.dry_run:
            print(f"would delete {d.name}")
        else:
            shutil.rmtree(d)
            print(f"deleted {d.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chatty-connector", description="Run Chatty's Claude Code / Codex jobs here.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="pair with Chatty using the code from the Claude Code integration card")
    p.add_argument("url")
    p.add_argument("code")
    p.add_argument("-y", "--yes", action="store_true", help="run the health check and install the service without asking")
    r = sub.add_parser("run", help="poll Chatty for jobs and run them")
    r.add_argument("--no-containment", action="store_true", help="Linux without user systemd (not recommended)")
    r.add_argument("--interval", type=float, default=5.0, help=argparse.SUPPRESS)
    sub.add_parser("doctor", help="check pairing, CLIs, profiles, sandbox and containment")
    sub.add_parser("install-service", help="install and start the background service (systemd user unit / launchd)")
    c = sub.add_parser("clean", help="delete old job directories (never ones with unpushed work)")
    c.add_argument("--older-than", default="30d")
    c.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per poll is noise
    commands = {"pair": cmd_pair, "run": cmd_run, "doctor": cmd_doctor,
                "install-service": cmd_install_service, "clean": cmd_clean}
    return commands[args.cmd](args, Paths.default())


if __name__ == "__main__":
    sys.exit(main())
