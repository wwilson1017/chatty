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
        subprocess.run(["npm", "ci"], cwd=str(FRONTEND), check=True)
    else:
        print("  Frontend dependencies already installed.")

    print("  Building frontend...")
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND), check=True)


def setup_whatsapp_bridge():
    """Install WhatsApp bridge sidecar dependencies if needed."""
    if not WA_BRIDGE.exists():
        return
    if not (WA_BRIDGE / "node_modules").exists():
        print("  Installing WhatsApp bridge dependencies...")
        subprocess.run(["npm", "ci"], cwd=str(WA_BRIDGE), check=True)
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

    start_server()


if __name__ == "__main__":
    main()
