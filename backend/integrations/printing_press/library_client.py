"""Read + fetch from the public Printing Press library on GitHub.

Source: ``github.com/mvanhorn/printing-press-library``. Each CLI lives at the
repo-relative ``path`` given in the root ``registry.json`` (schema v2), e.g.
``library/other/openalex``, and is its own Go module (``go.mod`` at that dir).

No ``git`` in the image, so we fetch via HTTPS only:

* **Catalog / manifest** — ``raw.githubusercontent.com`` reads (no API rate limit).
* **Source** — resolve the ref to an immutable commit SHA via the GitHub API,
  then stream the ``codeload`` ``tar.gz`` *for that SHA* and extract only the one
  CLI subtree in a single forward pass (peak disk stays at the subtree size, not
  the whole repo). The archive's wrapper directory is verified to carry the SHA,
  so a mutable branch/tag can't be substituted underneath us.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

from . import paths, safe_tar

logger = logging.getLogger(__name__)

REPO = "mvanhorn/printing-press-library"
_API_BASE = f"https://api.github.com/repos/{REPO}"
_RAW_BASE = f"https://raw.githubusercontent.com/{REPO}"
_CODELOAD = f"https://codeload.github.com/{REPO}/tar.gz"

REGISTRY_SCHEMA_VERSION = 2
TOOLS_MANIFEST_FILENAME = "tools-manifest.json"

Progress = Callable[[str, str], None]


def _emit(progress: Progress | None, phase: str, msg: str) -> None:
    if progress is not None:
        try:
            progress(phase, msg)
        except Exception:
            logger.debug("progress callback raised", exc_info=True)


def _gh_headers(accept: str) -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": "chatty-printing-press"}
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class _StreamReader(io.RawIOBase):
    """Minimal forward-only file object over an httpx byte iterator.

    ``tarfile`` opened in streaming mode (``r|gz``) only ever calls ``read(n)``
    sequentially, so we buffer just enough to satisfy each request. Tracks total
    bytes consumed for build/telemetry reporting.
    """

    def __init__(self, chunks: Iterator[bytes]):
        self._chunks = chunks
        self._buf = bytearray()
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        if size is None or size < 0:
            for chunk in self._chunks:
                self._buf += chunk
            data = bytes(self._buf)
            self._buf = bytearray()
            self.bytes_read += len(data)
            return data
        while len(self._buf) < size:
            try:
                self._buf += next(self._chunks)
            except StopIteration:
                break
        data = bytes(self._buf[:size])
        del self._buf[:size]
        self.bytes_read += len(data)
        return data


def resolve_sha(ref: str = "main") -> str:
    """Resolve a branch/tag/sha ``ref`` to its immutable commit SHA."""
    url = f"{_API_BASE}/commits/{ref}"
    resp = httpx.get(
        url, headers=_gh_headers("application/vnd.github.sha"), timeout=30.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    sha = resp.text.strip()
    return paths.validate_sha(sha)


def fetch_registry(ref: str = "main") -> dict[str, Any]:
    """Fetch and parse the root ``registry.json`` catalog at ``ref``."""
    url = f"{_RAW_BASE}/{ref}/registry.json"
    resp = httpx.get(url, headers=_gh_headers("application/json"), timeout=60.0,
                     follow_redirects=True)
    resp.raise_for_status()
    registry = resp.json()
    version = registry.get("schema_version")
    if version != REGISTRY_SCHEMA_VERSION:
        logger.warning(
            "registry.json schema_version %r != expected %d", version, REGISTRY_SCHEMA_VERSION
        )
    return registry


def read_manifest(src_dir: Path) -> dict[str, Any]:
    """Read ``tools-manifest.json`` from a staged CLI source dir."""
    path = Path(src_dir) / TOOLS_MANIFEST_FILENAME
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_source(
    slug: str, category: str, *, ref: str = "main", progress: Progress | None = None
) -> dict[str, Any]:
    """Fetch + stage one CLI's source subtree, pinned to an immutable commit.

    Returns ``{slug, category, ref, sha, src, files, bytes_downloaded, cached}``
    where ``src`` is the staged directory (containing ``go.mod`` and
    ``tools-manifest.json``). Idempotent: a previously staged ``(slug, sha)`` is
    reused.
    """
    slug = paths.validate_slug(slug)
    category = paths.validate_category(category)

    _emit(progress, "fetch", f"resolving {REPO}@{ref}")
    sha = resolve_sha(ref)
    dest = paths.staged_src_dir(slug, sha)
    if (dest / "go.mod").exists():
        _emit(progress, "fetch", f"using staged source @ {sha[:12]}")
        return {
            "slug": slug, "category": category, "ref": ref, "sha": sha,
            "src": dest, "files": None, "bytes_downloaded": 0, "cached": True,
        }

    subpath = f"library/{category}/{slug}"
    url = f"{_CODELOAD}/{sha}"
    paths.SRC_DIR.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{slug}-", dir=paths.SRC_DIR))

    _emit(progress, "fetch", f"downloading source subtree {subpath}")
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)
    try:
        with httpx.stream(
            "GET", url, headers=_gh_headers("application/octet-stream"),
            timeout=timeout, follow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            reader = _StreamReader(resp.iter_bytes(chunk_size=1 << 20))
            with tarfile.open(fileobj=reader, mode="r|gz") as tar:
                written, top = safe_tar.extract_subtree(
                    tar, staging, subpath, allow_symlinks=False
                )
            bytes_downloaded = reader.bytes_read

        # The codeload wrapper dir is "<repo-name>-<sha>"; its presence confirms
        # the archive really is the pinned commit (not a substituted ref).
        if not top or not top.endswith(f"-{sha}"):
            raise RuntimeError(
                f"archive top dir {top!r} does not match pinned sha {sha}"
            )
        if written == 0 or not (staging / "go.mod").exists():
            raise RuntimeError(
                f"subtree {subpath} not found in {REPO}@{sha} (is the path/category correct?)"
            )

        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        os.replace(staging, dest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    _emit(progress, "fetch", f"staged {written} files ({bytes_downloaded // 1024} KiB downloaded)")
    return {
        "slug": slug, "category": category, "ref": ref, "sha": sha,
        "src": dest, "files": written, "bytes_downloaded": bytes_downloaded, "cached": False,
    }
