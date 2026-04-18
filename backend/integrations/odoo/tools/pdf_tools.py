"""
Chatty — Odoo PDF & attachment tools.

Download Odoo document PDFs via QWeb report engine, read text from Odoo
attachments (PDFs, spreadsheets, CSV, plain text). Ported from CakeOS.
"""

import base64
import io
import logging
import xmlrpc.client

from ..helpers import safe_get_client

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

_TEXT_EXTENSIONS = {
    ".txt", ".eml", ".html", ".htm", ".xml", ".json", ".log",
    ".md", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".toml",
    ".py", ".js", ".css",
}
_PDF_EXTENSIONS = {".pdf"}
_SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
_CSV_EXTENSIONS = {".csv", ".tsv"}

_REPORT_MAP = {
    "purchase_order": {
        "report_name": "purchase.report_purchaseorder",
        "model": "purchase.order",
        "name_field": "name",
    },
    "invoice": {
        "report_name": "account.report_invoice",
        "model": "account.move",
        "name_field": "name",
    },
    "sale_order": {
        "report_name": "sale.report_saleorder",
        "model": "sale.order",
        "name_field": "name",
    },
    "delivery": {
        "report_name": "stock.report_deliveryslip",
        "model": "stock.picking",
        "name_field": "name",
    },
    "picking": {
        "report_name": "stock.report_picking",
        "model": "stock.picking",
        "name_field": "name",
    },
}

# ── File type classification ─────────────────────────────────────────────

def classify_mimetype(mimetype: str, filename: str) -> str:
    mimetype = (mimetype or "").lower()
    ext = ""
    if filename and "." in filename:
        ext = ("." + filename.rsplit(".", 1)[-1]).lower()

    if mimetype == "application/pdf" or ext in _PDF_EXTENSIONS:
        return "pdf"
    if ext in _SPREADSHEET_EXTENSIONS or mimetype in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        return "spreadsheet"
    if ext in _CSV_EXTENSIONS or mimetype == "text/csv":
        return "csv"
    if mimetype.startswith("text/") or ext in _TEXT_EXTENSIONS:
        return "text"
    return "binary"


def is_text_extractable(file_type: str) -> bool:
    return file_type in ("pdf", "spreadsheet", "csv", "text")


# ── Text extraction ──────────────────────────────────────────────────────

def extract_pdf_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    import pdfplumber
    parts = []
    total = 0
    truncated = False
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if not page_text:
                    continue
                remaining = max_chars - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(page_text) > remaining:
                    parts.append(page_text[:remaining])
                    truncated = True
                    break
                parts.append(page_text)
                total += len(page_text)
    except Exception as e:
        logger.warning("pdfplumber extraction failed: %s", e)
        return f"[PDF extraction error: {e}]", False
    return "\n\n".join(parts), truncated


def extract_spreadsheet_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    if data[:4] == b'\xd0\xcf\x11\xe0':
        return _extract_xls_text(data, max_chars)
    return _extract_xlsx_text(data, max_chars)


def _extract_xls_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    import xlrd
    parts = []
    total = 0
    truncated = False
    try:
        wb = xlrd.open_workbook(file_contents=data)
        for sheet_name in wb.sheet_names():
            ws = wb.sheet_by_name(sheet_name)
            if wb.nsheets > 1:
                header = f"--- Sheet: {sheet_name} ---"
                parts.append(header)
                total += len(header)
            for row_idx in range(ws.nrows):
                cells = [str(c.value) if c.value != "" else "" for c in ws.row(row_idx)]
                line = "\t".join(cells)
                remaining = max_chars - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(line) > remaining:
                    parts.append(line[:remaining])
                    truncated = True
                    break
                parts.append(line)
                total += len(line) + 1
            if truncated:
                break
    except Exception as e:
        logger.warning("xlrd extraction failed: %s", e)
        return f"[Spreadsheet extraction error: {e}]", False
    return "\n".join(parts), truncated


