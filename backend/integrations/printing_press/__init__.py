"""Printing Press integration — consume the public CLI library.

Chatty builds published Go CLIs from github.com/mvanhorn/printing-press-library
from source and exposes their `--json` command surface to agents as tools, via
subprocess (no MCP). This package owns the toolchain provisioning, source fetch,
build, install store, and runtime invocation.

See the integration plan for the milestone breakdown (M0–M7).
"""
