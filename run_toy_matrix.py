"""
Repeatable evaluation harness for /analyze-repo against the toy fixtures.

Sends a matrix of (repo × feedback → expected outcome) tuples through the
running metric-assistant server and prints a pass/fail table. Exit code
is non-zero if any case fails, so this can be wired into CI later.

The expected outcomes encode the "ground truth" documented in each toy's
README:
  - `matches`   : recommender should say feedback_matches_repo=true and
                  point at the file named in `top_candidate` as the first
                  candidate.
  - `mismatch`  : recommender should say feedback_matches_repo=false; a
                  concept named in `expect_mismatch_concept` must appear
                  in the mismatch_reason.

Run:
    python run_toy_matrix.py                    # runs against localhost:8080
    python run_toy_matrix.py --host X --port Y  # custom target
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


GITHUB_OWNER = "calvindeka"


@dataclass
class Case:
    repo:                   str
    feedback:               str
    expected:               str          # "matches" | "mismatch"
    top_candidate:          Optional[str] = None   # required if expected=matches
    expect_mismatch_concept: Optional[str] = None  # required if expected=mismatch


CASES: list[Case] = [
    # ── toy-frontend-latency: 3 feedback variants, all should match ──────────
    Case("toy-frontend-latency",
         "the search box is really laggy when I type",
         "matches", top_candidate="app.js"),
    Case("toy-frontend-latency",
         "typing in this app feels sluggish",
         "matches", top_candidate="app.js"),
    Case("toy-frontend-latency",
         "the ui is barely usable, everything lags",
         "matches", top_candidate="app.js"),

    # ── toy-backend-latency: 3 feedback variants, all should match ───────────
    Case("toy-backend-latency",
         "the orders API is really slow to respond",
         "matches", top_candidate="server.js"),
    Case("toy-backend-latency",
         "requests to /api/orders take forever",
         "matches", top_candidate="server.js"),
    Case("toy-backend-latency",
         "the backend is slow, hundreds of milliseconds per call",
         "matches", top_candidate="server.js"),

    # ── toy-mixed-latency: 3 feedback variants ───────────────────────────────
    # The discriminating test — bug is backend-only, so top candidate must be
    # server.js even though app.js also exists in the repo.
    Case("toy-mixed-latency",
         "loading my notes is really slow",
         "matches", top_candidate="server.js"),
    Case("toy-mixed-latency",
         "the notes app takes forever to load new notes",
         "matches", top_candidate="server.js"),
    Case("toy-mixed-latency",
         "when I open the notes list it's sluggish",
         "matches", top_candidate="server.js"),

    # ── toy-wrong-domain: 3 mismatch cases + 1 legitimate-match control ──────
    Case("toy-wrong-domain",
         "the chatbot keeps giving wrong answers",
         "mismatch", expect_mismatch_concept="chatbot"),
    Case("toy-wrong-domain",
         "the AI hallucinates when I ask factual questions",
         "mismatch", expect_mismatch_concept="hallucination"),
    Case("toy-wrong-domain",
         "the LLM's outputs are unreliable",
         "mismatch", expect_mismatch_concept="llm"),
    # Legitimate match: weather-shaped feedback on a weather app must NOT be
    # flagged. This is the guard against the analyzer just always saying
    # "false" on this repo.
    Case("toy-wrong-domain",
         "the temperature it shows for Tokyo looks wrong",
         "matches"),

    # ── toy-hallucination: 3 hallucination cases (should match) + 2 mismatch ─
    # The point of this fifth toy: the analyzer should localize hallucination
    # feedback to app.js (where the wrong-answer logic lives) AND correctly
    # refuse when feedback is about latency / backend / other bug classes.
    Case("toy-hallucination",
         "the chatbot keeps giving wrong answers",
         "matches", top_candidate="app.js"),
    Case("toy-hallucination",
         "the AI hallucinates and makes up facts",
         "matches", top_candidate="app.js"),
    Case("toy-hallucination",
         "FactBot answers confidently but is often wrong",
         "matches", top_candidate="app.js"),
    # Mismatch: this app has no backend / no API — feedback about those
    # should be flagged rather than force-fit into hallucination.
    Case("toy-hallucination",
         "the orders API is really slow to respond",
         "mismatch", expect_mismatch_concept="orders"),
    Case("toy-hallucination",
         "loading my notes takes forever",
         "mismatch", expect_mismatch_concept="notes"),
]


ANSI = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m",
        "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m"}


def _call(host: str, port: int, feedback: str, repo: str) -> dict:
    url = f"http://{host}:{port}/analyze-repo"
    body = json.dumps({
        "feedback": feedback,
        "repo_url": f"https://github.com/{GITHUB_OWNER}/{repo}",
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _evaluate(case: Case, response: dict) -> tuple[bool, str]:
    """Return (passed, note). Note explains a failure or optional observation."""
    matches = response.get("feedback_matches_repo")

    if case.expected == "matches":
        if not matches:
            return False, f"expected matches but got mismatch: {response.get('mismatch_reason')}"
        if case.top_candidate:
            cands = [c.get("path") for c in response.get("candidates", [])]
            if not cands:
                return False, "expected candidates, got none"
            if cands[0] != case.top_candidate:
                return False, (
                    f"top candidate was {cands[0]!r} but expected {case.top_candidate!r}"
                    f" (full list: {cands})"
                )
        return True, ""

    # expected == "mismatch"
    if matches:
        return False, "expected mismatch but analyzer said feedback matches repo"
    reason = (response.get("mismatch_reason") or "").lower()
    if case.expect_mismatch_concept and case.expect_mismatch_concept.lower() not in reason:
        return False, (
            f"mismatch flagged, but reason didn't mention {case.expect_mismatch_concept!r}: "
            f"{response.get('mismatch_reason')}"
        )
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the toy-repo evaluation matrix.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--quiet", action="store_true", help="Suppress per-case detail lines.")
    args = parser.parse_args()

    passed = 0
    failed = 0
    by_repo: dict[str, list[tuple[Case, bool, str]]] = {}

    for case in CASES:
        try:
            resp = _call(args.host, args.port, case.feedback, case.repo)
        except urllib.error.URLError as e:
            print(f"{ANSI['red']}ERROR{ANSI['reset']} contacting server: {e}", file=sys.stderr)
            return 2

        ok, note = _evaluate(case, resp)
        by_repo.setdefault(case.repo, []).append((case, ok, note))
        if ok:
            passed += 1
        else:
            failed += 1

    # Report
    print()
    for repo, rows in by_repo.items():
        repo_pass = sum(1 for _, ok, _ in rows if ok)
        repo_total = len(rows)
        color = ANSI["green"] if repo_pass == repo_total else ANSI["yellow"]
        print(f"{ANSI['bold']}{repo}{ANSI['reset']}  {color}{repo_pass}/{repo_total}{ANSI['reset']}")
        for case, ok, note in rows:
            icon = f"{ANSI['green']}✓{ANSI['reset']}" if ok else f"{ANSI['red']}✗{ANSI['reset']}"
            fb = case.feedback if len(case.feedback) <= 60 else case.feedback[:57] + "..."
            print(f"  {icon} [{case.expected:8s}] {fb!r}")
            if not ok:
                print(f"      {ANSI['red']}{note}{ANSI['reset']}")
        print()

    total = passed + failed
    tag = ANSI["green"] if failed == 0 else ANSI["red"]
    print(f"{tag}{passed}/{total} passed{ANSI['reset']}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
