"""Invoke an installed printed CLI command as a scoped subprocess, parse --json.

``run_cli(slug, command, args)`` is what the ToolRegistry binds as the executor
for a printed-CLI tool. It:

* resolves the built binary + decrypted credentials from the store,
* serializes ``args`` to argv driven by the manifest param schema — path params
  become positional args, query/body params become ``--kebab-case`` flags,
  booleans become presence flags (plan New #5),
* spawns with a **minimal, non-inherited env** (only PATH, a work-dir HOME/XDG,
  and the CLI's declared auth env vars) and a dedicated cwd, with a per-call
  timeout and process-group kill (plan R7),
* parses stdout as JSON and returns a structured dict (or ``{"error": ...}``).

Write-safety is **not** decided here — callers gate writes upstream (M3/M4) and
only invoke once authorized. This module just executes.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from . import paths, store, subprocess_util

logger = logging.getLogger(__name__)

DEFAULT_RUN_TIMEOUT = int(os.getenv("PP_CLI_TIMEOUT", "60"))

# Command path segments must be plain CLI tokens (defense-in-depth: the command
# comes from a resolved tool def, but never trust it into argv unchecked).
_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _normalize_command(command: str | list[str]) -> list[str]:
    parts = command.split() if isinstance(command, str) else list(command)
    if not parts:
        raise ValueError("empty command")
    for seg in parts:
        if not isinstance(seg, str) or not _SEGMENT_RE.match(seg):
            raise ValueError(f"invalid command segment: {seg!r}")
    return parts


def _validate_args(args: dict[str, Any], param_specs: list[dict] | None) -> str | None:
    """Validate args against the manifest param schema. Returns an error string."""
    if param_specs is None:
        return None
    known = {p["name"] for p in param_specs}
    unknown = [k for k in args if k not in known]
    if unknown:
        return f"unknown argument(s): {', '.join(sorted(unknown))}; valid: {', '.join(sorted(known))}"
    missing = [
        p["name"]
        for p in param_specs
        if p.get("required") and (args.get(p["name"]) in (None, ""))
    ]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    return None


def _serialize_args(
    args: dict[str, Any], param_specs: list[dict] | None
) -> tuple[list[str], list[str]]:
    """Map args → (positionals, flags). Path params → positional (manifest order);
    query/body params → ``--kebab-case`` flags; bools → presence flags."""
    spec_by_name = {p["name"]: p for p in (param_specs or [])}
    positionals: list[str] = []
    flags: list[str] = []

    # Path params first, in manifest order, so positional order is deterministic.
    for p in (param_specs or []):
        if p.get("location") == "path":
            val = args.get(p["name"])
            if val not in (None, ""):
                positionals.append(str(val))

    for name, value in args.items():
        spec = spec_by_name.get(name)
        if spec is not None and spec.get("location") == "path":
            continue  # already emitted as positional
        if value is None or value == "":
            continue
        flag = "--" + name.replace("_", "-")
        ptype = (spec or {}).get("type", "")
        if isinstance(value, bool) or ptype in ("boolean", "bool"):
            if value:
                flags.append(flag)  # presence flag; False → omit
        elif isinstance(value, (list, tuple)):
            for item in value:
                flags.extend([flag, str(item)])
        elif isinstance(value, dict):
            flags.extend([flag, json.dumps(value, separators=(",", ":"))])
        else:
            flags.extend([flag, str(value)])
    return positionals, flags


def _redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _scoped_env(work_dir: Path, env_vars: dict[str, str] | None) -> dict[str, str]:
    """A minimal, non-inherited environment for a CLI call (plan R7 / New #4).

    HOME + XDG point into the per-CLI work dir so the CLI persists its own state
    (e.g. a device-flow token) where later runs find it.
    """
    env = {
        "PATH": os.pathsep.join(["/usr/bin", "/bin"]),
        "HOME": str(work_dir),
        "XDG_CONFIG_HOME": str(work_dir / ".config"),
        "XDG_DATA_HOME": str(work_dir / ".local" / "share"),
        "XDG_CACHE_HOME": str(work_dir / ".cache"),
        "NO_COLOR": "1",
    }
    if env_vars:
        # `_`-prefixed keys are internal markers (e.g. device-flow "authorized"),
        # never real env the CLI should receive.
        env.update({k: v for k, v in env_vars.items()
                    if v not in (None, "") and not k.startswith("_")})
    return env


def cli_env(slug: str) -> tuple[Path, dict[str, str]]:
    """The (work_dir, scoped env) a CLI runs under — shared by run_cli and the
    device-flow relay so a token written during auth is found on later runs
    (plan New #4: identical cwd/HOME/XDG/auth env)."""
    work_dir = paths.cli_work_dir(slug)
    return work_dir, _scoped_env(work_dir, store.get_cli_credentials(slug))


def run_command(
    binary: str | Path,
    command: str | list[str],
    args: dict[str, Any] | None = None,
    *,
    work_dir: str | Path,
    env_vars: dict[str, str] | None = None,
    param_specs: list[dict] | None = None,
    timeout: int = DEFAULT_RUN_TIMEOUT,
) -> dict[str, Any]:
    """Execute one CLI command and return its parsed --json result (pure; no store).

    Returns the CLI's JSON object on success, or ``{"error": ...}`` on validation
    failure, non-JSON output, timeout, or non-zero exit.
    """
    args = args or {}
    try:
        command_parts = _normalize_command(command)
    except ValueError as exc:
        return {"error": str(exc)}

    err = _validate_args(args, param_specs)
    if err:
        return {"error": err}

    try:
        positionals, flags = _serialize_args(args, param_specs)
    except Exception as exc:  # serialization should never explode, but fail structured
        return {"error": f"could not serialize arguments: {exc}"}

    work_dir = Path(work_dir)
    for sub in ("", ".config", ".local/share", ".cache"):
        (work_dir / sub).mkdir(parents=True, exist_ok=True)

    argv = [str(binary), *command_parts, *positionals, "--json", *flags]
    env = _scoped_env(work_dir, env_vars)
    secrets = [v for v in (env_vars or {}).values() if v]

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("run_cli argv: %s", _redact(" ".join(argv), secrets))

    result = subprocess_util.run_capture(
        argv, cwd=str(work_dir), env=env, timeout=timeout,
    )
    stderr = _redact(result.stderr, secrets)

    if result.timed_out:
        logger.warning("CLI command timed out: %s", " ".join(command_parts))
        return {"error": f"command timed out after {timeout}s", "command": " ".join(command_parts)}

    parsed: Any = None
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = None

    if result.returncode != 0:
        payload: dict[str, Any] = {
            "error": "command failed",
            "exit_code": result.returncode,
            "command": " ".join(command_parts),
        }
        if parsed is not None:
            payload["detail"] = parsed
        elif stderr.strip():
            payload["stderr"] = stderr.strip()
        elif result.stdout.strip():
            payload["output"] = _redact(result.stdout, secrets)[:2000]
        return payload

    if parsed is None:
        return {
            "error": "command produced no JSON output",
            "command": " ".join(command_parts),
            "stderr": stderr.strip()[:2000] or None,
        }

    return parsed if isinstance(parsed, dict) else {"result": parsed}


def run_cli(
    slug: str,
    command: str | list[str],
    args: dict[str, Any] | None = None,
    *,
    param_specs: list[dict] | None = None,
    timeout: int = DEFAULT_RUN_TIMEOUT,
) -> dict[str, Any]:
    """Store-backed entry point: resolve the installed binary + creds, then run.

    This is the executor bound into the ToolRegistry for a printed-CLI tool.
    """
    try:
        slug = paths.validate_slug(slug)
    except paths.InvalidIdentifier:
        return {"error": f"invalid CLI: {slug!r}"}

    install = store.get_install(slug)
    if install is None:
        return {"error": f"CLI not installed: {slug}"}
    if install.build_status != store.BUILD_READY:
        return {"error": f"CLI {slug} is not ready (build status: {install.build_status})"}

    binary = paths.cli_bin(slug)
    if not binary.exists():
        return {"error": f"CLI binary missing for {slug}; reinstall needed"}

    env_vars = store.get_cli_credentials(slug)
    return run_command(
        binary, command, args,
        work_dir=paths.cli_work_dir(slug),
        env_vars=env_vars,
        param_specs=param_specs,
        timeout=timeout,
    )
