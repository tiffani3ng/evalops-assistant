# Flagged Feedback — Review Queue for Edge Cases

## What this addresses

Feedback that doesn't fit the existing 7-task / 8-problem taxonomy is currently
silently mapped to the closest match. Edge cases get lost. Over time, this
makes the recommender look generic — many different inputs produce nearly
identical output cards — because the underlying taxonomy isn't growing in
response to the variety of feedback the system actually sees.

This change adds a **review queue**. When a classification is weak (empty
labels, thin metric bundle, low summary detail, model-reported low
confidence), the feedback is logged with the specific reason for review.
Developers can then periodically inspect the queue and decide whether the
taxonomy should grow, the mappings refined, or the prompt rewritten.

Maps to the team brief: *"Add a way to integrate user feedback into the list
of problems / Flag potential new issues for developer review."*

## Architecture

Pure-Python, additive — does not modify any existing logic. Tiffanie's
existing flow (classify → recommend → return) is untouched; the flagging
step runs after recommendation and writes to its own log file.

```
flagging.py            Pure detection logic + log read/append.
                       No LLM dependency. Has a hook for a future
                       Claude-returned confidence score.

flask_app.py           Calls flagging.evaluate() after the recommendation
                       step, logs flagged items, and includes the flag
                       decision in the /analyze response.

                       New routes:
                         GET /flagged      → HTML review queue
                         GET /flagged.json → JSON dump

templates/flagged.html Review queue UI. Color-coded by severity.

seed_flagged.py        Populates the log with realistic fixtures.
                       Use to demo without depending on live LLM calls.

flagged_report.py      Generates a markdown review report grouped by
                       flag reason. Run periodically (or in cron).

flagged_feedback.jsonl Append-only JSONL log of flagged entries.
                       Gitignored — runtime artifact.

flagged_report.md      Generated markdown report. Gitignored — regenerate
                       with `python flagged_report.py`.
```

## Heuristics that trigger a flag

Tuned conservatively — better to under-flag than to spam the queue.

| Reason | Severity contribution | Meaning |
|---|---|---|
| `no_task_or_problem_identified` | high | Neither category matched. Strong taxonomy-gap signal. |
| `no_task_identified` | low | Problem matched but no task did. Possible new task type. |
| `no_problem_identified` | low | Task matched but no problem did. Possible new problem type. |
| `tiny_metric_bundle` | low | Recommender returned fewer than 2 metrics. |
| `low_detail_summary` | low | Classification summary was very short. |
| `model_self_reported_low_confidence` | high | Future hook — fires when the LLM prompt is updated to return a confidence score. |

Severity rolls up: any "high" reason → high. Two or more reasons → medium.
One "low" reason → low.

## Demo flow (under 3 minutes)

1. `python seed_flagged.py` — populates the log with 5 realistic fixtures.
2. `python flagged_report.py` — writes `flagged_report.md`. Open it.
3. Start the Flask app: `python flask_app.py`
4. Open `http://127.0.0.1:8080/flagged` — color-coded review queue.
5. Open `http://127.0.0.1:8080/flagged.json` — JSON dump for programmatic access.

## How a developer would use this in practice

- After each round of pilot feedback, run `python flagged_report.py` to get
  the markdown review.
- High-severity clusters (e.g., five items all flagged
  `no_task_or_problem_identified`) → discuss whether to expand the taxonomy.
- Patterns of `no_problem_identified` for a specific task → maybe a new
  problem category is needed for that task domain.
- `tiny_metric_bundle` clustered around a particular task → the mapping
  table for that task is under-specified.

## Closing the loop — review and propose

The flag-for-review pass catches edge cases; the next step is letting a
developer act on them. Each open entry in `/flagged` now exposes two
actions:

- **Mark as reviewed** (`POST /flagged/<id>/review`) — moves the entry
  out of the active queue. Reviewed ids live in `reviewed_entries.json`;
  the original log is never mutated. Toggle "Show reviewed too" on the
  page to see them.
- **Propose taxonomy update** (`POST /flagged/<id>/propose`) — opens an
  inline form (kind, suggested id, label, keywords, rationale) that writes
  to `taxonomy_suggestions.jsonl`. Proposals start with status `open`.

The proposal log is consumed by:

```
python proposed_taxonomy.py
```

…which reads `tasks.json`, `problems.json`, and the proposal log, then
emits a markdown report grouping open proposals by suggested id (so
duplicate ids surface as "N proposals converged" — a strong signal) and
flagging collisions with existing entries. Nothing is auto-merged; a
human applies accepted proposals by editing the JSON taxonomies and
manually flipping the proposal status to `merged`.

That closes the loop from item #2 ("flag for developer review") into
item #1 ("integrate user feedback into the list of problems") of the
team brief.

## Problem categorization — tech stack and nature

Each entry in `problems.json` now carries two extra fields:

- `tech_stack`: one of `frontend`, `backend`, `model`, `infra`, `mixed`
- `nature`: one of `bug`, `design`, `design+bug`

The `/analyze` response includes `classification.problem_categorizations`,
a list of `{id, label, tech_stack, nature}` for each problem the recommender
matched. The output UI shows these as a "Tech stack: … / Nature: …" chip row
below the existing task/problem chips, color-coded by category.

The propose form on `/flagged` now captures `tech_stack` and `nature` so new
problem proposals carry the same metadata into the taxonomy-suggestion log.
`proposed_taxonomy.py` surfaces the categorization in its diff report.

This addresses items #3 and #4 of the team brief: *categorize problems by
tech stack* and *design/bug/design+bug classification*. The richer version
(automated repo analysis to *infer* tech stack from a code link) is left for
follow-up work.

## Limits + extensions left for later

- **No automatic taxonomy suggestions.** A natural next step is to cluster
  flagged entries (embeddings) and pre-fill proposed categories. Out of
  scope here.
- **Proposals are manually merged.** Currently `proposed_taxonomy.py` is
  read-only; it doesn't write to `tasks.json` / `problems.json` / `mappings.json`.
  An "apply proposal" command that does the JSON edits + bumps proposal
  status to `merged` is a clean next step.
- **`model_self_reported_low_confidence` is wired through but inactive** —
  triggers only when the classification prompt is updated to return a
  confidence field. Trivial change in `llm_utils.py` when desired.
- **No rate limiting.** A single user could spam-fill the log. Not a
  concern for internal/pilot use; would matter in production.
