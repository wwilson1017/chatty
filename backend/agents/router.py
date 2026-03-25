"""
Chatty — Multi-agent management + per-agent chat/context/conversation routes.

Agent CRUD:
  GET    /api/agents                               — list all agents
  POST   /api/agents                               — create a new agent
  GET    /api/agents/{agent_id}                    — get agent details
  PUT    /api/agents/{agent_id}                    — update agent settings
  DELETE /api/agents/{agent_id}                    — delete agent + data

Per-agent (chat, context, conversations):
  POST   /api/agents/{agent_id}/chat               — SSE chat stream
  GET    /api/agents/{agent_id}/onboarding/progress
  GET    /api/agents/{agent_id}/context
  GET    /api/agents/{agent_id}/context/{filename}
  PUT    /api/agents/{agent_id}/context/{filename}
  DELETE /api/agents/{agent_id}/context/{filename}
  GET    /api/agents/{agent_id}/conversations
  POST   /api/agents/{agent_id}/conversations
  GET    /api/agents/{agent_id}/conversations/search
  GET    /api/agents/{agent_id}/conversations/{conv_id}
  DELETE /api/agents/{agent_id}/conversations/{conv_id}
  PATCH  /api/agents/{agent_id}/conversations/{conv_id}/title
"""

import importlib
import shutil
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.auth import get_current_user
from core.providers import get_ai_provider
from core.providers.credentials import CredentialStore
from core.agents.tool_registry import ToolRegistry
from . import db as agent_db
from .engine import (
    build_agent_config,
    get_context_manager,
    get_chat_service,
    invalidate_cache,
    DATA_DIR,
)
from core.agents import ai_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Integration tool loader ───────────────────────────────────────────────────

_INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
}


def _load_integration_tools() -> tuple[list[dict], dict]:
    """Load tool definitions and executors from all enabled integrations."""
    from integrations.registry import is_enabled

    tool_defs: list[dict] = []
    executors: dict = {}

    for name, (module_path, defs_attr) in _INTEGRATION_MODULES.items():
        if not is_enabled(name):
            continue
        try:
            # CRM Lite needs its DB initialized before tools can run
            if name == "crm_lite":
                from integrations.crm_lite.db import init_db, _connection
                if _connection is None:
                    init_db()

            mod = importlib.import_module(module_path)
            defs = getattr(mod, defs_attr, [])
            execs = getattr(mod, "TOOL_EXECUTORS", {})
            tool_defs.extend(defs)
            executors.update(execs)
        except Exception as e:
            logger.warning("Failed to load integration %s: %s", name, e)

    return tool_defs, executors


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_agent_or_404(agent_id: str) -> dict:
    agent = agent_db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _safe_filename(filename: str) -> bool:
    if not filename or not filename.endswith(".md"):
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    return True


# ── Request models ────────────────────────────────────────────────────────────

class CreateAgentRequest(BaseModel):
    agent_name: str
    personality: str = ""


class UpdateAgentRequest(BaseModel):
    agent_name: str | None = None
    personality: str | None = None
    avatar_url: str | None = None
    onboarding_complete: bool | None = None
    provider_override: str | None = None
    model_override: str | None = None
    gmail_enabled: bool | None = None
    calendar_enabled: bool | None = None


class ChatRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    training_mode: bool = False


class ContextWriteRequest(BaseModel):
    content: str


class UpdateTitleRequest(BaseModel):
    title: str


# ── Agent CRUD ────────────────────────────────────────────────────────────────

@router.get("")
async def list_agents(user=Depends(get_current_user)):
    """List all agents."""
    return {"agents": agent_db.list_agents()}


@router.post("")
async def create_agent(body: CreateAgentRequest, user=Depends(get_current_user)):
    """Create a new agent."""
    if not body.agent_name.strip():
        raise HTTPException(status_code=400, detail="agent_name is required")
    agent = agent_db.create_agent(body.agent_name.strip(), personality=body.personality)
    return agent


