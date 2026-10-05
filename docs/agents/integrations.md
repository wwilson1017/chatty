# Adding integrations

Moved verbatim from the root `AGENTS.md`.

## Adding Integrations

New integrations follow a consistent pattern. When connected globally, ALL agents automatically get the integration's tools — no per-agent opt-in required. This is a single-user app; if the user connected a service, they want their agents to use it.

### File structure

Mirror `integrations/quickbooks/` for credential-based integrations, or `integrations/google/` for OAuth-scoped integrations:

```
integrations/{name}/
├── __init__.py
├── client.py          # Authenticated API client (token refresh, retry)
├── onboarding.py      # setup_from_oauth() or setup() — persists credentials
├── tools.py           # Tool handler functions called by ToolRegistry
└── *_ops.py           # Raw API operations (each takes a service/client object)
```

### Wiring checklist

1. **Register** in `integrations/registry.py` → `AVAILABLE_INTEGRATIONS` dict
2. **Add routes** in `integrations/router.py` → setup, setup/complete (for OAuth), disconnect
3. **Add tool definitions** in `core/agents/tool_definitions.py` — each tool needs `name`, `description`, `input_schema`, `kind`, and `writes: bool`
4. **Add dispatch** in `core/agents/tool_registry.py` — add a `_execute_{name}` method and wire it in `execute_tool`
5. **For OAuth integrations**: use the shared two-step flow in `core/providers/oauth.py` — `start_oauth_flow()` returns `{flow_id, auth_url}`, frontend opens popup + polls, `/setup/complete` calls `consume_flow()`
6. **Frontend**: add a card component in `dashboard/` and wire it into `IntegrationsTab.tsx`
7. **Delimiter wrapping**: if the integration fetches data from external APIs, its tools are automatically wrapped in `<untrusted_tool_result>` delimiters (tools with `kind: "integration"` are wrapped by default). If the integration reads from local user data (like CRM Lite), add its tool name prefix to `_UNWRAPPED_INTEGRATION_PREFIXES` in `core/agents/security/delimiters.py`

### Tool auto-discovery

Tools appear for agents automatically when their integration is enabled globally:
- **QB/Odoo/BambooHR/CRM/QB CSV/Paperclip**: `_load_integration_tools()` in `agents/router.py` checks `is_enabled(name)` and injects tools + executors
- **Google (Gmail/Calendar/Drive)**: `google_capabilities()` in `integrations/google/policy.py` reads scope grants from `google.json` and returns capability flags passed to `get_tool_definitions()`. Supports multiple Google accounts with per-agent, per-service assignment.
- **Telegram**: each agent gets its own bot token; a single Telegram user can be linked to multiple agents simultaneously
- **Do NOT require per-agent flags** for new integrations. Connect once → all agents get the tools.

### Write tools

Tools that modify external data (send email, create event, upload file) must set `writes: True` in their tool definition. Chatty's `tool_mode` system will require user confirmation before executing write tools in "normal" mode. Write tools (excluding `context_memory` tools) are also subject to per-turn write budgets and optional hourly rate limits configured in admin settings.
