"""Import tool execution handlers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path

from core.agents.context_manager import ContextManager

from . import sessions
from .adapters.folder import FolderSourceAdapter
from .adapters.paste import PasteSourceAdapter
from .scrubber import scrub

logger = logging.getLogger(__name__)

_BLOCKED_CHATTY_FILES = {
    "_bootstrap.md", "_guide.md", "_integration-setup.md",
    "_pending-setup.md", "_onboarding-progress.md", "_import-bootstrap.md",
    "_load-order.json",
}

_ALLOWED_WRITE_TARGETS = {
    "soul.md", "identity.md", "user.md", "profile.md",
    "goals.md", "preferences.md", "environment.md", "MEMORY.md",
    "background.md",
}

_DAILY_RE = re.compile(r"^daily/\d{4}-\d{2}-\d{2}\.md$")


def _safe_import_filename(filename: str) -> bool:
    if not filename:
        return False
    if ".." in filename or filename.startswith("/") or "\\" in filename:
        return False
    if filename in _BLOCKED_CHATTY_FILES:
        return False
    if filename in _ALLOWED_WRITE_TARGETS:
        return True
    if _DAILY_RE.match(filename):
        return True
    if filename.startswith("imported-") and filename.endswith(".md") and "/" not in filename:
        return True
    return False


def _safe_scan_path(path: str) -> Path:
    """Resolve and validate a path for scan_directory. Must be under user's home."""
    home = Path.home()
    if home == Path("/"):
        raise ValueError("Cannot determine safe home directory — running as root is not supported for directory scanning")
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(home):
        raise ValueError(f"Path must be under your home directory ({home})")
    for blocked in ("/etc", "/var", "/usr", "/System", "/Library"):
        if str(resolved).startswith(blocked):
            raise ValueError(f"Cannot scan system directory: {blocked}")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Directory not found: {resolved}")
    return resolved


def execute_import_tool(
    tool_name: str,
    args: dict,
    session: sessions.ImportSession | None,
    ctx_manager: ContextManager,
) -> dict:
    try:
        if tool_name == "scan_directory":
            return _scan_directory(args, session)
        elif tool_name == "ingest_pasted_text":
            return _ingest_pasted_text(args, session)
        elif tool_name == "list_import_files":
            return _list_import_files(session)
        elif tool_name == "read_import_file":
            return _read_import_file(args, session)
        elif tool_name == "skip_import_file":
            return _skip_import_file(args, session)
        elif tool_name == "read_existing_context":
            return _read_existing_context(args, ctx_manager)
        elif tool_name == "write_import_context":
            return _write_import_context(args, ctx_manager)
        elif tool_name == "extract_zip":
            return _extract_zip(args, session)
        elif tool_name == "import_openclaw_agent":
            return _import_openclaw_agent(args, session)
        elif tool_name == "finalize_import":
            return _finalize_import(session, ctx_manager)
        else:
            return {"error": f"Unknown import tool: {tool_name}"}
    except FileNotFoundError as e:
        logger.warning("Import tool %s: file not found: %s", tool_name, e)
        return {"error": "File or directory not found."}
    except ValueError as e:
        logger.warning("Import tool %s: validation error: %s", tool_name, e)
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Import tool %s failed", tool_name)
        return {"error": "An unexpected error occurred. Check the server logs."}


def _scan_directory(
    args: dict,
    session: sessions.ImportSession | None,
) -> dict:
    path_str = args.get("path", "")
    resolved = _safe_scan_path(path_str)

    adapter = FolderSourceAdapter(resolved)

    if session:
        try:
            session.adapter.close()
        except Exception:
            pass
        session.adapter = adapter
    else:
        return {"error": "No active import session. Please restart the import."}

    files = adapter.list_files()
    return {
        "found": len(files),
        "files": [{"path": f.path, "size_bytes": f.size_bytes} for f in files],
        "source_path": str(resolved),
    }


