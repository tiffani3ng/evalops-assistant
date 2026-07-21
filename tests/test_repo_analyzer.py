"""Tests for repo_analyzer — URL parsing, reasoning primitives, DEV-mode
analyze() with a mocked README/file fetch, and the /analyze-repo route."""

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


# ── Reasoning primitives ──────────────────────────────────────────────────────

def test_extract_concepts_finds_multiple_matches():
    concepts = repo_analyzer.extract_concepts(
        "A weather app with a chatbot. Runs on the backend."
    )
    assert "weather" in concepts
    assert "chatbot" in concepts
    assert "backend" in concepts


def test_extract_concepts_returns_empty_on_empty_input():
    assert repo_analyzer.extract_concepts("") == set()


def test_extract_concepts_case_insensitive():
    concepts = repo_analyzer.extract_concepts("WEATHER LOOKUP")
    assert "weather" in concepts


def test_check_feedback_matches_flags_chatbot_in_weather_repo():
    repo_concepts = {"weather", "search"}
    feedback_concepts = {"chatbot", "hallucination"}
    matches, reason = repo_analyzer.check_feedback_matches(feedback_concepts, repo_concepts)
    assert matches is False
    assert "chatbot" in reason
    assert "hallucination" in reason


def test_check_feedback_matches_allows_generic_latency():
    repo_concepts = {"chatbot", "llm"}
    feedback_concepts = {"latency"}   # latency is non-domain, doesn't trigger mismatch
    matches, reason = repo_analyzer.check_feedback_matches(feedback_concepts, repo_concepts)
    assert matches is True
    assert reason is None


def test_check_feedback_matches_allows_domain_overlap():
    repo_concepts = {"chatbot", "llm", "backend"}
    feedback_concepts = {"chatbot", "latency"}
    matches, reason = repo_analyzer.check_feedback_matches(feedback_concepts, repo_concepts)
    assert matches is True


def test_check_feedback_matches_flags_partial_mismatch():
    repo_concepts = {"weather"}
    feedback_concepts = {"weather", "chatbot"}   # one match, one hard mismatch
    matches, reason = repo_analyzer.check_feedback_matches(feedback_concepts, repo_concepts)
    assert matches is False
    assert "chatbot" in reason


# ── DEV-mode analyze with mocked README + file listing ────────────────────────

class _FakeFile:
    def __init__(self, name: str, dl: str = "https://example.com/x"):
        self.name = name
        self.dl = dl

    def as_dict(self) -> dict:
        return {"name": self.name, "type": "file", "download_url": self.dl}


def _install_fetch_mocks(monkeypatch, readme: str, files: list[dict], file_contents: dict | None = None):
    """Replace the module's GitHub-touching functions with in-memory fakes."""
    file_contents = file_contents or {}

    def fake_fetch_readme(owner, repo):
        return readme

    def fake_list_files(owner, repo):
        return files

    def fake_fetch_text(url, max_bytes):
        return file_contents.get(url, "// no content mocked")

    monkeypatch.setattr(repo_analyzer, "fetch_readme", fake_fetch_readme)
    monkeypatch.setattr(repo_analyzer, "_list_repo_files", fake_list_files)
    monkeypatch.setattr(repo_analyzer, "_fetch_text", fake_fetch_text)


