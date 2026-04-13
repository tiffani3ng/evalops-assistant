## overview as of right now + to do + wants!!!

# tasks.json
- uses prof Wang's categories from email: ad hoc information gathering, long-term tracking, triage/classification, sensemaking, factual QA, report drafting, and verification. 
- Each entry has an id, label, description, and keywords.
- **hard coded w/ keywords... want to fix flexibility**
- **also doesn't include ALL tasks**

# problems.json
- common complaint types: latency, low trust, irrelevant results, information overload, hard to verify, poor coherence, low accuracy, and poor usability. 
- Each has an id, label, and keywords.
- **hard coded w/ keywords... want to fix flexibility**
- **also doesn't include ALL problems**

# metrics.json
- draws from the two spreadsheets (lit review + data schema).
- Each metric entry includes: id, label, type (interaction/model/survey), evaluation mode (online/offline/survey), signal type, description, instrumentation steps, burden level, and source IDs from lit review. 
- **NEED all metrics**

# mappings.json
- linking table, two sections: 
    - task_to_metrics (mapping each task to metrics)
    - problem_to_metrics (mapping each problem type to metrics)