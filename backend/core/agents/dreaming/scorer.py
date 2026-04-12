"""Dreaming scorer — ranks context files by usage signals.

Uses weighted signals (write recency, write frequency, mention frequency,
load rate, file age) to determine which files are most valuable to an agent.
"""

import math
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import tracker

logger = logging.getLogger(__name__)

# Signal weights (sum to 1.0)
WEIGHT_WRITE_RECENCY = 0.30
WEIGHT_WRITE_FREQUENCY = 0.25
WEIGHT_MENTION_FREQUENCY = 0.20
WEIGHT_LOAD_RATE = 0.15
WEIGHT_FILE_AGE = 0.10

# Thresholds
ARCHIVE_THRESHOLD = 0.1   # Below this = dormant
STALE_THRESHOLD = 0.4     # Below this = stale
HALF_LIFE_DAYS = 14.0     # Recency decay


def score_context_files(agent: str, data_dir: Path, days: int = 30) -> list[dict]:
    """Score all context files for an agent by usage signals.

    Returns list of {filename, score, classification, signals} sorted by score DESC.
    Classification: 'active' (>0.4), 'stale' (0.1-0.4), 'dormant' (<0.1).
    """
    usage_data = tracker.get_file_scores(agent, days=days)
    usage_by_file = {d["filename"]: d for d in usage_data}

    now = datetime.now(timezone.utc)
    results = []

    for f in sorted(data_dir.glob("*.md")):
        if f.name.startswith("_") and f.name != "_training-progress.md":
            continue  # Skip already-archived files

        usage = usage_by_file.get(f.name, {})
        writes = usage.get("write", 0) + usage.get("append", 0)
        mentions = usage.get("mentioned_in_response", 0)
        loaded = usage.get("loaded", 0)
        truncated = usage.get("truncated", 0)

        # Signal 1: Write recency (exponential decay)
        file_mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        days_since_write = (now - file_mtime).total_seconds() / 86400
        lam = math.log(2) / HALF_LIFE_DAYS
        write_recency = math.exp(-lam * days_since_write)

        # Signal 2: Write frequency
        write_freq = math.log1p(writes) / math.log1p(10)

        # Signal 3: Mention frequency
        mention_freq = math.log1p(mentions) / math.log1p(10)

        # Signal 4: Load rate (1.0 if never truncated)
        total_loads = loaded + truncated
        load_rate = loaded / total_loads if total_loads > 0 else 1.0

        # Signal 5: File age (newer = small boost)
        file_ctime = datetime.fromtimestamp(f.stat().st_ctime, tz=timezone.utc)
        days_old = (now - file_ctime).total_seconds() / 86400
        file_age_score = 1.0 - min(days_old / 90, 1.0)

        # Weighted score
        score = (
            WEIGHT_WRITE_RECENCY * write_recency
            + WEIGHT_WRITE_FREQUENCY * write_freq
            + WEIGHT_MENTION_FREQUENCY * mention_freq
            + WEIGHT_LOAD_RATE * load_rate
            + WEIGHT_FILE_AGE * file_age_score
        )

        # Classify
        if score >= STALE_THRESHOLD:
            classification = "active"
        elif score >= ARCHIVE_THRESHOLD:
            classification = "stale"
        else:
            classification = "dormant"

        results.append({
            "filename": f.name,
            "score": round(score, 3),
            "classification": classification,
            "signals": {
                "write_recency": round(write_recency, 3),
                "write_frequency": round(write_freq, 3),
                "mention_frequency": round(mention_freq, 3),
                "load_rate": round(load_rate, 3),
                "file_age": round(file_age_score, 3),
            },
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
