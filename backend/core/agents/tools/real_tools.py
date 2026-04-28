"""Chatty — Real AI tools (Python code tools).

Agent-created Python code tools that run in a sandboxed namespace.
Supports data transformation, aggregation, HTTP calls, and custom logic.

Safety model:
  1. AST validation — statically rejects imports, exec/eval, __dunder__ access
  2. Restricted namespace — __builtins__ is a whitelist dict (no open, exec, etc.)
  3. Timeout — ThreadPoolExecutor with 30s default
  4. HttpProxy — SSRF protection on outbound requests
"""

import ast
import concurrent.futures
import datetime
import decimal
import json
import logging
import math
import re
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in tool names (collision guard)
# ---------------------------------------------------------------------------

_BUILTIN_TOOL_NAMES = {
    "list_context_files", "read_context_file", "write_context_file",
    "append_to_context_file", "delete_context_file",
    "web_search", "web_fetch",
    "search_emails", "get_email", "get_email_thread",
    "list_calendar_events", "get_calendar_event", "search_calendar_events",
    "generate_report",
    "create_reminder", "list_reminders", "cancel_reminder",
    "create_scheduled_action", "list_scheduled_actions",
    "update_scheduled_action", "delete_scheduled_action",
    "create_real_tool", "update_real_tool", "list_real_tools",
    "delete_real_tool", "test_real_tool",
}

_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

# ---------------------------------------------------------------------------
# JSON Schema type validation — prevents agents from creating tools with
# invalid types (e.g. "list", "int") that brick the API.
# ---------------------------------------------------------------------------

_TYPE_COERCE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "text": "string",
}

_VALID_JSON_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


def _normalize_parameter_type(ptype: str) -> str:
    """Normalize a parameter type string to a valid JSON Schema type."""
    normalized = ptype.strip().strip("`").lower()
    bracket_idx = normalized.find("[")
    if bracket_idx > 0:
        normalized = normalized[:bracket_idx]
    of_idx = normalized.find(" of ")
    if of_idx > 0:
        normalized = normalized[:of_idx]
    if normalized in _TYPE_COERCE_MAP:
        return _TYPE_COERCE_MAP[normalized]
    if normalized in _VALID_JSON_SCHEMA_TYPES:
        return normalized
    raise ValueError(
        f"Invalid parameter type '{ptype}'. Valid types: "
        f"{', '.join(sorted(_VALID_JSON_SCHEMA_TYPES))}. "
        f"Common aliases: list->array, int->integer, float->number, dict->object, bool->boolean"
    )


# ---------------------------------------------------------------------------
# Markdown section helpers
# ---------------------------------------------------------------------------

def _split_sections(lines: list[str]) -> dict[str, str]:
    """Split lines into sections by ## headers. Text before first ## goes to '_preamble'."""
    sections: dict[str, str] = {}
    current = "_preamble"
    buf: list[str] = []
    for line in lines:
        m = re.match(r"^##\s+(.+)", line)
        if m:
            sections[current] = "\n".join(buf)
            current = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf)
    return sections


def _parse_parameters(text: str) -> list[dict]:
    """Parse a markdown table of parameters."""
    params = []
    if not text.strip():
        return params

    for line in text.strip().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*Name\s*\|", line) or re.match(r"^\|[\s\-:]+\|", line):
            continue

        raw_cells = line.split("|")
        cells = [c.strip() for c in raw_cells[1:-1]]
        if len(cells) < 3:
            continue

        name = cells[0] if len(cells) > 0 else ""
        ptype = _normalize_parameter_type(cells[1] if len(cells) > 1 else "string")
        required = cells[2].lower() in ("yes", "true") if len(cells) > 2 else False
        default = cells[3] if len(cells) > 3 else ""
        desc = cells[4] if len(cells) > 4 else ""

        if not name:
            continue

        params.append({
            "name": name,
            "type": ptype,
            "required": required,
            "default": default if default else None,
            "description": desc,
        })

    return params


# ---------------------------------------------------------------------------
# AST Validator
# ---------------------------------------------------------------------------

