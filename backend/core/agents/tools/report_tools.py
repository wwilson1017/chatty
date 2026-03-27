"""Chatty — Report generation tool + CRUD.

Handles the generate_report tool call from any AI agent, persisting reports
as JSON files in data/agents/{slug}/reports/. Also provides list/get/delete
for the Reports gallery.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CT_TZ = ZoneInfo("America/Chicago")

ALLOWED_CHART_TYPES = {
    "bar", "horizontal_bar", "stacked_bar", "grouped_bar",
    "line", "area", "pie", "donut", "table", "metric",
}

MAX_SECTIONS = 20
MAX_DATA_POINTS = 1000

_UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


def _valid_report_id(report_id: str) -> bool:
    return bool(_UUID_RE.match(report_id))


def _ensure_reports_dir(reports_dir: str) -> Path:
    path = Path(reports_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _coerce_numeric(values: list) -> list:
    result = []
    for v in values:
        if isinstance(v, str):
            try:
                result.append(float(v) if "." in v else int(v))
                continue
            except (ValueError, TypeError):
                pass
        result.append(v)
    return result


def generate_report(
    reports_dir: str,
    title: str,
    sections: list,
    subtitle: str = "",
) -> dict:
    """Validate sections, assign UUID, save JSON, return report data."""
    if not sections:
        return {"ok": False, "error": "At least one section is required"}

    if len(sections) > MAX_SECTIONS:
        return {"ok": False, "error": f"Too many sections ({len(sections)}). Maximum is {MAX_SECTIONS}."}

    validated_sections = []
    for i, section in enumerate(sections):
        chart_type = section.get("chart_type", "")
        if chart_type not in ALLOWED_CHART_TYPES:
            return {
                "ok": False,
                "error": f"Section {i}: invalid chart_type '{chart_type}'. "
                         f"Allowed: {', '.join(sorted(ALLOWED_CHART_TYPES))}",
            }

        data = section.get("data", {})
        if not data:
            return {"ok": False, "error": f"Section {i}: 'data' is required"}

        # Enforce data point limits
        total_points = 0
        for ds in data.get("datasets", []):
            total_points += len(ds.get("values", []))
        total_points += sum(len(row) for row in data.get("rows", []))
        total_points += len(data.get("metrics", []))
        if total_points > MAX_DATA_POINTS:
            return {"ok": False, "error": f"Section {i}: too many data points ({total_points}). Maximum is {MAX_DATA_POINTS}."}

        # Coerce numeric values
        if chart_type in ("bar", "horizontal_bar", "stacked_bar", "grouped_bar", "line", "area", "pie", "donut"):
            for ds in data.get("datasets", []):
                if "values" in ds:
                    ds["values"] = _coerce_numeric(ds["values"])
        elif chart_type == "table":
            rows = data.get("rows", [])
            data["rows"] = [_coerce_numeric(row) for row in rows]
        elif chart_type == "metric":
            for m in data.get("metrics", []):
                if "value" in m and isinstance(m["value"], str):
                    try:
                        m["value"] = float(m["value"]) if "." in m["value"] else int(m["value"])
                    except (ValueError, TypeError):
                        pass

        validated_sections.append({
            "chart_type": chart_type,
            "title": section.get("title", ""),
            "data": data,
            "options": section.get("options", {}),
        })

    report_id = str(uuid.uuid4())
    now = datetime.now(CT_TZ)
    report = {
        "id": report_id,
        "title": title,
        "subtitle": subtitle,
        "sections": validated_sections,
        "created_at": now.isoformat(),
    }

    dir_path = _ensure_reports_dir(reports_dir)
    filepath = dir_path / f"{report_id}.json"
    filepath.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    logger.info("Generated report '%s' (%s) with %d sections", title, report_id, len(validated_sections))
    return {"ok": True, **report}


def list_reports(reports_dir: str) -> list[dict]:
    """List all saved reports, newest first."""
    dir_path = Path(reports_dir)
    if not dir_path.exists():
        return []

    reports = []
    for f in dir_path.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            reports.append({
                "id": data["id"],
                "title": data.get("title", "Untitled"),
                "subtitle": data.get("subtitle", ""),
                "section_count": len(data.get("sections", [])),
                "created_at": data.get("created_at", ""),
            })
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Skipping invalid report file %s: %s", f.name, e)

    reports.sort(key=lambda r: r["created_at"], reverse=True)
    return reports


def get_report(reports_dir: str, report_id: str) -> dict | None:
    """Get a single report by ID."""
    if not _valid_report_id(report_id):
        return None
    filepath = Path(reports_dir) / f"{report_id}.json"
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read report %s: %s", report_id, e)
        return None


def delete_report(reports_dir: str, report_id: str) -> bool:
    """Delete a report by ID."""
    if not _valid_report_id(report_id):
        return False
    filepath = Path(reports_dir) / f"{report_id}.json"
    if not filepath.exists():
        return False
    filepath.unlink()
    logger.info("Deleted report %s", report_id)
    return True
