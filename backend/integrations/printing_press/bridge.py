"""Threshold-gated bridge that keeps the printed-CLI tool surface flat.

Installing a CLI can add dozens of commands (openalex alone has 43). Exposing
every one as its own tool would bloat the prompt, so above a token budget the
whole printed surface collapses to **three** meta-tools — ``cli_search`` /
``cli_describe`` / ``cli_call`` — and individual commands are reached through
them. Below the budget, commands stay as flat per-command tools.

Write-safety crux: ``cli_call`` is statically ``writes=False`` because its
write-ness depends on the *resolved* command. :func:`resolve_cli_call` is the
single, store-backed resolver every write gate calls to recover the real
``(slug, command, writes, …)`` before deciding whether to confirm/run.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Callable

from . import manifest as pp_manifest, runner, store
from .manifest import PrintedCommand

# Collapse to the bridge once flat printed defs would cost more than this many
# (estimated) tokens. Tunable for bigger context windows.
PRINTED_TOOL_TOKEN_BUDGET = int(os.getenv("PP_FLAT_TOOL_BUDGET", "2500"))

KIND_BRIDGE = "printed_cli_bridge"
_BRIDGE_TOOLS = ("cli_search", "cli_describe", "cli_call")


def is_bridge_tool(name: str) -> bool:
    return name in _BRIDGE_TOOLS


# ── catalog (store-backed; no per-request state) ──────────────────────────

def all_commands() -> list[PrintedCommand]:
    """Every command across all enabled+ready installed CLIs (re-derived from store)."""
    out: list[PrintedCommand] = []
    for inst in store.list_installed():
        if not (inst.enabled and inst.build_status == store.BUILD_READY):
            continue
        manifest = store.get_manifest(inst.slug)
        if not manifest:
            continue
        out.extend(pp_manifest.build_commands(inst.slug, manifest))
    return out


def _find_command(slug: str, tool_name: str) -> PrintedCommand | None:
    manifest = store.get_manifest(slug)
    if not manifest:
        return None
    for c in pp_manifest.build_commands(slug, manifest):
        if c.tool_name == tool_name:
            return c
    return None


# ── resolve-then-confirm (the single resolver every gate calls) ───────────

def resolve_cli_call(args: dict | None) -> dict:
    """Resolve a ``cli_call`` invocation to its concrete command + write verdict.

    Pure + store-backed so it can run at every write gate (chat confirm,
    /tool/execute, run_sync, background). Returns ``{"error": ...}`` for an
    unknown command; otherwise ``{slug, tool_name, command, command_args, params,
    writes, ref, tool_mode, description}``.
    """
    args = args or {}
    command = args.get("command", "")
    if not isinstance(command, str) or "__" not in command:
        return {"error": f"unknown CLI command: {command!r}"}
    slug = command.split("__", 1)[0]
    cmd = _find_command(slug, command)
    if cmd is None:
        return {"error": f"unknown CLI command: {command}"}
    install = store.get_install(slug)
    return {
        "slug": slug,
        "tool_name": command,
        "command": cmd.command,
        "command_args": args.get("arguments", {}) or {},
        "params": cmd.params,
        "writes": cmd.writes,
        "ref": install.sha if install else "",
        "tool_mode": install.tool_mode if install else store.TOOL_MODE_READONLY,
        "description": cmd.description,
    }


# ── BM25 search over command name + description ────────────────────────────

def _tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _bm25(query: str, docs: list[tuple[str, str]], limit: int) -> list[str]:
    q_terms = _tokenize(query)
    if not q_terms or not docs:
        return []
    tokenized = [(doc_id, _tokenize(text)) for doc_id, text in docs]
    n = len(tokenized)
    avgdl = sum(len(t) for _, t in tokenized) / n
    df: dict[str, int] = {}
    for _, toks in tokenized:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    k1, b = 1.5, 0.75
    scored: list[tuple[float, str]] = []
    for doc_id, toks in tokenized:
        if not toks:
            continue
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        dl = len(toks)
        score = 0.0
        for qt in q_terms:
            f = tf.get(qt, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[qt] + 0.5) / (df[qt] + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            scored.append((score, doc_id))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [doc_id for _, doc_id in scored[:limit]]


# ── the three bridge executors (sync; run via asyncio.to_thread) ──────────

def cli_search(query: str = "", limit: int = 10, **_: Any) -> dict:
    cmds = all_commands()
    by_name = {c.tool_name: c for c in cmds}
    docs = [(c.tool_name, f"{c.tool_name} {c.description}") for c in cmds]
    try:
        limit = max(1, min(int(limit), 25))
    except (TypeError, ValueError):
        limit = 10
    ids = _bm25(query, docs, limit)
    results = [
        {"command": i, "description": by_name[i].description, "writes": by_name[i].writes}
        for i in ids
    ]
    return {"query": query, "count": len(results), "results": results}


def cli_describe(command: str = "", **_: Any) -> dict:
    if not isinstance(command, str) or "__" not in command:
        return {"error": f"unknown CLI command: {command!r}"}
    cmd = _find_command(command.split("__", 1)[0], command)
    if cmd is None:
        return {"error": f"unknown CLI command: {command}"}
    return {
        "command": command,
        "description": cmd.description,
        "writes": cmd.writes,
        "input_schema": cmd.input_schema,
    }


def cli_call(command: str = "", arguments: dict | None = None, **_: Any) -> dict:
    resolved = resolve_cli_call({"command": command, "arguments": arguments or {}})
    if "error" in resolved:
        return resolved
    return runner.run_cli(
        resolved["slug"], resolved["command"], resolved["command_args"],
        param_specs=resolved["params"],
    )


# ── bridge tool definitions ───────────────────────────────────────────────

def _bridge_defs() -> list[dict]:
    return [
        {
            "name": "cli_search",
            "description": (
                "Search the commands of installed CLIs (connected APIs) by keyword. "
                "Returns matching command names you can then cli_describe and cli_call."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to match command names/descriptions"},
                    "limit": {"type": "integer", "description": "Max results (default 10, max 25)"},
                },
                "required": ["query"],
            },
            "kind": KIND_BRIDGE,
            "writes": False,
        },
        {
            "name": "cli_describe",
            "description": "Show the full input schema and write-status for one CLI command (from cli_search).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command name, e.g. openalex__authors_list"},
                },
                "required": ["command"],
            },
            "kind": KIND_BRIDGE,
            "writes": False,
        },
        {
            "name": "cli_call",
            "description": (
                "Run a CLI command. Find the command with cli_search and its arguments with "
                "cli_describe first. Pass the command name and an arguments object."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command name, e.g. openalex__authors_list"},
                    "arguments": {"type": "object", "description": "Arguments for the command (see cli_describe)"},
                },
                "required": ["command"],
            },
            "kind": KIND_BRIDGE,
            "writes": False,  # resolved per-call; see resolve_cli_call
        },
    ]


def _estimate_tokens(defs: list[dict]) -> int:
    return len(json.dumps(defs)) // 4


def build_printed_surface(
    commands: list[PrintedCommand],
) -> tuple[list[dict], dict[str, Callable[..., dict]]]:
    """Return the final printed-CLI tool surface for the given commands.

    Flat per-command tools when the surface is small; otherwise the three bridge
    tools. Returns ``(tool_defs, executors)`` keyed by tool name.
    """
    if not commands:
        return [], {}
    flat_defs = [pp_manifest.flat_def(c) for c in commands]
    if _estimate_tokens(flat_defs) <= PRINTED_TOOL_TOKEN_BUDGET:
        return flat_defs, {c.tool_name: pp_manifest.flat_executor(c) for c in commands}
    return _bridge_defs(), {
        "cli_search": cli_search,
        "cli_describe": cli_describe,
        "cli_call": cli_call,
    }
