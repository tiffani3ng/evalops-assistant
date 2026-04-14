import os
import json
from flask import Flask, render_template, request, jsonify

from llm_utils import classify_feedback, generate_bundle_explanation
from prompts import load_json, get_recommendations, apply_sanity_rules

app = Flask(__name__)

BASE = os.path.dirname(__file__)

tasks    = load_json(os.path.join(BASE, "tasks.json"))
problems = load_json(os.path.join(BASE, "problems.json"))
metrics  = load_json(os.path.join(BASE, "metrics.json"))
mappings = load_json(os.path.join(BASE, "mappings.json"))
sources  = load_json(os.path.join(BASE, "sources.json"))

task_label_map    = {t["id"]: t["label"] for t in tasks}
problem_label_map = {p["id"]: p["label"] for p in problems}


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

        return jsonify({
            "classification": {
                "task_labels":          task_labels,
                "problem_labels":       problem_labels,
                "summary":              classification.get("summary", ""),
                "task_labels_human":    [task_label_map.get(t, t) for t in task_labels],
                "problem_labels_human": [problem_label_map.get(p, p) for p in problem_labels],
            },
            "metrics":             metric_cards,
            "bundle_explanation":  bundle_explanation,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8080)
