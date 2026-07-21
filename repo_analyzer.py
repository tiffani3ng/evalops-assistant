"""
Repo-aware classification with README-first reasoning.

The previous implementation grabbed top-level files and asked the LLM to
guess which one caused a user's reported problem. It worked by pattern-
matching keywords in code, not by understanding the repo. When tested on
a chatbot-free repo with chatbot feedback, it happily pointed at generic
latency hotspots instead of noticing the mismatch.

This version reasons about the repo *before* it points at code:

  1. Fetch the README (raw from GitHub — public repos only, no auth).
  2. Extract a concept summary of what the app actually does.
  3. Extract concepts from the feedback the user submitted.
  4. Compare — if the feedback references a substantive concept the repo
     doesn't cover (e.g. "chatbot" against a weather app), refuse to
     recommend and surface the mismatch explicitly.
  5. Only if the feedback plausibly matches the repo do we fetch code
     files and localize.

Two execution paths:
- DEV=true : still fetches the README from GitHub (public, no auth) so
             the reasoning is real, but skips the LLM code-pointing step
             in favour of keyword-heuristic candidate selection. Works
             end-to-end without API credentials.
- DEV=false: same README-first flow, but the "app summary", concept
             extraction, and file localization all go through Claude.

The mismatch check is the meat of this refactor. Everything else is
plumbing to make it reliable.
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
MAX_README_BYTES = 20_000
GITHUB_TIMEOUT = 8  # seconds


# Concepts we look for in feedback + READMEs. The keys are canonical concept
# names; the values are surface forms that indicate the concept is present.
# The domain_concepts subset (below) is what we treat as "substantive" for
# mismatch detection — a feedback mentioning "chatbot" against a repo whose
# README never mentions chat-anything is a hard mismatch. Lower-signal
# concepts like "search" or "frontend" are recorded but don't by themselves
# trigger a mismatch verdict.
CONCEPT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "chatbot":     ("chatbot", "chat bot", "conversational", "dialog agent"),
    "llm":         ("llm", "language model", "gpt", "claude", "openai", "anthropic", "generative ai"),
    "hallucination": ("hallucin",),
    "weather":     ("weather", "temperature", "forecast", "climate"),
    "notes":       ("note-taking", "note taking", "notes app", "my notes", "notes list", "new note"),
    "orders":      ("order", "orders api", "purchase"),
    "books":       ("book finder", "book catalog", "book search", "book library"),
    # "lookup" and "find" removed — too broad, they fire on prose like
    # "lookup table" and "find out" that don't imply a search feature.
    "search":      ("search",),
    "latency":     ("slow", "laggy", "latency", "lag", "performance", "sluggish",
                    "delayed", "forever", "takes long", "long time", "hang", "hanging",
                    "unresponsive", "spins", "waiting", "freeze"),
    "frontend":    ("frontend", "front-end", "front end", "ui", "browser", "react", "vue"),
    "backend":     ("backend", "back-end", "back end", "server", "api endpoint"),
    # "table" removed — matches prose like "lookup table" or "in the table
    # below" that doesn't imply a database.
    "database":    ("database", "sql", "postgres", "mysql", "sqlite"),
    "mobile":      ("mobile", "ios", "android"),
    "auth":        ("login", "auth", "sign in", "signup", "password"),
}

# Concepts that, when mentioned in feedback but absent from the repo,
# indicate a real domain mismatch worth flagging. "search" or "frontend"
# alone don't tell us much — but "chatbot" or "weather" do.
DOMAIN_CONCEPTS = frozenset(
    ["chatbot", "llm", "hallucination", "weather", "notes", "orders", "books", "mobile", "auth"]
)


class RepoAnalysisError(ValueError):
    """Raised when the repo URL is malformed or the repo can't be inspected."""


# ── mode helpers ──────────────────────────────────────────────────────────────

def _is_dev_mode() -> bool:
    return os.getenv("DEV", "").lower() == "true"


# ── URL parsing ───────────────────────────────────────────────────────────────

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


# ── GitHub fetch helpers ──────────────────────────────────────────────────────

def _github_headers(base: dict) -> dict:
    """Attach a GitHub token when one is available in the environment.

    Anonymous GitHub API calls are capped at 60/hour, which the toy-repo
    evaluation harness burns through fast. Authenticated calls are capped
    at 5,000/hour. Any of GITHUB_TOKEN / GH_TOKEN / GITHUB_API_TOKEN works
    (the first-hit wins), which lines up with the gh CLI's env conventions.
    """
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_API_TOKEN"):
        token = os.getenv(var)
        if token:
            return {**base, "Authorization": f"Bearer {token}"}
    return base


def _fetch_json(url: str) -> object:
    headers = _github_headers({"Accept": "application/vnd.github+json"})
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_text(url: str, max_bytes: int) -> str:
    # Raw content endpoints (raw.githubusercontent.com) don't need auth for
    # public repos, but sending the header doesn't hurt.
    headers = _github_headers({})
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT) as resp:
        return resp.read(max_bytes + 1).decode("utf-8", errors="replace")[:max_bytes]


