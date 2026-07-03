"""In-memory feedback store for thumbs up/down and correction loops."""

from __future__ import annotations

import threading
import time
from collections import deque

_LOCK = threading.RLock()
_FEEDBACK = deque(maxlen=5000)
_NEXT_ID = 1


def add_feedback(entry: dict) -> int:
    global _NEXT_ID
    with _LOCK:
        feedback_id = _NEXT_ID
        _NEXT_ID += 1
        saved = dict(entry)
        saved["feedback_id"] = feedback_id
        saved["created_at"] = time.time()
        _FEEDBACK.append(saved)
        return feedback_id


def summary() -> dict:
    with _LOCK:
        rows = list(_FEEDBACK)

    total = len(rows)
    thumbs_up = sum(1 for row in rows if row.get("rating") == "up")
    thumbs_down = sum(1 for row in rows if row.get("rating") == "down")
    corrections = [row for row in rows if str(row.get("correction") or "").strip()]

    return {
        "total_feedback": total,
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "positive_rate": round((thumbs_up / total), 4) if total else 0.0,
        "corrections_count": len(corrections),
        "recent_corrections": [
            {
                "feedback_id": row.get("feedback_id"),
                "question": row.get("question"),
                "correction": row.get("correction"),
            }
            for row in corrections[-10:]
        ],
    }


def reset() -> None:
    global _NEXT_ID
    with _LOCK:
        _FEEDBACK.clear()
        _NEXT_ID = 1