_FORBIDDEN_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
)

_FORBIDDEN_CALLS = {
    "exec", "eval", "compile", "execfile",
    "open", "input",
    "__import__",
    "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir",
    "breakpoint",
    "exit", "quit",
}

_FORBIDDEN_ATTR_NAMES = {
    "system", "popen", "environ",
    "Popen", "subprocess",
}


class _ASTValidator(ast.NodeVisitor):
    """Walk the AST and collect safety violations."""

    def __init__(self):
        self.errors: list[str] = []

    def visit_Import(self, node):
        self.errors.append(f"Line {node.lineno}: import statements are not allowed")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        self.errors.append(f"Line {node.lineno}: from...import statements are not allowed")
        self.generic_visit(node)

    def visit_Global(self, node):
        self.errors.append(f"Line {node.lineno}: global statements are not allowed")
        self.generic_visit(node)

    def visit_Nonlocal(self, node):
        self.errors.append(f"Line {node.lineno}: nonlocal statements are not allowed")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
            self.errors.append(f"Line {node.lineno}: call to '{node.func.id}()' is not allowed")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.attr, str) and node.attr.startswith("__") and node.attr.endswith("__"):
            self.errors.append(f"Line {node.lineno}: dunder attribute access '{node.attr}' is not allowed")
        if isinstance(node.attr, str) and node.attr in _FORBIDDEN_ATTR_NAMES:
            self.errors.append(f"Line {node.lineno}: attribute '{node.attr}' is not allowed")
        self.generic_visit(node)


def validate_code_ast(code: str) -> list[str]:
    """Validate Python code using AST analysis. Returns list of error messages (empty = safe)."""
    errors = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    top_funcs = [
        node for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    run_funcs = [f for f in top_funcs if f.name == "run"]

    if not run_funcs:
        errors.append("Code must define a top-level function named 'run'")
    elif len(run_funcs) > 1:
        errors.append("Code must define exactly one 'run' function")
    else:
        run_func = run_funcs[0]
        args = run_func.args
        if not args.args or args.args[0].arg != "ctx":
            errors.append("The 'run' function must have 'ctx' as its first parameter")

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.Str)):
            continue
        errors.append(f"Line {node.lineno}: only function definitions and constant assignments are allowed at the top level")

    validator = _ASTValidator()
    validator.visit(tree)
    errors.extend(validator.errors)

    return errors


# ---------------------------------------------------------------------------
# ToolContext — Sandbox object providing safe service access
# ---------------------------------------------------------------------------

class HttpProxy:
    """Safe HTTP client with timeouts and SSRF protection."""

    _BLOCKED_HOSTS = {
        "metadata.google.internal",
        "169.254.169.254",
        "metadata.google.internal.",
    }

    def _validate_url(self, url: str):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname in self._BLOCKED_HOSTS:
            raise PermissionError(f"Requests to '{hostname}' are blocked")
        if hostname.startswith("169.254."):
            raise PermissionError(f"Requests to link-local addresses are blocked")

    def get(self, url: str, headers: dict | None = None, timeout: float = 10.0) -> dict:
        self._validate_url(url)
        import httpx
        resp = httpx.get(url, headers=headers or {}, timeout=timeout, follow_redirects=True)
        return {"status": resp.status_code, "body": resp.text, "headers": dict(resp.headers)}

    def post(self, url: str, json_body: dict | None = None,
             headers: dict | None = None, timeout: float = 10.0) -> dict:
        self._validate_url(url)
        import httpx
        resp = httpx.post(url, json=json_body, headers=headers or {}, timeout=timeout, follow_redirects=True)
        return {"status": resp.status_code, "body": resp.text, "headers": dict(resp.headers)}


class ToolContext:
    """Sandboxed context object providing safe access to services.

    Injected as the first argument (ctx) to every real tool's run() function.
    """

    def __init__(self):
        self.http = HttpProxy()
        self.json = json
        self.datetime = datetime
        self.math = math
        self.re = re
        self.decimal = decimal.Decimal


