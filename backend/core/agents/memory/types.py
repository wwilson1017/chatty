"""Memory type classification — 10 types with durability tiers.

Every daily-note entry or temporal fact can optionally carry a *memory type*
that indicates what kind of knowledge it represents.  The type influences how
long the consolidation pipeline retains the item and lets agents filter
searches by category.
"""

MEMORY_TYPES: set[str] = {
    "decision",
    "preference",
    "problem",
    "milestone",
    "insight",
    "person",
    "task",
    "idea",
    "reference",
    "someday-maybe",
}

# ---------------------------------------------------------------------------
# Durability tiers  (lower number = more durable)
# ---------------------------------------------------------------------------

TIER_1_ALWAYS_KEEP: set[str] = {"decision", "preference"}
TIER_2_KEEP_IF_RECENT: set[str] = {"person", "insight", "reference"}
TIER_3_KEEP_IF_RELEVANT: set[str] = {"milestone", "idea", "problem"}
TIER_4_DROP_WHEN_RESOLVED: set[str] = {"task", "someday-maybe"}

DURABILITY_TIERS: dict[str, int] = {}
for _t in TIER_1_ALWAYS_KEEP:
    DURABILITY_TIERS[_t] = 1
for _t in TIER_2_KEEP_IF_RECENT:
    DURABILITY_TIERS[_t] = 2
for _t in TIER_3_KEEP_IF_RELEVANT:
    DURABILITY_TIERS[_t] = 3
for _t in TIER_4_DROP_WHEN_RESOLVED:
    DURABILITY_TIERS[_t] = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_memory_type(memory_type: str | None) -> str | None:
    """Normalize and validate a memory type.  Returns *None* if invalid."""
    if not memory_type:
        return None
    normalized = memory_type.strip().lower()
    return normalized if normalized in MEMORY_TYPES else None


def type_tag(memory_type: str) -> str:
    """Return the inline tag format, e.g. ``[decision]``."""
    return f"[{memory_type}]"


def extract_type_tag(line: str) -> str | None:
    """Extract a memory-type tag from a line like ``[decision] Some text``.

    Returns the tag string (e.g. ``"decision"``) or *None*.
    """
    stripped = line.strip()
    if stripped.startswith("[") and "]" in stripped:
        tag = stripped[1 : stripped.index("]")].strip().lower()
        if tag in MEMORY_TYPES:
            return tag
    return None
