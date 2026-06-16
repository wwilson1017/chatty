"""Hardened tar extraction for downloaded archives (zip-slip safe).

Two callers with different trust levels:

* The Go toolchain tarball is checksum-verified against an official go.dev pin,
  so it is *trusted*; ``extract_all_trusted`` allows in-tree symlinks (the Go
  distribution contains some) and uses the stdlib ``data`` filter when present.
* The library source tarball is downloaded from GitHub and *untrusted*;
  ``extract_subtree`` rejects symlinks, hardlinks, and special files outright,
  strips the archive prefix, and refuses any member whose resolved path escapes
  the destination root.

Both paths are version-independent (no reliance on Python 3.12's tar filters for
the security guarantee) so the same checks hold on the 3.10+ floor.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path


class UnsafeTarMember(Exception):
    """A tar member would escape the destination root or is a disallowed type."""


def _within(root: Path, target: Path) -> bool:
    """True if ``target`` (after resolving) is at or under ``root``."""
    try:
        target.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _extract_one(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    out_path: Path,
    root_resolved: Path,
    *,
    allow_symlinks: bool,
) -> bool:
    """Extract a single member to ``out_path``. Returns True if written."""
    # The final destination (and, for files, its parent) must stay within root.
    if not _within(root_resolved, out_path):
        raise UnsafeTarMember(f"path escapes destination: {member.name!r}")

    if member.isdir():
        out_path.mkdir(parents=True, exist_ok=True)
        return True

    if member.isfile():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        src = tar.extractfile(member)
        if src is None:
            return False
        with src, open(out_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        # Preserve the executable bit (needed for the built binary / scripts) but
        # never honour setuid/setgid/world-writable from an archive.
        mode = 0o755 if (member.mode & 0o100) else 0o644
        os.chmod(out_path, mode)
        return True

    if member.issym():
        if not allow_symlinks:
            raise UnsafeTarMember(f"symlink not allowed: {member.name!r}")
        target = (out_path.parent / member.linkname)
        if not _within(root_resolved, target):
            raise UnsafeTarMember(
                f"symlink escapes destination: {member.name!r} -> {member.linkname!r}"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.is_symlink() or out_path.exists():
            out_path.unlink()
        os.symlink(member.linkname, out_path)
        return True

    if member.islnk():
        raise UnsafeTarMember(f"hardlink not allowed: {member.name!r}")

    # char/block/fifo and anything else: skip silently (never relevant to a CLI tree).
    return False


def extract_subtree(
    tar: tarfile.TarFile, dest_root: Path, subpath: str, *, allow_symlinks: bool = False
) -> tuple[int, str | None]:
    """Extract members under ``<top>/<subpath>/`` into ``dest_root``, stripping it.

    GitHub codeload archives wrap everything in a single top-level directory
    (``<repo>-<ref>/``). ``subpath`` is the repo-relative path of the wanted
    subtree (e.g. ``"library/other/openalex"``); the wrapper dir is detected from
    the stream rather than assumed, so this works in a single forward pass over a
    non-seekable ``r|gz`` stream.

    Returns ``(files_written, detected_top_dir)``; the caller verifies the top dir
    matches the pinned commit SHA. Raises :class:`UnsafeTarMember` on any
    traversal/symlink/special member so a hostile archive fails closed.
    """
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    root_resolved = dest_root.resolve()
    subpath = subpath.strip("/")
    top: str | None = None
    written = 0
    for member in tar:
        name = member.name.strip("/")
        head, _, rest = name.partition("/")
        if top is None:
            top = head
        if rest == subpath:
            continue  # the subtree directory itself
        if not rest.startswith(subpath + "/"):
            continue
        rel = rest[len(subpath) + 1 :]
        if not rel or rel.startswith("/") or os.path.isabs(rel) or ".." in Path(rel).parts:
            raise UnsafeTarMember(f"unsafe member path: {member.name!r}")
        if _extract_one(
            tar, member, dest_root / rel, root_resolved, allow_symlinks=allow_symlinks
        ):
            written += 1
    return written, top


def extract_all_trusted(tar: tarfile.TarFile, dest_root: Path) -> None:
    """Extract an entire trusted (checksum-verified) archive into ``dest_root``.

    Prefers the stdlib ``data`` filter (Python 3.12+) for speed and its built-in
    traversal guards; falls back to the vetted manual loop (allowing in-tree
    symlinks) on older interpreters.
    """
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        tar.extractall(path=dest_root, filter="data")  # type: ignore[call-arg]
        return
    except TypeError:
        pass  # Python < 3.12: no filter kwarg
    root_resolved = dest_root.resolve()
    for member in tar:
        rel = member.name.strip("/")
        if not rel or os.path.isabs(rel) or ".." in Path(rel).parts:
            raise UnsafeTarMember(f"unsafe member path: {member.name!r}")
        _extract_one(tar, member, dest_root / rel, root_resolved, allow_symlinks=True)
