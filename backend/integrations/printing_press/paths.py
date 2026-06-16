"""Filesystem layout + identifier validation for the Printing Press integration.

All printed-CLI state lives under Chatty's persistent data root
(``backend/data/`` locally, the Railway volume in prod), matching the per-module
``DATA_DIR`` convention used elsewhere (``core/encryption.py:25``, ``main.py:90``).

Layout::

    data/
      go/                          # provisioned Go toolchain + GOPATH/GOCACHE
        go1.26.4/                  #   extracted GOROOT
        gopath/  cache/  home/     #   GOPATH, GOCACHE, hermetic HOME
      printing_press/
        src/<slug>@<sha>/          # staged CLI source subtree (per pinned commit)
      clis/<slug>/
        bin/<slug>-pp-cli          # built binary
        work/                      # per-CLI runtime cwd (CLI owns its device token here)
        install.json  creds.json   # install metadata + encrypted credentials

Slugs and categories come from the library ``registry.json`` and refs are
resolved to immutable commit SHAs; everything that lands in a filesystem path is
validated here so a malicious or malformed catalog entry can't escape the data
root (path traversal, absolute paths).
"""

from __future__ import annotations

import re
from pathlib import Path

# backend/data — canonical data root. This file is backend/integrations/printing_press/paths.py,
# so three parents up is backend/.
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

GO_DIR = DATA_DIR / "go"
PP_DIR = DATA_DIR / "printing_press"
SRC_DIR = PP_DIR / "src"
CLIS_DIR = DATA_DIR / "clis"

# CLI binaries are named "<slug>-pp-cli" (the generator's cmd/<slug>-pp-cli target).
CLI_BINARY_SUFFIX = "-pp-cli"

# Registry slugs/categories are lowercase kebab (observed: "1password", "judge-me",
# "developer-tools", "food-and-dining"). Anchored, length-capped, must start
# alphanumeric so a segment can never be "", ".", or "..".
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CATEGORY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Resolved refs are git commit SHAs (40 hex today; allow up to 64 for SHA-256).
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


class InvalidIdentifier(ValueError):
    """A slug/category/ref failed validation before being used in a path."""


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise InvalidIdentifier(f"invalid CLI slug: {slug!r}")
    return slug


def validate_category(category: str) -> str:
    if not isinstance(category, str) or not _CATEGORY_RE.match(category):
        raise InvalidIdentifier(f"invalid category: {category!r}")
    return category


def validate_sha(sha: str) -> str:
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise InvalidIdentifier(f"invalid commit sha: {sha!r}")
    return sha


def go_root(version: str) -> Path:
    """GOROOT for a provisioned toolchain version, e.g. data/go/go1.26.4."""
    if not re.match(r"^\d+\.\d+(\.\d+)?$", version):
        raise InvalidIdentifier(f"invalid go version: {version!r}")
    return GO_DIR / f"go{version}"


def cli_dir(slug: str) -> Path:
    return CLIS_DIR / validate_slug(slug)


def cli_bin(slug: str) -> Path:
    slug = validate_slug(slug)
    return CLIS_DIR / slug / "bin" / f"{slug}{CLI_BINARY_SUFFIX}"


def cli_work_dir(slug: str) -> Path:
    return CLIS_DIR / validate_slug(slug) / "work"


def staged_src_dir(slug: str, sha: str) -> Path:
    """Staged source subtree for a pinned (slug, commit) pair: src/<slug>@<sha>."""
    return SRC_DIR / f"{validate_slug(slug)}@{validate_sha(sha)}"
