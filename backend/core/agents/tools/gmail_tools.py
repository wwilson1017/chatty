"""
Chatty — Gmail tools for agents.

Uses the user's OAuth access token (stored in CredentialStore).
Adapted from CAKE OS apps/jordan/tools/gmail_tools.py — service account
replaced with user OAuth token.
"""

import logging

from core.gmail_client import list_messages, get_message, get_thread

logger = logging.getLogger(__name__)


def search_emails(access_token: str, query: str, max_results: int = 10) -> dict:
    """Search Gmail messages matching a query."""
    try:
        messages = list_messages(access_token, query=query, max_results=max_results)
        return {"messages": messages, "count": len(messages)}
    except Exception as e:
        logger.error("Gmail search error: %s", e)
        return {"error": str(e)}


def get_email(access_token: str, message_id: str) -> dict:
    """Get a specific Gmail message by ID."""
    try:
        message = get_message(access_token, message_id)
        return message
    except Exception as e:
        logger.error("Gmail get_message error: %s", e)
        return {"error": str(e)}


def get_email_thread(access_token: str, thread_id: str) -> dict:
    """Get all messages in a Gmail thread."""
    try:
        thread = get_thread(access_token, thread_id)
        return thread
    except Exception as e:
        logger.error("Gmail get_thread error: %s", e)
        return {"error": str(e)}