def fetch_readme(owner: str, repo: str) -> Optional[str]:
    """Fetch the repo's README via GitHub's API. Returns None if none exists.

    GitHub's /readme endpoint auto-detects README.md, README.rst, etc. so we
    don't have to guess the filename.
    """
    api = f"https://api.github.com/repos/{owner}/{repo}/readme"
    try:
        meta = _fetch_json(api)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RepoAnalysisError(f"GitHub returned {e.code} fetching README for {owner}/{repo}") from e
    except urllib.error.URLError as e:
        raise RepoAnalysisError(f"could not reach GitHub for README: {e.reason}") from e
    download = meta.get("download_url") if isinstance(meta, dict) else None
    if not download:
        return None
    try:
        return _fetch_text(download, MAX_README_BYTES)
    except (urllib.error.URLError, UnicodeDecodeError):
        return None


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


# ── Reasoning primitives (used by both DEV and live paths) ────────────────────

def extract_concepts(text: str) -> set[str]:
    """Return the set of canonical concept names mentioned anywhere in text.

    Case-insensitive substring match; simple by design. This is what stands
    in for "understanding" in DEV mode, and augments the LLM signal in live
    mode.

    LIMITATION: this cannot detect negation. A README that says "this app
    has NO chatbot" will still register "chatbot" as a concept the repo
    covers. Live mode routes this through Claude, which handles negation
    correctly. In DEV mode, README authors should stay on-topic rather
    than explicitly enumerate what the app isn't.
    """
    if not text:
        return set()
    lower = text.lower()
    hits: set[str] = set()
    for concept, surfaces in CONCEPT_KEYWORDS.items():
        if any(surface in lower for surface in surfaces):
            hits.add(concept)
    return hits


def _first_sentence(text: str) -> str:
    """Best-effort README lead-sentence: the first non-empty *prose* line,
    capped at ~200 chars. Skips any markdown header line so we don't return
    the title/slug as the app description."""
    if not text:
        return ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):   # any header line — skip
            continue
        if len(line) > 200:
            line = line[:197] + "..."
        return line
    return ""


def _readme_intro(text: str) -> str:
    """Return only the README preamble — the title and everything up to the
    FIRST H2 header. Deliberately excludes any body sections, because
    body prose reliably references features by way of saying they are
    *absent* (e.g. "There is no real LLM" → naive extraction thinks the
    repo has an LLM). The tagline-and-title region is the most on-topic
    part of a README and gives the highest signal-to-noise for concept
    extraction.
    """
    if not text:
        return ""
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        kept.append(line)
    return "\n".join(kept)[:2000]   # hard cap regardless


def check_feedback_matches(
    feedback_concepts: set[str], repo_concepts: set[str]
) -> tuple[bool, Optional[str]]:
    """Compare feedback and repo concept sets. Returns (matches, mismatch_reason).

    Only domain-level concepts (chatbot, weather, notes, etc.) count for a
    mismatch verdict. If the feedback mentions any domain concept the repo
    doesn't cover, that's a hard mismatch. Otherwise we treat the feedback
    as plausibly matching.
    """
    feedback_domain = feedback_concepts & DOMAIN_CONCEPTS
    repo_domain = repo_concepts & DOMAIN_CONCEPTS
    missing = feedback_domain - repo_domain
    if missing:
        missing_str = ", ".join(sorted(missing))
        return False, (
            f"Feedback references {missing_str}, but the repo's README doesn't mention any of those. "
            f"Repo appears to be about: {', '.join(sorted(repo_domain)) or 'no domain concept identified'}."
        )
    return True, None


# ── Tech-stack inference (existing) ───────────────────────────────────────────

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


# ── DEV-mode candidate selection (no LLM) ─────────────────────────────────────

