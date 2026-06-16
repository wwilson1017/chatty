"""Device-code OAuth relay for printed CLIs that support it.

Most published CLIs authenticate by pasted credential (api_key / bearer / PAT),
which Chatty stores encrypted and injects as env vars at run time — no relay
needed. A minority use device-code OAuth, where the CLI embeds its own client ID
and owns the token. For those we *drive the CLI's own subcommands*:

    <bin> auth device --json   → {user_code, verification_uri, interval}
    <bin> auth poll   --json   → blocks/returns until authorized; the CLI then
                                 persists its token under its work dir

so the token never enters Chatty's store. We relay the code+URL to the browser
and background-poll. Capability is detected from the CLI's ``auth --help`` and the
affordance is gated on it (plan R6); paste is always the fallback.

State is in-memory (single worker, like the build jobs / OAuth flows).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import paths, runner, store, subprocess_util

logger = logging.getLogger(__name__)

PENDING = "pending"
AUTHORIZED = "authorized"
ERROR = "error"
EXPIRED = "expired"

_DEVICE_FLOWS: dict[str, "DeviceFlow"] = {}
_lock = threading.Lock()
_MAX_POLL_SECONDS = 600


@dataclass
class DeviceFlow:
    flow_id: str
    slug: str
    status: str = PENDING
    user_code: str = ""
    verification_uri: str = ""
    error: str | None = None
    created_at: float = 0.0


def supports_device_flow(slug: str) -> bool:
    """True if the CLI exposes a device-code subcommand (probed from auth --help)."""
    try:
        slug = paths.validate_slug(slug)
    except paths.InvalidIdentifier:
        return False
    binary = paths.cli_bin(slug)
    if not binary.exists():
        return False
    work_dir, env = runner.cli_env(slug)
    work_dir.mkdir(parents=True, exist_ok=True)
    res = subprocess_util.run_capture(
        [str(binary), "auth", "--help"], cwd=str(work_dir), env=env, timeout=15,
        merge_stderr=True,
    )
    text = res.stdout.lower()
    # A device-code flow exposes a "device" (or "login") initiator command.
    return bool(re.search(r"^\s*(device|login)\b", text, re.MULTILINE))


def get_flow(flow_id: str) -> DeviceFlow | None:
    return _DEVICE_FLOWS.get(flow_id)


def start_device_flow(slug: str) -> dict[str, Any]:
    """Kick off ``<bin> auth device`` and begin background polling.

    Returns ``{flow_id, user_code, verification_uri}`` or ``{"error": ...}``.
    """
    slug = paths.validate_slug(slug)
    binary = paths.cli_bin(slug)
    if not binary.exists():
        return {"error": f"CLI not built: {slug}"}

    work_dir, env = runner.cli_env(slug)
    work_dir.mkdir(parents=True, exist_ok=True)
    res = subprocess_util.run_capture(
        [str(binary), "auth", "device", "--json"], cwd=str(work_dir), env=env, timeout=30,
    )
    if res.returncode != 0:
        return {"error": f"could not start device flow: {res.stderr.strip()[:300]}"}
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return {"error": "device flow returned no JSON"}

    flow_id = uuid.uuid4().hex
    flow = DeviceFlow(
        flow_id=flow_id, slug=slug, created_at=time.time(),
        user_code=str(data.get("user_code", "")),
        verification_uri=str(data.get("verification_uri", "")),
    )
    with _lock:
        _DEVICE_FLOWS[flow_id] = flow
    threading.Thread(target=_poll, args=(flow, str(binary), str(work_dir), env), daemon=True).start()
    return {"flow_id": flow_id, "user_code": flow.user_code, "verification_uri": flow.verification_uri}


def _poll(flow: DeviceFlow, binary: str, work_dir: str, env: dict[str, str]) -> None:
    """Block on ``<bin> auth poll`` until the CLI authorizes (it persists its token)."""
    try:
        res = subprocess_util.run_capture(
            [binary, "auth", "poll", "--json"], cwd=work_dir, env=env, timeout=_MAX_POLL_SECONDS,
        )
        if res.timed_out:
            flow.status = EXPIRED
        elif res.returncode == 0:
            flow.status = AUTHORIZED
            # Record that this CLI is authed (no secret enters the store; the CLI
            # owns its token under work_dir). A marker cred keeps needs_auth false.
            store.save_cli_credentials(flow.slug, {"_device_authorized": "1"})
        else:
            flow.status = ERROR
            flow.error = res.stderr.strip()[:300] or "authorization failed"
    except Exception as exc:  # noqa: BLE001
        flow.status = ERROR
        flow.error = str(exc)
