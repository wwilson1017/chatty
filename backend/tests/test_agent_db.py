"""Tests for agents/db.py — agent CRUD operations."""

import uuid

from agents.db import (
    create_agent,
    delete_agent,
    get_agent,
    get_agent_by_slug,
    list_agents,
    update_agent,
)


class TestCreateAgent:
    def test_returns_dict_with_uuid_id(self, agent_db):
        agent = create_agent("Test Agent")
        assert isinstance(agent, dict)
        # Should be a valid UUID
        uuid.UUID(agent["id"])

    def test_slug_is_lowercase_hyphenated(self, agent_db):
        agent = create_agent("My Agent")
        assert agent["slug"] == "my-agent"

    def test_special_chars_stripped_from_slug(self, agent_db):
        agent = create_agent("Hello, World! @#$%")
        assert agent["slug"] == "hello-world"

    def test_duplicate_name_gets_uuid_suffix(self, agent_db):
        first = create_agent("Sales Bot")
        second = create_agent("Sales Bot")
        assert first["slug"] == "sales-bot"
        assert second["slug"].startswith("sales-bot-")
        assert second["slug"] != first["slug"]
        # Suffix should be a hex fragment
        suffix = second["slug"].removeprefix("sales-bot-")
        assert len(suffix) >= 6
        int(suffix, 16)


class TestGetAgent:
    def test_returns_correct_agent_by_id(self, agent_db):
        created = create_agent("Lookup Agent")
        fetched = get_agent(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["agent_name"] == "Lookup Agent"

    def test_nonexistent_id_returns_none(self, agent_db):
        assert get_agent("nonexistent-id") is None


class TestGetAgentBySlug:
    def test_returns_correct_agent_by_slug(self, agent_db):
        created = create_agent("Slug Lookup")
        fetched = get_agent_by_slug("slug-lookup")
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_nonexistent_slug_returns_none(self, agent_db):
        assert get_agent_by_slug("no-such-slug") is None


class TestListAgents:
    def test_empty_when_no_agents(self, agent_db):
        assert list_agents() == []

    def test_returns_all_agents(self, agent_db):
        create_agent("Agent A")
        create_agent("Agent B")
        agents = list_agents()
        assert len(agents) == 2
        names = {a["agent_name"] for a in agents}
        assert names == {"Agent A", "Agent B"}


class TestUpdateAgent:
    def test_changes_name(self, agent_db):
        agent = create_agent("Old Name")
        updated = update_agent(agent["id"], agent_name="New Name")
        assert updated["agent_name"] == "New Name"

    def test_name_change_updates_slug(self, agent_db):
        agent = create_agent("Before Rename")
        assert agent["slug"] == "before-rename"
        updated = update_agent(agent["id"], agent_name="After Rename")
        assert updated["slug"] == "after-rename"

    def test_ignores_unknown_fields(self, agent_db):
        agent = create_agent("Stable Agent")
        updated = update_agent(agent["id"], bogus_field="should be ignored")
        assert updated is not None
        assert updated["agent_name"] == "Stable Agent"
        assert "bogus_field" not in updated

    def test_google_accounts_stored_as_json_text(self, agent_db):
        agent = create_agent("Google Agent")
        updated = update_agent(
            agent["id"],
            google_accounts='{"gmail": ["acc1@example.com"]}',
        )
        assert updated["google_accounts"]["gmail"] == ["acc1@example.com"]


class TestDeleteAgent:
    def test_returns_true_and_agent_is_gone(self, agent_db):
        agent = create_agent("Doomed Agent")
        assert delete_agent(agent["id"]) is True
        assert get_agent(agent["id"]) is None

    def test_nonexistent_returns_false(self, agent_db):
        assert delete_agent("nonexistent-id") is False
