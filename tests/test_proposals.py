"""Tests for the proposals module — validation + storage."""

from __future__ import annotations

import json

import pytest

import proposals


# ── add() validation ──────────────────────────────────────────────────────────

def test_add_validates_kind(tmp_log_paths):
    with pytest.raises(proposals.ProposalValidationError):
        proposals.add(
            source_flagged_id=None,
            kind="invalid",
            suggested_id="abc",
            suggested_label="Abc",
            suggestions_path=tmp_log_paths["suggestions"],
        )


def test_add_rejects_uppercase_id(tmp_log_paths):
    with pytest.raises(proposals.ProposalValidationError):
        proposals.add(
            source_flagged_id=None,
            kind="problem",
            suggested_id="BadId",
            suggested_label="Bad",
            suggestions_path=tmp_log_paths["suggestions"],
        )


def test_add_rejects_id_starting_with_digit(tmp_log_paths):
    with pytest.raises(proposals.ProposalValidationError):
        proposals.add(
            source_flagged_id=None,
            kind="problem",
            suggested_id="1bad",
            suggested_label="Bad",
            suggestions_path=tmp_log_paths["suggestions"],
        )


def test_add_rejects_empty_label(tmp_log_paths):
    with pytest.raises(proposals.ProposalValidationError):
        proposals.add(
            source_flagged_id=None,
            kind="problem",
            suggested_id="ok",
            suggested_label="   ",
            suggestions_path=tmp_log_paths["suggestions"],
        )


def test_add_rejects_invalid_tech_stack(tmp_log_paths):
    with pytest.raises(proposals.ProposalValidationError):
        proposals.add(
            source_flagged_id=None,
            kind="problem",
            suggested_id="ok",
            suggested_label="Label",
            tech_stack="quantum",  # not in VALID_TECH_STACKS
            suggestions_path=tmp_log_paths["suggestions"],
        )


def test_add_rejects_invalid_nature(tmp_log_paths):
    with pytest.raises(proposals.ProposalValidationError):
        proposals.add(
            source_flagged_id=None,
            kind="problem",
            suggested_id="ok",
            suggested_label="Label",
            nature="vibe",  # not in VALID_NATURES
            suggestions_path=tmp_log_paths["suggestions"],
        )


def test_add_accepts_empty_optional_enums(tmp_log_paths):
    pid = proposals.add(
        source_flagged_id=None,
        kind="problem",
        suggested_id="ok",
        suggested_label="Label",
        tech_stack="",
        nature=None,
        suggestions_path=tmp_log_paths["suggestions"],
    )
    written = proposals.read_all(tmp_log_paths["suggestions"])
    assert len(written) == 1
    assert written[0]["id"] == pid
    assert written[0]["tech_stack"] is None
    assert written[0]["nature"] is None


def test_add_writes_complete_record(tmp_log_paths):
    proposal_id = proposals.add(
        source_flagged_id="src-123",
        kind="problem",
        suggested_id="multi_turn_coherence",
        suggested_label="Multi-turn coherence loss",
        suggested_keywords="multi-turn, follow-up, conversation",
        rationale="Edge cases where context is lost",
        tech_stack="model",
        nature="bug",
        suggestions_path=tmp_log_paths["suggestions"],
    )
    entries = proposals.read_all(tmp_log_paths["suggestions"])
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == proposal_id
    assert e["source_flagged_id"] == "src-123"
    assert e["kind"] == "problem"
    assert e["suggested_id"] == "multi_turn_coherence"
    assert e["suggested_keywords"] == ["multi-turn", "follow-up", "conversation"]
    assert e["tech_stack"] == "model"
    assert e["nature"] == "bug"
    assert e["status"] == "open"


# ── keyword coercion ──────────────────────────────────────────────────────────

def test_coerce_keywords_handles_string_list_and_none():
    assert proposals._coerce_keywords(None) == []
    assert proposals._coerce_keywords("a, b , ,c") == ["a", "b", "c"]
    assert proposals._coerce_keywords(["x", "  y "]) == ["x", "y"]


# ── query helpers ─────────────────────────────────────────────────────────────

def test_open_proposals_filters_status(tmp_log_paths):
    proposals.add(
        source_flagged_id=None,
        kind="problem",
        suggested_id="alpha",
        suggested_label="Alpha",
        suggestions_path=tmp_log_paths["suggestions"],
    )
    # Manually write a merged entry directly to simulate one already applied.
    with tmp_log_paths["suggestions"].open("a") as f:
        f.write(json.dumps({
            "id": "merged-1",
            "kind": "problem",
            "suggested_id": "beta",
            "suggested_label": "Beta",
            "status": "merged",
        }) + "\n")

    opened = proposals.open_proposals(tmp_log_paths["suggestions"])
    assert len(opened) == 1
    assert opened[0]["suggested_id"] == "alpha"


def test_proposals_for_flagged_filters_by_source(tmp_log_paths):
    proposals.add(
        source_flagged_id="a",
        kind="problem",
        suggested_id="x",
        suggested_label="X",
        suggestions_path=tmp_log_paths["suggestions"],
    )
    proposals.add(
        source_flagged_id="b",
        kind="problem",
        suggested_id="y",
        suggested_label="Y",
        suggestions_path=tmp_log_paths["suggestions"],
    )
    matched = proposals.proposals_for_flagged("a", tmp_log_paths["suggestions"])
    assert len(matched) == 1
    assert matched[0]["suggested_id"] == "x"