# ---------------------------------------------------------------------------
# Safe builtins whitelist
# ---------------------------------------------------------------------------

_SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "abs": abs, "all": all, "any": any, "bool": bool,
    "dict": dict, "enumerate": enumerate, "filter": filter,
    "float": float, "frozenset": frozenset, "int": int,
    "isinstance": isinstance, "issubclass": issubclass,
    "iter": iter, "len": len, "list": list, "map": map,
    "max": max, "min": min, "next": next, "range": range,
    "reversed": reversed, "round": round, "set": set,
    "slice": slice, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple, "type": type, "zip": zip,
    "hasattr": hasattr, "repr": repr, "format": format,
    "chr": chr, "ord": ord,
    "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError,
    "RuntimeError": RuntimeError, "PermissionError": PermissionError,
    "Exception": Exception, "StopIteration": StopIteration,
    "ZeroDivisionError": ZeroDivisionError, "AttributeError": AttributeError,
}


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def execute_real_tool(code: str, ctx: ToolContext, arguments: dict,
                      timeout: float = 30.0) -> dict:
    """Execute a real tool's Python code in a sandboxed namespace."""
    compiled = compile(code, "<real_tool>", "exec")
    namespace: dict = {"__builtins__": _SAFE_BUILTINS}
    exec(compiled, namespace)

    run_fn = namespace.get("run")
    if not callable(run_fn):
        raise ValueError("Tool code does not define a callable 'run' function")

    def _run():
        return run_fn(ctx, **arguments)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run)
        try:
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Tool execution timed out after {timeout}s")

    if result is None:
        return {"result": None}
    if not isinstance(result, (dict, list, str, int, float, bool)):
        raise ValueError(f"Tool must return a JSON-serializable type, got {type(result).__name__}")

    return result if isinstance(result, dict) else {"result": result}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_real_tool_definition(content: str) -> dict:
    """Parse a *.realtool.md file into a structured tool definition."""
    lines = content.strip().splitlines()
    if not lines:
        raise ValueError("Empty tool definition")

    name_match = re.match(r"^#\s+(\S+)", lines[0])
    if not name_match:
        raise ValueError("Tool definition must start with '# tool_name'")
    name = name_match.group(1)

    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid tool name '{name}': must be alphanumeric with hyphens/underscores")
    if name in _BUILTIN_TOOL_NAMES:
        raise ValueError(f"Tool name '{name}' collides with a built-in tool")

    sections = _split_sections(lines[1:])

    description = sections.get("_preamble", "").strip()
    if not description:
        raise ValueError("Tool definition must include a description after the name")

    params = _parse_parameters(sections.get("Parameters", ""))

    code_section = sections.get("Code", "").strip()
    if not code_section:
        raise ValueError("Tool definition must include a ## Code section with a Python code block")

    code = _extract_code_block(code_section)
    if not code:
        raise ValueError("## Code section must contain a ```python fenced code block")

    ast_errors = validate_code_ast(code)
    if ast_errors:
        raise ValueError("Code validation failed:\n" + "\n".join(f"  - {e}" for e in ast_errors))

    writes_text = sections.get("Writes", "").strip().lower()
    writes = writes_text in ("yes", "true")

    return {
        "name": name,
        "description": description,
        "parameters": params,
        "code": code,
        "writes": writes,
    }


def _extract_code_block(text: str) -> str:
    """Extract Python code from a ```python fenced block."""
    m = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# File I/O handlers (called by tool_registry)
# ---------------------------------------------------------------------------

def create_real_tool(tools_dir: str, name: str, definition: str) -> dict:
    """Validate and write a new real tool definition file."""
    d = Path(tools_dir)
    d.mkdir(parents=True, exist_ok=True)

    try:
        parsed = parse_real_tool_definition(definition)
    except ValueError as e:
        return {"error": str(e)}

    if parsed["name"] != name:
        return {"error": f"Tool name in definition ('{parsed['name']}') must match the 'name' argument ('{name}')"}

    filepath = d / f"{name}.realtool.md"
    if filepath.exists():
        return {"error": f"Tool '{name}' already exists. Use update_real_tool to modify it."}

    filepath.write_text(definition, encoding="utf-8")
    logger.info("Real tool created: %s", name)
    return {"name": name, "ok": True, "description": parsed["description"]}


