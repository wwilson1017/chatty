"""Drive operations — each function takes an authenticated Drive v3 service."""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

_LIST_FIELDS = "files(id,name,mimeType,modifiedTime,size,webViewLink,parents),nextPageToken"

# Google Workspace native MIME types we can export to text/markdown/csv
_EXPORT_MAP = {
    "application/vnd.google-apps.document": {
        "txt": "text/plain",
        "markdown": "text/markdown",
        "html": "text/html",
        "default": "text/plain",
    },
    "application/vnd.google-apps.spreadsheet": {
        "csv": "text/csv",
        "default": "text/csv",
    },
    "application/vnd.google-apps.presentation": {
        "txt": "text/plain",
        "default": "text/plain",
    },
}


def _format_file(f: dict) -> dict:
    return {
        "id": f.get("id"),
        "name": f.get("name", ""),
        "mime_type": f.get("mimeType", ""),
        "modified": f.get("modifiedTime", ""),
        "size": f.get("size"),
        "web_view_link": f.get("webViewLink", ""),
        "parents": f.get("parents", []),
    }


# ── Read ops ─────────────────────────────────────────────────────────────────

def list_files_op(
    service,
    query: str = "",
    folder_id: str = "",
    max_results: int = 20,
) -> list[dict]:
    """List Drive files. `query` accepts Drive search syntax (e.g. "name contains 'report'")."""
    q_parts = []
    if query:
        q_parts.append(query)
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    # Exclude trashed by default
    q_parts.append("trashed = false")
    q = " and ".join(q_parts)

    resp = service.files().list(
        q=q,
        pageSize=max_results,
        fields=_LIST_FIELDS,
        orderBy="modifiedTime desc",
    ).execute()
    return [_format_file(f) for f in resp.get("files", [])]


def search_files_op(
    service,
    name_contains: str = "",
    mime_type: str = "",
    max_results: int = 20,
) -> list[dict]:
    """Search Drive by name and/or MIME type."""
    q_parts = ["trashed = false"]
    if name_contains:
        safe = name_contains.replace("\\", "\\\\").replace("'", "\\'")
        q_parts.append(f"name contains '{safe}'")
    if mime_type:
        safe_mime = mime_type.replace("\\", "\\\\").replace("'", "\\'")
        q_parts.append(f"mimeType = '{safe_mime}'")
    q = " and ".join(q_parts)

    resp = service.files().list(
        q=q,
        pageSize=max_results,
        fields=_LIST_FIELDS,
        orderBy="modifiedTime desc",
    ).execute()
    return [_format_file(f) for f in resp.get("files", [])]


def get_file_content_op(
    service,
    file_id: str,
    as_format: str = "default",
    max_bytes: int = 1_000_000,
) -> dict:
    """Fetch file content. Google-native files are exported; binaries return bytes as text if possible."""
    from googleapiclient.http import MediaIoBaseDownload

    # First get metadata so we know the MIME type
    meta = service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,webViewLink",
    ).execute()
    mime = meta.get("mimeType", "")

    export_options = _EXPORT_MAP.get(mime)
    buffer = io.BytesIO()

    if export_options:
        # Google Docs/Sheets/Slides — export to requested format
        export_mime = export_options.get(as_format) or export_options["default"]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        # Binary upload — just download it
        request = service.files().get_media(fileId=file_id)

    downloader = MediaIoBaseDownload(buffer, request, chunksize=256 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        if buffer.tell() > max_bytes:
            return {
                "error": f"File exceeds {max_bytes}-byte read limit",
                "name": meta.get("name"),
                "mime_type": mime,
                "web_view_link": meta.get("webViewLink", ""),
            }

    raw = buffer.getvalue()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    return {
        "id": file_id,
        "name": meta.get("name"),
        "mime_type": mime,
        "content": text,
        "web_view_link": meta.get("webViewLink", ""),
    }


# ── Write ops ────────────────────────────────────────────────────────────────

def upload_file_op(
    service,
    filename: str,
    content: str,
    mime_type: str = "text/plain",
    parent_folder_id: str = "",
) -> dict:
    """Upload a new file to Drive. Returns {id, name, web_view_link}."""
    from googleapiclient.http import MediaIoBaseUpload

    metadata: dict = {"name": filename}
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8") if isinstance(content, str) else content),
        mimetype=mime_type,
        resumable=False,
    )
    created = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,mimeType,webViewLink",
    ).execute()
    return {
        "ok": True,
        "id": created.get("id"),
        "name": created.get("name"),
        "mime_type": created.get("mimeType"),
        "web_view_link": created.get("webViewLink", ""),
    }
