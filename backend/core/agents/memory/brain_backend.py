"""
Chatty — Second-brain memory backend (LONG-TERM memory only).

An agent whose ``memory_backend`` is ``brain`` keeps its memory tools (same
names, same schemas as ``MEMORY_TOOLS``) but the long-term ones go to a
``brain`` server (https://github.com/wwilson1017/brain, ``brain/server/router.py``)
over HTTP.  Short-term memory — daily notes, meetings, topic files, persona —
stays in the per-agent ``context/`` exactly as with the builtin backend.
``ToolRegistry._execute_memory`` dispatches ``BRAIN_TOOLS`` here when
``agents.engine.get_brain_backend`` returns an instance; everything else runs locally.

Route map (brain → Chatty result shape):
  read_memory   → GET /memory          search_memory   → GET /search (+ local daily/topic hits, merged by the registry)
  add_fact      → POST /facts          query_facts     → GET /facts
  invalidate_fact → POST /facts/{id}/invalidate
  update_memory → refused: the brain's MEMORY.md is owner-maintained (AGENTS.md)
  propose_change → POST /propose     list_proposals → GET /review?harness=chatty
    (structural changes are PROPOSED, the owner accepts them via the brain CLI)
  GET /context  → the prompt's MEMORY section (context_text)
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# The long-term tools a brain-backed agent routes here. Daily notes, meetings,
# commitments and consolidate_memory stay on the local builtin implementation.
BRAIN_TOOLS = frozenset({
    "read_memory", "update_memory", "search_memory", "add_fact", "query_facts", "invalidate_fact",
    "propose_change", "list_proposals",
})
PROPOSAL_KINDS = ("merge-people", "move-note", "memory-section", "rule", "agents-md")
BRAIN_WRITE_TOOLS = frozenset({"add_fact", "update_memory", "invalidate_fact"})
# Appended to the brain write tools' descriptions (from Hermes' memory tool).
BRAIN_SKIP_TEXT = (
    " Skip: task progress, completed-work logs, temporary status, assistant actions, in-progress state, "
    "and negative claims about tools or access (they go stale and harden into refusals). When in doubt, store less."
)
# GET /context — the brain's session-start block, injected into the system
# prompt in place of the local MEMORY.md + topic notes + daily manifest.
CONTEXT_MAX_CHARS = 8_000
CONTEXT_TTL_SECONDS = 60.0     # heartbeats fire every 60s; don't hammer the bridge
CONTEXT_TIMEOUT_SECONDS = 5.0  # prompt assembly is on the request path
CONTEXT_UNAVAILABLE = "[brain unavailable — tool reads still work]"
UPDATE_MEMORY_REFUSED = (
    "update_memory is not available on the brain backend: MEMORY.md there is maintained by its owner "
    "and the nightly job. Record the durable fact with add_fact, or the event with append_daily_note."
)
NOT_CONFIGURED = "brain integration is not configured (Settings → Integrations → Second Brain)"
UNREACHABLE = "brain unreachable"


class BrainBackend:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        agent_slug: str = "",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.agent_slug = agent_slug
        headers = {"X-Api-Key": api_key} if api_key else {}
        # transport lets tests plug in httpx.MockTransport — no sockets
        self._client = httpx.Client(base_url=self.base_url or "http://unconfigured", timeout=timeout,
                                    headers=headers, transport=transport)
        self._context_cache: tuple[float, str] | None = None  # (expires_at, text)

    def close(self) -> None:
        self._client.close()

    # ── system-prompt memory block ───────────────────────────────────────

    def context_text(self, max_chars: int = CONTEXT_MAX_CHARS) -> str:
        """The brain's ``GET /context`` text for the system prompt, cached per instance
        for CONTEXT_TTL_SECONDS. Failures are cached too, as CONTEXT_UNAVAILABLE, so a
        dead bridge costs one 5 s timeout per minute, not one per turn."""
        now = time.monotonic()
        if self._context_cache and self._context_cache[0] > now:
            return self._context_cache[1]
        data = self._request("GET", "/context", params={"max_chars": max_chars},
                             timeout=CONTEXT_TIMEOUT_SECONDS)
        if "error" in data:
            logger.warning("brain /context unavailable: %s", data["error"])
            text = CONTEXT_UNAVAILABLE
        else:
            text = (data.get("text") or "").strip() or "(the brain has no memory content yet)"
        self._context_cache = (now + CONTEXT_TTL_SECONDS, text)
        return text

    # ── transport ────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kw) -> dict:
        if not self.base_url:
            return {"error": NOT_CONFIGURED}
        try:
            resp = self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            logger.warning("brain %s %s failed: %s", method, path, e)
            return {"error": UNREACHABLE}
        try:
            data = resp.json()
        except ValueError:
            return {"error": f"brain returned non-JSON ({resp.status_code})"}
        if resp.status_code >= 400:
            detail = data.get("error") or data.get("detail") if isinstance(data, dict) else data
            return {"error": f"brain error ({resp.status_code}): {detail}"}
        return data

    def _get(self, path: str, **params) -> dict:
        return self._request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def _post(self, path: str, **body) -> dict:
        return self._request("POST", path, json={k: v for k, v in body.items() if v is not None})

    # ── dispatch ─────────────────────────────────────────────────────────

    def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name not in BRAIN_TOOLS:
            return {"error": f"{tool_name} is a local memory tool, not a brain tool"}
        if tool_name == "update_memory":
            return {"error": UPDATE_MEMORY_REFUSED}
        handler = getattr(self, f"_{tool_name}", None)
        if handler is None:
            return {"error": f"Unknown memory tool: {tool_name}"}
        return handler(args)

    def _read_memory(self, args: dict) -> dict:
        data = self._get("/memory")
        return data if "error" in data else {"content": _sanitize(data.get("text", ""))}

    def _search_memory(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        # simplification: source_type / memory_type / date filters are not forwarded —
        # the brain's /search takes only q + limit; add them there first if needed.
        data = self._get("/search", q=query, limit=_clamp(args.get("limit", 20), 20, 100))
        if "error" in data:
            return data
        results = data.get("results", [])
        for r in results:
            for key in ("title", "snippet"):
                if r.get(key):
                    r[key] = _sanitize(r[key])
        out = {"query": query, "results": results, "total": len(results)}
        if data.get("index") == "incomplete":
            out["warning"] = "brain index incomplete — some notes may be missing from these results"
        return out

    def _add_fact(self, args: dict) -> dict:
        for key in ("subject", "predicate", "object"):
            if not (args.get(key) or "").strip():
                return {"error": f"{key} is required"}
        return self._post(
            "/facts",
            subject=args["subject"].strip(), predicate=args["predicate"].strip(), object=args["object"].strip(),
            memory_type=args.get("memory_type"), confidence=args.get("confidence", 1.0),
            created_by="chatty", origin_class="agent", harness="chatty", agent=self.agent_slug or None,
        )

    def _query_facts(self, args: dict) -> dict:
        data = self._get(
            "/facts", subject=args.get("subject"), predicate=args.get("predicate"), as_of=args.get("as_of"),
            include_expired=bool(args.get("include_expired", False)), limit=_clamp(args.get("limit", 50), 50, 500),
            track_retrieval=True,
        )
        if isinstance(data, dict) and "error" in data:
            return data
        facts = data if isinstance(data, list) else []
        memory_type = args.get("memory_type")
        if memory_type:  # /facts has no memory_type filter; apply it here
            facts = [f for f in facts if f.get("memory_type") == memory_type]
        for fact in facts:
            for key in ("subject", "predicate", "object"):
                if fact.get(key):
                    fact[key] = _sanitize(fact[key])
        return {"facts": facts, "total": len(facts)}

    def _invalidate_fact(self, args: dict) -> dict:
        try:
            fact_id = int(args.get("fact_id"))
        except (TypeError, ValueError):
            return {"error": "fact_id must be an integer"}
        return self._post(f"/facts/{fact_id}/invalidate", valid_to=args.get("valid_to"))

    # ── proposals (brain/review/propose.py) ──────────────────────────────

    def _propose_change(self, args: dict) -> dict:
        kind = (args.get("kind") or "").strip()
        if kind not in PROPOSAL_KINDS:
            return {"error": f"kind must be one of: {', '.join(PROPOSAL_KINDS)}"}
        payload = args.get("payload")
        if not isinstance(payload, dict) or not payload:
            return {"error": "payload must be a non-empty object"}
        reason = (args.get("reason") or "").strip()
        if not reason:
            return {"error": "reason is required"}
        return self._post(
            "/propose", kind=kind, payload=payload, reason=reason, evidence=(args.get("evidence") or None),
            origin_class="agent", harness="chatty", agent=self.agent_slug or None,
        )

    def _list_proposals(self, args: dict) -> dict:
        status = args.get("status") or "pending"
        if status not in ("pending", "rejected", "all"):
            return {"error": "status must be pending, rejected or all"}
        data = self._get("/review", kind=args.get("kind"), status=status, harness="chatty")
        if isinstance(data, dict) and "error" in data:
            return data
        rows = data if isinstance(data, list) else data.get("proposals", []) if isinstance(data, dict) else []
        for row in rows:
            for key in ("line", "reason", "decision"):
                if isinstance(row.get(key), str):
                    row[key] = _sanitize(row[key])
        return {"proposals": rows, "total": len(rows)}


def _clamp(value, on_error: int, maximum: int) -> int:
    """``value`` as an int in 1..maximum; *on_error* when it is not a number."""
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return on_error


def _sanitize(text: str) -> str:
    from core.agents.security.scanner import sanitize_memory_content
    return sanitize_memory_content(text)
