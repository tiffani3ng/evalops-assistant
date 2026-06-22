"""
Generate a markdown review report from the flagged-feedback log.

Reads flagged_feedback.jsonl, groups entries by flag reason, summarizes
severity, and writes a developer-readable .md document. Designed to be
run periodically (manually or in cron) so a human can review the queue
and decide whether the taxonomy needs to grow.

Run:
    python flagged_report.py                    # writes flagged_report.md
    python flagged_report.py --out report.md    # custom path
    python flagged_report.py --stdout           # print to stdout
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import flagging


REASON_DESCRIPTIONS = {
    "no_task_or_problem_identified":
        "Neither a task nor a problem category matched. Strong candidate for taxonomy expansion.",
    "no_task_identified":
        "Problem category matched but no task did. Consider whether a new task type is needed.",
    "no_problem_identified":
        "Task matched but no problem category did. Consider whether a new problem type is needed.",
    "tiny_metric_bundle":
        "Recommender returned fewer than 2 metrics. Likely a thin classification or a gap in mappings.",
    "low_detail_summary":
        "Summary was very short — the LLM may not have understood the feedback well.",
    "model_self_reported_low_confidence":
        "The classification model explicitly flagged its own output as low-confidence.",
}


def _fmt_entry(entry: dict) -> str:
    severity = entry.get("flag", {}).get("severity") or "—"
    reasons = entry.get("flag", {}).get("reasons", [])
    classification = entry.get("classification", {})
    tasks = ", ".join(classification.get("task_labels") or []) or "(none)"
    problems = ", ".join(classification.get("problem_labels") or []) or "(none)"
    metrics = entry.get("metric_ids") or []

    parts = [
        f"- **[{severity.upper()}]** *\"{entry.get('feedback', '')}\"*",
        f"    - Timestamp: `{entry.get('timestamp', '?')}`",
        f"    - Tasks identified: `{tasks}`",
        f"    - Problems identified: `{problems}`",
        f"    - Metrics recommended ({len(metrics)}): `{', '.join(metrics) if metrics else 'none'}`",
        f"    - Flag reasons: {', '.join(f'`{r}`' for r in reasons)}",
    ]
    if entry.get("model_context"):
        parts.append(f"    - Model context: {entry['model_context']}")
    if entry.get("stakeholder_context"):
        parts.append(f"    - Stakeholder: {entry['stakeholder_context']}")
    return "\n".join(parts)


def build_report(entries: list[dict]) -> str:
    if not entries:
        return (
            "# Flagged Feedback Review\n\n"
            f"_Generated {datetime.now().isoformat(timespec='seconds')}_\n\n"
            "No flagged feedback in the queue.\n"
        )

    severity_counts = Counter(e.get("flag", {}).get("severity") or "—" for e in entries)
    reason_counts = Counter()
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        for reason in entry.get("flag", {}).get("reasons", []):
            reason_counts[reason] += 1
            by_reason[reason].append(entry)

    out: list[str] = []
    out.append("# Flagged Feedback Review")
    out.append("")
    out.append(f"_Generated {datetime.now().isoformat(timespec='seconds')}_")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"- **Total flagged items:** {len(entries)}")
    out.append("- **By severity:**")
    for sev in ("high", "medium", "low", "—"):
        if severity_counts.get(sev):
            out.append(f"    - {sev}: {severity_counts[sev]}")
    out.append("- **By reason (most common first):**")
    for reason, n in reason_counts.most_common():
        out.append(f"    - `{reason}`: {n}")
    out.append("")

    out.append("## Recommended Action")
    out.append("")
    out.append(
        "Review high-severity items first. For each cluster of items sharing a reason, "
        "decide whether the taxonomy should be expanded (new task or problem category), "
        "the mappings refined (better metric coverage), or the prompt rewritten."
    )
    out.append("")

    out.append("## Items by Reason")
    out.append("")
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        out.append(f"### `{reason}` ({len(items)})")
        out.append("")
        out.append(f"_{REASON_DESCRIPTIONS.get(reason, 'No description.')}_")
        out.append("")
        for entry in items:
            out.append(_fmt_entry(entry))
            out.append("")

    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a markdown report of flagged feedback.")
    parser.add_argument("--out", default="flagged_report.md", help="Output file path (default: flagged_report.md)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing a file")
    args = parser.parse_args()

    entries = flagging.read_log()
    report = build_report(entries)

    if args.stdout:
        print(report)
    else:
        out_path = Path(args.out)
        out_path.write_text(report)
        print(f"Wrote report ({len(entries)} entries) to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
