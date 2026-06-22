"""
Flag-for-review logic for feedback that doesn't fit the existing taxonomy.

When the recommender silently falls back to "closest match" on feedback that
the 7-task / 8-problem taxonomy can't cover well, those edge cases are lost.
This module detects weak classifications heuristically, records them with the
reason, and exposes a queue developers can review to decide whether the
taxonomy needs to grow.

Pure logic — no LLM dependency. Designed so a Claude-returned confidence
score can later be added as an extra signal without changing the public API.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


LOG_PATH = Path(__file__).parent / "flagged_feedback.jsonl"
REVIEWED_PATH = Path(__file__).parent / "reviewed_entries.json"

# Heuristic thresholds (tuned conservatively — better to under-flag than to
# spam the review queue).
MIN_METRIC_BUNDLE = 2
MIN_SUMMARY_CHARS = 12


@dataclass
class FlagDecision:
    flagged: bool
    reasons: list[str]
    severity: Optional[str]  # "high" | "medium" | "low" | None

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(
    feedback: str,
    classification: dict,
    metric_ids: list[str],
    claude_confidence: Optional[str] = None,
) -> FlagDecision:
    """Decide whether a single feedback submission should be flagged for review.

    classification is the dict returned by classify_feedback in llm_utils.py:
      {task_labels: [...], problem_labels: [...], summary: "..."}
    metric_ids is the list of metric ids in the final recommended bundle.
    claude_confidence is a future hook — pass "low"|"medium"|"high" once the
    classification prompt is updated to return one.
    """
    task_labels = classification.get("task_labels") or []
    problem_labels = classification.get("problem_labels") or []
    summary = (classification.get("summary") or "").strip()

    reasons: list[str] = []

    if not task_labels and not problem_labels:
        reasons.append("no_task_or_problem_identified")
    else:
        if not task_labels:
            reasons.append("no_task_identified")
        if not problem_labels:
            reasons.append("no_problem_identified")

    if len(metric_ids) < MIN_METRIC_BUNDLE:
        reasons.append("tiny_metric_bundle")

    if len(summary) < MIN_SUMMARY_CHARS:
        reasons.append("low_detail_summary")

    if claude_confidence and claude_confidence.lower() == "low":
        reasons.append("model_self_reported_low_confidence")

    severity = _severity_for(reasons)
    return FlagDecision(
        flagged=bool(reasons),
        reasons=reasons,
        severity=severity,
    )


def _severity_for(reasons: list[str]) -> Optional[str]:
    if not reasons:
        return None
    if "no_task_or_problem_identified" in reasons:
        return "high"
    if "model_self_reported_low_confidence" in reasons:
        return "high"
    if len(reasons) >= 2:
        return "medium"
    return "low"


def log(
    feedback: str,
    model_context: Optional[str],
    stakeholder_context: Optional[str],
    classification: dict,
    metric_ids: list[str],
    decision: FlagDecision,
    log_path: Path = LOG_PATH,
) -> str:
    """Append one JSON line to the flagged-feedback log. Returns the entry id.

    The log is JSONL so it can be tailed, grep'd, sliced, and never grows a
    parse cliff if a single line is malformed. Each entry gets a stable
    uuid id so review and proposal actions can target it.
    """
    entry_id = str(uuid.uuid4())
    entry = {
        "id": entry_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feedback": feedback,
        "model_context": model_context,
        "stakeholder_context": stakeholder_context,
        "classification": classification,
        "metric_ids": metric_ids,
        "flag": decision.to_dict(),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry_id


def read_log(log_path: Path = LOG_PATH) -> list[dict]:
    """Read the JSONL log; tolerate malformed lines."""
    if not log_path.exists():
        return []
    entries = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def read_reviewed_ids(reviewed_path: Path = REVIEWED_PATH) -> set[str]:
    """Return the set of entry ids that have been marked as reviewed."""
    if not reviewed_path.exists():
        return set()
    try:
        return set(json.loads(reviewed_path.read_text()))
    except (json.JSONDecodeError, ValueError):
        return set()


def mark_reviewed(entry_id: str, reviewed_path: Path = REVIEWED_PATH) -> bool:
    """Add an entry id to the reviewed set. Returns True if it was newly added.

    Idempotent — calling on an already-reviewed id is a no-op that returns False.
    """
    if not entry_id:
        return False
    reviewed = read_reviewed_ids(reviewed_path)
    if entry_id in reviewed:
        return False
    reviewed.add(entry_id)
    reviewed_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed_path.write_text(json.dumps(sorted(reviewed), indent=2) + "\n")
    return True


def find_entry(entry_id: str, log_path: Path = LOG_PATH) -> Optional[dict]:
    """Locate a single log entry by id."""
    if not entry_id:
        return None
    for entry in read_log(log_path):
        if entry.get("id") == entry_id:
            return entry
    return None
