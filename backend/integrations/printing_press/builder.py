"""Build a staged CLI's source into a runnable binary with the pinned toolchain.

``go build -mod=readonly ./cmd/<slug>-pp-cli`` → ``data/clis/<slug>/bin/<slug>-pp-cli``.
Runs as a tracked subprocess with the hermetic build env (``toolchain.build_env``),
a hard timeout, bounded parallelism (to cap CPU/RAM on small Railway boxes), and
process-group kill on timeout. Build output is captured so failures surface a
(redacted, truncated) compiler log rather than a bare exit code.

This module never blocks the request worker on its own — the build-job layer
(M5) runs it on a background threadpool. Here it is a plain, synchronous,
cancellable function.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from . import paths, subprocess_util, toolchain

logger = logging.getLogger(__name__)

# Bound build parallelism so a cold build doesn't OOM a small box. Used for both
# `go build -p` and GOMAXPROCS. Override via env for bigger machines.
BUILD_PARALLELISM = int(os.getenv("PP_GO_BUILD_PROCS", "2"))
DEFAULT_BUILD_TIMEOUT = int(os.getenv("PP_GO_BUILD_TIMEOUT", "600"))

# Cap captured build log so a pathological build can't blow up memory/logs.
_MAX_LOG_BYTES = 64 * 1024

Progress = Callable[[str, str], None]


class BuildError(RuntimeError):
    """A `go build` invocation failed (non-zero exit, timeout, or bad layout)."""


def _emit(progress: Progress | None, phase: str, msg: str) -> None:
    if progress is not None:
        try:
            progress(phase, msg)
        except Exception:
            logger.debug("progress callback raised", exc_info=True)


def discover_cmd(src_dir: Path, slug: str) -> str:
    """Return the cmd package name to build (e.g. ``openalex-pp-cli``).

    Prefers ``cmd/<slug>-pp-cli``; otherwise the sole ``*-pp-cli`` under ``cmd/``.
    Never selects the ``-pp-mcp`` sibling.
    """
    cmd_root = Path(src_dir) / "cmd"
    preferred = f"{slug}{paths.CLI_BINARY_SUFFIX}"  # <slug>-pp-cli
    if (cmd_root / preferred / "main.go").exists():
        return preferred
    candidates = [
        d.name
        for d in sorted(cmd_root.glob("*"))
        if d.is_dir() and d.name.endswith(paths.CLI_BINARY_SUFFIX) and (d / "main.go").exists()
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise BuildError(
        f"cannot determine CLI build target under {cmd_root} "
        f"(looked for {preferred!r}; found {candidates or 'none'})"
    )


def go_build(
    slug: str,
    src_dir: Path,
    *,
    progress: Progress | None = None,
    timeout: int = DEFAULT_BUILD_TIMEOUT,
    parallelism: int = BUILD_PARALLELISM,
) -> dict[str, Any]:
    """Build the staged CLI at ``src_dir`` into ``data/clis/<slug>/bin/<slug>-pp-cli``.

    Returns ``{binary, cmd, duration_s, log, size_bytes}``. Raises
    :class:`BuildError` on any failure.
    """
    slug = paths.validate_slug(slug)
    src_dir = Path(src_dir)
    if not (src_dir / "go.mod").exists():
        raise BuildError(f"no go.mod under staged source {src_dir}")

    cmd_name = discover_cmd(src_dir, slug)
    out = paths.cli_bin(slug)
    out.parent.mkdir(parents=True, exist_ok=True)

    _emit(progress, "toolchain", "ensuring Go toolchain")
    go = toolchain.ensure_go(progress)

    env = toolchain.build_env({"GOMAXPROCS": str(parallelism)})
    argv = [
        str(go), "build",
        "-mod=readonly",
        "-trimpath",
        "-ldflags=-s -w",
        "-p", str(parallelism),
        "-o", str(out),
        f"./cmd/{cmd_name}",
    ]

    _emit(progress, "build", f"go build ./cmd/{cmd_name}")
    logger.info("building %s: %s (cwd=%s)", slug, " ".join(argv), src_dir)
    # The build runs in its own process group so a timeout kills the whole tree
    # (go spawns compile/link children). The build log (stderr merged) is capped.
    result = subprocess_util.run_capture(
        argv, cwd=str(src_dir), env=env, timeout=timeout,
        stdout_cap=_MAX_LOG_BYTES, merge_stderr=True,
    )
    log = result.stdout
    if result.timed_out:
        raise BuildError(f"go build for {slug} timed out after {timeout}s")
    if result.returncode != 0:
        logger.warning("go build failed for %s (rc=%s):\n%s", slug, result.returncode, log)
        raise BuildError(f"go build for {slug} failed (exit {result.returncode}):\n{log}")
    if not out.exists():
        raise BuildError(f"go build for {slug} reported success but {out} is missing")

    size = out.stat().st_size
    _emit(progress, "build", f"built {out.name} ({size // 1024} KiB, {result.duration_s:.1f}s)")
    logger.info("built %s in %.1fs (%d bytes)", slug, result.duration_s, size)
    return {
        "binary": out, "cmd": cmd_name, "duration_s": result.duration_s,
        "log": log, "size_bytes": size,
    }
