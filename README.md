# tasks.json
- uses Wang's categories from his email: ad hoc information gathering, long-term tracking, triage/classification, sensemaking, factual QA, report drafting, and verification. 
- Each entry has an id, label, description, and keywords.
- **hard coded w/ keywords... want to fix flexibility**
- **also doesn't include ALL tasks**

# problems.json
- covers common complaint types: latency, low trust, irrelevant results, information overload, hard to verify, poor coherence, low accuracy, and poor usability. 
- Each has an id, label, and keywords.
- **hard coded w/ keywords... want to fix flexibility**

# metrics.json
- draws from the two spreadsheets (lit review + data schema).
- Each metric entry includes: id, label, type (interaction/model/survey), evaluation mode (online/offline/survey), signal type, description, instrumentation steps, burden level, and source IDs from lit review. 

# mappings.json
- linking table, two sections: 
    - task_to_metrics (mapping each task to metrics)
    - problem_to_metrics (mapping each problem type to metrics)




    
- **extension 1: allow multiple inputs.**
    **1. stakeholder feedback**
    **2. optional: model context (what does it do, what setting is it meant for)**
    **3. optional: stakeholder context (what are they trying to do, what is the end goal, what is the info used for)**

