from dotenv import load_dotenv
load_dotenv()
import os

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY is missing")

import anthropic
import json

client = anthropic.Anthropic(api_key=api_key)  # ANTHROPIC_API_KEY env var

## currently acts as just a MATCHING between tasks list and problem list
### extension 1: the ablity to parse flexible text and use that to map onto task/problem types and return metrics (EMBEDDINGS)
### extension 2: ability for user to input model task, model context, problem context, and then from there pull metrics 
###              from the specific way they're tested in the literature ( expand the knowledge base with implementation contexts from the papers )

def classify_feedback(feedback: str, tasks: list, problems: list,
                      model_context: str = None, stakeholder_context: str = None) -> dict:   
    """Send feedback to Claude, get back structured labels."""
    
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