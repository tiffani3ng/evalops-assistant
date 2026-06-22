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

## Limits + extensions left for later

- **No automatic taxonomy suggestions.** A natural next step is to cluster
  flagged entries (embeddings) and propose candidate new categories. Out of
  scope here.
- **No queue management UI** — items can't be marked "reviewed" or "ignored"
  yet. The log is append-only.
- **`model_self_reported_low_confidence` is wired through but inactive** —
  triggers only when the classification prompt is updated to return a
  confidence field. Trivial change in `llm_utils.py` when desired.
- **No rate limiting.** A single user could spam-fill the log. Not a
  concern for internal/pilot use; would matter in production.