def update_real_tool(tools_dir: str, name: str, definition: str) -> dict:
    """Validate and overwrite an existing real tool definition file."""
    d = Path(tools_dir)
    filepath = d / f"{name}.realtool.md"
    if not filepath.exists():
        return {"error": f"Tool '{name}' does not exist. Use create_real_tool to create it."}

    try:
        parsed = parse_real_tool_definition(definition)
    except ValueError as e:
        return {"error": str(e)}

    if parsed["name"] != name:
        return {"error": f"Tool name in definition ('{parsed['name']}') must match the 'name' argument ('{name}')"}

    filepath.write_text(definition, encoding="utf-8")
    logger.info("Real tool updated: %s", name)
    return {"name": name, "ok": True, "description": parsed["description"]}


def list_real_tools(tools_dir: str) -> dict:
    """List all real tool definitions."""
    d = Path(tools_dir)
    if not d.exists():
        return {"tools": []}

    tools = []
    for f in sorted(d.glob("*.realtool.md")):
        try:
            parsed = parse_real_tool_definition(f.read_text(encoding="utf-8"))
            tools.append({
                "name": parsed["name"],
                "description": parsed["description"],
                "writes": parsed["writes"],
            })
        except ValueError as e:
            tools.append({"name": f.stem.removesuffix(".realtool"), "error": str(e)})

    return {"tools": tools}


def delete_real_tool(tools_dir: str, name: str) -> dict:
    """Delete a real tool definition file."""
    d = Path(tools_dir)
    filepath = d / f"{name}.realtool.md"
    if not filepath.exists():
        return {"error": f"Tool '{name}' not found"}

    filepath.unlink()
    logger.info("Real tool deleted: %s", name)
    return {"name": name, "deleted": True}


def test_real_tool(definition: str, test_args: dict | None = None,
                   ctx: ToolContext | None = None) -> dict:
    """Parse, validate, and execute a real tool definition without persisting."""
    try:
        parsed = parse_real_tool_definition(definition)
    except ValueError as e:
        return {"error": f"Validation failed: {str(e)}"}

    if ctx is None:
        ctx = ToolContext()

    try:
        result = execute_real_tool(parsed["code"], ctx, test_args or {})
        return {"ok": True, "name": parsed["name"], "result": result}
    except TimeoutError as e:
        return {"error": str(e)}
    except Exception as e:
        tb = traceback.format_exc()
        return {"error": f"Execution failed: {str(e)}", "traceback": tb}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _parsed_to_registry_entry(parsed: dict) -> dict:
    """Convert a parsed real tool definition into a ToolRegistry entry."""
    properties = {}
    required = []
    for p in parsed["parameters"]:
        prop: dict = {"type": p["type"], "description": p.get("description", "")}
        if p["type"] == "array":
            prop["items"] = {}
        if p.get("default"):
            prop["description"] += f" (default: {p['default']})"
        properties[p["name"]] = prop
        if p["required"]:
            required.append(p["name"])

    return {
        "name": parsed["name"],
        "description": parsed["description"],
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required if required else [],
        },
        "kind": "real_tool",
        "writes": parsed["writes"],
        "code": parsed["code"],
        "defaults": {p["name"]: p["default"] for p in parsed["parameters"] if p.get("default")},
    }


def load_all_real_tools(tools_dir: str) -> list[dict]:
    """Parse all *.realtool.md files and return tool registry entries."""
    d = Path(tools_dir)
    if not d.exists():
        return []

    entries = []
    for f in sorted(d.glob("*.realtool.md")):
        try:
            parsed = parse_real_tool_definition(f.read_text(encoding="utf-8"))
            entries.append(_parsed_to_registry_entry(parsed))
        except (ValueError, KeyError) as e:
            logger.warning("Skipping invalid real tool %s: %s", f.name, e)
            continue

    return entries
