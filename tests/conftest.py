"""
Shared pytest fixtures. Sets DEV=true before any test imports flask_app or
llm_utils so the LLM clients never have to authenticate during tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Make DEV mode the default for the whole test session — must run before
# flask_app or llm_utils is imported anywhere.
os.environ["DEV"] = "true"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder-not-used-in-dev")

# Make the project root importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_log_paths(tmp_path, monkeypatch):
    """Redirect every persistent log to a temp directory for hermetic tests."""
    import flagging
    import proposals

    log_path = tmp_path / "flagged_feedback.jsonl"
    reviewed_path = tmp_path / "reviewed_entries.json"
    suggestions_path = tmp_path / "taxonomy_suggestions.jsonl"

    monkeypatch.setattr(flagging, "LOG_PATH", log_path)
    monkeypatch.setattr(flagging, "REVIEWED_PATH", reviewed_path)
    monkeypatch.setattr(proposals, "SUGGESTIONS_PATH", suggestions_path)

    return {
        "log": log_path,
        "reviewed": reviewed_path,
        "suggestions": suggestions_path,
    }


@pytest.fixture
def app(tmp_log_paths):
    """Flask test client with all logs pointing at a temp dir."""
    import flask_app

    flask_app.app.config["TESTING"] = True
    return flask_app.app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sample_flagged_entry(tmp_log_paths):
    """Write a single flagged entry to the log and return its id."""
    import flagging

    decision = flagging.evaluate(
        feedback="Some weird out-of-vocab feedback",
        classification={"task_labels": [], "problem_labels": [], "summary": "short"},
        metric_ids=[],
    )
    assert decision.flagged
    entry_id = flagging.log(
        feedback="Some weird out-of-vocab feedback",
        model_context=None,
        stakeholder_context=None,
        classification={"task_labels": [], "problem_labels": [], "summary": "short"},
        metric_ids=[],
        decision=decision,
        log_path=tmp_log_paths["log"],
    )
    return entry_id
