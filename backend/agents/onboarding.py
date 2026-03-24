"""
Chatty — Generic agent onboarding prompt.

Defines the default training topics for a new agent.
Each topic maps to a context file the agent will fill in during onboarding.
"""

DEFAULT_TRAINING_TOPICS = [
    {
        "name": "Introduction",
        "description": "Learn the user's name, role, and what they want from this agent",
        "filename": "profile.md",
    },
    {
        "name": "Goals & Priorities",
        "description": "Understand what the user is trying to accomplish and what matters most to them",
        "filename": "goals.md",
    },
    {
        "name": "Work & Projects",
        "description": "Learn about the user's current projects, responsibilities, and workflow",
        "filename": "work.md",
    },
    {
        "name": "Preferences & Style",
        "description": "Understand communication preferences, response style, and pet peeves",
        "filename": "preferences.md",
    },
    {
        "name": "Context & Background",
        "description": "Any other background information that would help this agent be more useful",
        "filename": "background.md",
    },
]


def get_onboarding_topics(custom_topics: list | None = None) -> list[dict]:
    """Return the training topics for an agent.

    If custom_topics is provided, those override the defaults.
    """
    if custom_topics:
        return custom_topics
    return DEFAULT_TRAINING_TOPICS


def get_onboarding_personality(agent_name: str) -> str:
    """Return the default personality intro for a new agent."""
    return (
        f"You are {agent_name}, a helpful personal AI assistant. "
        "You are friendly, proactive, and excellent at remembering details. "
        "You adapt your communication style to match the user's preferences. "
        "You save important information to your knowledge files so you can be more helpful over time."
    )
