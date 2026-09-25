"""
Chatty — Second-brain memory backend.

An agent whose ``memory_backend`` is ``brain`` keeps its memory tools (same
names, same schemas as ``MEMORY_TOOLS``) but every call goes to a ``brain``
server (https://github.com/wwilson1017/brain, ``brain/server/router.py``) over
HTTP instead of the per-agent ``memory.db`` + ``context/``.  ``ToolRegistry
._execute_memory`` dispatches here when ``agents.engine.get_brain_backend``
returns an instance.

Route map (brain → Chatty result shape):
  append_daily_note → POST /daily          read_daily_note → GET /daily/{date}
  list_daily_notes  → GET /daily           read_memory     → GET /memory
  search_memory     → GET /search          add_fact        → POST /facts
  query_facts       → GET /facts           invalidate_fact → POST /facts/{id}/invalidate
  update_memory     → refused: the brain's MEMORY.md is owner-maintained (AGENTS.md)
  list_meetings / read_meeting / consolidate_memory / complete_commitment → not supported
"""

import logging

import httpx

logger = logging.getLogger(__name__)

UNSUPPORTED = {"list_meetings", "read_meeting", "consolidate_memory", "complete_commitment"}
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

    def close(self) -> None:
        self._client.close()

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
        if tool_name in UNSUPPORTED:
            return {"error": f"{tool_name} is not supported by the brain backend"}
        if tool_name == "update_memory":
            return {"error": UPDATE_MEMORY_REFUSED}
        handler = getattr(self, f"_{tool_name}", None)
        if handler is None:
            return {"error": f"Unknown memory tool: {tool_name}"}
        return handler(args)

    def _append_daily_note(self, args: dict) -> dict:
        content = (args.get("content") or "").strip()
        if not content:
            return {"error": "content is required"}
        # simplification: the brain stamps entries "now"; a `date` argument is
        # ignored and the returned `date` says which day was written.
        return self._post("/daily", content=content, type=args.get("memory_type"))

    def _read_daily_note(self, args: dict) -> dict:
        date = args.get("date") or ""
        if not date:
            return {"error": "date is required"}
        data = self._get(f"/daily/{date}")
        if "error" not in data and data.get("content"):
            data["content"] = _sanitize(data["content"])
        return data

    def _list_daily_notes(self, args: dict) -> dict:
        data = self._get("/daily", limit=_clamp(args.get("limit", 30), 30, 365))
        return data if "error" in data else {"notes": data.get("notes", [])}

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


def _clamp(value, on_error: int, maximum: int) -> int:
    """``value`` as an int in 1..maximum; *on_error* when it is not a number."""
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return on_error


def _sanitize(text: str) -> str:
    from core.agents.security.scanner import sanitize_memory_content
    return sanitize_memory_content(text)
