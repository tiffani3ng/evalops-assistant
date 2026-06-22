from dotenv import load_dotenv
load_dotenv()
import os

import anthropic
import json

DEV_MODE = os.getenv("DEV", "").lower() == "true"

api_key = os.getenv("ANTHROPIC_API_KEY")
if not DEV_MODE and not api_key:
    raise ValueError("ANTHROPIC_API_KEY is missing (or set DEV=true to use mock classifications)")

client = anthropic.Anthropic(api_key=api_key) if not DEV_MODE else None

## currently acts as just a MATCHING between tasks list and problem list
### extension 1: the ablity to parse flexible text and use that to map onto task/problem types and return metrics (EMBEDDINGS)
### extension 2: ability for user to input model task, model context, problem context, and then from there pull metrics 
###              from the specific way they're tested in the literature ( expand the knowledge base with implementation contexts from the papers )

_DEV_KEYWORD_RULES = [
    # (keywords, task_labels, problem_labels, summary)
    (("slow", "latency", "wait", "takes too long", "speed"),
     ["factual_qa"], ["latency"], "Latency complaint — responses are too slow."),
    (("wrong", "incorrect", "inaccurate", "made up", "hallucinat"),
     ["factual_qa"], ["low_accuracy"], "Accuracy concern — responses contain incorrect information."),
    (("confusing", "incoherent", "unclear", "jumbled"),
     ["sensemaking"], ["poor_coherence"], "Coherence issue — output is hard to follow."),
    (("trust", "believe", "skeptical", "reliable"),
     ["factual_qa"], ["low_trust"], "Trust gap — user lacks confidence in answers."),
    (("verify", "source", "cite", "where did this"),
     ["verification"], ["hard_to_verify"], "Verification gap — provenance is unclear."),
    (("too much", "overwhelming", "cluttered", "noisy"),
     ["sensemaking"], ["information_overload"], "Information overload."),
    (("irrelevant", "off-topic", "not what i asked", "unrelated"),
     ["ad_hoc_info_gathering"], ["irrelevant_results"], "Relevance failure — results don't match intent."),
    (("hard to use", "clunky", "navigate", "ux", "interface"),
     [], ["poor_usability"], "Usability issue."),
]


def _dev_classify(feedback: str) -> dict:
    """Keyword-based mock classifier used when DEV=true.

    Matches simple lexical patterns and falls back to empty labels for
    feedback outside the seed vocabulary — which is intentional, since
    empty labels are precisely what the flag-for-review queue is built
    to catch. This makes the dev path useful for demoing both healthy
    and edge-case classifications.
    """
    fb = feedback.lower()
    for keywords, task_labels, problem_labels, summary in _DEV_KEYWORD_RULES:
        if any(k in fb for k in keywords):
            return {
                "task_labels": task_labels,
                "problem_labels": problem_labels,
                "summary": summary,
            }
    # No match — return empty labels so the flag-for-review queue catches it.
    return {
        "task_labels": [],
        "problem_labels": [],
        "summary": "Feedback did not match any known taxonomy keywords.",
    }


def classify_feedback(feedback: str, tasks: list, problems: list,
                      model_context: str = None, stakeholder_context: str = None) -> dict:
    """Send feedback to Claude, get back structured labels."""

    if DEV_MODE:
        return _dev_classify(feedback)

    task_list = "\n".join(f"- {t['id']}: {t['label']} — {t['description']}" for t in tasks)
    problem_list = "\n".join(f"- {p['id']}: {p['label']}" for p in problems)
    
    system_prompt = f"""You are an evaluation metrics assistant for AI workflows.

Your job: classify user feedback into task categories and problem categories.

RULES:
- Use ONLY the provided taxonomy. Do not invent new labels.
- Return valid JSON only. No preamble, no markdown backticks.
- You may select multiple task_labels and problem_labels if appropriate.
- Provide a brief one-sentence summary.

AVAILABLE TASKS:
{task_list}

AVAILABLE PROBLEM TYPES:
{problem_list}"""
    
    context_block=""
    if model_context:
        context_block += f"\nModel context: {model_context}"
    if stakeholder_context:
        context_block += f"\nStakeholder context: {stakeholder_context}"

    user_prompt = f"""Classify this stakeholder feedback: {context_block}

"{feedback}"

Return JSON with this exact structure:
{{
  "task_labels": ["task_id_1", "task_id_2"],
  "problem_labels": ["problem_id_1", "problem_id_2"],
  "summary": "One sentence describing the core issue."
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    response_text = message.content[0].text
    # Strip any accidental markdown fencing
    response_text = response_text.strip().strip("`").strip()
    if response_text.startswith("json"):
        response_text = response_text[4:].strip()

    return json.loads(response_text)

def generate_bundle_explanation(feedback: str, classification: dict, recommended_metrics: list) -> str:
    """given original feedback, classification, and recommended metrics bundle, ask Claude for 1 sentence explanation on why bundle addresses concerns"""

    metric_names = ", ".join(m["label"] for m in recommended_metrics)

    if DEV_MODE:
        if not recommended_metrics:
            return "No metrics were recommended — this feedback did not match the existing taxonomy and has been flagged for review."
        return f"These metrics ({metric_names}) together address the concerns surfaced in the feedback by covering both observable signals and stakeholder perception."

    prompt = f"""A stakeholder said: "{feedback}"

    Their concerns were classified as tasks: {classification.get("task_labels", [])} and problems: {classification.get("problem_labels", [])}.

    The recommended evaluation metric bundle is {metric_names}.

    In exactly one sentence, explain why these metrics together address the stakeholder's concerns and how they complement each other as a bundle"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text.strip()