import anthropic
import json

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY env var

## currently acts as just a MATCHING between tasks list and problem list
### extension 1: the ablity to parse flexible text and use that to map onto task/problem types and return metrics
### extension 2: ability for user to input model task, model context, problem context, and then from there pull metrics 
###              from the specific way they're tested in the literature

def classify_feedback(feedback: str, tasks: list, problems: list) -> dict:
    """Send feedback to Claude, get back structured labels."""

    # takes user feedback plus task and problem lists, builds a system prompt 
    # telling Claude to act as a controlled labeler using ONLY provided taxonomy, 
    # sends feedback, and gets back structured JSON with task_labels, problem_labels, and a one-sentence summary
    
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

    user_prompt = f"""Classify this stakeholder feedback:

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
    # Strip any markdown
    response_text = response_text.strip().strip("`").strip()
    if response_text.startswith("json"):
        response_text = response_text[4:].strip()
    
    return json.loads(response_text)