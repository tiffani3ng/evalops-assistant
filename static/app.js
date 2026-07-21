"use strict";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const hero          = document.getElementById("hero");
const analyzeBtn    = document.getElementById("analyze-btn");
const spinner       = document.getElementById("spinner");
const errorMsg      = document.getElementById("error-msg");
const resultsSection = document.getElementById("results-section");
const metricsGrid   = document.getElementById("metrics-grid");
const bundleExp     = document.getElementById("bundle-explanation");
const interpretation = document.getElementById("interpretation");

// ── State ─────────────────────────────────────────────────────────────────────
function setState(state) {
  if (state === "loading") {
    analyzeBtn.disabled = true;
    spinner.classList.remove("hidden");
    errorMsg.classList.add("hidden");
  } else if (state === "results") {
    analyzeBtn.disabled = false;
    spinner.classList.add("hidden");
    hero.classList.add("has-results");
    resultsSection.classList.remove("hidden");
    scheduleCardReveal();
  } else {
    // idle
    analyzeBtn.disabled = false;
    spinner.classList.add("hidden");
  }
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderResults(data) {
  const { classification, metrics, bundle_explanation } = data;

  // Bundle explanation
  bundleExp.textContent = bundle_explanation;

  // Interpretation: summary + chips
  const taskChips = (classification.task_labels_human || [])
    .map(l => `<span class="label-chip task">${l}</span>`).join("");
  const problemChips = (classification.problem_labels_human || [])
    .map(l => `<span class="label-chip problem">${l}</span>`).join("");

  // Problem categorizations: unique tech_stack + nature across all classified problems
  const cats = classification.problem_categorizations || [];
  const uniqueStacks  = [...new Set(cats.map(c => c.tech_stack).filter(Boolean))];
  const uniqueNatures = [...new Set(cats.map(c => c.nature).filter(Boolean))];
  const stackChips = uniqueStacks
    .map(s => `<span class="label-chip stack" data-stack="${s}">${s}</span>`).join("");
  const natureChips = uniqueNatures
    .map(n => `<span class="label-chip nature" data-nature="${n}">${n}</span>`).join("");

  const categorizationRow = (stackChips || natureChips)
    ? `<div class="categorization-row">
        ${stackChips ? `<span class="categorization-label">Tech stack:</span>${stackChips}` : ""}
        ${natureChips ? `<span class="categorization-label">Nature:</span>${natureChips}` : ""}
      </div>`
    : "";

  interpretation.innerHTML = `
    <p class="summary">${classification.summary || ""}</p>
    ${taskChips || problemChips
      ? `<div class="label-row">${taskChips}${problemChips}</div>`
      : ""}
    ${categorizationRow}
  `;

  // Metric cards — built invisible, revealed via scheduleCardReveal()
  metricsGrid.innerHTML = "";
  metrics.forEach(m => {
    const card = document.createElement("div");
    card.className = "metric-card";
    card.dataset.type = m.type;

    const steps = (m.instrumentation || [])
      .map((s, i) => `<li><span class="step-num">${i + 1}</span>${s}</li>`)
      .join("");

    const sources = (m.source_ids || []).length
      ? `<p class="card-sources">Sources: ${m.source_ids.map(id => `<a class="card-source-link" href="/sources#source-${id}">[${id}]</a>`).join(" ")}</p>`
      : "";

    card.innerHTML = `
      <div class="card-header">
        <span class="type-badge">${m.type}</span>
        <span class="eval-tag" data-mode="${m.evaluation_mode}">${m.evaluation_mode}</span>
      </div>
      <h3 class="card-title">${m.label}</h3>
      <p class="card-desc">${m.description}</p>
      <div class="card-details">
        <div class="card-details-inner">
          <p class="card-details-heading">How to implement</p>
          <ol class="card-steps">${steps}</ol>
          ${sources}
        </div>
      </div>
    `;
    metricsGrid.appendChild(card);
  });
}

// ── Staggered card reveal ─────────────────────────────────────────────────────
function scheduleCardReveal() {
  const cards = document.querySelectorAll(".metric-card");
  // Wait for hero CSS transition to substantially complete (~400ms),
  // then reveal cards one by one every 70ms.
  cards.forEach((card, i) => {
    setTimeout(() => card.classList.add("visible"), 400 + i * 70);
  });
}

// ── Analysis fetch ────────────────────────────────────────────────────────────
async function runAnalysis() {
  const feedbackInput       = document.getElementById("feedback-input");
  const modelContextInput   = document.getElementById("model-context-input");
  const stakeholderInput    = document.getElementById("stakeholder-context-input");

  if (feedbackInput.value.trim() === "test") {
    feedbackInput.value       = "This research chatbot takes too long to respond";
    modelContextInput.value   = "A research assistant for undergraduate students";
    stakeholderInput.value    = "Undergraduate economics students";
    // expand the context details if collapsed
    const contextToggle = document.querySelector(".context-toggle");
    if (contextToggle && !contextToggle.open) contextToggle.open = true;
  }

  const feedback           = feedbackInput.value.trim();
  const modelContext       = modelContextInput.value.trim();
  const stakeholderContext = stakeholderInput.value.trim();

  if (!feedback) {
    showError("Please enter some feedback before analyzing.");
    return;
  }

  setState("loading");

  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        feedback,
        model_context:       modelContext       || null,
        stakeholder_context: stakeholderContext || null,
      }),
    });

    const payload = await res.json();

    if (!res.ok) {
      throw new Error(payload.error || "Analysis failed. Please try again.");
    }

    renderResults(payload);
    setState("results");

  } catch (err) {
    showError(err.message || "Something went wrong.");
    setState("idle");
  }
}

// ── Error display ─────────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove("hidden");
  setTimeout(() => errorMsg.classList.add("hidden"), 6000);
}

// ── Typewriter title ──────────────────────────────────────────────────────────
function typeTitle() {
  const titleEl = document.querySelector(".main-title");
  const text    = titleEl.textContent.trim();
  titleEl.textContent = "";

  const cursor = document.createElement("span");
  cursor.className = "type-cursor";
  titleEl.appendChild(cursor);

  let i = 0;
  const interval = setInterval(() => {
    if (i < text.length) {
      titleEl.insertBefore(document.createTextNode(text[i]), cursor);
      i++;
    } else {
      clearInterval(interval);
    }
  }, 65);
}

// ── Event wiring ──────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  typeTitle();

  analyzeBtn.addEventListener("click", runAnalysis);

  document.getElementById("feedback-input").addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") runAnalysis();
  });
});