def _ingest_pasted_text(
    args: dict,
    session: sessions.ImportSession | None,
) -> dict:
    text = args.get("text", "")
    if not text.strip():
        return {"error": "No text provided"}

    adapter = PasteSourceAdapter(text)

    if session:
        try:
            session.adapter.close()
        except Exception:
            pass
        session.adapter = adapter
    else:
        return {"error": "No active import session. Please restart the import."}

    files = adapter.list_files()
    return {
        "found": len(files),
        "files": [{"path": f.path, "size_bytes": f.size_bytes} for f in files],
    }


def _extract_zip(
    args: dict,
    session: sessions.ImportSession | None,
) -> dict:
    if not session:
        return {"error": "No active import session. Please restart the import."}

    filename = args.get("filename", "")
    if not filename:
        return {"error": "No filename provided"}

    agent = None
    try:
        from agents import db as agent_db
        agent = agent_db.get_agent(session.agent_id)
    except Exception:
        pass

    if not agent:
        return {"error": "Agent not found"}

    safe_name = Path(filename).name
    if not safe_name.endswith(".zip") or ".." in safe_name or "/" in safe_name or "\\" in safe_name or "\0" in safe_name:
        return {"error": "Invalid zip filename"}

    file_cache_dir = Path(__file__).resolve().parent.parent.parent / "data" / "agents" / agent["slug"] / "file_cache"
    zip_path = (file_cache_dir / safe_name).resolve()
    if not zip_path.is_relative_to(file_cache_dir.resolve()):
        return {"error": "Invalid zip filename"}
    if not zip_path.is_file():
        return {"error": "Zip file not found in uploads. Make sure you dragged a .zip file into the chat."}

    from .adapters.zip import ZipSourceAdapter
    adapter = ZipSourceAdapter(zip_path)

    try:
        session.adapter.close()
    except Exception:
        pass
    session.adapter = adapter

    files = adapter.list_files()
    return {
        "found": len(files),
        "files": [{"path": f.path, "size_bytes": f.size_bytes} for f in files],
        "source": f"zip:{filename}",
    }


def _import_openclaw_agent(
    args: dict,
    session: sessions.ImportSession | None,
) -> dict:
    if not session:
        return {"error": "No active import session. Please restart the import."}

    agent_id = args.get("agent_id", "")
    if not agent_id:
        return {"error": "No agent_id provided"}

    from .adapters.openclaw import OpenClawFolderAdapter
    try:
        adapter = OpenClawFolderAdapter(agent_id)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}

    try:
        session.adapter.close()
    except Exception:
        pass
    session.adapter = adapter

    info = adapter.discover()
    files = adapter.list_files()
    return {
        "found": len(files),
        "agent_name": info.agent_name,
        "files": [{"path": f.path, "size_bytes": f.size_bytes} for f in files],
        "source": f"openclaw:{agent_id}",
    }


def _list_import_files(session: sessions.ImportSession | None) -> dict:
    if not session:
        return {"error": "No active import session."}

    files = session.adapter.list_files()
    return {
        "files": [
            {
                "path": f.path,
                "size_bytes": f.size_bytes,
                "skipped": f.path in session.skipped_files,
            }
            for f in files
        ],
    }


def _read_import_file(args: dict, session: sessions.ImportSession | None) -> dict:
    if not session:
        return {"error": "No active import session."}

    path = args.get("path", "")
    if path in session.skipped_files:
        return {"error": f"File '{path}' was marked as skipped."}

    content = session.adapter.read_file(path)
    return {"path": path, "content": content, "size_bytes": len(content.encode("utf-8"))}


def _skip_import_file(args: dict, session: sessions.ImportSession | None) -> dict:
    if not session:
        return {"error": "No active import session."}

    path = args.get("path", "")
    reason = args.get("reason", "")
    session.skipped_files.add(path)
    return {"skipped": path, "reason": reason}