@router.get("/{agent_id}")
async def get_agent(agent_id: str, user=Depends(get_current_user)):
    """Get a single agent by ID."""
    return _get_agent_or_404(agent_id)


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: UpdateAgentRequest, user=Depends(get_current_user)):
    """Update agent settings."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    for field in ("onboarding_complete", "gmail_enabled", "calendar_enabled"):
        if field in updates:
            updates[field] = int(updates[field])
    agent = agent_db.update_agent(agent_id, **updates)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    invalidate_cache(agent["slug"])
    return agent


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, user=Depends(get_current_user)):
    """Delete an agent and all its data."""
    agent = _get_agent_or_404(agent_id)
    slug = agent["slug"]
    agent_db.delete_agent(agent_id)
    invalidate_cache(slug)
    agent_dir = DATA_DIR / slug
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
        logger.info("Deleted agent data directory: %s", agent_dir)
    return {"deleted": True, "agent_id": agent_id}


# ── Per-agent: Chat ───────────────────────────────────────────────────────────

@router.post("/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest, user=Depends(get_current_user)):
    """Stream a chat response for a specific agent."""
    agent = _get_agent_or_404(agent_id)
    config = build_agent_config(agent)
    ctx_manager = get_context_manager(agent["slug"])
    chat_service = get_chat_service(agent["slug"])

    store = CredentialStore()
    provider = get_ai_provider(
        agent_provider=config.provider_override or None,
        agent_model=config.model_override or None,
    )
    if not provider:
        raise HTTPException(status_code=400, detail="No AI provider configured")

    google_token = ""
    if config.gmail_enabled or config.calendar_enabled:
        google_token = store.get_google_token() or ""

    integration_tool_defs, integration_executors = _load_integration_tools()

    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_access_token=google_token,
        integration_executors=integration_executors,
    )

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
            integration_tool_defs=integration_tool_defs or None,
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


# ── Per-agent: Onboarding progress ───────────────────────────────────────────

@router.get("/{agent_id}/onboarding/progress")
async def onboarding_progress(agent_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    ctx_manager = get_context_manager(agent["slug"])
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


# ── Per-agent: Context CRUD ───────────────────────────────────────────────────

@router.get("/{agent_id}/context")
async def list_context(agent_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    ctx_manager = get_context_manager(agent["slug"])
    return {"files": ctx_manager.list_context_files()}


@router.get("/{agent_id}/context/{filename}")
async def get_context(agent_id: str, filename: str, user=Depends(get_current_user)):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    agent = _get_agent_or_404(agent_id)
    ctx_manager = get_context_manager(agent["slug"])
    content = ctx_manager.read_context(filename)
    if not content and not (ctx_manager.data_dir / filename).exists():
        raise HTTPException(status_code=404, detail="File not found")
    return {"filename": filename, "content": content}


@router.put("/{agent_id}/context/{filename}")
async def put_context(
    agent_id: str, filename: str, req: ContextWriteRequest, user=Depends(get_current_user)
):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    agent = _get_agent_or_404(agent_id)
    ctx_manager = get_context_manager(agent["slug"])
    ctx_manager.write_context(filename, req.content)
    return {"filename": filename, "ok": True}


@router.delete("/{agent_id}/context/{filename}")
async def delete_context(agent_id: str, filename: str, user=Depends(get_current_user)):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    agent = _get_agent_or_404(agent_id)
    ctx_manager = get_context_manager(agent["slug"])
    if not ctx_manager.delete_context(filename):
        raise HTTPException(status_code=404, detail="File not found")
    return {"filename": filename, "deleted": True}


# ── Per-agent: Conversations ──────────────────────────────────────────────────

@router.get("/{agent_id}/conversations/search")
async def search_conversations(agent_id: str, q: str = "", user=Depends(get_current_user)):
    _get_agent_or_404(agent_id)
    if not q.strip():
        return {"results": []}
    chat_service = get_chat_service(agent_db.get_agent(agent_id)["slug"])
    return {"results": chat_service.search_conversations(q.strip())}


@router.get("/{agent_id}/conversations")
async def list_conversations(
    agent_id: str, limit: int = 50, offset: int = 0, user=Depends(get_current_user)
):
    agent = _get_agent_or_404(agent_id)
    chat_service = get_chat_service(agent["slug"])
    return {"conversations": chat_service.list_conversations(limit, offset)}


@router.post("/{agent_id}/conversations")
async def create_conversation(agent_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    chat_service = get_chat_service(agent["slug"])
    return chat_service.create_conversation()


@router.get("/{agent_id}/conversations/{conv_id}")
async def get_conversation(agent_id: str, conv_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    chat_service = get_chat_service(agent["slug"])
    result = chat_service.get_conversation(conv_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@router.delete("/{agent_id}/conversations/{conv_id}")
async def delete_conversation(agent_id: str, conv_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    chat_service = get_chat_service(agent["slug"])
    if not chat_service.delete_conversation(conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}


@router.patch("/{agent_id}/conversations/{conv_id}/title")
async def update_title(
    agent_id: str, conv_id: str, req: UpdateTitleRequest, user=Depends(get_current_user)
):
    agent = _get_agent_or_404(agent_id)
    chat_service = get_chat_service(agent["slug"])
    new_title = chat_service.rename_conversation(conv_id, req.title)
    if new_title is None:
        raise HTTPException(status_code=404, detail="Conversation not found or title empty")
    return {"title": new_title}
