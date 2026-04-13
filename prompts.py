import json

def load_json(path):
    with open(path) as f:
        return json.load(f)

def get_recommendations(task_labels: list, problem_labels: list, 
                         metrics: list, mappings: dict) -> list:
    """look up recommended metrics from the mapping tables."""
    # takes task and problem labels from Claude's classification, 
    # looks them up in mapping tables, 
    # collects all associated metrics, deduplicates, and
    # sorts by type (interaction, model, survey).     <------------ is there a better way?
    
    recommended_ids = set()
    
    # get metrics linked to identified tasks
    for task in task_labels:
        if task in mappings["task_to_metrics"]:
            recommended_ids.update(mappings["task_to_metrics"][task])
    
    # get metrics linked to identified problems
    for problem in problem_labels:
        if problem in mappings["problem_to_metrics"]:
            recommended_ids.update(mappings["problem_to_metrics"][problem])
    
    # look up full metric details
    metrics_by_id = {m["id"]: m for m in metrics}
    recommended = []
    for mid in recommended_ids:
        if mid in metrics_by_id:
            recommended.append(metrics_by_id[mid])
    
    # sort
    type_order = {"interaction": 0, "model": 1, "survey": 2, "workflow": 3}
    recommended.sort(key=lambda m: type_order.get(m.get("type", ""), 99))
    
    return recommended


def apply_sanity_rules(task_labels, problem_labels, recommended, metrics):
    """hard-coded fallback, makes sure obvious things i CAN control for are never missed""" 

    # EX. if "latency," always include response_time
    # EX. if "low_trust," always include trust_score.

    rec_ids = {m["id"] for m in recommended}
    metrics_by_id = {m["id"]: m for m in metrics}
    
    must_include = {
        "latency": "response_time",
        "low_trust": "trust_score",
        "low_accuracy": "hallucination_rate",
    }
    
    task_must_include = {
        "verification": "source_click_rate",
    }
    
    for problem in problem_labels:
        if problem in must_include:
            mid = must_include[problem]
            if mid not in rec_ids and mid in metrics_by_id:
                recommended.append(metrics_by_id[mid])
                rec_ids.add(mid)
    
    for task in task_labels:
        if task in task_must_include:
            mid = task_must_include[task]
            if mid not in rec_ids and mid in metrics_by_id:
                recommended.append(metrics_by_id[mid])
                rec_ids.add(mid)
    
    return recommended