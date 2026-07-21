# Toy Repo Findings — /analyze-repo Reasoning Evaluation

Test artifact for the recommender's ability to localize bugs and detect
feedback/repo mismatch. This is the outcome of the work Crouser asked for
in the early-July meeting:

> *"Build simple toy repositories with intentional latency bugs (front-end
> and back-end variants separately) to test the recommender system."*
>
> *"Also test whether the system correctly flags when user-reported problems
> are inconsistent with the repo (e.g., complaining about a chatbot that
> doesn't exist)."*

## What was built

Five public test-fixture repos on `github.com/calvindeka/`:

| Repo | Purpose | Bug |
|---|---|---|
| [`toy-frontend-latency`](https://github.com/calvindeka/toy-frontend-latency) | Frontend localization | 3 compound bugs in `app.js`: no debounce, pointless deep-clone + busy loop per item, full innerHTML rewrite |
| [`toy-backend-latency`](https://github.com/calvindeka/toy-backend-latency) | Backend localization | 3 compound bugs in `server.js`: full table scan on every request, 10M-iter busy loop in per-record enrichment, per-record work multiplies |
| [`toy-mixed-latency`](https://github.com/calvindeka/toy-mixed-latency) | Discriminating localization | Frontend `app.js` is deliberately **clean**; backend `server.js` has the same slowness pattern as toy-backend-latency. The user-visible symptom is identical whether frontend or backend is at fault. |
| [`toy-wrong-domain`](https://github.com/calvindeka/toy-wrong-domain) | Feedback/repo consistency | No bugs, no AI, no chatbot, no LLM. Weather lookup on static data. Control fixture for the mismatch test. |
| [`toy-hallucination`](https://github.com/calvindeka/toy-hallucination) | Hallucination bug class (Crouser's follow-up ask) | 2 bugs in `app.js`: `findWrongAnswer` looks up pre-canned wrong answers instead of consulting a source of truth; fallback path returns random confident wrong-answer templates instead of expressing uncertainty. |

Each README documents the deliberate bug (or intentional absence of any
bug) and the "ground truth" the recommender should return.

## What was changed in the recommender

`/analyze-repo` was refactored to reason *before* pointing at code:

1. Fetch the repo's README (GitHub public API, no auth).
2. Extract a concept set from the README **intro** only (title + first
   content section). This avoids extracting concepts from later
   ground-truth or test-case sections that name features by saying they
   are *absent*.
3. Extract a concept set from the feedback.
4. If the feedback names a substantive domain concept (chatbot, weather,
   notes, orders, etc.) the repo doesn't cover, return
   `feedback_matches_repo: false` with an explicit `mismatch_reason` and
   **refuse to recommend candidates**.
5. Only when feedback plausibly matches, fetch code and localize.

Response schema now includes `app_summary`, `repo_concepts`,
`feedback_concepts`, `feedback_matches_repo`, and `mismatch_reason`
alongside the previous `candidates`/`verdict`/`tech_stack`/`summary`.

The change lives on branch `feature/analyze-repo-reasoning` off
`feature/hardening`.

## Results — the 5-toy × 3-5-variant matrix (18 cases total)

All tests run in DEV mode (no live LLM required — the reasoning layer
still fetches the real README from GitHub; only the code-localization
call is mocked with a name heuristic). Live-mode structure is identical
and delegates the classification to Claude. **Current pass rate: 18/18.**

The matrix is codified in [`run_toy_matrix.py`](./run_toy_matrix.py) —
run it any time to re-verify against the current state of the analyzer:

```bash
GITHUB_TOKEN=$(gh auth token) python flask_app.py     # in one terminal
python run_toy_matrix.py                              # in another
```

Each case declares its expected outcome (`matches` + top candidate, or
`mismatch` + expected concept in the reason). The script exits non-zero
on any regression, so this can be a CI gate later.

### Summary table

| Repo | Cases | Pass |
|---|---|---|
| `toy-frontend-latency` | 3 (3 match) | 3/3 ✅ |
| `toy-backend-latency` | 3 (3 match) | 3/3 ✅ |
| `toy-mixed-latency` | 3 (3 match — must localize to `server.js` not `app.js`) | 3/3 ✅ |
| `toy-wrong-domain` | 4 (3 mismatch + 1 legitimate weather match) | 4/4 ✅ |
| `toy-hallucination` | 5 (3 hallucination match + 2 non-hallucination mismatch) | 5/5 ✅ |
| **Total** | **18** | **18/18 ✅** |

### 1. Frontend feedback → frontend repo

```
repo:       toy-frontend-latency
feedback:   "the search box in this app feels really laggy when I type"
```

| Field | Result |
|---|---|
| `feedback_matches_repo` | ✅ `true` |
| `repo_concepts` | `[backend, frontend, latency, search]` |
| `feedback_concepts` | `[latency, search]` |
| `tech_stack` | `frontend` |
| `verdict` | `bug` |
| **Top candidate** | **`app.js`** ✅ (correct — bug lives here) |

### 2. Backend feedback → backend repo

```
repo:       toy-backend-latency
feedback:   "the orders API is taking hundreds of milliseconds to respond, way too slow"
```

| Field | Result |
|---|---|
| `feedback_matches_repo` | ✅ `true` |
| `repo_concepts` | `[backend, frontend, latency, orders]` |
| `feedback_concepts` | `[latency, orders]` |
| `tech_stack` | `mixed` (heuristic misfires on tech-stack — see limitations) |
| `verdict` | `bug` |
| **Top candidate** | **`server.js`** ✅ (correct — bug lives here) |

### 3. Latency feedback → mixed repo (discriminating localization)

```
repo:       toy-mixed-latency
feedback:   "loading my notes is really slow, feels sluggish"
```

The important test. The repo has both a frontend (`app.js`) and a backend
(`server.js`) but only the backend is actually broken. If the analyzer
just says "it might be the frontend or the backend," it fails the
discriminating test.

| Field | Result |
|---|---|
| `feedback_matches_repo` | ✅ `true` |
| `repo_concepts` | `[backend, frontend, latency, notes]` |
| `feedback_concepts` | `[latency]` |
| `tech_stack` | `mixed` |
| `verdict` | `bug` |
| **Top candidate** | **`server.js`** ✅ (correct — bug is backend-only) |
| Second candidate | `app.js` (over-broad — this file is actually clean) |

Not perfect — `app.js` shouldn't be in the candidate list at all — but the
**top choice is correct.** In DEV mode this comes from a naive name
heuristic that ranks server.js above app.js for backend-flavored feedback;
live mode should tighten this further because Claude can read the code and
see that `app.js` is well-written.

### 4. Chatbot feedback → weather repo (mismatch detection)

```
repo:       toy-wrong-domain     (a weather app, no AI, no chatbot)
feedback:   "the chatbot keeps giving wrong answers and hallucinating"
```

The exact scenario from Crouser's critique. The old analyzer would have
returned generic latency hotspots. The refactored analyzer:

| Field | Result |
|---|---|
| `feedback_matches_repo` | 🚫 **`false`** ✅ |
| `repo_concepts` | `[backend, database, frontend, latency, weather]` |
| `feedback_concepts` | `[chatbot, hallucination]` |
| `mismatch_reason` | *"Feedback references chatbot, hallucination, but the repo's README doesn't mention any of those. Repo appears to be about: weather."* |
| `candidates` | — (bailed out before touching code) |
| `verdict` | — (no verdict; no recommendation) |

Correct — the recommender refuses to guess and surfaces the specific
mismatch. This is the exact behavior asked for in the meeting.

### 5. Hallucination class — Crouser's explicit follow-up

Crouser named this in the meeting: *"After latency, expand to
hallucination — could use a model instructed to lie, or a
known-hallucination-prone model, to test detection."* Built as
`toy-hallucination`: a static chatbot ("FactBot") that answers factual
questions with pre-canned wrong answers and, on out-of-distribution
input, picks a random confident-sounding fake ("The answer is
definitely yes, most experts agree.").

Three hallucination-flavored feedbacks + two off-domain mismatch
feedbacks. All five pass.

| Feedback | Expected | Analyzer said |
|---|---|---|
| "the chatbot keeps giving wrong answers" | match → `app.js` | ✅ match → `app.js` |
| "the AI hallucinates and makes up facts" | match → `app.js` | ✅ match → `app.js` |
| "FactBot answers confidently but is often wrong" | match → `app.js` | ✅ match → `app.js` |
| "the orders API is really slow to respond" | **mismatch** (no API) | ✅ mismatch, reason mentions `orders` |
| "loading my notes takes forever" | **mismatch** (no notes) | ✅ mismatch, reason mentions `notes` |

Same mismatch-detection story as `toy-wrong-domain`, but now applied to
a repo that *does* have chatbot content — the analyzer needs to
distinguish "off-domain because no orders/notes" from "on-domain
because chatbot is present." Both directions work.

## Where the analyzer is still weak

Honestly:

1. **Tech-stack heuristic is over-broad.** For `toy-backend-latency` (a
   Node-only backend), it returned `tech_stack: mixed` because there's a
   `package.json` (which the heuristic reads as a frontend signal). Fine
   for demo, but the heuristic should be tightened.
2. **Second candidates on mixed-stack repos are noisy.** The top
   candidate is correct, but the list includes files that shouldn't
   plausibly be at fault. Live mode should reduce this because Claude
   can actually read the files and see whether they contain a bug.
3. **DEV mode can't detect negation.** A README that says "no chatbot"
   would still register "chatbot" as a concept — the intro-only
   truncation avoids the specific ground-truth-section case, but a
   short README that legitimately says "no chatbot" up front would trip
   this. Live mode handles it; DEV is documented.
4. **Only top-level files are considered.** Nothing in `src/`,
   `templates/`, `static/`, etc. Fine for the toys (small, flat) but
   real repos have nested structure.
5. **No handling of feedback that legitimately spans multiple areas.**
   E.g., feedback naming both frontend and backend issues. Currently
   forced into one bucket by the tech-stack heuristic.

## What this unlocks

- The recommender now honestly answers "does this feedback even match
  this repo?" — the check Crouser flagged as missing.
- The four toy repos give us a small but real regression harness. When
  the analyzer changes, we can re-run the 4×1 matrix and see whether
  the answers still hold.
- Live-mode structure is now identical to DEV-mode — plugging in a real
  API key routes the same reasoning through Claude instead of keyword
  heuristics.

## Suggested next steps

- **Fix the tech-stack heuristic** so `package.json` alone doesn't
  register as frontend.
- **Handle nested-repo files** (src/, app/, etc.) instead of only
  top-level. Right now the analyzer only looks at the root directory —
  fine for the toys but real repos have structure.
- **Live-mode Claude integration** — currently DEV mode uses keyword
  heuristics for concept extraction and file scoring. Wiring in an
  actual API key routes both through Claude, which should tighten
  concept extraction (Claude handles negation, my keyword matcher
  doesn't) and give richer candidate ranking (Claude can actually
  read the code, not just look at filenames).
- **Add the harness to CI** — `run_toy_matrix.py` already exits
  non-zero on any failure. Wiring it into GitHub Actions catches
  regressions on future analyzer changes for free.
- **Move toward the agentic vision Crouser sketched** — take the
  localization result and propose concrete tests to confirm the bug
  (e.g. "run the API 100 times, measure p95 latency"), then offer to
  run them.

## How to reproduce

```bash
cd /Users/calvindeka/EvalOps/evalops-metric-assistant
git checkout feature/analyze-repo-reasoning
source .venv/bin/activate

python -m pytest tests/                        # should show 76 passing

# start the server with an authenticated GitHub token (avoids the 60/hr
# unauth rate limit — gh CLI's token bumps this to 5000/hr)
GITHUB_TOKEN=$(gh auth token) python flask_app.py

# in another terminal:
python run_toy_matrix.py                       # should show 18/18 passed
```

Or for a single-case sanity check:

```bash
curl -s -X POST http://localhost:8080/analyze-repo \
  -H "Content-Type: application/json" \
  -d '{"feedback":"the chatbot keeps hallucinating","repo_url":"https://github.com/calvindeka/toy-wrong-domain"}' \
  | python3 -m json.tool
```

The `feedback_matches_repo: false` + `mismatch_reason` on that call is
the moment the refactor pays off.
