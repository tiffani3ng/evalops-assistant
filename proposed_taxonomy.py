"""
Diff the current taxonomy against the proposal log, or apply a proposal.

Default behaviour (no --apply) is read-only: reads tasks.json, problems.json,
and taxonomy_suggestions.jsonl and writes a markdown diff report. Nothing is
mutated.

With --apply <proposal_id>, the named proposal is committed to the taxonomy
JSON files and its status in the suggestion log is bumped to "merged". This
closes the review loop end-to-end without anyone hand-editing JSON.

Run:
    python proposed_taxonomy.py                       # writes proposed_taxonomy.md
    python proposed_taxonomy.py --stdout              # print diff to stdout
    python proposed_taxonomy.py --out path.md         # custom diff output path
    python proposed_taxonomy.py --apply <proposal_id> # commit one proposal
    python proposed_taxonomy.py --apply <proposal_id> --dry-run  # preview only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
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
                if p.get("tech_stack") or p.get("nature"):
                    cat_parts = []
                    if p.get("tech_stack"):
                        cat_parts.append(f"tech_stack=`{p['tech_stack']}`")
                    if p.get("nature"):
                        cat_parts.append(f"nature=`{p['nature']}`")
                    out.append(f"    - Categorization: {', '.join(cat_parts)}")
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


class ApplyError(RuntimeError):
    """Raised when --apply cannot proceed (unknown id, collision, etc.)."""


def apply_proposal(
    proposal_id: str,
    *,
    tasks_path: Path = BASE / "tasks.json",
    problems_path: Path = BASE / "problems.json",
    suggestions_path: Path = proposals.SUGGESTIONS_PATH,
    dry_run: bool = False,
) -> dict:
    """Commit one open proposal to the taxonomy and mark it merged.

    Returns a small summary dict describing what changed. Raises ApplyError
    on any non-recoverable problem (missing proposal, id collision, already
    merged, etc.) — the caller decides how to render the error.
    """
    all_props = proposals.read_all(suggestions_path)
    target = next((p for p in all_props if p.get("id") == proposal_id), None)
    if target is None:
        raise ApplyError(f"no proposal with id {proposal_id!r}")
    if target.get("status") != "open":
        raise ApplyError(
            f"proposal {proposal_id} has status {target.get('status')!r}, expected 'open'"
        )

    kind = target["kind"]
    target_path = problems_path if kind == "problem" else tasks_path
    entries = json.loads(target_path.read_text())

    if any(e.get("id") == target["suggested_id"] for e in entries):
        raise ApplyError(
            f"{kind} id {target['suggested_id']!r} already exists in {target_path.name}; "
            "reject the proposal or pick a different id"
        )

    new_entry: dict = {
        "id":       target["suggested_id"],
        "label":    target["suggested_label"],
        "keywords": target.get("suggested_keywords") or [],
    }
    if kind == "task":
        # tasks have a description field; problems don't.
        new_entry["description"] = target.get("rationale") or "Added via taxonomy proposal."
        # Match the schema order tasks use (id, label, description, keywords).
        new_entry = {
            "id":          new_entry["id"],
            "label":       new_entry["label"],
            "description": new_entry["description"],
            "keywords":    new_entry["keywords"],
        }
    else:
        if target.get("tech_stack"):
            new_entry["tech_stack"] = target["tech_stack"]
        if target.get("nature"):
            new_entry["nature"] = target["nature"]

    if dry_run:
        return {
            "would_apply":   True,
            "kind":          kind,
            "target_path":   str(target_path),
            "new_entry":     new_entry,
            "proposal_id":   proposal_id,
        }

    # Write taxonomy file
    entries.append(new_entry)
    target_path.write_text(json.dumps(entries, indent=2) + "\n")

    # Mark proposal as merged — rewrite suggestion log with updated status
    updated = []
    for p in all_props:
        if p.get("id") == proposal_id:
            p = {**p, "status": "merged", "merged_at": datetime.now(timezone.utc).isoformat()}
        updated.append(p)
    with suggestions_path.open("w") as f:
        for p in updated:
            f.write(json.dumps(p) + "\n")

    return {
        "applied":      True,
        "kind":         kind,
        "target_path":  str(target_path),
        "new_entry":    new_entry,
        "proposal_id":  proposal_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff the taxonomy against the proposal log, or apply a proposal.")
    parser.add_argument("--out", default="proposed_taxonomy.md", help="Diff output path (default: proposed_taxonomy.md)")
    parser.add_argument("--stdout", action="store_true", help="Print diff to stdout instead of writing")
    parser.add_argument("--apply", metavar="PROPOSAL_ID", help="Apply this proposal to the taxonomy")
    parser.add_argument("--dry-run", action="store_true", help="With --apply, show what would change without writing")
    args = parser.parse_args()

    if args.apply:
        try:
            result = apply_proposal(args.apply, dry_run=args.dry_run)
        except ApplyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        verb = "Would apply" if args.dry_run else "Applied"
        print(f"{verb} proposal {result['proposal_id']} ({result['kind']}) to {result['target_path']}:")
        print(json.dumps(result["new_entry"], indent=2))
        if not args.dry_run:
            print("Proposal status marked as 'merged' in taxonomy_suggestions.jsonl.")
        return 0

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