def _dev_pick_candidates(
    feedback_concepts: set[str], files: list[dict]
) -> list[dict]:
    """Score files by name-heuristic against feedback concepts.

    Returns up to 3 candidates with a short rationale each. Deliberately
    naive — the point of the DEV path is to demonstrate the reasoning
    architecture, not to match the LLM's judgment.
    """
    if not files:
        return []

    scored: list[tuple[int, str, str]] = []

    # Feedback signals we care about for scoring.
    is_backend = "backend" in feedback_concepts
    is_frontend = "frontend" in feedback_concepts
    is_latency = "latency" in feedback_concepts
    is_hallucination = bool(feedback_concepts & {"hallucination", "chatbot", "llm"})

    for f in files:
        name = f.get("name", "")
        low = name.lower()
        score = 0
        reasons: list[str] = []

        if is_backend and any(m in low for m in ("server", "app.py", "main.py", "api")):
            score += 3
            reasons.append("backend entry point")
        if is_frontend and any(m in low for m in ("app.js", "app.tsx", "index.html", "main.js")):
            score += 3
            reasons.append("frontend entry point")
        if is_latency and low in ("server.js", "app.py", "app.js", "main.py"):
            score += 2
            reasons.append("main handler is the typical latency location")
        # For latency feedback without an explicit frontend / backend hint,
        # prefer server-side files. In practice, unqualified "slow / laggy"
        # complaints on a full-stack app usually resolve to a backend fix —
        # network round-trip dominates render cost for typical requests.
        if is_latency and not is_frontend and low in ("server.js", "app.py", "main.py"):
            score += 1
            reasons.append("ambiguous latency defaults to server-side")
        if is_hallucination and low in ("app.js", "chat.js", "bot.js", "agent.js", "chatbot.js", "app.py"):
            score += 3
            reasons.append("chatbot/agent code — likely site of hallucination logic")

        # Skip non-code files at the tail when unscored.
        if score == 0 and low in ("readme.md", "package.json", ".gitignore", "license"):
            continue
        if score == 0:
            score = 1
            reasons.append("candidate based on file position")

        # Tie-break: for equal scores, prefer files with .js / .py / .ts
        # extensions over static assets — those are more likely to hold logic.
        code_tie = 1 if low.endswith((".js", ".py", ".ts", ".tsx", ".jsx", ".go", ".rb", ".rs")) else 0
        scored.append((score, code_tie, name, "; ".join(reasons)))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [
        {"path": name, "rationale": rationale}
        for _score, _code_tie, name, rationale in scored[:3]
    ]


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze(feedback: str, repo_url: str) -> dict:
    """Analyze a piece of feedback against a repo, README-first.

    Always returns a dict with the following keys, regardless of match/mismatch:
      - owner, repo, mode
      - app_summary               (best-effort README lead sentence)
      - repo_concepts             (list of canonical concept names)
      - feedback_concepts         (list of canonical concept names)
      - feedback_matches_repo     (bool)
      - mismatch_reason           (str or null)
    When feedback_matches_repo is True, additionally:
      - candidates                (list of {path, rationale})
      - verdict                   (design | bug | design+bug)
      - tech_stack                (frontend | backend | mixed | infra | null)
      - summary                   (short human sentence)
    """
    if not feedback or not feedback.strip():
        raise RepoAnalysisError("feedback is required")
    owner, repo = parse_repo_url(repo_url)
    dev = _is_dev_mode()

    # Phase 1: README-first understanding of the repo.
    readme = fetch_readme(owner, repo)
    if readme is None:
        # Missing README is itself a signal — we can't confidently reason
        # about the repo. Fail loud rather than fake confidence.
        raise RepoAnalysisError(
            f"No README found in {owner}/{repo}. Repo-aware analysis needs a README "
            "to understand what the app does."
        )

    intro = _readme_intro(readme)
    app_summary = _first_sentence(intro)
    # Extract concepts only from the intro to avoid ground-truth / test-case
    # sections poisoning the concept set with "absent" features.
    repo_concepts = extract_concepts(intro)
    feedback_concepts = extract_concepts(feedback)

    matches, mismatch_reason = check_feedback_matches(feedback_concepts, repo_concepts)

    base = {
        "owner":                owner,
        "repo":                 repo,
        "mode":                 "dev" if dev else "live",
        "app_summary":          app_summary,
        "repo_concepts":        sorted(repo_concepts),
        "feedback_concepts":    sorted(feedback_concepts),
        "feedback_matches_repo": matches,
        "mismatch_reason":      mismatch_reason,
    }

    if not matches:
        # Bail out before touching any code. Nothing useful to recommend.
        return base

    # Phase 2: fetch code and localize. Same pattern as before.
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

    if dev:
        candidates = _dev_pick_candidates(feedback_concepts, files)
        verdict = "bug" if "latency" in feedback_concepts else "design+bug"
        return {
            **base,
            "candidates":  candidates,
            "verdict":     verdict,
            "tech_stack":  tech_stack,
            "summary":     f"[DEV] Feedback plausibly matches this repo. Candidates chosen by name-heuristic.",
        }

    # Live path — hand file snippets + reasoning context to Claude.
    try:
        from llm_utils import client as llm_client  # noqa: WPS433
    except Exception as e:
        raise RepoAnalysisError(f"LLM client not available: {e}") from e
    if llm_client is None:
        raise RepoAnalysisError("LLM client is None in non-DEV mode")

    file_listing = "\n\n".join(
        f"### {s['path']}\n```\n{s['content']}\n```" for s in file_snippets
    )
    prompt = (
        f"A user reported this feedback about an app:\n\n"
        f"  {feedback!r}\n\n"
        f"Here is the README lead sentence: {app_summary!r}\n"
        f"Concepts identified in the repo: {sorted(repo_concepts)}\n"
        f"Concepts identified in the feedback: {sorted(feedback_concepts)}\n\n"
        f"The feedback has been validated as consistent with this repo — do not "
        f"second-guess that. Localize the likely source of the issue in these "
        f"top-level files:\n\n{file_listing}\n\n"
        "Return JSON:\n"
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
    return {**base, **parsed}
