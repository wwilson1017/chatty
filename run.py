#!/usr/bin/env python3
"""
Chatty — Local launcher.

Run this script to set up and start Chatty on your machine.

Usage:
    git clone https://github.com/WWilson1017/chatty.git
    cd chatty
    python run.py
"""

import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
NPM = "npm.cmd" if os.name == "nt" else "npm"


def _python() -> str:
    """Return the path to the venv Python interpreter."""
    if platform.system() == "Windows":
        return str(VENV / "Scripts" / "python.exe")
    return str(VENV / "bin" / "python")


def _pip() -> str:
    """Return the path to the venv pip."""
    if platform.system() == "Windows":
        return str(VENV / "Scripts" / "pip.exe")
    return str(VENV / "bin" / "pip")


def check_python():
    v = sys.version_info
    if v < (3, 10):
        print(f"Error: Python 3.10+ is required (you have {v.major}.{v.minor}).")
        print("Download Python from https://www.python.org/downloads/")
        sys.exit(1)
    print(f"  Python {v.major}.{v.minor}.{v.micro}")


def check_node():
    node = shutil.which("node")
    if not node:
        print("Error: Node.js is not installed.")
        print("Download Node.js from https://nodejs.org/")
        sys.exit(1)
    result = subprocess.run([node, "--version"], capture_output=True, text=True)
    version = result.stdout.strip().lstrip("v")
    major = int(version.split(".")[0])
    if major < 18:
        print(f"Error: Node.js 18+ is required (you have {version}).")
        print("Download Node.js from https://nodejs.org/")
        sys.exit(1)
    print(f"  Node.js {version}")


def setup_env():
    if ENV_FILE.exists():
        print("  .env file already exists, skipping.")
        return
    if ENV_EXAMPLE.exists():
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
    else:
        content = (
            "AUTH_PASSWORD=changeme\n"
            "JWT_SECRET=change-me-in-production\n"
        )
    # Auto-generate a secure JWT secret
    content = content.replace("change-me-in-production", secrets.token_hex(32))
    # Prompt for password
    print()
    password = input("  Choose a login password (or press Enter for 'changeme'): ").strip()
    if password:
        # Quote the value to handle special characters (=, #, spaces)
        safe_password = password.replace("'", "'\\''")
        content = content.replace("AUTH_PASSWORD=changeme", f"AUTH_PASSWORD='{safe_password}'")
    ENV_FILE.write_text(content, encoding="utf-8")
    print("  Created .env file.")


