"""Source adapter for local OpenClaw installations.

Reads ~/.openclaw/openclaw.json to discover agents and resolve workspace paths,
then delegates to FolderSourceAdapter for actual file reading.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .base import FileEntry, SourceAdapter, SourceInfo
from .folder import FolderSourceAdapter

logger = logging.getLogger(__name__)

DEFAULT_STATE_DIR = Path.home() / ".openclaw"
DEFAULT_CONFIG = DEFAULT_STATE_DIR / "openclaw.json"


def discover_openclaw_agents(
    config_path: Path | None = None,
) -> list[dict]:
    """Read openclaw.json and return a list of {id, name, workspace} dicts."""
    path = config_path or DEFAULT_CONFIG
    if not path.is_file():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read OpenClaw config at %s", path)
        return []

    agents_section = data.get("agents", {})
    agent_list = agents_section.get("list", [])
    default_workspace = agents_section.get("defaults", {}).get("workspace")
    state_dir = path.parent

    results = []
    for entry in agent_list:
        agent_id = entry.get("id", "")
        name = entry.get("name", agent_id)

        workspace = entry.get("workspace")
        if not workspace:
            if agent_id == "default":
                workspace = str(state_dir / "workspace")
            else:
                workspace = str(state_dir / f"workspace-{agent_id}")
        else:
            workspace = str(Path(workspace).expanduser())

        results.append({"id": agent_id, "name": name, "workspace": workspace})

    return results


class OpenClawFolderAdapter(SourceAdapter):
    """Read files from a specific OpenClaw agent's workspace directory."""

    def __init__(self, agent_id: str, config_path: Path | None = None) -> None:
        agents = discover_openclaw_agents(config_path)
        match = next((a for a in agents if a["id"] == agent_id), None)
        if not match:
            available = [a["id"] for a in agents]
            raise ValueError(
                f"OpenClaw agent '{agent_id}' not found. Available: {available}"
            )

        self._agent_id = agent_id
        self._agent_name = match["name"]
        self._inner = FolderSourceAdapter(match["workspace"])

    def discover(self) -> SourceInfo:
        info = self._inner.discover()
        info.agent_name = self._agent_name
        return info

    def list_files(self) -> list[FileEntry]:
        return self._inner.list_files()

    def read_file(self, path: str) -> str:
        return self._inner.read_file(path)

    def close(self) -> None:
        self._inner.close()
