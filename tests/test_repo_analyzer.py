"""Tests for repo_analyzer — URL parsing, DEV-mode analysis, and the route."""

from __future__ import annotations

import pytest

import repo_analyzer


# ── URL parsing ───────────────────────────────────────────────────────────────

def test_parse_repo_url_accepts_canonical_form():
    assert repo_analyzer.parse_repo_url("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_repo_url_strips_dot_git():
    assert repo_analyzer.parse_repo_url("https://github.com/owner/repo.git") == ("owner", "repo")


def test_parse_repo_url_strips_trailing_slash():
    assert repo_analyzer.parse_repo_url("https://github.com/owner/repo/") == ("owner", "repo")


def test_parse_repo_url_handles_www():
    assert repo_analyzer.parse_repo_url("https://www.github.com/o/r") == ("o", "r")


def test_parse_repo_url_rejects_non_github():
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.parse_repo_url("https://gitlab.com/owner/repo")


def test_parse_repo_url_rejects_empty():
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.parse_repo_url("")


# ── Tech stack inference ──────────────────────────────────────────────────────

def test_infer_tech_stack_picks_backend_from_python():
    assert repo_analyzer._infer_tech_stack(["app.py", "requirements.txt"]) == "backend"


def test_infer_tech_stack_picks_frontend_from_tsx():
    assert repo_analyzer._infer_tech_stack(["Component.tsx", "package.json"]) == "frontend"


def test_infer_tech_stack_picks_mixed_when_both_present():
    assert repo_analyzer._infer_tech_stack(["app.py", "Component.tsx"]) == "mixed"


# ── DEV-mode analyze ──────────────────────────────────────────────────────────

def test_analyze_in_dev_mode_returns_mock(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    result = repo_analyzer.analyze(
        "the chatbot is slow", "https://github.com/example/demo"
    )
    assert result["mode"] == "dev"
    assert result["owner"] == "example"
    assert result["repo"] == "demo"
    assert result["candidates"]
    assert "verdict" in result
    assert "tech_stack" in result


def test_analyze_rejects_empty_feedback(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.analyze("   ", "https://github.com/o/r")


def test_analyze_rejects_bad_repo_url(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.analyze("some feedback", "https://example.com/owner/repo")


# ── /analyze-repo route ───────────────────────────────────────────────────────

def test_analyze_repo_route_happy_path(client):
    resp = client.post(
        "/analyze-repo",
        json={"feedback": "the chatbot is slow", "repo_url": "https://github.com/example/demo"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["owner"] == "example"
    assert body["repo"] == "demo"
    assert body["mode"] == "dev"
    assert body["candidates"]


def test_analyze_repo_route_missing_feedback(client):
    resp = client.post("/analyze-repo", json={"repo_url": "https://github.com/o/r"})
    assert resp.status_code == 400
    assert "feedback" in resp.get_json()["error"]


def test_analyze_repo_route_missing_url(client):
    resp = client.post("/analyze-repo", json={"feedback": "something"})
    assert resp.status_code == 400
    assert "repo_url" in resp.get_json()["error"]


def test_analyze_repo_route_bad_url(client):
    resp = client.post(
        "/analyze-repo",
        json={"feedback": "x", "repo_url": "not-a-real-url"},
    )
    assert resp.status_code == 400
