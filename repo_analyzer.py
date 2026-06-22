"""
Repo-aware classification — the stretch item from the team brief.

Given a piece of feedback *and* a GitHub repo URL, fetch a small slice of the
repo, ask the LLM where the issue likely originates, and return a verdict
plus a list of candidate files with rationales. Returns design/bug/design+bug
and an inferred tech_stack alongside the existing problem categorization.

Two execution paths:
- DEV=true (default during tests / demos): no network, no LLM. Returns a
  deterministic mock response so the endpoint can be exercised end-to-end
  without credentials.
- DEV=false: fetches the repo's root listing from the public GitHub API,
  downloads a handful of plausibly-relevant files, and asks Claude to point
  at the likely sources of the problem.

The real path is intentionally conservative — it touches only top-level
files, caps total bytes sent to the LLM, and bails fast on any error. The
goal is a useful first signal, not a full code-search tool.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional


GITHUB_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:/|\.git)?/?$"
)

MAX_FILES = 10
MAX_BYTES_PER_FILE = 5000
GITHUB_TIMEOUT = 8  # seconds


class RepoAnalysisError(ValueError):
    """Raised when the repo URL is malformed or the repo can't be inspected."""


def _is_dev_mode() -> bool:
    return os.getenv("DEV", "").lower() == "true"


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract owner/repo from a GitHub URL, or raise RepoAnalysisError."""
    if not url:
        raise RepoAnalysisError("repo_url is required")
    m = GITHUB_URL_PATTERN.match(url.strip())
    if not m:
        raise RepoAnalysisError(
            "repo_url must look like https://github.com/<owner>/<repo>"
        )
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_text(url: str, max_bytes: int) -> str:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
        return resp.read(max_bytes + 1).decode("utf-8", errors="replace")[:max_bytes]


def _list_repo_files(owner: str, repo: str) -> list[dict]:
    api = f"https://api.github.com/repos/{owner}/{repo}/contents"
    try:
        listing = _fetch_json(api)
    except urllib.error.HTTPError as e:
        raise RepoAnalysisError(f"GitHub returned {e.code} for {owner}/{repo}") from e
    except urllib.error.URLError as e:
        raise RepoAnalysisError(f"could not reach GitHub: {e.reason}") from e
    if not isinstance(listing, list):
        raise RepoAnalysisError("unexpected GitHub response shape")
    return [e for e in listing if e.get("type") == "file"][:MAX_FILES]


def _infer_tech_stack(file_names: list[str]) -> Optional[str]:
    names = " ".join(n.lower() for n in file_names)
    has_frontend = any(
        ext in names for ext in (".tsx", ".ts", ".jsx", "package.json", "vite", "next")
    )
    has_backend = any(
        marker in names
        for marker in ("flask", "fastapi", "django", "app.py", "main.py", "server.")
    )
    if has_frontend and has_backend:
        return "mixed"
    if has_frontend:
        return "frontend"
    if has_backend:
        return "backend"
    if any(n.endswith((".py", ".rb", ".go", ".java", ".rs")) for n in file_names):
        return "backend"
    return None


def _dev_analyze(feedback: str, owner: str, repo: str) -> dict:
    """Canned mock response so the endpoint is demo-able without network."""
    return {
        "owner": owner,
        "repo":  repo,
        "candidates": [
            {
                "path": "app.py",
                "rationale": "Entry-point file is the most likely source of a routing / latency issue.",
            },
            {
                "path": "templates/index.html",
                "rationale": "Frontend template responsible for the user-facing input.",
            },
        ],
        "verdict":     "design+bug",
        "tech_stack":  "mixed",
        "summary":     f"[DEV] Hypothetical analysis for feedback: {feedback!r}",
        "mode":        "dev",
    }


def analyze(feedback: str, repo_url: str) -> dict:
    """Top-level entry point. Validates input, picks the execution path."""
    if not feedback or not feedback.strip():
        raise RepoAnalysisError("feedback is required")
    owner, repo = parse_repo_url(repo_url)

    if _is_dev_mode():
        return _dev_analyze(feedback, owner, repo)

    files = _list_repo_files(owner, repo)
    if not files:
        raise RepoAnalysisError("no files visible at repo root — is this a valid public repo?")
    file_snippets: list[dict] = []
    for f in files:
        if not f.get("download_url"):
            continue
        try:
            text = _fetch_text(f["download_url"], MAX_BYTES_PER_FILE)
        except (urllib.error.URLError, UnicodeDecodeError):
            continue
        file_snippets.append({"path": f["name"], "content": text})
        if len(file_snippets) >= MAX_FILES:
            break

    tech_stack = _infer_tech_stack([s["path"] for s in file_snippets])

    # Real-mode LLM call is left as a small skeleton — wires up once an
    # Anthropic / OpenAI key is configured. Importing inside the function so
    # this module can be unit-tested without the SDK installed.
    try:
        from llm_utils import client as llm_client  # noqa: WPS433
    except Exception as e:  # llm_utils raises if no API key in non-DEV mode
        raise RepoAnalysisError(f"LLM client not available: {e}") from e

    if llm_client is None:
        raise RepoAnalysisError("LLM client is None in non-DEV mode")

    file_listing = "\n\n".join(
        f"### {s['path']}\n```\n{s['content']}\n```" for s in file_snippets
    )
    prompt = (
        f"A user reported this feedback about an AI tool:\n\n"
        f"  {feedback!r}\n\n"
        f"Here are the top-level files in the repo:\n\n{file_listing}\n\n"
        "Return JSON with this shape:\n"
        '{ "candidates": [{"path": "...", "rationale": "..."}], '
        '"verdict": "design"|"bug"|"design+bug", "summary": "..." }'
    )
    response = llm_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip().strip("`").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()
    parsed = json.loads(raw)
    parsed.setdefault("tech_stack", tech_stack)
    parsed["owner"] = owner
    parsed["repo"] = repo
    parsed["mode"] = "live"
    return parsed
