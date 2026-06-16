"""Turn a CLI's ``tools-manifest.json`` into Chatty agent tool defs + executors.

Each manifest tool (e.g. ``authors_list``) becomes:

* a Chatty tool def — name ``<slug>__<manifest_name>`` (e.g. ``openalex__authors_list``),
  ``kind="printed_cli"``, ``integration="pp:<slug>"``, ``writes`` derived from the
  HTTP method, ``input_schema`` from the manifest params; and
* an executor closure that maps the call to ``runner.run_cli(slug, command, args)``,
  where the CLI command path is the manifest name split on ``_`` (``authors_list``
  → ``authors list``; verified to resolve for every command of a published CLI)
  and the manifest params drive arg→argv serialization.

The full param schema lives in the executor closure, not the tool def, so the
def stays a clean provider-facing shape (name/description/input_schema).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

from . import runner

KIND_PRINTED_CLI = "printed_cli"

# HTTP methods that mutate state → the tool is a write (needs confirmation).
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# manifest param type → JSON Schema type (default to string for anything odd).
_JSON_TYPES = {
    "string": "string", "integer": "integer", "int": "integer",
    "number": "number", "float": "number", "boolean": "boolean",
    "bool": "boolean", "array": "array", "object": "object",
}

# Provider tool-name limit (Anthropic/OpenAI both cap at 64, charset [A-Za-z0-9_-]).
_MAX_TOOL_NAME = 64


def integration_id(slug: str) -> str:
    return f"pp:{slug}"


def tool_name(slug: str, manifest_name: str) -> str:
    """``<slug>__<manifest_name>``, guaranteed ≤64 chars and provider-safe."""
    name = f"{slug}__{manifest_name}"
    if len(name) <= _MAX_TOOL_NAME:
        return name
    # Preserve uniqueness with a short digest suffix when truncation is needed.
    digest = hashlib.sha1(name.encode()).hexdigest()[:6]
    keep = _MAX_TOOL_NAME - len(digest) - 1
    return f"{name[:keep]}_{digest}"


def command_path(manifest_name: str) -> list[str]:
    """Manifest tool name → CLI command path (``authors_list`` → ``[authors, list]``)."""
    return manifest_name.split("_")


def is_write(tool: dict) -> bool:
    return str(tool.get("method", "")).upper() in _WRITE_METHODS


def _input_schema(params: list[dict]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        name = p.get("name")
        if not name:
            continue
        schema: dict[str, Any] = {"type": _JSON_TYPES.get(str(p.get("type", "")).lower(), "string")}
        if p.get("description"):
            schema["description"] = p["description"]
        props[name] = schema
        if p.get("required"):
            required.append(name)
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


@dataclass
class PrintedCommand:
    """One CLI command, with everything the flat surface and the bridge need."""
    tool_name: str            # "openalex__authors_list"
    slug: str                 # "openalex"
    command: list[str]        # ["authors", "list"]
    description: str          # "[OpenAlex] List authors."
    input_schema: dict        # JSON schema for the model
    writes: bool              # derived from HTTP method
    params: list[dict] = field(default_factory=list)  # manifest params (runner argv)

    @property
    def integration(self) -> str:
        return integration_id(self.slug)


def build_commands(slug: str, manifest: dict) -> list[PrintedCommand]:
    """Parse a CLI's manifest into PrintedCommand records."""
    api_name = manifest.get("api_name", slug)
    commands: list[PrintedCommand] = []
    for t in manifest.get("tools", []):
        mname = t.get("name")
        if not mname:
            continue
        params = t.get("params", []) or []
        desc = t.get("description", "") or mname
        commands.append(PrintedCommand(
            tool_name=tool_name(slug, mname),
            slug=slug,
            command=command_path(mname),
            description=f"[{api_name}] {desc}",
            input_schema=_input_schema(params),
            writes=is_write(t),
            params=params,
        ))
    return commands


def flat_def(cmd: PrintedCommand) -> dict:
    """The provider-facing tool def for a single command (flat surface)."""
    return {
        "name": cmd.tool_name,
        "description": cmd.description,
        "input_schema": cmd.input_schema,
        "kind": KIND_PRINTED_CLI,
        "writes": cmd.writes,
        "integration": cmd.integration,
    }


def flat_executor(cmd: PrintedCommand) -> Callable[..., dict]:
    """Sync executor closure. Invoked via asyncio.to_thread by the ToolRegistry."""
    def _run(**args: Any) -> dict:
        return runner.run_cli(cmd.slug, cmd.command, args, param_specs=cmd.params)
    return _run


def build(slug: str, manifest: dict) -> tuple[list[dict], dict[str, Callable[..., dict]]]:
    """Build (flat tool_defs, executors) for an installed CLI from its manifest."""
    commands = build_commands(slug, manifest)
    return [flat_def(c) for c in commands], {c.tool_name: flat_executor(c) for c in commands}
