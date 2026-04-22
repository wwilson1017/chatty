"""Drive operations — each function takes an authenticated Drive v3 service.

9 tools: search, list_folder, get_file_info, read_file_content (read),
create_folder, create_file, move_file, rename_file, copy_file (write).
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

MIME_FOLDER = "application/vnd.google-apps.folder"

_LIST_FIELDS = "files(id,name,mimeType,modifiedTime,size,webViewLink,parents)"

_DETAIL_FIELDS = (
    "id,name,mimeType,modifiedTime,createdTime,size,owners,"
    "lastModifyingUser,webViewLink,parents,description,shared,sharingUser"
)

_EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

_READABLE_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
)

_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024


def _format_file(f: dict) -> dict:
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType", ""),
        "modified_time": f.get("modifiedTime", ""),
        "size": f.get("size"),
        "web_link": f.get("webViewLink", ""),
        "is_folder": f.get("mimeType") == MIME_FOLDER,
    }


def _format_file_detail(f: dict) -> dict:
    owners = [
        {"name": o.get("displayName", ""), "email": o.get("emailAddress", "")}
        for o in f.get("owners", [])
    ]
    last_modified_by = f.get("lastModifyingUser", {})
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType", ""),
        "modified_time": f.get("modifiedTime", ""),
        "created_time": f.get("createdTime", ""),
        "size": f.get("size"),
        "web_link": f.get("webViewLink", ""),
        "is_folder": f.get("mimeType") == MIME_FOLDER,
        "owners": owners,
        "last_modified_by": {
            "name": last_modified_by.get("displayName", ""),
            "email": last_modified_by.get("emailAddress", ""),
        } if last_modified_by else None,
        "shared": f.get("shared", False),
        "description": f.get("description", ""),
    }


# ── Read ops ─────────────────────────────────────────────────────────────────

def search_files_op(service, query: str, max_results: int = 20) -> list[dict]:
    """Search files in Drive using query syntax (e.g. "name contains 'budget'")."""
    if "trashed" not in query.lower():
        query = f"({query}) and trashed = false"
    resp = service.files().list(
        q=query,
        pageSize=max_results,
        fields=_LIST_FIELDS,
        orderBy="modifiedTime desc",
    ).execute()
    return [_format_file(f) for f in resp.get("files", [])]


def list_folder_op(service, folder_id: str = "root", max_results: int = 50) -> list[dict]:
    """List contents of a Drive folder."""
    q = f"'{folder_id}' in parents and trashed = false"
    resp = service.files().list(
        q=q,
        pageSize=max_results,
        fields=_LIST_FIELDS,
        orderBy="folder,name",
    ).execute()
    return [_format_file(f) for f in resp.get("files", [])]


def get_file_info_op(service, file_id: str) -> dict:
    """Get detailed metadata for a Drive file."""
    f = service.files().get(
        fileId=file_id,
        fields=_DETAIL_FIELDS,
    ).execute()
    return _format_file_detail(f)


def read_file_content_op(service, file_id: str, max_chars: int = 50000) -> dict:
    """Read file content from Drive.

    Google Docs/Slides → plain text, Sheets → CSV. Text-based files downloaded directly.
    Binary files return an error.
    """
    meta = service.files().get(
        fileId=file_id, fields="id,name,mimeType,size",
    ).execute()

    mime_type = meta.get("mimeType", "")
    name = meta.get("name", "")

    export_mime = _EXPORT_MIME_MAP.get(mime_type)
    if export_mime:
        raw = service.files().export(fileId=file_id, mimeType=export_mime).execute()
        content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return {
            "file_id": file_id, "name": name, "mime_type": mime_type,
            "export_format": export_mime,
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
            "char_count": len(content),
        }

    if mime_type.startswith("application/vnd.google-apps."):
        return {
            "error": f"Cannot read content of {mime_type}. Only Google Docs, Sheets, and Slides can be exported as text. Use get_drive_file_info to see metadata.",
            "file_id": file_id, "name": name, "mime_type": mime_type,
        }

    file_size = int(meta.get("size", 0) or 0)
    if file_size > _MAX_DOWNLOAD_BYTES:
        return {
            "error": f"File is too large to read ({file_size:,} bytes, max {_MAX_DOWNLOAD_BYTES:,}). Use get_drive_file_info to see metadata.",
            "file_id": file_id, "name": name, "mime_type": mime_type,
        }

    is_readable = any(mime_type.startswith(p) for p in _READABLE_MIME_PREFIXES)
    if not is_readable:
        return {
            "error": f"Cannot read binary file content (type: {mime_type}). Use get_drive_file_info to see metadata.",
            "file_id": file_id, "name": name, "mime_type": mime_type,
        }

    from googleapiclient.http import MediaIoBaseDownload
    from io import BytesIO
    request = service.files().get_media(fileId=file_id)
    buffer = BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    content = buffer.getvalue().decode("utf-8", errors="replace")

    return {
        "file_id": file_id, "name": name, "mime_type": mime_type,
        "export_format": "native",
        "content": content[:max_chars],
        "truncated": len(content) > max_chars,
        "char_count": len(content),
    }


# ── Write ops ────────────────────────────────────────────────────────────────

def create_folder_op(service, name: str, parent_folder_id: str = "root") -> dict:
    """Create a new folder in Drive."""
    meta = {
        "name": name,
        "mimeType": MIME_FOLDER,
        "parents": [parent_folder_id],
    }
    folder = service.files().create(
        body=meta,
        fields="id,name,mimeType,modifiedTime,webViewLink",
    ).execute()
    return {"ok": True, **_format_file(folder)}


def create_file_op(
    service,
    name: str,
    content: str = "",
    file_type: str = "document",
    folder_id: str = "root",
) -> dict:
    """Create a new file in Drive with text content.

    file_type: 'document' for Google Doc, 'text' for plain text file.
    """
    from googleapiclient.http import MediaInMemoryUpload

    file_meta: dict = {"name": name, "parents": [folder_id]}

    if file_type == "document":
        file_meta["mimeType"] = "application/vnd.google-apps.document"
        upload_mime = "text/plain"
    else:
        upload_mime = "text/plain"

    media = MediaInMemoryUpload(
        content.encode("utf-8"),
        mimetype=upload_mime,
        resumable=False,
    )
    created = service.files().create(
        body=file_meta,
        media_body=media,
        fields="id,name,mimeType,modifiedTime,webViewLink",
    ).execute()
    return {"ok": True, **_format_file(created)}


def move_file_op(service, file_id: str, new_parent_id: str) -> dict:
    """Move a file to a different folder."""
    f = service.files().get(fileId=file_id, fields="parents").execute()
    current_parents = ",".join(f.get("parents", []))
    updated = service.files().update(
        fileId=file_id,
        addParents=new_parent_id,
        removeParents=current_parents,
        fields="id,name,mimeType,modifiedTime,webViewLink,parents",
    ).execute()
    return {"ok": True, **_format_file(updated)}


def rename_file_op(service, file_id: str, new_name: str) -> dict:
    """Rename a file or folder."""
    updated = service.files().update(
        fileId=file_id,
        body={"name": new_name},
        fields="id,name,mimeType,modifiedTime,webViewLink",
    ).execute()
    return {"ok": True, **_format_file(updated)}


def copy_file_op(
    service,
    file_id: str,
    new_name: str | None = None,
    folder_id: str | None = None,
) -> dict:
    """Copy a file, optionally with a new name and/or into a different folder."""
    body: dict = {}
    if new_name:
        body["name"] = new_name
    if folder_id:
        body["parents"] = [folder_id]

    copied = service.files().copy(
        fileId=file_id,
        body=body,
        fields="id,name,mimeType,modifiedTime,webViewLink",
    ).execute()
    return {"ok": True, **_format_file(copied)}
