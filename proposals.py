"""
Taxonomy update proposals — the developer-side of the flag-for-review loop.

A flagged entry tells you *something* didn't fit the taxonomy. A proposal
captures the developer's reaction: "here's the new task / problem category
I'd add to handle this kind of feedback." Proposals are stored in an
append-only JSONL log; they are not auto-merged into the live taxonomy.
A human applies them with `proposed_taxonomy.py` after review.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


SUGGESTIONS_PATH = Path(__file__).parent / "taxonomy_suggestions.jsonl"

VALID_KINDS = ("task", "problem")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ProposalValidationError(ValueError):
    """Raised when a proposal payload fails validation before write."""


def _coerce_keywords(raw: object) -> list[str]:
    """Accept a list, a comma-separated string, or None; return a clean list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [k.strip() for k in raw.split(",")]
    elif isinstance(raw, Iterable):
        items = [str(k).strip() for k in raw]
    else:
        return []
    return [k for k in items if k]


def add(
    *,
    source_flagged_id: Optional[str],
    kind: str,
    suggested_id: str,
    suggested_label: str,
    suggested_keywords: object = None,
    rationale: Optional[str] = None,
    suggestions_path: Path = SUGGESTIONS_PATH,
) -> str:
    """Validate and append a proposal. Returns the new proposal id."""
    kind = (kind or "").strip().lower()
    if kind not in VALID_KINDS:
        raise ProposalValidationError(f"kind must be one of {VALID_KINDS}, got {kind!r}")

    suggested_id = (suggested_id or "").strip().lower()
    if not ID_PATTERN.match(suggested_id):
        raise ProposalValidationError(
            "suggested_id must be lowercase, start with a letter, and contain only "
            "letters, digits, and underscores"
        )

    suggested_label = (suggested_label or "").strip()
    if not suggested_label:
        raise ProposalValidationError("suggested_label is required")

    keywords = _coerce_keywords(suggested_keywords)
    rationale = (rationale or "").strip() or None

    proposal_id = str(uuid.uuid4())
    proposal = {
        "id": proposal_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_flagged_id": source_flagged_id or None,
        "kind": kind,
        "suggested_id": suggested_id,
        "suggested_label": suggested_label,
        "suggested_keywords": keywords,
        "rationale": rationale,
        "status": "open",
    }
    suggestions_path.parent.mkdir(parents=True, exist_ok=True)
    with suggestions_path.open("a") as f:
        f.write(json.dumps(proposal) + "\n")
    return proposal_id


def read_all(suggestions_path: Path = SUGGESTIONS_PATH) -> list[dict]:
    """Read every proposal; tolerate malformed lines."""
    if not suggestions_path.exists():
        return []
    out = []
    with suggestions_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def open_proposals(suggestions_path: Path = SUGGESTIONS_PATH) -> list[dict]:
    """Proposals not yet marked merged or rejected."""
    return [p for p in read_all(suggestions_path) if p.get("status", "open") == "open"]


def proposals_for_flagged(
    flagged_id: str, suggestions_path: Path = SUGGESTIONS_PATH
) -> list[dict]:
    """All proposals that originated from a given flagged entry."""
    if not flagged_id:
        return []
    return [p for p in read_all(suggestions_path) if p.get("source_flagged_id") == flagged_id]