def _extract_xlsx_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    from openpyxl import load_workbook
    parts = []
    total = 0
    truncated = False
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            if len(wb.sheetnames) > 1:
                header = f"--- Sheet: {sheet_name} ---"
                parts.append(header)
                total += len(header)
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                line = "\t".join(cells)
                remaining = max_chars - total
                if remaining <= 0:
                    truncated = True
                    break
                if len(line) > remaining:
                    parts.append(line[:remaining])
                    truncated = True
                    break
                parts.append(line)
                total += len(line) + 1
            if truncated:
                break
        wb.close()
    except Exception as e:
        logger.warning("openpyxl extraction failed: %s", e)
        return f"[Spreadsheet extraction error: {e}]", False
    return "\n".join(parts), truncated


def extract_csv_text(data: bytes, max_chars: int) -> tuple[str, bool]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def extract_text(data: bytes, file_type: str, max_chars: int) -> tuple[str, bool]:
    if file_type == "pdf":
        return extract_pdf_text(data, max_chars)
    if file_type == "spreadsheet":
        return extract_spreadsheet_text(data, max_chars)
    if file_type == "csv":
        return extract_csv_text(data, max_chars)
    if file_type == "text":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        if len(text) <= max_chars:
            return text, False
        return text[:max_chars], True
    return "", False


def decode_datas(datas) -> bytes:
    if isinstance(datas, xmlrpc.client.Binary):
        return datas.data
    if isinstance(datas, (bytes, str)):
        try:
            return base64.b64decode(datas)
        except Exception as e:
            logger.warning("Failed to base64-decode Odoo attachment datas: %s", e)
            return b""
    return b""


# ── Tool handlers ────────────────────────────────────────────────────────

def download_odoo_pdf(document_type: str, record_id: int) -> dict:
    client = safe_get_client()
    if not client:
        return {"error": "Odoo not connected"}

    mapping = _REPORT_MAP.get(document_type)
    if not mapping:
        supported = ", ".join(sorted(_REPORT_MAP.keys()))
        return {"error": f"Unknown document type '{document_type}'. Supported: {supported}"}

    report_name = mapping["report_name"]
    model = mapping["model"]
    name_field = mapping["name_field"]

    reports = client.search_read(
        "ir.actions.report",
        [["report_name", "=", report_name]],
        ["id"],
        limit=1,
    )
    if not reports:
        return {"error": f"Report '{report_name}' not found in Odoo. The module may not be installed."}
    report_id = reports[0]["id"]

    records = client.search_read(
        model, [["id", "=", record_id]], ["id", name_field], limit=1,
    )
    if not records:
        return {"error": f"{document_type} with ID {record_id} not found"}

    display_name = records[0].get(name_field, str(record_id))
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(display_name))
    safe_name = safe_name.strip("_") or f"{document_type}_{record_id}"
    filename = f"{safe_name}.pdf"

    try:
        result = client.execute(
            "ir.actions.report", "_render_qweb_pdf", report_id, [record_id],
        )
    except Exception as e:
        logger.error("Odoo PDF render failed for %s/%s: %s", document_type, record_id, e)
        return {"error": f"Failed to render PDF: {e}"}

    if not result:
        return {"error": "Odoo returned empty result from PDF render"}

    pdf_data = result[0] if isinstance(result, (list, tuple)) else result

    if isinstance(pdf_data, xmlrpc.client.Binary):
        raw_bytes = pdf_data.data
    elif isinstance(pdf_data, bytes):
        if pdf_data[:5] == b"%PDF-":
            raw_bytes = pdf_data
        else:
            try:
                raw_bytes = base64.b64decode(pdf_data)
            except Exception:
                raw_bytes = pdf_data
    elif isinstance(pdf_data, str):
        try:
            raw_bytes = base64.b64decode(pdf_data)
        except Exception:
            return {"error": "Failed to decode PDF data from Odoo"}
    else:
        return {"error": f"Unexpected PDF data type from Odoo: {type(pdf_data).__name__}"}

    pdf_base64 = base64.b64encode(raw_bytes).decode("ascii")

    return {
        "ok": True,
        "document_type": document_type,
        "record_id": record_id,
        "display_name": display_name,
        "filename": filename,
        "pdf_base64": pdf_base64,
        "size_bytes": len(raw_bytes),
    }