def test_analyze_dev_returns_full_response_shape(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    _install_fetch_mocks(
        monkeypatch,
        readme="Order lookup API for testing backend latency.",
        files=[
            {"name": "server.js", "type": "file", "download_url": "https://x/server.js"},
            {"name": "README.md", "type": "file", "download_url": "https://x/README.md"},
        ],
    )
    result = repo_analyzer.analyze(
        "the orders API is really slow", "https://github.com/example/demo"
    )
    for k in ("owner", "repo", "mode", "app_summary", "repo_concepts",
              "feedback_concepts", "feedback_matches_repo", "mismatch_reason",
              "candidates", "verdict", "tech_stack", "summary"):
        assert k in result, f"missing key: {k}"
    assert result["mode"] == "dev"
    assert result["feedback_matches_repo"] is True
    assert result["mismatch_reason"] is None


def test_analyze_dev_flags_chatbot_feedback_on_weather_repo(monkeypatch):
    """The critical case from the meeting: feedback references something the
    repo demonstrably doesn't have. Must return matches=False and refuse to
    recommend candidates."""
    monkeypatch.setenv("DEV", "true")
    _install_fetch_mocks(
        monkeypatch,
        readme="A simple weather lookup app for demonstrating city forecasts.",
        files=[
            {"name": "app.js", "type": "file", "download_url": "https://x/app.js"},
        ],
    )
    result = repo_analyzer.analyze(
        "the chatbot keeps giving wrong answers",
        "https://github.com/example/weather",
    )
    assert result["feedback_matches_repo"] is False
    assert "chatbot" in result["mismatch_reason"]
    # No candidates, no verdict — bailed out before touching code
    assert "candidates" not in result
    assert "verdict" not in result


def test_analyze_dev_backend_latency_localizes(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    _install_fetch_mocks(
        monkeypatch,
        readme="Order lookup API. Backend-only.",
        files=[
            {"name": "server.js", "type": "file", "download_url": "https://x/server.js"},
            {"name": "README.md", "type": "file", "download_url": "https://x/README.md"},
            {"name": "package.json", "type": "file", "download_url": "https://x/package.json"},
        ],
    )
    result = repo_analyzer.analyze(
        "the api is slow, backend performance issue",
        "https://github.com/example/orders",
    )
    assert result["feedback_matches_repo"] is True
    # server.js should be the top candidate
    top_paths = [c["path"] for c in result["candidates"]]
    assert "server.js" in top_paths


def test_analyze_dev_raises_when_readme_missing(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    monkeypatch.setattr(repo_analyzer, "fetch_readme", lambda owner, repo: None)
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.analyze("some feedback", "https://github.com/o/r")


def test_analyze_rejects_empty_feedback(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.analyze("   ", "https://github.com/o/r")


def test_analyze_rejects_bad_repo_url(monkeypatch):
    monkeypatch.setenv("DEV", "true")
    with pytest.raises(repo_analyzer.RepoAnalysisError):
        repo_analyzer.analyze("some feedback", "https://example.com/owner/repo")


# ── /analyze-repo route ───────────────────────────────────────────────────────

def test_analyze_repo_route_happy_path(client, monkeypatch):
    _install_fetch_mocks(
        monkeypatch,
        readme="A book finder app with a search box. Frontend-only.",
        files=[
            {"name": "app.js", "type": "file", "download_url": "https://x/app.js"},
            {"name": "index.html", "type": "file", "download_url": "https://x/index.html"},
        ],
    )
    resp = client.post(
        "/analyze-repo",
        json={"feedback": "the search feels laggy",
              "repo_url": "https://github.com/example/books"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["owner"] == "example"
    assert body["repo"] == "books"
    assert body["mode"] == "dev"
    assert body["feedback_matches_repo"] is True
    assert body["candidates"]


def test_analyze_repo_route_flags_mismatch(client, monkeypatch):
    # NOTE: the README deliberately does not use the word "chatbot" at all.
    # Naive keyword extraction can't detect negation ("no chatbot" would
    # still be flagged as a chatbot concept), so the fair test is a README
    # that stays entirely on-topic. See repo_analyzer.extract_concepts.
    _install_fetch_mocks(
        monkeypatch,
        readme="A simple weather lookup tool. Enter a city, get the forecast.",
        files=[
            {"name": "app.js", "type": "file", "download_url": "https://x/app.js"},
        ],
    )
    resp = client.post(
        "/analyze-repo",
        json={"feedback": "the chatbot is broken",
              "repo_url": "https://github.com/example/weather"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["feedback_matches_repo"] is False
    assert "chatbot" in body["mismatch_reason"]


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