def _read_existing_context(args: dict, ctx_manager: ContextManager) -> dict:
    filename = args.get("filename", "")
    if not filename.endswith(".md"):
        return {"error": "Filename must end with .md"}
    if "/" in filename or "\\" in filename or ".." in filename:
        return {"error": "Filename must not contain path separators"}

    content = ctx_manager.read_context(filename)
    if not content:
        return {"error": f"File '{filename}' does not exist yet."}
    return {"filename": filename, "content": content}


def _write_import_context(args: dict, ctx_manager: ContextManager) -> dict:
    filename = args.get("filename", "")
    content = args.get("content", "")

    if not _safe_import_filename(filename):
        return {"error": f"Cannot write to '{filename}'. Allowed targets: {sorted(_ALLOWED_WRITE_TARGETS)} or daily/YYYY-MM-DD.md"}

    if _DAILY_RE.match(filename):
        daily_dir = Path(ctx_manager.data_dir) / "daily"
        daily_dir.mkdir(exist_ok=True)

    ctx_manager.write_context(filename, content)
    return {"written": filename, "size_bytes": len(content.encode("utf-8"))}


def _finalize_import(
    session: sessions.ImportSession | None,
    ctx_manager: ContextManager,
) -> dict:
    if not session:
        return {"error": "No active import session."}

    # 1. Compute file hashes for re-import diffing
    file_hashes: dict[str, str] = {}
    try:
        for f in session.adapter.list_files():
            if f.path not in session.skipped_files:
                content = session.adapter.read_file(f.path)
                file_hashes[f.path] = hashlib.sha256(content.encode()).hexdigest()
    except Exception:
        logger.warning("Could not compute file hashes for import source")

    # 2. Persist import source metadata
    from agents import db as agent_db
    agent_db.upsert_import_source(
        agent_id=session.agent_id,
        adapter_type=type(session.adapter).__name__,
        source_config="{}",
        file_hashes=json.dumps(file_hashes),
    )
    agent_db.update_agent(session.agent_id, onboarding_complete=1)

    # 3. Generate the primed opener
    agent = agent_db.get_agent(session.agent_id)
    agent_name = agent["agent_name"] if agent else "Agent"

    from .primed_opener import generate_opener
    opener_text = generate_opener(ctx_manager, agent_name)

    # 4. Create a new normal conversation with the opener as the first message
    new_conversation_id = None
    try:
        from agents.engine import get_chat_service
        slug = agent["slug"] if agent else ""
        if slug:
            chat_svc = get_chat_service(slug)
            new_conv = chat_svc.create_conversation(title="(just getting started)")
            new_conversation_id = new_conv["id"]

            chat_svc.save_message(
                conversation_id=new_conversation_id,
                msg_id=str(uuid.uuid4()),
                role="assistant",
                content=opener_text,
                seq=0,
            )
    except Exception:
        logger.exception("Failed to create primed opener conversation")

    # 5. Remove the _import-bootstrap.md file now that import is done
    bootstrap_path = Path(ctx_manager.data_dir) / "_import-bootstrap.md"
    if bootstrap_path.exists():
        bootstrap_path.unlink()

    # 6. Clean up file_cache (uploaded zips)
    if agent:
        import shutil
        file_cache = Path(ctx_manager.data_dir).parent / "file_cache"
        if file_cache.is_dir():
            shutil.rmtree(file_cache, ignore_errors=True)

    # 7. Reindex memory DB so imported context is searchable
    if agent:
        try:
            from agents.engine import ensure_memory_db
            ensure_memory_db(agent["slug"])
        except Exception:
            logger.warning("Could not reindex memory DB after import")

    # 8. Clean up session
    sessions.remove_session(session.token)

    return {
        "ok": True,
        "agent_id": session.agent_id,
        "files_imported": len(file_hashes),
        "files_skipped": len(session.skipped_files),
        "new_conversation_id": new_conversation_id,
        "opener_preview": opener_text[:200],
    }
