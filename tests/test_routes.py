"""Integration tests for Flask routes — uses DEV mode so no real LLM calls."""

from __future__ import annotations

import json


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_sources_returns_200(client):
    resp = client.get("/sources")
    assert resp.status_code == 200


def test_analyze_requires_feedback(client):
    resp = client.post("/analyze", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body


def test_analyze_classifies_slow_as_latency(client):
    resp = client.post("/analyze", json={"feedback": "The chatbot is too slow"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "latency" in body["classification"]["problem_labels"]
    cats = body["classification"]["problem_categorizations"]
    assert any(c["tech_stack"] == "backend" and c["nature"] == "bug" for c in cats)
    # Healthy classification should not be flagged.
    assert body["flag"]["flagged"] is False


def test_analyze_flags_out_of_vocab_feedback(client):
    resp = client.post(
        "/analyze",
        json={"feedback": "Nothing matches this weird unfamiliar phrase pattern"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["flag"]["flagged"] is True
    assert body["flag"]["severity"] == "high"


def test_flagged_view_renders(client):
    resp = client.get("/flagged")
    assert resp.status_code == 200
    assert b"Flagged for Review" in resp.data


def test_flagged_json_returns_count(client):
    resp = client.get("/flagged.json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "count" in body
    assert "entries" in body
    assert "reviewed_ids" in body


def test_review_action_marks_reviewed(client):
    # Submit a flaggable analyze first so an entry exists.
    client.post("/analyze", json={"feedback": "completely out-of-vocabulary text"})
    entries = client.get("/flagged.json").get_json()["entries"]
    assert entries, "expected at least one flagged entry"
    entry_id = entries[-1]["id"]

    resp = client.post(f"/flagged/{entry_id}/review", follow_redirects=False)
    assert resp.status_code == 302

    after = client.get("/flagged.json").get_json()
    assert entry_id in after["reviewed_ids"]


def test_review_unknown_id_404s(client):
    resp = client.post("/flagged/nonexistent-id/review")
    assert resp.status_code == 404


def test_propose_action_stores_proposal(client):
    client.post("/analyze", json={"feedback": "another out of vocabulary thing"})
    entries = client.get("/flagged.json").get_json()["entries"]
    entry_id = entries[-1]["id"]

    resp = client.post(
        f"/flagged/{entry_id}/propose",
        data={
            "kind": "problem",
            "suggested_id": "new_category",
            "suggested_label": "A new category",
            "suggested_keywords": "alpha, beta",
            "rationale": "covers a gap",
            "tech_stack": "model",
            "nature": "bug",
        },
    )
    assert resp.status_code == 302

    proposals_body = client.get("/proposals.json").get_json()
    assert proposals_body["proposals"]
    p = proposals_body["proposals"][0]
    assert p["suggested_id"] == "new_category"
    assert p["tech_stack"] == "model"
    assert p["nature"] == "bug"
    assert p["source_flagged_id"] == entry_id


def test_propose_with_bad_id_returns_400(client):
    client.post("/analyze", json={"feedback": "another out of vocab thing"})
    entries = client.get("/flagged.json").get_json()["entries"]
    entry_id = entries[-1]["id"]
    resp = client.post(
        f"/flagged/{entry_id}/propose",
        data={
            "kind": "problem",
            "suggested_id": "BadCapitalId",
            "suggested_label": "Bad",
        },
    )
    assert resp.status_code == 400


def test_propose_unknown_id_404s(client):
    resp = client.post(
        "/flagged/nonexistent/propose",
        data={"kind": "problem", "suggested_id": "ok", "suggested_label": "Ok"},
    )
    assert resp.status_code == 404
