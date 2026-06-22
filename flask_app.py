import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for

from llm_utils import classify_feedback, generate_bundle_explanation
from prompts import load_json, get_recommendations, apply_sanity_rules
import flagging
import proposals

app = Flask(__name__)

BASE = os.path.dirname(__file__)

tasks    = load_json(os.path.join(BASE, "tasks.json"))
problems = load_json(os.path.join(BASE, "problems.json"))
metrics  = load_json(os.path.join(BASE, "metrics.json"))
mappings = load_json(os.path.join(BASE, "mappings.json"))
sources  = load_json(os.path.join(BASE, "sources.json"))

task_label_map    = {t["id"]: t["label"] for t in tasks}
problem_label_map = {p["id"]: p["label"] for p in problems}
problem_by_id     = {p["id"]: p for p in problems}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sources")
def sources_page():
    return render_template("sources.html", sources=sources)


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}

    feedback           = (data.get("feedback") or "").strip()
    model_context      = (data.get("model_context") or "").strip() or None
    stakeholder_context = (data.get("stakeholder_context") or "").strip() or None

    if not feedback:
        return jsonify({"error": "Feedback is required."}), 400

    try:
        classification = classify_feedback(
            feedback, tasks, problems, model_context, stakeholder_context
        )

        task_labels    = classification.get("task_labels", [])
        problem_labels = classification.get("problem_labels", [])

        recommended = get_recommendations(task_labels, problem_labels, metrics, mappings)
        recommended = apply_sanity_rules(task_labels, problem_labels, recommended, metrics)

        bundle_explanation = generate_bundle_explanation(feedback, classification, recommended)

        metric_ids = [m["id"] for m in recommended]
        flag_decision = flagging.evaluate(feedback, classification, metric_ids)
        if flag_decision.flagged:
            flagging.log(
                feedback=feedback,
                model_context=model_context,
                stakeholder_context=stakeholder_context,
                classification=classification,
                metric_ids=metric_ids,
                decision=flag_decision,
            )

        metric_cards = [
            {
                "id":              m["id"],
                "label":           m["label"],
                "type":            m.get("type", ""),
                "evaluation_mode": m.get("evaluation_mode", ""),
                "description":     m.get("description", ""),
                "instrumentation": m.get("instrumentation", []),
                "source_ids":      m.get("source_ids", []),
            }
            for m in recommended
        ]

        problem_categorizations = []
        for pid in problem_labels:
            entry = problem_by_id.get(pid)
            if not entry:
                continue
            problem_categorizations.append({
                "id":          pid,
                "label":       entry.get("label", pid),
                "tech_stack":  entry.get("tech_stack"),
                "nature":      entry.get("nature"),
            })

        return jsonify({
            "classification": {
                "task_labels":          task_labels,
                "problem_labels":       problem_labels,
                "summary":              classification.get("summary", ""),
                "task_labels_human":    [task_label_map.get(t, t) for t in task_labels],
                "problem_labels_human": [problem_label_map.get(p, p) for p in problem_labels],
                "problem_categorizations": problem_categorizations,
            },
            "metrics":             metric_cards,
            "bundle_explanation":  bundle_explanation,
            "flag":               flag_decision.to_dict(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/flagged")
def flagged_view():
    """HTML review queue for feedback that didn't fit the existing taxonomy."""
    show_reviewed = request.args.get("show_reviewed") == "1"
    all_entries = flagging.read_log()
    reviewed_ids = flagging.read_reviewed_ids()
    if show_reviewed:
        open_entries = all_entries
    else:
        open_entries = [e for e in all_entries if e.get("id") not in reviewed_ids]

    # Group proposals by source flagged entry for easy template rendering.
    all_proposals = proposals.read_all()
    proposals_by_source: dict[str, list[dict]] = {}
    for p in all_proposals:
        src = p.get("source_flagged_id")
        if src:
            proposals_by_source.setdefault(src, []).append(p)

    return render_template(
        "flagged.html",
        entries=open_entries,
        count=len(open_entries),
        reviewed_count=len(reviewed_ids),
        total_count=len(all_entries),
        reviewed_ids=reviewed_ids,
        proposals_by_source=proposals_by_source,
        show_reviewed=show_reviewed,
    )


@app.route("/flagged.json")
def flagged_json():
    """JSON dump of the review queue. For programmatic access."""
    entries = flagging.read_log()
    reviewed_ids = flagging.read_reviewed_ids()
    return jsonify(
        {
            "count": len(entries),
            "entries": entries,
            "reviewed_ids": sorted(reviewed_ids),
            "proposals": proposals.read_all(),
        }
    )


@app.route("/flagged/<entry_id>/review", methods=["POST"])
def flagged_review(entry_id: str):
    """Mark a flagged entry as reviewed (moves it out of the active queue)."""
    if not flagging.find_entry(entry_id):
        return jsonify({"error": "entry not found"}), 404
    flagging.mark_reviewed(entry_id)
    return redirect(url_for("flagged_view"))


@app.route("/flagged/<entry_id>/propose", methods=["POST"])
def flagged_propose(entry_id: str):
    """Attach a taxonomy-update proposal to a flagged entry."""
    if not flagging.find_entry(entry_id):
        return jsonify({"error": "entry not found"}), 404

    form = request.form
    try:
        proposal_id = proposals.add(
            source_flagged_id=entry_id,
            kind=form.get("kind", ""),
            suggested_id=form.get("suggested_id", ""),
            suggested_label=form.get("suggested_label", ""),
            suggested_keywords=form.get("suggested_keywords", ""),
            rationale=form.get("rationale", ""),
            tech_stack=form.get("tech_stack") or None,
            nature=form.get("nature") or None,
        )
    except proposals.ProposalValidationError as e:
        # Render the review queue with the error banner so the user sees the
        # problem in context rather than getting a raw JSON page.
        all_entries = flagging.read_log()
        reviewed_ids = flagging.read_reviewed_ids()
        open_entries = [e_ for e_ in all_entries if e_.get("id") not in reviewed_ids]
        all_proposals = proposals.read_all()
        proposals_by_source: dict[str, list[dict]] = {}
        for p in all_proposals:
            src = p.get("source_flagged_id")
            if src:
                proposals_by_source.setdefault(src, []).append(p)
        return render_template(
            "flagged.html",
            entries=open_entries,
            count=len(open_entries),
            reviewed_count=len(reviewed_ids),
            total_count=len(all_entries),
            reviewed_ids=reviewed_ids,
            proposals_by_source=proposals_by_source,
            show_reviewed=False,
            error=str(e),
            error_entry_id=entry_id,
        ), 400

    return redirect(url_for("flagged_view") + f"#flag-{entry_id}")


@app.route("/flagged/<entry_id>")
def flagged_entry_view(entry_id: str):
    """Permalink view for a single flagged entry, regardless of review status."""
    entry = flagging.find_entry(entry_id)
    if not entry:
        return render_template(
            "flagged.html",
            entries=[],
            count=0,
            reviewed_count=0,
            total_count=0,
            reviewed_ids=set(),
            proposals_by_source={},
            show_reviewed=True,
            error=f"No flagged entry with id {entry_id!r}.",
            error_entry_id=None,
        ), 404

    reviewed_ids = flagging.read_reviewed_ids()
    all_proposals = proposals.read_all()
    proposals_by_source: dict[str, list[dict]] = {}
    for p in all_proposals:
        src = p.get("source_flagged_id")
        if src:
            proposals_by_source.setdefault(src, []).append(p)

    return render_template(
        "flagged.html",
        entries=[entry],
        count=1,
        reviewed_count=len(reviewed_ids),
        total_count=len(flagging.read_log()),
        reviewed_ids=reviewed_ids,
        proposals_by_source=proposals_by_source,
        show_reviewed=True,
        single_entry=True,
    )


@app.route("/proposals.json")
def proposals_json():
    """JSON dump of all taxonomy-update proposals."""
    return jsonify({"proposals": proposals.read_all()})


if __name__ == "__main__":
    app.run(debug=True, port=8080)
