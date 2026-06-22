"""
Populate the flagged-feedback log with realistic fixture entries.

Useful for demos, local development, and verifying the review queue UI
without depending on live LLM calls. Idempotent — clears the existing
log before writing.

Run:
    python seed_flagged.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import flagging


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


FIXTURES = [
    # High severity — taxonomy completely failed to match
    {
        "feedback": "The AI keeps drifting off-topic when I ask follow-up questions in the same conversation.",
        "model_context": "RAG chatbot with multi-turn history",
        "stakeholder_context": "Customer success analysts",
        "classification": {"task_labels": [], "problem_labels": [], "summary": "Multi-turn coherence issue not captured by current categories."},
        "metric_ids": [],
        "hours_ago": 48,
    },
    # High severity — model self-reported low confidence (future hook)
    {
        "feedback": "It works fine until I paste a long document, then the answers get worse.",
        "model_context": "Document Q&A tool with 32k context window",
        "stakeholder_context": "Intelligence analysts",
        "classification": {"task_labels": ["sensemaking"], "problem_labels": [], "summary": "Long-context degradation."},
        "metric_ids": ["task_completion_time"],
        "claude_confidence": "low",
        "hours_ago": 22,
    },
    # Medium severity — partial classification
    {
        "feedback": "Sometimes I get a great answer, sometimes a bad one, for what feels like the same question.",
        "model_context": "Internal knowledge assistant",
        "stakeholder_context": "Support team",
        "classification": {"task_labels": ["factual_qa"], "problem_labels": [], "summary": "Inconsistent answer quality."},
        "metric_ids": ["accuracy", "trust_score"],
        "hours_ago": 11,
    },
    # Medium severity — too-thin metric bundle, short summary
    {
        "feedback": "The model is too cautious, refuses things it shouldn't.",
        "model_context": None,
        "stakeholder_context": "Product team",
        "classification": {"task_labels": [], "problem_labels": ["poor_usability"], "summary": "Over-refusal."},
        "metric_ids": ["sus_score"],
        "hours_ago": 6,
    },
    # Low severity — thin metric bundle, mostly classified
    {
        "feedback": "I wish it would tell me when it's not sure instead of guessing.",
        "model_context": "Question-answering assistant",
        "stakeholder_context": "End users",
        "classification": {"task_labels": ["factual_qa"], "problem_labels": ["low_trust"], "summary": "Lack of explicit uncertainty signalling."},
        "metric_ids": ["trust_score"],
        "hours_ago": 1.5,
    },
]


def seed(log_path=flagging.LOG_PATH) -> int:
    """Write fixture entries to the log. Returns the count written.

    Also clears review state and proposal logs so the demo starts clean.
    """
    # Clear existing log + review state + proposal log so seeding is deterministic.
    for p in (log_path, flagging.REVIEWED_PATH,
              Path(__file__).parent / "taxonomy_suggestions.jsonl"):
        if p.exists():
            p.unlink()

    count = 0
    for fixture in FIXTURES:
        decision = flagging.evaluate(
            feedback=fixture["feedback"],
            classification=fixture["classification"],
            metric_ids=fixture["metric_ids"],
            claude_confidence=fixture.get("claude_confidence"),
        )
        if not decision.flagged:
            # Sanity check — every fixture is intentionally a flaggable case.
            print(f"warning: fixture not flagged by evaluator: {fixture['feedback'][:50]}")
            continue
        flagging.log(
            feedback=fixture["feedback"],
            model_context=fixture["model_context"],
            stakeholder_context=fixture["stakeholder_context"],
            classification=fixture["classification"],
            metric_ids=fixture["metric_ids"],
            decision=decision,
            log_path=log_path,
        )
        count += 1

    return count


if __name__ == "__main__":
    written = seed()
    print(f"Seeded {written} flagged-feedback entries to {flagging.LOG_PATH}")
