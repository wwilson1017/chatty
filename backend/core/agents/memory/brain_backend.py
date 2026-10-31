"""
Chatty — Second-brain memory backend (LONG-TERM memory only), on Common Brain.

An agent whose ``memory_backend`` is ``brain`` keeps its long-term memory in a
Common Brain account (commonbrain.ai: memories and pages every AI the person uses
shares) and its short-term memory — daily notes, meetings, topic files, persona —
in the per-agent ``context/`` exactly as with the builtin backend.

Chatty reaches the brain over Common Brain's REST API with a program key, sent only
as ``Authorization: Bearer cb_…``:
  GET  /api/v1               the tools this key may call: name, description, input_schema, read_only
  POST /api/v1/tools/{name}  call one: a JSON object of arguments in, its result out
                             (400/403/404/413/429 answer {error})

A brain-backed agent's long-term tools are Common Brain's own, by name and schema
(``ALLOWED_TOOLS`` ∩ GET /api/v1; ``tool_definitions``), and background turns drop
the ones that are not ``read_only``. ``ToolRegistry._execute_memory`` sends every
``brain_*`` call to ``call``. ``brain_start`` is not a tool here: its rules and
memories are the prompt's MEMORY section (``context_text``).
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# The Common Brain tools a brain-backed agent gets (the rest of GET /api/v1 — start,
# history, restore, onboarding, curate, forget — are the person's or a curator's).
ALLOWED_TOOLS = (
    "brain_search", "brain_page_list", "brain_page_get", "brain_page_write", "brain_page_append",
    "brain_page_edit", "brain_remember", "brain_memory_update", "brain_changes",
)
# The builtin long-term tools a brain-backed agent does not get: Common Brain's replace them.
# search_memory stays, searching only the local daily notes and topic files.
REPLACED_TOOLS = frozenset({
    "read_memory", "update_memory", "add_fact", "query_facts", "invalidate_fact", "consolidate_memory",
})
# Appended to the brain write tools' descriptions (from Hermes' memory tool).
BRAIN_SKIP_TEXT = (
    " Skip: task progress, completed-work logs, temporary status, assistant actions, in-progress state, "
    "and negative claims about tools or access (they go stale and harden into refusals). When in doubt, store less."
)
# brain_start, rendered — the system prompt's MEMORY section in place of local MEMORY.md.
CONTEXT_MAX_CHARS = 8_000
CONTEXT_TTL_SECONDS = 60.0     # heartbeats fire every 60s; don't hammer the brain
CONTEXT_TIMEOUT_SECONDS = 5.0  # prompt assembly is on the request path
TOOLS_TTL_SECONDS = 600.0      # GET /api/v1 changes only when the key or Common Brain does
CONTEXT_UNAVAILABLE = "[brain unavailable — tool reads still work]"
TRUNCATED = "\n… (cut here: brain_search finds the rest)"
NOT_CONFIGURED = "brain integration is not configured (Settings → Integrations → Second Brain)"
UNREACHABLE = "brain unreachable"
# A call that timed out after it was sent may still have been applied: the brain finishes it after we give up.
TIMED_OUT = "brain timed out — if this was a change it may still have been applied; read it back before retrying"
# Below uvicorn's 5 s keep-alive, so a pooled connection is never reused just as the server closes it.
KEEPALIVE_EXPIRY_SECONDS = 4.0


class BrainBackend:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # transport lets tests plug in httpx.MockTransport — no sockets.  retries=1 re-tries connection
        # failures only (the request never reached the brain), never a request the server received.
        if transport is None:
            transport = httpx.HTTPTransport(
                retries=1, limits=httpx.Limits(keepalive_expiry=KEEPALIVE_EXPIRY_SECONDS),
            )
        self._client = httpx.Client(base_url=self.base_url or "http://unconfigured", timeout=timeout,
                                    headers=headers, transport=transport)
        self._context_cache: tuple[float, str] | None = None  # (expires_at, text)
        self._tools_cache: tuple[float, list[dict]] | None = None  # (expires_at, GET /api/v1 tools)

    def close(self) -> None:
        self._client.close()

    # ── system-prompt memory block ───────────────────────────────────────

    def start(self) -> dict:
        """``brain_start``: the rules, the locked and newest memories, the pages; or {"error"}."""
        return self.call("brain_start", {}, timeout=CONTEXT_TIMEOUT_SECONDS)

    def context_text(self, max_chars: int = CONTEXT_MAX_CHARS) -> str:
        """``brain_start`` rendered for the system prompt, cached for CONTEXT_TTL_SECONDS.
        Failures are cached too, as CONTEXT_UNAVAILABLE, so a dead brain costs one 5 s
        timeout per minute, not one per turn."""
        now = time.monotonic()
        if self._context_cache and self._context_cache[0] > now:
            return self._context_cache[1]
        data = self.start()
        if "error" in data:
            logger.warning("brain_start unavailable: %s", data["error"])
            text = CONTEXT_UNAVAILABLE
        else:
            text = _render_start(data, max_chars)
        self._context_cache = (now + CONTEXT_TTL_SECONDS, text)
        return text

    # ── tools ────────────────────────────────────────────────────────────

    def tools(self) -> list[dict]:
        """GET /api/v1's tools that are in ALLOWED_TOOLS, cached for TOOLS_TTL_SECONDS. A failed
        fetch keeps the last list (or none) and tries again after CONTEXT_TTL_SECONDS."""
        now = time.monotonic()
        if self._tools_cache and self._tools_cache[0] > now:
            return self._tools_cache[1]
        data = self._request("GET", "/api/v1", timeout=CONTEXT_TIMEOUT_SECONDS)
        if "error" in data:
            logger.warning("brain GET /api/v1 unavailable: %s", data["error"])
            listed, ttl = (self._tools_cache[1] if self._tools_cache else []), CONTEXT_TTL_SECONDS
        else:
            listed = [t for t in data.get("tools") or [] if t.get("name") in ALLOWED_TOOLS]
            ttl = TOOLS_TTL_SECONDS
        self._tools_cache = (now + ttl, listed)
        return listed

    def tool_definitions(self, background_mode: bool = False) -> list[dict]:
        """The allowed tools as Chatty tool definitions. Background turns (heartbeats, crons, the
        coach) get only the read_only ones: their findings belong in the local daily note."""
        out = []
        for t in self.tools():
            writes = t.get("read_only") is not True
            if writes and background_mode:
                continue
            out.append({
                "name": t["name"],
                "description": (t.get("description") or t.get("title") or t["name"]) + (BRAIN_SKIP_TEXT if writes else ""),
                "input_schema": t.get("input_schema") or {"type": "object", "properties": {}},
                "kind": "memory",
                "writes": writes,
                "context_memory": True,
            })
        return out

    def call(self, tool_name: str, args: dict, timeout: float | None = None) -> dict:
        """POST /api/v1/tools/<tool_name>: its result, or {"error"}. Results come back verbatim
        (not sanitized): a page body is read to be edited, and brain_page_edit's old_str must
        match it exactly. The prompt block is sanitized where it is injected (ContextManager)."""
        if tool_name != "brain_start" and tool_name not in ALLOWED_TOOLS:
            return {"error": f"{tool_name} is not a Common Brain tool Chatty's agents use"}
        kw = {"timeout": timeout} if timeout is not None else {}
        return self._request("POST", f"/api/v1/tools/{tool_name}", json=args or {}, **kw)

    # ── transport ────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kw) -> dict:
        if not self.base_url:
            return {"error": NOT_CONFIGURED}
        try:
            resp = self._client.request(method, path, **kw)
        except (httpx.ReadTimeout, httpx.WriteTimeout) as e:
            logger.warning("brain %s %s timed out: %s", method, path, e)
            return {"error": UNREACHABLE if method == "GET" else TIMED_OUT}
        except httpx.HTTPError as e:
            logger.warning("brain %s %s failed: %s", method, path, e)
            return {"error": UNREACHABLE}
        try:
            data = resp.json()
        except ValueError:
            return {"error": f"brain returned non-JSON ({resp.status_code})"}
        if resp.status_code >= 400:
            detail = data.get("error") if isinstance(data, dict) else data
            return {"error": f"brain error ({resp.status_code}): {detail}"}
        return data if isinstance(data, dict) else {"error": f"brain returned {type(data).__name__}, not an object"}


def _render_start(data: dict, max_chars: int) -> str:
    """brain_start as the prompt's MEMORY section: its rules, then its memories (the locked ones,
    then the newest), cut at a line to max_chars."""
    lines = ["Rules (from brain_start, already called for you this turn):"]
    lines += [f"- {rule}" for rule in data.get("rules") or []]
    lines += ["", "Memories (#id for brain_memory_update; a locked one is the person's own words):"]
    memories = data.get("memories") or []
    lines += [f"- {m.get('text', '')} (#{m.get('id')}{', locked' if m.get('locked') else ''})" for m in memories]
    if not memories:
        lines.append("(none yet)")
    lines += [data[k] for k in ("more_memories", "read_only") if isinstance(data.get(k), str)]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - len(TRUNCATED)].rsplit("\n", 1)[0] + TRUNCATED
    return text
