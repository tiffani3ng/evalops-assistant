"""Tests for the flagging module — pure detection logic + log handling."""

from __future__ import annotations

import json

import pytest

import flagging


# ── evaluate() — heuristic detection ──────────────────────────────────────────

def test_healthy_classification_is_not_flagged():
    decision = flagging.evaluate(
        feedback="The chatbot is too slow",
        classification={
            "task_labels": ["factual_qa"],
            "problem_labels": ["latency"],
            "summary": "Latency complaint — responses are too slow.",
        },
        metric_ids=["response_time", "task_completion_time", "efficiency_cost"],
    )
    assert decision.flagged is False
    assert decision.reasons == []
    assert decision.severity is None


def test_empty_labels_flag_with_high_severity():
    decision = flagging.evaluate(
        feedback="something weird",
        classification={"task_labels": [], "problem_labels": [], "summary": "Could not classify."},
        metric_ids=[],
    )
    assert decision.flagged is True
    assert "no_task_or_problem_identified" in decision.reasons
    assert decision.severity == "high"


def test_only_task_missing_is_low_severity():
    decision = flagging.evaluate(
        feedback="hard to use",
        classification={
            "task_labels": [],
            "problem_labels": ["poor_usability"],
            "summary": "Usability issue with the interface design.",
        },
        metric_ids=["sus_score", "nasa_tlx", "task_completion_time"],
    )
    assert decision.flagged is True
    assert decision.reasons == ["no_task_identified"]
    assert decision.severity == "low"


def test_only_problem_missing_is_low_severity():
    decision = flagging.evaluate(
        feedback="searching through documents",
        classification={
            "task_labels": ["ad_hoc_info_gathering"],
            "problem_labels": [],
            "summary": "User is searching documents but no problem signal yet.",
        },
        metric_ids=["precision", "recall", "ndcg"],
    )
    assert decision.flagged is True
    assert decision.reasons == ["no_problem_identified"]
    assert decision.severity == "low"


def test_thin_metric_bundle_flags():
    decision = flagging.evaluate(
        feedback="something",
        classification={
            "task_labels": ["factual_qa"],
            "problem_labels": ["latency"],
            "summary": "Latency complaint detected.",
        },
        metric_ids=["response_time"],
    )
    assert decision.flagged is True
    assert "tiny_metric_bundle" in decision.reasons


def test_short_summary_flags():
    decision = flagging.evaluate(
        feedback="something",
        classification={
            "task_labels": ["factual_qa"],
            "problem_labels": ["latency"],
            "summary": "slow",  # less than 12 chars
        },
        metric_ids=["response_time", "task_completion_time", "efficiency_cost"],
    )
    assert decision.flagged is True
    assert "low_detail_summary" in decision.reasons


def test_low_confidence_signal_escalates_to_high():
    decision = flagging.evaluate(
        feedback="something nuanced",
        classification={
            "task_labels": ["factual_qa"],
            "problem_labels": ["low_trust"],
            "summary": "User mistrusts the answer for unclear reasons.",
        },
        metric_ids=["trust_score", "hallucination_rate", "source_click_rate"],
        claude_confidence="low",
    )
    assert decision.flagged is True
    assert "model_self_reported_low_confidence" in decision.reasons
    assert decision.severity == "high"


def test_two_reasons_escalate_to_medium():
    decision = flagging.evaluate(
        feedback="something",
        classification={
            "task_labels": ["factual_qa"],
            "problem_labels": [],
            "summary": "?",
        },
        metric_ids=["a"],
    )
    assert "no_problem_identified" in decision.reasons
    assert "tiny_metric_bundle" in decision.reasons
    assert "low_detail_summary" in decision.reasons
    assert decision.severity == "medium"


# ── log + read_log ────────────────────────────────────────────────────────────

def test_log_writes_a_jsonl_line_and_returns_id(tmp_log_paths):
    decision = flagging.evaluate(
        feedback="x",
        classification={"task_labels": [], "problem_labels": [], "summary": "y"},
        metric_ids=[],
    )
    entry_id = flagging.log(
        feedback="x",
        model_context=None,
        stakeholder_context=None,
        classification={"task_labels": [], "problem_labels": [], "summary": "y"},
        metric_ids=[],
        decision=decision,
        log_path=tmp_log_paths["log"],
    )
    assert entry_id
    assert tmp_log_paths["log"].exists()
    line = tmp_log_paths["log"].read_text().strip()
    obj = json.loads(line)
    assert obj["id"] == entry_id
    assert obj["feedback"] == "x"
    assert obj["flag"]["flagged"] is True


def test_read_log_returns_empty_when_missing(tmp_log_paths):
    # tmp_log_paths.log file does not exist yet
    assert flagging.read_log(tmp_log_paths["log"]) == []


def test_read_log_tolerates_malformed_lines(tmp_log_paths):
    tmp_log_paths["log"].write_text('{"id": "ok", "feedback": "valid"}\n{not json}\n')
    entries = flagging.read_log(tmp_log_paths["log"])
    assert len(entries) == 1
    assert entries[0]["id"] == "ok"


# ── mark_reviewed / find_entry ────────────────────────────────────────────────

def test_mark_reviewed_is_idempotent(tmp_log_paths, sample_flagged_entry):
    # tmp_log_paths is auto-injected through the fixture chain
    first = flagging.mark_reviewed(sample_flagged_entry, reviewed_path=tmp_log_paths["reviewed"])
    second = flagging.mark_reviewed(sample_flagged_entry, reviewed_path=tmp_log_paths["reviewed"])
    assert first is True
    assert second is False
    assert sample_flagged_entry in flagging.read_reviewed_ids(tmp_log_paths["reviewed"])


def test_mark_reviewed_rejects_empty_id(tmp_log_paths):
    assert flagging.mark_reviewed("", reviewed_path=tmp_log_paths["reviewed"]) is False


def test_find_entry_returns_none_for_unknown(tmp_log_paths):
    assert flagging.find_entry("no-such-id", log_path=tmp_log_paths["log"]) is None


def test_find_entry_locates_existing(tmp_log_paths, sample_flagged_entry):
    entry = flagging.find_entry(sample_flagged_entry, log_path=tmp_log_paths["log"])
    assert entry is not None
    assert entry["id"] == sample_flagged_entry
