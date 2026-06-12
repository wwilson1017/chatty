"""Deferred tool loading — reduce token usage by loading tool schemas on demand.

When an agent has many tools enabled (>DEFERRED_TOOL_THRESHOLD), only core tools
are sent to the provider with full schemas. Everything else appears as a compact
catalog in the system prompt, and the AI loads full schemas via find_tools().
"""

from __future__ import annotations

import logging
from collections import defaultdict

from .tool_definitions import TOOL_KIND_LABELS

logger = logging.getLogger(__name__)

ALWAYS_LOADED_KINDS: set[str] = {
    "context",
    "memory",
    "playbook",
    "shared_context",
    "chat_history",
    "reminder",
    "scheduled_action",
}

DEFERRED_TOOL_THRESHOLD = 100
MIN_ITERATIONS_FOR_DEFERRAL = 4
MAX_CATALOG_CHARS = 3000
MAX_FIND_TOOLS_RESULTS = 20

FIND_TOOLS_DEF: dict = {
    "name": "find_tools",
    "description": (
        "Search for and load additional tools by keyword or exact name. "
        "Call this when you need tools listed in the 'Available Tools' catalog. "
        "Once loaded, tools become callable for the rest of this conversation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search keyword (e.g. 'email', 'invoice', 'calendar') "
                    "or exact tool name (e.g. 'send_email'). "
                    "Returns matching tools that become available for use."
                ),
            },
        },
        "required": ["query"],
    },
    "kind": "meta",
    "writes": False,
    "context_memory": False,
}

INTEGRATION_LABELS: dict[str, str] = {
    "crm_lite": "CRM",
    "odoo": "Odoo",
    "bamboohr": "BambooHR",
    "quickbooks": "QuickBooks",
    "qb_csv": "QuickBooks CSV",
    "paperclip": "Paperclip",
    "todoist": "Todoist",
}

# Maps common search terms → (kind values, integration names, name prefixes)
# that should match. Each alias entry is a tuple of three lists.
SEARCH_ALIASES: dict[str, tuple[list[str], list[str], list[str]]] = {
    # (kinds, integrations, name_prefixes)
    "email": (["gmail"], [], []),
    "mail": (["gmail"], [], []),
    "gmail": (["gmail"], [], []),
    "invoice": ([], ["quickbooks"], ["qbo_"]),
    "payment": ([], ["quickbooks"], ["qbo_"]),
    "estimate": ([], ["quickbooks"], ["qbo_"]),
    "billing": ([], ["quickbooks"], ["qbo_"]),
    "quickbooks": ([], ["quickbooks"], ["qbo_"]),
    "qbo": ([], ["quickbooks"], ["qbo_"]),
    "drive": (["drive"], [], []),
    "docs": (["drive"], [], []),
    "files": (["drive"], [], []),
    "tasks": ([], ["crm_lite", "odoo", "todoist"], []),
    "todo": ([], ["todoist"], []),
    "todoist": ([], ["todoist"], []),
    "employees": ([], ["bamboohr"], ["bhr_"]),
    "hr": ([], ["bamboohr"], ["bhr_"]),
    "staff": ([], ["bamboohr"], ["bhr_"]),
    "bamboohr": ([], ["bamboohr"], ["bhr_"]),
    "ticket": ([], ["odoo"], ["odoo_"]),
    "helpdesk": ([], ["odoo"], ["odoo_"]),
    "lead": ([], ["crm_lite", "odoo"], ["crm_", "odoo_"]),
    "deal": ([], ["crm_lite"], ["crm_"]),
    "pipeline": ([], ["crm_lite", "odoo"], ["crm_", "odoo_"]),
    "customer": ([], ["crm_lite", "quickbooks"], ["crm_", "qbo_"]),
    "prospect": ([], ["crm_lite"], ["crm_"]),
    "contact": ([], ["crm_lite"], ["crm_"]),
    "crm": ([], ["crm_lite"], ["crm_"]),
    "vendor": ([], ["quickbooks"], ["qbo_"]),
    "supplier": ([], ["quickbooks"], ["qbo_"]),
    "calendar": (["calendar"], [], []),
    "event": (["calendar"], [], []),
    "meeting": (["calendar"], [], []),
    "schedule": (["calendar"], [], []),
    "attachment": ([], ["paperclip"], ["paperclip_"]),
    "clip": ([], ["paperclip"], ["paperclip_"]),
    "paperclip": ([], ["paperclip"], ["paperclip_"]),
    "web": (["web"], [], []),
    "search": (["web"], [], ["web_"]),
    "fetch": (["web"], [], ["web_"]),
    "odoo": ([], ["odoo"], ["odoo_"]),
    "erp": ([], ["odoo"], ["odoo_"]),
    "csv": ([], ["qb_csv"], ["qb_csv_"]),
    "import": ([], ["qb_csv"], ["qb_csv_"]),
    "report": (["report"], [], []),
    "setup": (["setup"], [], []),
    "integrate": (["setup"], [], []),
}


