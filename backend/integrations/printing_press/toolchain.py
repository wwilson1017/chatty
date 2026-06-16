"""Lazy, pinned, checksum-verified Go toolchain provisioning.

The default Chatty image stays lean (no Go). The first time a printed CLI needs
to be built, we download the pinned Go release to the persistent volume
(``data/go/``), verify it against an official ``go.dev`` SHA-256, and extract it.
Subsequent builds reuse it.

Pin: **go1.26.4**. The published library currently emits ``go 1.26.3`` go.mod
directives; a newer patch satisfies that. ``GOTOOLCHAIN=local`` (set in the build
env) means a CLI requiring a *newer* Go fails loudly with a toolchain error
rather than silently downloading an unpinned toolchain over the network — the
provisioned toolchain is the only one we ever execute.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Callable

import httpx

from . import paths, safe_tar

logger = logging.getLogger(__name__)

GO_VERSION = "1.26.4"
_DL_BASE = "https://go.dev/dl"

# Pinned SHA-256 of each official archive (https://go.dev/dl/?mode=json).
# Keyed by (go_os, go_arch). Update in lockstep with GO_VERSION.
_GO_SHA256: dict[tuple[str, str], str] = {
    ("darwin", "amd64"): "05dc9b5f9997744520aaebb3d5deaa7c755371aebbfb7f97c2511a9f3367538d",
    ("darwin", "arm64"): "b62ad2b6d7d2464f12a5bcad7ff47f19d08325773b5efd21610e445a05a9bf53",
    ("linux", "amd64"): "1153d3d50e0ac764b447adfe05c2bcf08e889d42a02e0fe0259bd47f6733ad7f",
    ("linux", "arm64"): "ef758ae7c6cf9267c9c0ef080b8965f453d89ab2d25d9eb22de4405925238768",
}

# (phase, message) progress sink.
Progress = Callable[[str, str], None]

_PROVISION_LOCK = threading.Lock()


def current_platform() -> tuple[str, str]:
    """Map the host to Go's (GOOS, GOARCH) naming. Raises on unsupported hosts."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    go_os = {"darwin": "darwin", "linux": "linux"}.get(system)
    go_arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine)
    if not go_os or not go_arch:
        raise RuntimeError(
            f"unsupported platform for Go toolchain: {platform.system()}/{platform.machine()}"
        )
    return go_os, go_arch


def go_root() -> Path:
    return paths.go_root(GO_VERSION)


def go_binary() -> Path:
    return go_root() / "bin" / "go"


def is_provisioned() -> bool:
    """True if the pinned toolchain is already extracted and runnable."""
    return go_binary().exists()


def _emit(progress: Progress | None, phase: str, msg: str) -> None:
    if progress is not None:
        try:
            progress(phase, msg)
        except Exception:  # progress must never break provisioning
            logger.debug("progress callback raised", exc_info=True)


def _download_verified(url: str, sha256: str, dest: Path, progress: Progress | None) -> None:
    """Stream ``url`` to ``dest``, verifying its SHA-256 before returning."""
    hasher = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=30.0)
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                hasher.update(chunk)
                f.write(chunk)
    actual = hasher.hexdigest()
    if actual != sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Go toolchain checksum mismatch for {url}: expected {sha256}, got {actual}"
        )
    tmp.replace(dest)


def ensure_go(progress: Progress | None = None) -> Path:
    """Idempotently provision the pinned Go toolchain. Returns the ``go`` binary path.

    Thread-safe: only one provisioning runs at a time (builds are serialized on a
    single-worker pool, but the lock makes the function safe regardless).
    """
    if is_provisioned():
        return go_binary()

    with _PROVISION_LOCK:
        if is_provisioned():  # another thread won the race
            return go_binary()

        go_os, go_arch = current_platform()
        key = (go_os, go_arch)
        sha256 = _GO_SHA256.get(key)
        if not sha256:
            raise RuntimeError(f"no pinned Go checksum for {go_os}/{go_arch}")

        filename = f"go{GO_VERSION}.{go_os}-{go_arch}.tar.gz"
        url = f"{_DL_BASE}/{filename}"
        paths.GO_DIR.mkdir(parents=True, exist_ok=True)

        _emit(progress, "toolchain", f"downloading {filename}")
        logger.info("provisioning Go toolchain %s from %s", GO_VERSION, url)
        archive = paths.GO_DIR / filename
        _download_verified(url, sha256, archive, progress)

        _emit(progress, "toolchain", "extracting toolchain")
        # Extract into a staging dir (archive top-level is "go/"), then atomically
        # rename the inner "go" tree to the versioned GOROOT so a partial extract
        # never looks provisioned.
        staging = Path(tempfile.mkdtemp(prefix=".go-extract-", dir=paths.GO_DIR))
        try:
            with tarfile.open(archive, mode="r:gz") as tar:
                safe_tar.extract_all_trusted(tar, staging)
            extracted_root = staging / "go"
            if not (extracted_root / "bin" / "go").exists():
                raise RuntimeError("extracted Go toolchain missing bin/go")
            target = go_root()
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            os.replace(extracted_root, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            archive.unlink(missing_ok=True)

        # Pre-create the writable Go dirs so the build env points at real paths.
        for d in (paths.GO_DIR / "gopath", paths.GO_DIR / "cache", paths.GO_DIR / "home"):
            d.mkdir(parents=True, exist_ok=True)

        _emit(progress, "toolchain", f"Go {GO_VERSION} ready")
        logger.info("Go toolchain %s provisioned at %s", GO_VERSION, go_root())
        return go_binary()


def build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """A hermetic, minimal environment for invoking the provisioned ``go``.

    Deliberately does NOT inherit ``os.environ`` (R7): only a minimal PATH, a
    contained HOME, and the Go knobs. ``GOTOOLCHAIN=local`` forbids auto-download;
    ``CGO_ENABLED=0`` keeps builds toolchain-free (published CLIs use pure-Go deps
    such as modernc.org/sqlite); ``GOFLAGS=-mod=readonly`` forbids go.mod/go.sum
    edits (the CLIs ship a complete go.sum).
    """
    gobin = str(go_root() / "bin")
    env = {
        "PATH": os.pathsep.join([gobin, "/usr/bin", "/bin"]),
        "HOME": str(paths.GO_DIR / "home"),
        "GOROOT": str(go_root()),
        "GOPATH": str(paths.GO_DIR / "gopath"),
        "GOCACHE": str(paths.GO_DIR / "cache"),
        "GOENV": "off",
        "GOTOOLCHAIN": "local",
        "GOFLAGS": "-mod=readonly",
        "GOPROXY": "https://proxy.golang.org,direct",
        "GOSUMDB": "sum.golang.org",
        "CGO_ENABLED": "0",
    }
    if extra:
        env.update(extra)
    return env
