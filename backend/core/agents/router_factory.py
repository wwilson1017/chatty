"""
Chatty — Shared agent router factory.

Creates a FastAPI router with chat + context + conversation endpoints.
Used by the multi-agent system (agents/router.py) to mount per-agent routes.

No voice endpoints. No Odoo/tool-confirmation flow.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.auth import get_current_user
from core.providers import get_ai_provider
from core.providers.credentials import CredentialStore
from .config import AgentConfig
from .context_manager import ContextManager
from .tool_registry import ToolRegistry
from .chat_history.service import ChatHistoryService
from . import ai_service


# ── Request models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    training_mode: bool = False


class ContextWriteRequest(BaseModel):
    content: str


class UpdateTitleRequest(BaseModel):
    title: str


# ── Filename safety ───────────────────────────────────────────────────────────

def _safe_filename(filename: str) -> bool:
    if not filename or not filename.endswith(".md"):
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    return True


# ── Factory ───────────────────────────────────────────────────────────────────

def create_agent_router(
    config: AgentConfig,
    ctx_manager: ContextManager,
    chat_service: ChatHistoryService | None = None,
    integration_tool_defs: list[dict] | None = None,
) -> APIRouter:
    """Create a FastAPI router for a single agent.

    The router is intended to be mounted at /api/agents/{agent_id}/ by
    the multi-agent router. It does NOT include the /api/agents prefix itself.

    Args:
        config: Agent configuration
        ctx_manager: Per-agent context file manager
        chat_service: Optional chat history service (enables /conversations endpoints)
        integration_tool_defs: Extra tool definitions from enabled integrations
    """
    router = APIRouter()

    # ── Chat (SSE) ────────────────────────────────────────────────────

    @router.post("/chat")
    async def chat(req: ChatRequest, user=Depends(get_current_user)):
        store = CredentialStore()
        provider = get_ai_provider(
            agent_provider=config.provider_override or None,
            agent_model=config.model_override or None,
        )
        if not provider:
            raise HTTPException(status_code=400, detail="No AI provider configured")

        # Get Google access token if Gmail/Calendar enabled
        google_token = ""
        if config.gmail_enabled or config.calendar_enabled:
            google_token = store.get_google_token() or ""

        registry = ToolRegistry(
            context_dir=config.context_dir,
            google_access_token=google_token,
        )

        # Anthropic API key for smart title generation (haiku)
        _, anthropic_profile = store.get_active_profile(provider_override="anthropic")
        anthropic_api_key = (anthropic_profile or {}).get("api_key", "")

        async def event_generator():
            async for event in ai_service.chat(
                config=config,
                provider=provider,
                registry=registry,
                ctx_manager=ctx_manager,
                messages=req.messages,
                training_mode=req.training_mode,
                conversation_id=req.conversation_id,
                chat_service=chat_service,
                anthropic_api_key=anthropic_api_key,
                integration_tool_defs=integration_tool_defs,
            ):
                yield event

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Onboarding progress ───────────────────────────────────────────

    @router.get("/onboarding/progress")
    def onboarding_progress(user=Depends(get_current_user)):
        content = ctx_manager.read_context("_onboarding-progress.md")
        if not content:
            return {"topics": [], "completed": 0, "total": 0}

        topics = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [x]"):
                topics.append({"name": stripped[6:].strip(), "status": "done"})
            elif stripped.startswith("- [~]"):
                topics.append({"name": stripped[6:].strip(), "status": "skipped"})
            elif stripped.startswith("- [ ]"):
                topics.append({"name": stripped[6:].strip(), "status": "pending"})

        done = sum(1 for t in topics if t["status"] == "done")
        return {"topics": topics, "completed": done, "total": len(topics)}

    # ── Context CRUD ──────────────────────────────────────────────────

    @router.get("/context")
    def list_context(user=Depends(get_current_user)):
        return {"files": ctx_manager.list_context_files()}

    @router.get("/context/{filename}")
    def get_context(filename: str, user=Depends(get_current_user)):
        if not _safe_filename(filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        content = ctx_manager.read_context(filename)
        if not content and not (ctx_manager.data_dir / filename).exists():
            raise HTTPException(status_code=404, detail="File not found")
        return {"filename": filename, "content": content}

    @router.put("/context/{filename}")
    def put_context(filename: str, req: ContextWriteRequest, user=Depends(get_current_user)):
        if not _safe_filename(filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        ctx_manager.write_context(filename, req.content)
        return {"filename": filename, "ok": True}

    @router.delete("/context/{filename}")
    def delete_context(filename: str, user=Depends(get_current_user)):
        if not _safe_filename(filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not ctx_manager.delete_context(filename):
            raise HTTPException(status_code=404, detail="File not found")
        return {"filename": filename, "deleted": True}

    # ── Conversations (when chat_service provided) ────────────────────

    if chat_service is not None:

        @router.get("/conversations/search")
        def search_conversations(q: str = "", user=Depends(get_current_user)):
            if not q.strip():
                return {"results": []}
            return {"results": chat_service.search_conversations(q.strip())}

        @router.get("/conversations")
        def list_conversations(limit: int = 50, offset: int = 0, user=Depends(get_current_user)):
            return {"conversations": chat_service.list_conversations(limit, offset)}

        @router.post("/conversations")
        def create_conversation(user=Depends(get_current_user)):
            return chat_service.create_conversation()

        @router.get("/conversations/{conv_id}")
        def get_conversation(conv_id: str, user=Depends(get_current_user)):
            result = chat_service.get_conversation(conv_id)
            if not result:
                raise HTTPException(status_code=404, detail="Conversation not found")
            return result

        @router.delete("/conversations/{conv_id}")
        def delete_conversation(conv_id: str, user=Depends(get_current_user)):
            if not chat_service.delete_conversation(conv_id):
                raise HTTPException(status_code=404, detail="Conversation not found")
            return {"deleted": True}

        @router.patch("/conversations/{conv_id}/title")
        def update_conversation_title(
            conv_id: str, req: UpdateTitleRequest, user=Depends(get_current_user)
        ):
            new_title = chat_service.rename_conversation(conv_id, req.title)
            if new_title is None:
                raise HTTPException(status_code=404, detail="Conversation not found or title empty")
            return {"title": new_title}

    return router
