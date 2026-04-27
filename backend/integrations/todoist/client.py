"""Chatty — Todoist API client."""

import logging

from todoist_api_python.api import TodoistAPI
from todoist_api_python.api_async import TodoistAPIAsync

logger = logging.getLogger(__name__)


def get_client_sync() -> TodoistAPI | None:
    """Return a sync TodoistAPI client, or None if not configured."""
    from integrations.registry import get_credentials, is_enabled
    if not is_enabled("todoist"):
        return None
    creds = get_credentials("todoist")
    token = creds.get("api_token", "")
    if not token:
        return None
    return TodoistAPI(token)


def get_client_async() -> TodoistAPIAsync | None:
    """Return an async TodoistAPIAsync client, or None if not configured."""
    from integrations.registry import get_credentials, is_enabled
    if not is_enabled("todoist"):
        return None
    creds = get_credentials("todoist")
    token = creds.get("api_token", "")
    if not token:
        return None
    return TodoistAPIAsync(token)


def test_connection(api_token: str) -> bool:
    """Validate an API token by fetching projects."""
    try:
        api = TodoistAPI(api_token)
        list(api.get_projects())
        return True
    except Exception as e:
        logger.error("Todoist connection test failed: %s", e)
        return False