def read_odoo_attachment(attachment_id: int, max_chars: int = 50_000) -> dict:
    client = safe_get_client()
    if not client:
        return {"error": "Odoo not connected"}

    records = client.search_read(
        "ir.attachment",
        [["id", "=", attachment_id]],
        ["id", "name", "mimetype", "file_size", "datas"],
        limit=1,
    ) or []

    if not records:
        return {"error": f"Attachment #{attachment_id} not found"}

    rec = records[0]
    filename = rec.get("name", "")
    mimetype = rec.get("mimetype", "")
    file_size = rec.get("file_size", 0) or 0
    file_type = classify_mimetype(mimetype, filename)

    if file_size > MAX_FILE_SIZE:
        return {
            "id": attachment_id, "filename": filename, "mimetype": mimetype,
            "file_size": file_size, "file_type": file_type, "text_content": None,
            "note": f"File too large ({file_size / (1024*1024):.1f} MB, limit {MAX_FILE_SIZE / (1024*1024):.0f} MB)",
        }

    if not is_text_extractable(file_type):
        return {
            "id": attachment_id, "filename": filename, "mimetype": mimetype,
            "file_size": file_size, "file_type": file_type, "text_content": None,
            "note": f"Binary file — text extraction not supported for {mimetype or file_type}",
        }

    datas = rec.get("datas")
    if not datas:
        return {
            "id": attachment_id, "filename": filename, "mimetype": mimetype,
            "file_size": file_size, "file_type": file_type, "text_content": None,
            "note": "Attachment has no binary content",
        }

    raw = decode_datas(datas)
    if not raw:
        return {
            "id": attachment_id, "filename": filename, "mimetype": mimetype,
            "file_size": file_size, "file_type": file_type, "text_content": None,
            "note": "Failed to decode attachment data",
        }

    if len(raw) > MAX_FILE_SIZE:
        return {
            "id": attachment_id, "filename": filename, "mimetype": mimetype,
            "file_size": len(raw), "file_type": file_type, "text_content": None,
            "note": f"File too large ({len(raw) / (1024*1024):.1f} MB)",
        }

    text, truncated = extract_text(raw, file_type, max_chars)

    result = {
        "id": attachment_id, "filename": filename, "mimetype": mimetype,
        "file_size": file_size, "file_type": file_type,
        "text_content": text if text else None,
        "chars_extracted": len(text), "truncated": truncated,
    }
    if not text and file_type == "pdf":
        result["note"] = "PDF has no extractable text (may be scanned/image-based)"
    if truncated:
        result["note"] = f"Content truncated at {max_chars} characters"
    return result


# ── Tool definitions ─────────────────────────────────────────────────────

PDF_TOOL_DEFS = [
    {
        "name": "odoo_download_pdf",
        "description": (
            "Download a PDF report from Odoo. Renders the document via Odoo's QWeb report "
            "engine. Supported types: purchase_order, invoice, sale_order, delivery, picking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": ["purchase_order", "invoice", "sale_order", "delivery", "picking"],
                    "description": "Type of document to download",
                },
                "record_id": {
                    "type": "integer",
                    "description": "Odoo record ID of the document",
                },
            },
            "required": ["document_type", "record_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "odoo_read_attachment",
        "description": (
            "Read an Odoo attachment and extract its text content. "
            "Supports PDFs (text extraction), spreadsheets (.xlsx/.xls), CSV, and plain text files. "
            "Returns the extracted text — useful for reading invoices, POs, or documents attached to records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "integer",
                    "description": "Odoo attachment ID (ir.attachment record ID)",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to extract (default 50000)",
                },
            },
            "required": ["attachment_id"],
        },
        "kind": "integration",
        "writes": False,
    },
]

PDF_EXECUTORS = {
    "odoo_download_pdf": lambda **kw: download_odoo_pdf(**kw),
    "odoo_read_attachment": lambda **kw: read_odoo_attachment(**kw),
}
