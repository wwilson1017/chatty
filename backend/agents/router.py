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
import io
import json as _json_mod
import shutil
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.auth import get_current_user, decode_access_token
from core.providers import get_ai_provider
from core.providers.credentials import CredentialStore
from core.agents.tool_registry import ToolRegistry
from core.agents.reminders.tools import (
    create_reminder_handler,
    list_reminders_handler,
    cancel_reminder_handler,
)
from core.agents.scheduled_actions.tools import (
    create_scheduled_action_handler,
    list_scheduled_actions_handler,
    update_scheduled_action_handler,
    delete_scheduled_action_handler,
)
from . import db as agent_db
from .engine import (
    build_agent_config,
    get_context_manager,
    get_chat_service,
    ensure_memory_db,
    invalidate_cache,
    DATA_DIR,
)
from .templates import seed_context_files
from core.agents import ai_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Integration tool loader ───────────────────────────────────────────────────

_INTEGRATION_MODULES = {
    "crm_lite": ("integrations.crm_lite.tools", "CRM_LITE_TOOL_DEFS"),
    "odoo": ("integrations.odoo.tools", "ODOO_TOOL_DEFS"),
    "bamboohr": ("integrations.bamboohr.tools", "BAMBOOHR_TOOL_DEFS"),
    "quickbooks": ("integrations.quickbooks.tools", "QB_TOOL_DEFS"),
    "qb_csv": ("integrations.qb_csv.tools", "QB_CSV_TOOL_DEFS"),
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

            # QB CSV needs its DB initialized before tools can run
            if name == "qb_csv":
                from integrations.qb_csv.db import init_db as init_qb_csv, _connection as qb_csv_conn
                if qb_csv_conn is None:
                    init_qb_csv()

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


def _build_agent_handlers(agent_slug: str) -> tuple[dict, dict]:
    """Build reminder and scheduled action handler dicts for an agent."""
    reminder_handlers = {
        "create_reminder": lambda **kw: create_reminder_handler(agent_slug, **kw),
        "list_reminders": lambda **kw: list_reminders_handler(agent_slug, **kw),
        "cancel_reminder": lambda **kw: cancel_reminder_handler(agent_slug, **kw),
    }
    sa_handlers = {
        "create_scheduled_action": lambda **kw: create_scheduled_action_handler(agent_slug, **kw),
        "list_scheduled_actions": lambda **kw: list_scheduled_actions_handler(agent_slug, **kw),
        "update_scheduled_action": lambda **kw: update_scheduled_action_handler(agent_slug, **kw),
        "delete_scheduled_action": lambda **kw: delete_scheduled_action_handler(agent_slug, **kw),
    }
    return reminder_handlers, sa_handlers


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
    telegram_enabled: bool | None = None


class ChatRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    training_mode: bool = False
    training_type: str | None = None
    plan_mode: bool = False
    tool_mode: str = "normal"
    approved_tool: dict | None = None


class ToolExecuteRequest(BaseModel):
    tool: str
    args: dict


class ContextWriteRequest(BaseModel):
    content: str


class UpdateTitleRequest(BaseModel):
    title: str


class AvatarSelectRequest(BaseModel):
    index: int


# ── Agent CRUD ────────────────────────────────────────────────────────────────

@router.get("")
async def list_agents(user=Depends(get_current_user)):
    """List all agents."""
    return {"agents": agent_db.list_agents()}


@router.post("")
async def create_agent(body: CreateAgentRequest, user=Depends(get_current_user)):
    """Create a new agent and seed default context files."""
    if not body.agent_name.strip():
        raise HTTPException(status_code=400, detail="agent_name is required")

    existing_count = len(agent_db.list_agents())
    agent = agent_db.create_agent(body.agent_name.strip(), personality=body.personality)

    # Seed default context files (soul.md, identity.md, user.md, bootstrap, guide)
    context_dir = DATA_DIR / agent["slug"] / "context"
    seed_context_files(context_dir, agent["agent_name"])

    # Bootstrap shared knowledge when 2+ agents exist and bootstrap hasn't completed
    if existing_count >= 1:
        from core.agents.shared_context.bootstrap import run_bootstrap_sync, should_bootstrap
        if should_bootstrap():
            def _bootstrap_thread():
                try:
                    run_bootstrap_sync()
                except Exception:
                    logger.exception("Shared knowledge bootstrap thread failed")

            import threading
            threading.Thread(
                target=_bootstrap_thread,
                daemon=True,
                name="shared-knowledge-bootstrap",
            ).start()
            logger.info("Shared knowledge bootstrap triggered (2nd agent created)")

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
    for field in ("onboarding_complete", "gmail_enabled", "calendar_enabled", "telegram_enabled"):
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


# ── Per-agent: Avatar ────────────────────────────────────────────────────────

# Server-side storage for generated avatar URLs (keyed by agent_id)
_avatar_urls: dict[str, list[str]] = {}
_avatar_cooldowns: dict[str, float] = {}
_AVATAR_COOLDOWN_SECONDS = 300  # 5 minutes between generations


@router.get("/{agent_id}/avatar/availability")
async def avatar_availability(agent_id: str, user=Depends(get_current_user)):
    """Check whether avatar generation is available (requires OpenAI)."""
    _get_agent_or_404(agent_id)
    store = CredentialStore()
    _, profile = store.get_active_profile(provider_override="openai")
    openai_connected = bool(profile and (profile.get("access") or profile.get("key")))
    return {"generate_available": openai_connected, "upload_available": True}


@router.post("/{agent_id}/avatar/generate")
async def avatar_generate(agent_id: str, user=Depends(get_current_user)):
    """Generate 3 avatar options using DALL-E 3 based on agent personality."""
    import time as _time
    from .avatar import generate_avatar_options

    agent = _get_agent_or_404(agent_id)

    # Rate limit: one generation per agent per 5 minutes
    last_gen = _avatar_cooldowns.get(agent_id, 0)
    if _time.time() - last_gen < _AVATAR_COOLDOWN_SECONDS:
        remaining = int(_AVATAR_COOLDOWN_SECONDS - (_time.time() - last_gen))
        raise HTTPException(429, f"Please wait {remaining}s before generating again")

    ctx_manager = get_context_manager(agent["slug"])
    identity = ctx_manager.read_context("profile.md")
    soul = ctx_manager.read_context("preferences.md")
    db_personality = agent.get("personality", "")
    if db_personality:
        soul = f"{soul}\n\n{db_personality}" if soul else db_personality
    agent_name = agent.get("agent_name") or "Assistant"

    store = CredentialStore()
    _, profile = store.get_active_profile(provider_override="openai")
    p = profile or {}
    openai_token = p.get("key") or p.get("access") or ""

    try:
        urls = await generate_avatar_options(identity, soul, agent_name, openai_token, count=3)
        _avatar_urls[agent_id] = urls
        _avatar_cooldowns[agent_id] = _time.time()
        return {"urls": urls, "count": len(urls), "partial": len(urls) < 3}
    except ValueError as e:
        raise HTTPException(503, f"Avatar generation not available: {e}")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        logger.error("Avatar generation unexpected error: %s", e)
        raise HTTPException(502, f"Avatar generation failed: {e}")


@router.post("/{agent_id}/avatar/select")
async def avatar_select(agent_id: str, req: AvatarSelectRequest, user=Depends(get_current_user)):
    """Download and save a chosen avatar by index. URL is resolved server-side."""
    from .avatar import download_and_save_avatar

    urls = _avatar_urls.get(agent_id)
    if not urls:
        # Clear stale cooldown so user can re-generate (e.g. after server restart)
        _avatar_cooldowns.pop(agent_id, None)
        raise HTTPException(400, "No avatar options available — generate first")
    if req.index < 0 or req.index >= len(urls):
        raise HTTPException(400, f"Invalid index {req.index}, must be 0-{len(urls) - 1}")

    agent = _get_agent_or_404(agent_id)
    slug = agent["slug"]
    agent_dir = DATA_DIR / slug
    gcs_prefix = f"agents/{slug}/"

    try:
        await download_and_save_avatar(urls[req.index], agent_dir, gcs_prefix)
        agent_db.update_agent(agent_id, avatar_url=f"/api/agents/{agent_id}/avatar")
        _avatar_urls.pop(agent_id, None)
        return {"ok": True, "avatar_url": f"/api/agents/{agent_id}/avatar"}
    except Exception as e:
        logger.error("Avatar save failed: %s", e)
        raise HTTPException(502, f"Avatar save failed: {e}")


@router.post("/{agent_id}/avatar/upload")
async def avatar_upload(
    agent_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload a custom avatar image."""
    from core.storage import upload_file

    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(400, "Avatar must be PNG, JPEG, or WebP")

    max_size = 2 * 1024 * 1024
    contents = await file.read(max_size + 1)
    if len(contents) > max_size:
        raise HTTPException(400, "Avatar must be under 2MB")

    agent = _get_agent_or_404(agent_id)
    slug = agent["slug"]
    agent_dir = DATA_DIR / slug
    agent_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = agent_dir / "avatar.png"
    avatar_path.write_bytes(contents)

    upload_file(avatar_path, f"agents/{slug}/avatar.png")
    agent_db.update_agent(agent_id, avatar_url=f"/api/agents/{agent_id}/avatar")

    return {"ok": True, "avatar_url": f"/api/agents/{agent_id}/avatar"}


@router.get("/{agent_id}/avatar")
async def get_avatar(agent_id: str, request: Request, token: str | None = None):
    """Serve the agent's avatar image.

    Supports ?token= query param for <img> tags that can't send auth headers.
    """
    from fastapi.responses import FileResponse

    auth_header = request.headers.get("Authorization")
    jwt_token = None
    if auth_header and auth_header.startswith("Bearer "):
        jwt_token = auth_header.removeprefix("Bearer ").strip()
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(401, "Not authenticated")
    try:
        decode_access_token(jwt_token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    agent = _get_agent_or_404(agent_id)
    avatar_path = DATA_DIR / agent["slug"] / "avatar.png"
    if not avatar_path.exists():
        raise HTTPException(404, "No avatar set")
    return FileResponse(str(avatar_path), media_type="image/png")


# ── Per-agent: Chat (shared helper) ──────────────────────────────────────────

def _stream_chat(agent: dict, messages: list, training_mode: bool, conversation_id: str | None,
                  training_type: str | None = None, plan_mode: bool = False,
                  tool_mode: str = "normal", approved_tool: dict | None = None):
    """Build provider, registry, and return a StreamingResponse for agent chat."""
    config = build_agent_config(agent)
    ctx_manager = get_context_manager(agent["slug"])
    chat_service = get_chat_service(agent["slug"])

    # Ensure MemoryDB is initialized (lazy, cached after first call)
    try:
        ensure_memory_db(agent["slug"])
    except Exception:
        pass  # Non-critical — search will degrade gracefully

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

    reminder_handlers, sa_handlers = _build_agent_handlers(agent["slug"])
    registry = ToolRegistry(
        context_dir=config.context_dir,
        gcs_prefix=config.gcs_prefix,
        google_access_token=google_token,
        integration_executors=integration_executors,
        agent_slug=agent["slug"],
        agent_name=config.agent_name,
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

    _, anthropic_profile = store.get_active_profile(provider_override="anthropic")
    anthropic_api_key = (anthropic_profile or {}).get("key", "")

    async def event_generator():
        async for event in ai_service.chat(
            config=config,
            provider=provider,
            registry=registry,
            ctx_manager=ctx_manager,
            messages=messages,
            training_mode=training_mode,
            training_type=training_type,
            plan_mode=plan_mode,
            conversation_id=conversation_id,
            chat_service=chat_service,
            anthropic_api_key=anthropic_api_key,
            integration_tool_defs=integration_tool_defs or None,
            tool_mode=tool_mode,
            approved_tool=approved_tool,
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


@router.post("/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest, user=Depends(get_current_user)):
    """Stream a chat response for a specific agent."""
    agent = _get_agent_or_404(agent_id)
    return _stream_chat(agent, req.messages, req.training_mode, req.conversation_id,
                        training_type=req.training_type, plan_mode=req.plan_mode,
                        tool_mode=req.tool_mode, approved_tool=req.approved_tool)


# ── Per-agent: Plan mode approve/iterate ──────────────────────────────────────


class PlanApproveRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    plan_text: str = ""


class PlanIterateRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    feedback: str = ""


@router.post("/{agent_id}/plan/approve")
async def plan_approve(agent_id: str, req: PlanApproveRequest, user=Depends(get_current_user)):
    """Approve a plan and execute it in power mode."""
    agent = _get_agent_or_404(agent_id)
    # Append the plan + approval as a user message
    messages = list(req.messages)
    messages.append({
        "role": "user",
        "content": f"[Plan Approved] Execute this plan:\n\n{req.plan_text}",
    })
    return _stream_chat(agent, messages, False, req.conversation_id,
                        tool_mode="power")


@router.post("/{agent_id}/plan/iterate")
async def plan_iterate(agent_id: str, req: PlanIterateRequest, user=Depends(get_current_user)):
    """Send feedback on a plan and stay in plan mode."""
    agent = _get_agent_or_404(agent_id)
    messages = list(req.messages)
    messages.append({
        "role": "user",
        "content": req.feedback or "Please revise the plan.",
    })
    return _stream_chat(agent, messages, False, req.conversation_id,
                        plan_mode=True)


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


# ── Per-agent: File upload chat ──────────────────────────────────────────────

_ALLOWED_EXTENSIONS = {"csv", "xlsx", "md", "txt"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_MAX_FILES = 5


@router.post("/{agent_id}/chat/upload")
async def agent_chat_upload(
    agent_id: str,
    payload: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    user=Depends(get_current_user),
):
    """Chat with file attachments. Reads file contents and prepends to the user message."""
    agent = _get_agent_or_404(agent_id)

    try:
        body = _json_mod.loads(payload)
    except _json_mod.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Process uploaded files
    file_texts = []
    for f in files[:_MAX_FILES]:
        ext = (f.filename or "").rsplit(".", 1)[-1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"File type '.{ext}' not allowed")

        content_bytes = await f.read()
        if len(content_bytes) > _MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"File '{f.filename}' exceeds 10 MB limit")
        if not content_bytes:
            continue

        # Convert XLSX to CSV
        if ext == "xlsx":
            try:
                import csv
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(content_bytes), read_only=True)
                csv_out = io.StringIO()
                writer = csv.writer(csv_out)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    writer.writerow([str(cell) if cell is not None else "" for cell in row])
                text = csv_out.getvalue()
                wb.close()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to parse '{f.filename}': {e}")
        else:
            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = content_bytes.decode("latin-1")
                except UnicodeDecodeError:
                    raise HTTPException(status_code=400, detail=f"Cannot decode '{f.filename}'")

        # Auto-detect QBO CSV exports when the integration is enabled
        if ext == "csv":
            try:
                from integrations.registry import is_enabled as _is_enabled
                if _is_enabled("qb_csv"):
                    import csv as _csv_mod
                    _reader = _csv_mod.reader(io.StringIO(text))
                    _headers = next(_reader, None)
                    if _headers:
                        from integrations.qb_csv.parser import detect_entity_type
                        _entity = detect_entity_type(
                            [h.strip().lower() for h in _headers],
                            filename=f.filename or "",
                        )
                        if _entity:
                            file_texts.append(
                                f"[Attached file: {f.filename}] [QuickBooks CSV detected: {_entity}]\n"
                                f"{text}\n[End of file]"
                            )
                            continue
            except Exception:
                logger.debug("QBO CSV detection failed for %s", f.filename, exc_info=True)

        file_texts.append(f"[Attached file: {f.filename}]\n{text}\n[End of file]")

    # Prepend file contents to the last user message
    if file_texts:
        last_msg = messages[-1]
        prefix = "\n\n".join(file_texts)
        last_msg["content"] = prefix + "\n\n" + (last_msg.get("content") or "")

    return _stream_chat(
        agent, messages, body.get("training_mode", False), body.get("conversation_id"),
        training_type=body.get("training_type"), plan_mode=body.get("plan_mode", False),
        tool_mode=body.get("tool_mode", "normal"), approved_tool=body.get("approved_tool"),
    )


# ── Per-agent: Tool execute (confirmation approval) ─────────────────────────

@router.post("/{agent_id}/tool/execute")
async def tool_execute(agent_id: str, req: ToolExecuteRequest, user=Depends(get_current_user)):
    """Execute a write tool after user approval (confirmation flow)."""
    agent = _get_agent_or_404(agent_id)
    config = build_agent_config(agent)

    store = CredentialStore()
    google_token = ""
    if config.gmail_enabled or config.calendar_enabled:
        google_token = store.get_google_token() or ""

    integration_tool_defs, integration_executors = _load_integration_tools()
    reminder_handlers, sa_handlers = _build_agent_handlers(agent["slug"])

    registry = ToolRegistry(
        context_dir=config.context_dir,
        google_access_token=google_token,
        integration_executors=integration_executors,
        agent_slug=agent["slug"],
        reminder_handlers=reminder_handlers,
        scheduled_action_handlers=sa_handlers,
    )

    from core.agents.tool_definitions import get_tool_definitions, build_writes_map
    tool_defs = get_tool_definitions(
        gmail_enabled=config.gmail_enabled,
        calendar_enabled=config.calendar_enabled,
        integration_tools=integration_tool_defs,
    )
    writes_map = build_writes_map(tool_defs)
    if not writes_map.get(req.tool, False):
        raise HTTPException(status_code=400, detail="Tool is not a write operation")

    kind_map = {t["name"]: t.get("kind", "context") for t in tool_defs}
    kind = kind_map.get(req.tool, "context")
    result = await registry.execute_tool(req.tool, req.args, kind)

    # Sync context files to GCS after write
    ctx_manager = get_context_manager(agent["slug"])
    from core.agents.ai_service import _sync_context_after_tool
    _sync_context_after_tool(req.tool, result, ctx_manager)

    return result


# ── Per-agent: Reports ───────────────────────────────────────────────────────

@router.get("/{agent_id}/reports")
async def list_agent_reports(agent_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    from core.agents.tools.report_tools import list_reports
    reports_dir = str(DATA_DIR / agent["slug"] / "reports")
    return {"reports": list_reports(reports_dir)}


@router.get("/{agent_id}/reports/{report_id}")
async def get_agent_report(agent_id: str, report_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    from core.agents.tools.report_tools import get_report
    reports_dir = str(DATA_DIR / agent["slug"] / "reports")
    report = get_report(reports_dir, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/{agent_id}/reports/{report_id}")
async def delete_agent_report(agent_id: str, report_id: str, user=Depends(get_current_user)):
    agent = _get_agent_or_404(agent_id)
    from core.agents.tools.report_tools import delete_report
    reports_dir = str(DATA_DIR / agent["slug"] / "reports")
    if not delete_report(reports_dir, report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True}