def should_defer_tools(tool_count: int, max_iterations: int = 20) -> bool:
    """Shared gating: returns True if deferred loading should be used."""
    return (
        tool_count > DEFERRED_TOOL_THRESHOLD
        and max_iterations >= MIN_ITERATIONS_FOR_DEFERRAL
    )


def _get_group_label(tool: dict) -> str:
    """Get the display label for a tool's group (kind or integration)."""
    integration = tool.get("integration", "")
    if integration:
        return INTEGRATION_LABELS.get(integration, integration.replace("_", " ").title())
    kind = tool.get("kind", "")
    return TOOL_KIND_LABELS.get(kind, kind.replace("_", " ").title())


def _get_group_key(tool: dict) -> str:
    """Get a stable sort key for grouping."""
    integration = tool.get("integration", "")
    if integration:
        return f"integration:{integration}"
    return f"kind:{tool.get('kind', '')}"


def build_tool_catalog(
    tool_defs: list[dict],
) -> tuple[list[dict], list[dict], set[str], str]:
    """Split tool definitions into active and deferred buckets.

    Returns:
        (active_tools, deferred_tools, deferred_names, catalog_text)
    """
    active: list[dict] = []
    deferred: list[dict] = []

    for t in tool_defs:
        kind = t.get("kind", "")
        if kind in ALWAYS_LOADED_KINDS:
            active.append(t)
        else:
            deferred.append(t)

    deferred_names = {t["name"] for t in deferred}

    if not deferred:
        return active, [], set(), ""

    # Group deferred tools by category for catalog display
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in deferred:
        groups[_get_group_key(t)].append(t)

    catalog_lines = [
        "## Available Tools (use find_tools to load)\n",
        "You have additional tools beyond those above. "
        "Call find_tools with a keyword to search and load them. "
        "Once loaded, tools become callable normally.\n",
    ]

    for group_key in sorted(groups.keys()):
        tools_in_group = groups[group_key]
        label = _get_group_label(tools_in_group[0])
        names = ", ".join(t["name"] for t in tools_in_group)
        catalog_lines.append(f"**{label}:** {names}")

    catalog_text = "\n".join(catalog_lines)

    # Truncate if too long
    if len(catalog_text) > MAX_CATALOG_CHARS:
        total_deferred = len(deferred)
        truncated_lines = [catalog_lines[0], catalog_lines[1]]
        char_count = sum(len(line) + 1 for line in truncated_lines)

        for line in catalog_lines[2:]:
            if char_count + len(line) + 1 > MAX_CATALOG_CHARS - 80:
                break
            truncated_lines.append(line)
            char_count += len(line) + 1

        shown = sum(1 for line in truncated_lines if line.startswith("**"))
        total_groups = len(groups)
        if shown < total_groups:
            truncated_lines.append(
                f"\n... and {total_groups - shown} more categories "
                f"({total_deferred} total tools). Use find_tools to discover them."
            )
        catalog_text = "\n".join(truncated_lines)

    return active, deferred, deferred_names, catalog_text


def execute_find_tools(query: str, deferred_tools: list[dict]) -> dict:
    """Search deferred tools by keyword, returning matched tool definitions.

    The matched_tools list contains full tool defs (for adding to provider_tools).
    The caller should return only loaded_names to the AI — not full schemas.

    Returns dict with: matched_tools, loaded_names, count, truncated, total_matches
    """
    if not query or not deferred_tools:
        return {
            "matched_tools": [],
            "loaded_names": [],
            "count": 0,
            "truncated": False,
            "total_matches": 0,
            "note": "No tools matched. Try a different keyword.",
        }

    query_lower = query.strip().lower()

    # Priority 1: Exact name match (case-insensitive)
    exact = [t for t in deferred_tools if t["name"].lower() == query_lower]
    if exact:
        return {
            "matched_tools": exact,
            "loaded_names": [t["name"] for t in exact],
            "count": len(exact),
            "truncated": False,
            "total_matches": len(exact),
            "note": "Tools loaded and ready to use.",
        }

    # Priority 2: Alias expansion — match by kind, integration, or name prefix
    alias = SEARCH_ALIASES.get(query_lower)
    if alias:
        alias_kinds, alias_integrations, alias_prefixes = alias
        matched: list[dict] = []
        seen: set[str] = set()
        for t in deferred_tools:
            if t["name"] in seen:
                continue
            if t.get("kind", "") in alias_kinds:
                seen.add(t["name"])
                matched.append(t)
            elif t.get("integration", "") in alias_integrations:
                seen.add(t["name"])
                matched.append(t)
            elif any(t["name"].startswith(p) for p in alias_prefixes):
                seen.add(t["name"])
                matched.append(t)
        if matched:
            return _build_result(matched)

    # Priority 3: Kind or integration field match
    kind_matches = [
        t for t in deferred_tools
        if t.get("kind", "") == query_lower or t.get("integration", "") == query_lower
    ]
    if kind_matches:
        return _build_result(kind_matches)

    # Priority 4: Substring match on name and description
    substring_matches = [
        t for t in deferred_tools
        if query_lower in t["name"].lower()
        or query_lower in t.get("description", "").lower()
    ]
    if substring_matches:
        return _build_result(substring_matches)

    return {
        "matched_tools": [],
        "loaded_names": [],
        "count": 0,
        "truncated": False,
        "total_matches": 0,
        "note": f"No tools matched query '{query[:200]}'. Try a different keyword.",
    }


