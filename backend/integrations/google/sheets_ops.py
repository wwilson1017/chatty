"""Google Sheets operations — each function takes an authenticated Sheets v4 service.

Curated CRUD: read_range, read_metadata (read), write_range, append_rows,
clear_range, create, add_tab (write). Deleting a spreadsheet is delete_drive_file.
Patterns adapted from the Hermes agent and CAKE OS sheets writers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SHEET_URL = "https://docs.google.com/spreadsheets/d/{}/edit"

# Soft cap on the number of cells returned by a single read so a huge range
# can't blow up tool output / context. Rows past the cap are dropped.
_MAX_READ_CELLS = 20000


# ── Read ─────────────────────────────────────────────────────────────────────

def get_values_op(service, spreadsheet_id: str, range_a1: str) -> dict:
    """Read cell values from an A1 range (e.g. "Sheet1!A1:D10")."""
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_a1,
    ).execute()
    values = resp.get("values", [])
    truncated = False
    cells = sum(len(row) for row in values)
    if cells > _MAX_READ_CELLS:
        # Keep whole rows up to the cap, but always return at least the first
        # row so a very wide first row doesn't yield "truncated but 0 rows".
        kept: list[list] = []
        running = 0
        for row in values:
            if kept and running + len(row) > _MAX_READ_CELLS:
                break
            kept.append(row)
            running += len(row)
        values = kept
        truncated = True
    return {
        "spreadsheet_id": spreadsheet_id,
        "range": resp.get("range", range_a1),
        "values": values,
        "row_count": len(values),
        "truncated": truncated,
        "web_link": _SHEET_URL.format(spreadsheet_id),
    }


def get_metadata_op(service, spreadsheet_id: str) -> dict:
    """Read spreadsheet title and the list of its sheets/tabs with dimensions."""
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="properties.title,sheets.properties(sheetId,title,gridProperties)",
    ).execute()
    sheets = []
    for s in meta.get("sheets", []):
        p = s.get("properties", {})
        grid = p.get("gridProperties", {})
        sheets.append({
            "sheet_id": p.get("sheetId"),
            "title": p.get("title", ""),
            "row_count": grid.get("rowCount"),
            "column_count": grid.get("columnCount"),
        })
    return {
        "spreadsheet_id": spreadsheet_id,
        "title": meta.get("properties", {}).get("title", ""),
        "sheets": sheets,
        "web_link": _SHEET_URL.format(spreadsheet_id),
    }


# ── Write ────────────────────────────────────────────────────────────────────

def update_values_op(service, spreadsheet_id: str, range_a1: str, values: list[list]) -> dict:
    """Overwrite the given A1 range with a 2D array of values (USER_ENTERED)."""
    resp = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    return {
        "ok": True, "spreadsheet_id": spreadsheet_id,
        "updated_range": resp.get("updatedRange", range_a1),
        "updated_cells": resp.get("updatedCells", 0),
        "web_link": _SHEET_URL.format(spreadsheet_id),
    }


def append_rows_op(service, spreadsheet_id: str, range_a1: str, values: list[list]) -> dict:
    """Append rows after the last row of data in the given range (INSERT_ROWS)."""
    resp = service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    updates = resp.get("updates", {})
    return {
        "ok": True, "spreadsheet_id": spreadsheet_id,
        "updated_range": updates.get("updatedRange", ""),
        "updated_rows": updates.get("updatedRows", 0),
        "web_link": _SHEET_URL.format(spreadsheet_id),
    }


def clear_values_op(service, spreadsheet_id: str, range_a1: str) -> dict:
    """Clear all values in the given A1 range (keeps formatting)."""
    resp = service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=range_a1, body={},
    ).execute()
    return {
        "ok": True, "spreadsheet_id": spreadsheet_id,
        "cleared_range": resp.get("clearedRange", range_a1),
        "web_link": _SHEET_URL.format(spreadsheet_id),
    }


def create_spreadsheet_op(service, title: str) -> dict:
    """Create a new spreadsheet."""
    ss = service.spreadsheets().create(
        body={"properties": {"title": title}},
        fields="spreadsheetId,properties.title",
    ).execute()
    ss_id = ss.get("spreadsheetId", "")
    return {
        "ok": True, "spreadsheet_id": ss_id,
        "title": ss.get("properties", {}).get("title", title),
        "web_link": _SHEET_URL.format(ss_id),
    }


def add_sheet_op(service, spreadsheet_id: str, title: str) -> dict:
    """Add a new sheet/tab to an existing spreadsheet."""
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    replies = resp.get("replies", [])
    new_props = replies[0].get("addSheet", {}).get("properties", {}) if replies else {}
    return {
        "ok": True, "spreadsheet_id": spreadsheet_id,
        "sheet_id": new_props.get("sheetId"),
        "title": new_props.get("title", title),
        "web_link": _SHEET_URL.format(spreadsheet_id),
    }