def setup_venv():
    if VENV.exists():
        print("  Virtual environment already exists, skipping.")
        return
    print("  Creating virtual environment...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    print("  Installing Python dependencies...")
    subprocess.run(
        [_pip(), "install", "-r", str(BACKEND / "requirements.txt")],
        check=True,
    )
    (VENV / "deps_installed").touch()


def install_deps():
    """Install pip deps if requirements have changed."""
    if VENV.exists() and (VENV / "deps_installed").exists():
        # Check if requirements.txt is newer than our marker
        req_mtime = (BACKEND / "requirements.txt").stat().st_mtime
        marker_mtime = (VENV / "deps_installed").stat().st_mtime
        if req_mtime <= marker_mtime:
            print("  Python dependencies up to date.")
            return
    print("  Installing Python dependencies...")
    subprocess.run(
        [_pip(), "install", "-r", str(BACKEND / "requirements.txt")],
        check=True,
    )
    (VENV / "deps_installed").touch()


WA_BRIDGE = BACKEND / "whatsapp-bridge"


def setup_frontend():
    if not (FRONTEND / "node_modules").exists():
        print("  Installing frontend dependencies...")
        subprocess.run([NPM, "ci"], cwd=str(FRONTEND), check=True)
    else:
        print("  Frontend dependencies already installed.")

    print("  Building frontend...")
    subprocess.run([NPM, "run", "build"], cwd=str(FRONTEND), check=True)


def setup_whatsapp_bridge():
    """Install WhatsApp bridge sidecar dependencies if needed."""
    if not WA_BRIDGE.exists():
        return
    if not (WA_BRIDGE / "node_modules").exists():
        print("  Installing WhatsApp bridge dependencies...")
        subprocess.run([NPM, "ci"], cwd=str(WA_BRIDGE), check=True)
    else:
        print("  WhatsApp bridge dependencies already installed.")


def start_whatsapp_bridge() -> subprocess.Popen | None:
    """Start the WhatsApp bridge sidecar if configured."""
    if not WA_BRIDGE.exists() or not (WA_BRIDGE / "node_modules").exists():
        return None
    # Only start if WHATSAPP_BRIDGE_URL is configured
    if not os.environ.get("WHATSAPP_BRIDGE_URL"):
        return None
    print("  Starting WhatsApp bridge sidecar on port 3001...")
    return subprocess.Popen(
        ["node", "index.js"],
        cwd=str(WA_BRIDGE),
        env={**os.environ, "PORT": "3001"},
    )


COMPUTER_IMAGE = "ghcr.io/wwilson1017/chatty-computer:latest"
COMPUTER_PORT = 8765
COMPUTER_URL = f"http://127.0.0.1:{COMPUTER_PORT}"
COMPUTER_CONTAINER = "chatty-computer"


def _read_env() -> dict:
    """KEY=VALUE lines of .env with surrounding quotes stripped — enough for the keys run.py writes."""
    values = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def setup_computer():
    """Start the virtual computer (docs/computer.md) in Docker. Asks once: a COMPUTER_URL line in
    .env, even an empty one, means the question was answered."""
    env = _read_env()
    url, secret = env.get("COMPUTER_URL", ""), env.get("COMPUTER_SECRET", "")
    if "COMPUTER_URL" in env and url != COMPUTER_URL:
        return  # declined earlier (empty), or a computer run.py doesn't manage
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "info"], capture_output=True).returncode != 0:
        print("  Docker isn't available, so no virtual computer. See docs/computer.md to add one later.")
        return
    if not (url and secret):
        answer = input("  Give your agents a virtual computer (a Docker container, ~1.4 GB download)? [y/N] ").strip().lower()
        with ENV_FILE.open("a", encoding="utf-8") as f:
            if answer not in ("y", "yes"):
                f.write("\n# Virtual computer: declined. Delete these lines to be asked again (see docs/computer.md).\nCOMPUTER_URL=\n")
                print("  Skipped.")
                return
            secret = secrets.token_urlsafe(36)
            f.write(f"\n# Virtual computer (see docs/computer.md)\nCOMPUTER_URL={COMPUTER_URL}\nCOMPUTER_SECRET={secret}\n")
        # A container left from an earlier setup still carries its old secret: recreate it below (the volume stays).
        subprocess.run([docker, "rm", "-f", COMPUTER_CONTAINER], capture_output=True)
    if subprocess.run([docker, "start", COMPUTER_CONTAINER], capture_output=True).returncode != 0:
        print("  Starting the virtual computer (the first run downloads the image)...")
        created = subprocess.run([
            docker, "run", "-d", "--name", COMPUTER_CONTAINER, "--restart", "unless-stopped",
            "-p", f"127.0.0.1:{COMPUTER_PORT}:8080", "-v", f"{COMPUTER_CONTAINER}:/data",
            "-e", f"COMPUTER_SECRET={secret}", "-e", "HOST=0.0.0.0", "--shm-size=1g", COMPUTER_IMAGE,
        ])
        if created.returncode != 0:
            print("  Couldn't start the virtual computer; Chatty runs without it. See docs/computer.md.")
            return
    print(f"  Virtual computer running at {COMPUTER_URL} (container {COMPUTER_CONTAINER}).")


def start_server():
    wa_proc = start_whatsapp_bridge()
    print()
    print("=" * 50)
    print("  Chatty is running at http://localhost:8000")
    if wa_proc:
        print("  WhatsApp bridge running on port 3001")
    print("  Press Ctrl+C to stop.")
    print("=" * 50)
    print()
    try:
        subprocess.run(
            [
                _python(), "-m", "uvicorn",
                "main:app",
                "--host", "127.0.0.1",
                "--port", "8000",
            ],
            cwd=str(BACKEND),
        )
    finally:
        if wa_proc:
            wa_proc.terminate()
            wa_proc.wait(timeout=5)


def main():
    print()
    print("Chatty — Local Setup")
    print("=" * 50)

    print("\nChecking prerequisites...")
    check_python()
    check_node()

    print("\nSetting up environment...")
    setup_env()

    print("\nSetting up Python...")
    setup_venv()
    install_deps()

    print("\nSetting up frontend...")
    setup_frontend()

    print("\nSetting up WhatsApp bridge...")
    setup_whatsapp_bridge()

    print("\nSetting up the virtual computer...")
    setup_computer()

    start_server()


if __name__ == "__main__":
    main()