def _build_result(matched: list[dict]) -> dict:
    """Build a find_tools result dict, applying the cap."""
    total = len(matched)
    truncated = total > MAX_FIND_TOOLS_RESULTS
    capped = matched[:MAX_FIND_TOOLS_RESULTS]

    result: dict = {
        "matched_tools": capped,
        "loaded_names": [t["name"] for t in capped],
        "count": len(capped),
        "truncated": truncated,
        "total_matches": total,
        "note": "Tools loaded and ready to use.",
    }
    if truncated:
        result["note"] = (
            f"Showing {MAX_FIND_TOOLS_RESULTS} of {total} matches. "
            "Use a more specific query to find additional tools."
        )
    return result


def load_deferred_tools(
    matched_tools: list[dict],
    tool_defs: list[dict],
    kind_map: dict[str, str],
    deferred_tools: list[dict],
    deferred_names: set[str],
    writes_map: dict[str, bool] | None = None,
    cm_map: dict[str, bool] | None = None,
    integration_map: dict[str, str] | None = None,
) -> list[str]:
    """Add matched tools to all maps and remove from deferred pool.

    Mutates tool_defs, kind_map, deferred_tools, deferred_names, and optional maps.
    Returns list of loaded tool names.
    """
    loaded_names: list[str] = []

    for t in matched_tools:
        name = t["name"]
        if name in kind_map:
            # Already loaded (e.g., from a previous find_tools call in this loop)
            continue

        tool_defs.append(t)
        kind_map[name] = t.get("kind", "context")
        loaded_names.append(name)

        if writes_map is not None:
            writes_map[name] = t.get("writes", False)
        if cm_map is not None:
            cm_map[name] = t.get("context_memory", False)
        if integration_map is not None:
            integration_map[name] = t.get("integration", "")

        deferred_names.discard(name)

    # Remove loaded tools from deferred list
    if loaded_names:
        loaded_set = set(loaded_names)
        deferred_tools[:] = [t for t in deferred_tools if t["name"] not in loaded_set]

    return loaded_names


_INTERNAL_FIELDS = {"kind", "writes", "context_memory", "integration"}


def build_provider_tools(tool_defs: list[dict]) -> list[dict]:
    """Strip internal fields from tool defs for provider consumption."""
    return [{k: v for k, v in t.items() if k not in _INTERNAL_FIELDS} for t in tool_defs]


def handle_deferred_tool_call(
    tool_name: str,
    tool_args: dict,
    deferred_tools: list[dict],
    deferred_names: set[str],
    tool_defs: list[dict],
    kind_map: dict[str, str],
    writes_map: dict[str, bool] | None = None,
    cm_map: dict[str, bool] | None = None,
    integration_map: dict[str, str] | None = None,
) -> tuple[dict | None, bool]:
    """Handle deferred tool guard and find_tools intercept.

    Returns (result, tools_changed):
      - result: a JSON-serializable dict if handled, None if not a deferred concern
      - tools_changed: True if find_tools loaded new tools (caller should rebuild provider_tools)

    Mutates tool_defs, kind_map, deferred_tools, deferred_names, and optional maps.
    """
    if deferred_names and tool_name in deferred_names:
        return (
            {"error": f"Tool '{tool_name}' is available but not loaded. Call find_tools('{tool_name}') first."},
            False,
        )

    if tool_name == "find_tools" and deferred_names is not None:
        query = tool_args.get("query", "")
        find_result = execute_find_tools(query, deferred_tools)
        matched = find_result.pop("matched_tools", [])
        tools_changed = False
        if matched:
            load_deferred_tools(
                matched, tool_defs, kind_map, deferred_tools, deferred_names,
                writes_map=writes_map, cm_map=cm_map, integration_map=integration_map,
            )
            tools_changed = True
        return find_result, tools_changed

    return None, False
