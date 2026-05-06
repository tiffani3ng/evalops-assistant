# ------------------------------------------------------
               LEGACY STREAMLIT PROTOTYPE
                   FOR REFERENCE ONLY
# ------------------------------------------------------

import streamlit as st
from llm_utils import classify_feedback, generate_bundle_explanation
from prompts import load_json, get_recommendations, apply_sanity_rules

# Load knowledge base
tasks = load_json("tasks.json")
problems = load_json("problems.json")
metrics = load_json("metrics.json")
mappings = load_json("mappings.json")

st.title("EvalOps Benchmarking Assistant")
st.caption("Powered by Claude.")

feedback = st.text_area(
    "Stakeholder feedback:",
    placeholder="e.g. 'This chatbot takes too long to respond and I don't trust the answers.'",
    height=120
)

with st.expander("Optional context"):
    model_context = st.text_area(
        "Model context:", 
        placeholder="e.g. 'A customer support chatbot for a SaaS product, used by non-technical end users.'", 
        height=80
    )
    stakeholder_context = st.text_area(
        "Stakeholder context:",
        placeholder="e.g. 'A product manager reviewing weekly support escalations to decide which issues to prioritize.",
        height=80
    )

if st.button("Analyze", type="primary"):
    if not feedback.strip():
        st.warning("Please enter some feedback.")
    else:
        with st.spinner("Analyzing feedback with Claude..."): ### NOOO change as text loading animation
            # Step 1: Claude classifies the feedback
            classification = classify_feedback(
                feedback, tasks, problems,
                model_context = model_context.strip() or None,
                stakeholder_context=stakeholder_context.strip() or None,
                )
        
        # Step 2: Python looks up metrics
        recommended = get_recommendations(
            classification["task_labels"],
            classification["problem_labels"],
            metrics, mappings
        )
        
        # Step 3: Apply sanity rules
        recommended = apply_sanity_rules(
            classification["task_labels"],
            classification["problem_labels"],
            recommended, metrics
        )

        # Step 4: Claude explains why this bundle addresses the stakeholder's concerns
        bundle_explanation = generate_bundle_explanation(feedback, classification, recommended)

        # Step 5: Display results
        st.subheader("Interpretation")
        
        task_map = {t["id"]: t["label"] for t in tasks}
        problem_map = {p["id"]: p["label"] for p in problems}
        
        st.markdown("**Likely tasks:**")
        for t in classification["task_labels"]:
            st.markdown(f"- {task_map.get(t, t)}")
        
        st.markdown("**Likely issues:**")
        for p in classification["problem_labels"]:
            st.markdown(f"- {problem_map.get(p, p)}")
        
        st.markdown(f"**Summary:** {classification['summary']}")

        st.divider()
        st.subheader("Recommended Metrics")
        st.info(bundle_explanation)
        
        for m in recommended:
            with st.expander(f"{m['label']}  ({m['type']}, {m['evaluation_mode']})"):
                st.write(m["description"])
                st.markdown("**How to instrument:**")
                for step in m["instrumentation"]:
                    st.markdown(f"- {step}")
                if m.get("source_ids"):
                    st.caption(f"Literature sources: {m['source_ids']}")
