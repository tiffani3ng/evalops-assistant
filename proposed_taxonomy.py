"""
Diff the current taxonomy against the proposal log.

Reads tasks.json, problems.json, and taxonomy_suggestions.jsonl, then prints a
markdown report showing what the taxonomy would look like if every open
proposal were accepted — separated cleanly from the existing entries.

Nothing is mutated. The script is meant to give a developer a single review
artifact: "here are the entries waiting on me, here is what they'd become."

Run:
    python proposed_taxonomy.py                  # writes proposed_taxonomy.md
    python proposed_taxonomy.py --stdout         # print to stdout
    python proposed_taxonomy.py --out path.md    # custom output path
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import proposals


BASE = Path(__file__).parent


def _load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def _index_by_id(entries: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in entries if "id" in e}


def build_report() -> str:
    tasks = _load_json(BASE / "tasks.json")
    problems = _load_json(BASE / "problems.json")
    existing_task_ids = _index_by_id(tasks)
    existing_problem_ids = _index_by_id(problems)

    all_proposals = proposals.read_all()
    open_proposals = [p for p in all_proposals if p.get("status", "open") == "open"]

    # Group open proposals by suggested_id to surface duplicates and clusters.
    by_kind: dict[str, dict[str, list[dict]]] = {
        "task": defaultdict(list),
        "problem": defaultdict(list),
    }
    for p in open_proposals:
        kind = p.get("kind")
        if kind in by_kind:
            by_kind[kind][p["suggested_id"]].append(p)

    out: list[str] = []
    out.append("# Proposed Taxonomy Updates")
    out.append("")
    out.append(f"_Generated {datetime.now().isoformat(timespec='seconds')}_")
    out.append("")
    out.append(f"- Current taxonomy: {len(tasks)} tasks, {len(problems)} problems")
    out.append(f"- Open proposals: {len(open_proposals)}")
    out.append("")
    out.append("Run `python flagged_report.py` to see the underlying flagged feedback.")
    out.append("")

    if not open_proposals:
        out.append("No open proposals. Taxonomy is unchanged.")
        return "\n".join(out)

    for kind, label_plural in (("problem", "Problems"), ("task", "Tasks")):
        existing = existing_problem_ids if kind == "problem" else existing_task_ids
        clusters = by_kind[kind]
        if not clusters:
            continue

        out.append(f"## Proposed new {label_plural}")
        out.append("")
        for suggested_id, group in sorted(clusters.items()):
            collision = suggested_id in existing
            header = f"### `{suggested_id}`"
            if collision:
                header += "  ⚠️ collides with existing id"
            out.append(header)
            out.append("")
            if collision:
                existing_label = existing[suggested_id].get("label", "?")
                out.append(f"> Conflict: this id already exists as `{existing_label}`. "
                           f"Reviewer needs to pick a new id or merge into the existing entry.")
                out.append("")
            if len(group) > 1:
                out.append(f"_{len(group)} proposals converged on this id — strong signal._")
                out.append("")

            for p in group:
                kws = p.get("suggested_keywords") or []
                rationale = p.get("rationale") or "(no rationale provided)"
                out.append(f"- **{p['suggested_label']}**")
                out.append(f"    - Keywords: {', '.join(f'`{k}`' for k in kws) if kws else '_(none)_'}")
                out.append(f"    - Rationale: {rationale}")
                if p.get("source_flagged_id"):
                    out.append(f"    - Source flagged entry: `{p['source_flagged_id']}`")
                out.append(f"    - Proposal id: `{p['id']}`")
                out.append("")

    out.append("## How to apply")
    out.append("")
    out.append(
        "For each proposal you accept, add a new object to the corresponding\n"
        "`tasks.json` or `problems.json` and (if applicable) extend `mappings.json`\n"
        "to point the new id at relevant metrics. Then mark the proposal status\n"
        "in `taxonomy_suggestions.jsonl` as `merged` (manual edit) so it stops\n"
        "showing up in this report."
    )
    out.append("")

    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff the taxonomy against the proposal log.")
    parser.add_argument("--out", default="proposed_taxonomy.md", help="Output path (default: proposed_taxonomy.md)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing")
    args = parser.parse_args()

    report = build_report()
    if args.stdout:
        print(report)
    else:
        out_path = Path(args.out)
        out_path.write_text(report)
        print(f"Wrote proposed taxonomy report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
