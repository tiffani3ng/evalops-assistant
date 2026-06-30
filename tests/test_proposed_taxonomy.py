"""Tests for proposed_taxonomy.apply_proposal — the merge-loop closer."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import proposals
import proposed_taxonomy


@pytest.fixture
def taxonomy_workspace(tmp_path, monkeypatch):
    """Copy the real tasks.json / problems.json into a temp dir and point
    apply_proposal at those copies. Suggestion log is also temp."""
    project_root = Path(__file__).resolve().parent.parent
    tasks_path = tmp_path / "tasks.json"
    problems_path = tmp_path / "problems.json"
    suggestions_path = tmp_path / "taxonomy_suggestions.jsonl"
    shutil.copy(project_root / "tasks.json", tasks_path)
    shutil.copy(project_root / "problems.json", problems_path)
    monkeypatch.setattr(proposals, "SUGGESTIONS_PATH", suggestions_path)
    return {
        "tasks":       tasks_path,
        "problems":    problems_path,
        "suggestions": suggestions_path,
    }


def _add_proposal(ws, **kwargs) -> str:
    defaults = dict(
        source_flagged_id=None,
        kind="problem",
        suggested_id="multi_turn_coherence",
        suggested_label="Multi-turn coherence loss",
        suggested_keywords=["multi-turn", "follow-up"],
        rationale="Edge cases not in current taxonomy.",
        tech_stack="model",
        nature="bug",
        suggestions_path=ws["suggestions"],
    )
    defaults.update(kwargs)
    return proposals.add(**defaults)


def test_apply_problem_proposal_adds_to_problems_json(taxonomy_workspace):
    ws = taxonomy_workspace
    pid = _add_proposal(ws)

    result = proposed_taxonomy.apply_proposal(
        pid,
        tasks_path=ws["tasks"],
        problems_path=ws["problems"],
        suggestions_path=ws["suggestions"],
    )
    assert result["applied"] is True
    assert result["kind"] == "problem"

    problems_after = json.loads(ws["problems"].read_text())
    new = next(p for p in problems_after if p["id"] == "multi_turn_coherence")
    assert new["label"] == "Multi-turn coherence loss"
    assert new["tech_stack"] == "model"
    assert new["nature"] == "bug"
    assert new["keywords"] == ["multi-turn", "follow-up"]


def test_apply_marks_proposal_as_merged(taxonomy_workspace):
    ws = taxonomy_workspace
    pid = _add_proposal(ws)
    proposed_taxonomy.apply_proposal(
        pid,
        tasks_path=ws["tasks"],
        problems_path=ws["problems"],
        suggestions_path=ws["suggestions"],
    )
    after = proposals.read_all(ws["suggestions"])
    target = next(p for p in after if p["id"] == pid)
    assert target["status"] == "merged"
    assert "merged_at" in target


def test_apply_dry_run_does_not_mutate(taxonomy_workspace):
    ws = taxonomy_workspace
    problems_before = ws["problems"].read_text()
    pid = _add_proposal(ws)
    sugg_before = ws["suggestions"].read_text()

    result = proposed_taxonomy.apply_proposal(
        pid,
        tasks_path=ws["tasks"],
        problems_path=ws["problems"],
        suggestions_path=ws["suggestions"],
        dry_run=True,
    )
    assert result.get("would_apply") is True
    assert ws["problems"].read_text() == problems_before
    assert ws["suggestions"].read_text() == sugg_before


def test_apply_unknown_proposal_raises(taxonomy_workspace):
    ws = taxonomy_workspace
    with pytest.raises(proposed_taxonomy.ApplyError):
        proposed_taxonomy.apply_proposal(
            "no-such-id",
            tasks_path=ws["tasks"],
            problems_path=ws["problems"],
            suggestions_path=ws["suggestions"],
        )


def test_apply_already_merged_raises(taxonomy_workspace):
    ws = taxonomy_workspace
    pid = _add_proposal(ws)
    proposed_taxonomy.apply_proposal(
        pid,
        tasks_path=ws["tasks"],
        problems_path=ws["problems"],
        suggestions_path=ws["suggestions"],
    )
    with pytest.raises(proposed_taxonomy.ApplyError):
        proposed_taxonomy.apply_proposal(
            pid,
            tasks_path=ws["tasks"],
            problems_path=ws["problems"],
            suggestions_path=ws["suggestions"],
        )


def test_apply_id_collision_raises(taxonomy_workspace):
    ws = taxonomy_workspace
    pid = _add_proposal(ws, suggested_id="latency")  # latency already exists
    with pytest.raises(proposed_taxonomy.ApplyError) as excinfo:
        proposed_taxonomy.apply_proposal(
            pid,
            tasks_path=ws["tasks"],
            problems_path=ws["problems"],
            suggestions_path=ws["suggestions"],
        )
    assert "already exists" in str(excinfo.value)


def test_apply_task_proposal_includes_description(taxonomy_workspace):
    ws = taxonomy_workspace
    pid = _add_proposal(
        ws,
        kind="task",
        suggested_id="agent_orchestration",
        suggested_label="Agent orchestration",
        rationale="Coordinating multiple LLM calls in a workflow.",
        tech_stack=None,
        nature=None,
    )
    proposed_taxonomy.apply_proposal(
        pid,
        tasks_path=ws["tasks"],
        problems_path=ws["problems"],
        suggestions_path=ws["suggestions"],
    )
    tasks_after = json.loads(ws["tasks"].read_text())
    new = next(t for t in tasks_after if t["id"] == "agent_orchestration")
    assert new["description"] == "Coordinating multiple LLM calls in a workflow."
    # Task entries should NOT carry tech_stack / nature
    assert "tech_stack" not in new
    assert "nature" not in new
