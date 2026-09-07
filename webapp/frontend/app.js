const API_BASE = window.DSSAT_API_BASE || "";

const experimentSelect = document.getElementById("experiment-select");
const experimentMeta = document.getElementById("experiment-meta");
const runValidateBtn = document.getElementById("run-validate-btn");
const runCalibrateBtn = document.getElementById("run-calibrate-btn");
const loadingOverlay = document.getElementById("loading-overlay");
const loadingText = document.getElementById("loading-text");

let validationChart = null;
let convergenceChart = null;
let experiments = [];

// Tracks which result sections have real (not tour-peeked) content, so the
// tour knows which sections it's safe to re-hide when it moves on.
const renderedReal = { validation: false, calibration: false, upload: false };

function setLoading(on, text) {
  loadingOverlay.classList.toggle("hidden", !on);
  if (text) loadingText.textContent = text;
}

// The backend sends null for statistically undefined values (e.g. R-squared
// when a variable has zero variance across treatments, such as every
// treatment sharing the same planting date).
function fmtNum(value, decimals) {
  return value === null || value === undefined || Number.isNaN(value)
    ? "n/a"
    : value.toFixed(decimals);
}

function metricCard(label, value, cls = "") {
  return `<div class="metric-card"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>`;
}

async function loadExperiments() {
  const res = await fetch(`${API_BASE}/api/experiments`);
  experiments = await res.json();
  experimentSelect.innerHTML = experiments
    .map((e) => `<option value="${e.code}">${e.title}</option>`)
    .join("");
  updateExperimentMeta();
}

function updateExperimentMeta() {
  const exp = experiments.find((e) => e.code === experimentSelect.value);
  if (!exp) return;
  experimentMeta.textContent = `Cultivar: ${exp.cultivar_code} (${exp.cultivar_name}) · ${exp.n_treatments} treatments`;
}

experimentSelect.addEventListener("change", updateExperimentMeta);

async function runValidation() {
  setLoading(true, "Running real DSSAT-CSM simulation…");
  runValidateBtn.disabled = true;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60000); // free-tier cold start can be slow
  try {
    const code = experimentSelect.value;
    const res = await fetch(`${API_BASE}/api/validate?experiment_code=${encodeURIComponent(code)}`, {
      signal: controller.signal,
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderValidation(data);
  } catch (err) {
    if (err.name === "AbortError") {
      alert("Validation timed out after 60s — the free-tier backend may be waking up from idle. Try again.");
    } else {
      alert(`Validation failed: ${err.message}`);
    }
  } finally {
    clearTimeout(timeoutId);
    setLoading(false);
    runValidateBtn.disabled = false;
  }
}

function renderValidation(data) {
  renderedReal.validation = true;
  document.getElementById("validation-section").classList.remove("hidden");
  const r = data.report;
  document.getElementById("metric-cards").innerHTML = [
    metricCard("RMSE", fmtNum(r.rmse, 1), ""),
    metricCard("Normalized RMSE", `${fmtNum(r.nrmse_pct, 1)}%`, ""),
    metricCard("Willmott's d", fmtNum(r.willmott_d, 3), r.willmott_d > 0.9 ? "good" : ""),
    metricCard("R²", fmtNum(r.r_squared, 3), r.r_squared > 0.9 ? "good" : ""),
  ].join("");

  const labels = data.treatments.map((t) => `Trt ${t.treatment}`);
  const simulated = data.treatments.map((t) => t.simulated);
  const measured = data.treatments.map((t) => t.measured);

  if (validationChart) validationChart.destroy();
  validationChart = new Chart(document.getElementById("validation-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Simulated", data: simulated, backgroundColor: "#4fb286" },
        { label: "Measured", data: measured, backgroundColor: "#e0a94f" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: { display: true, text: `${data.variable} — ${data.cultivar}`, color: "#e8edf2" },
        legend: { labels: { color: "#e8edf2" } },
      },
      scales: {
        x: { ticks: { color: "#8ea0b3" }, grid: { color: "#263544" } },
        y: { ticks: { color: "#8ea0b3" }, grid: { color: "#263544" } },
      },
    },
  });
}

async function runCalibration() {
  setLoading(true, "Calibrating cultivar coefficients — running many DSSAT-CSM simulations…");
  runCalibrateBtn.disabled = true;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 150000); // 150s safety net
  try {
    const body = {
      experiment_code: experimentSelect.value,
      maxiter: parseInt(document.getElementById("maxiter-input").value, 10),
      popsize: parseInt(document.getElementById("popsize-input").value, 10),
    };
    const res = await fetch(`${API_BASE}/api/calibrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderCalibration(data);
  } catch (err) {
    if (err.name === "AbortError") {
      alert(
        "Calibration timed out after 150s. The free-tier host is slow — try lowering Generations/Population and running again."
      );
    } else {
      alert(`Calibration failed: ${err.message}`);
    }
  } finally {
    clearTimeout(timeoutId);
    setLoading(false);
    runCalibrateBtn.disabled = false;
  }
}

function renderCalibration(data) {
  renderedReal.calibration = true;
  document.getElementById("calibration-section").classList.remove("hidden");
  document.getElementById("calibration-summary").innerHTML = [
    metricCard("Baseline RMSE", data.baseline_score.toFixed(1)),
    metricCard("Calibrated RMSE", data.calibrated_score.toFixed(1), "good"),
    metricCard("Improvement", `${data.improvement_pct.toFixed(1)}%`, "improve"),
    metricCard("DSSAT-CSM runs", data.n_evaluations),
  ].join("");

  const runningBest = [];
  let best = Infinity;
  data.history.forEach((h) => {
    best = Math.min(best, h.score);
    runningBest.push(best);
  });

  if (convergenceChart) convergenceChart.destroy();
  convergenceChart = new Chart(document.getElementById("convergence-chart"), {
    type: "line",
    data: {
      labels: runningBest.map((_, i) => i + 1),
      datasets: [
        {
          label: "Best RMSE so far",
          data: runningBest,
          borderColor: "#4fb286",
          backgroundColor: "transparent",
          tension: 0.15,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: { display: true, text: "Calibration convergence", color: "#e8edf2" },
        legend: { labels: { color: "#e8edf2" } },
      },
      scales: {
        x: { title: { display: true, text: "Simulation run", color: "#8ea0b3" }, ticks: { color: "#8ea0b3" }, grid: { color: "#263544" } },
        y: { ticks: { color: "#8ea0b3" }, grid: { color: "#263544" } },
      },
    },
  });

  const paramsTable = document.getElementById("params-table");
  const rows = Object.entries(data.best_params)
    .map(([k, v]) => `<tr><td>${k}</td><td>${v.toFixed(3)}</td></tr>`)
    .join("");
  paramsTable.innerHTML = `<thead><tr><th>Genetic coefficient</th><th>Calibrated value</th></tr></thead><tbody>${rows}</tbody>`;
}

// --- Guide modal ---

const guideOverlay = document.getElementById("guide-overlay");
document.getElementById("open-guide-btn").addEventListener("click", () => {
  guideOverlay.classList.remove("hidden");
});
document.getElementById("close-guide-btn").addEventListener("click", () => {
  guideOverlay.classList.add("hidden");
});
guideOverlay.addEventListener("click", (e) => {
  if (e.target === guideOverlay) guideOverlay.classList.add("hidden");
});

// --- Upload your own data ---

let uploadChart = null;
let uploadResultCache = null;

const runUploadBtn = document.getElementById("run-upload-btn");
const uploadStatus = document.getElementById("upload-status");
const uploadVariableSelect = document.getElementById("upload-variable-select");

async function runUpload() {
  const filexInput = document.getElementById("upload-filex");
  if (!filexInput.files.length) {
    uploadStatus.textContent = "Choose an experiment (FileX) file first.";
    return;
  }

  const form = new FormData();
  form.append("filex", filexInput.files[0]);
  const observedInput = document.getElementById("upload-observed");
  const observedTInput = document.getElementById("upload-observed-t");
  if (observedInput.files.length) form.append("observed", observedInput.files[0]);
  if (observedTInput.files.length) form.append("observed_timeseries", observedTInput.files[0]);

  setLoading(true, "Running your experiment through the real DSSAT-CSM engine…");
  runUploadBtn.disabled = true;
  uploadStatus.textContent = "";
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60000);
  try {
    const res = await fetch(`${API_BASE}/api/upload/validate`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    renderUploadResult(data);
  } catch (err) {
    if (err.name === "AbortError") {
      uploadStatus.textContent = "Timed out after 60s — the free-tier backend may be waking up. Try again.";
    } else {
      uploadStatus.textContent = `Failed: ${err.message}`;
    }
    document.getElementById("upload-results-section").classList.add("hidden");
  } finally {
    clearTimeout(timeoutId);
    setLoading(false);
    runUploadBtn.disabled = false;
  }
}

function renderUploadResult(data) {
  renderedReal.upload = true;
  uploadResultCache = data;
  document.getElementById("upload-results-section").classList.remove("hidden");
  const messageEl = document.getElementById("upload-message");
  const pickerEl = document.getElementById("upload-variable-picker");
  const chartWrap = document.getElementById("upload-chart-wrap");
  const tableWrap = document.getElementById("upload-table-wrap");

  if (!data.has_observed_data) {
    messageEl.textContent = data.message;
    pickerEl.classList.add("hidden");
    chartWrap.classList.add("hidden");
    document.getElementById("upload-metric-cards").innerHTML = "";
    tableWrap.classList.remove("hidden");
    const rows = data.simulated_summary || [];
    const cols = rows.length ? Object.keys(rows[0]) : [];
    const table = document.getElementById("upload-summary-table");
    table.innerHTML =
      `<thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>` +
      `<tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${r[c]}</td>`).join("")}</tr>`).join("")}</tbody>`;
    return;
  }

  messageEl.textContent = `Ran "${data.filename}" successfully — ${data.variables.length} validated variable(s) found.`;
  tableWrap.classList.add("hidden");
  pickerEl.classList.remove("hidden");
  chartWrap.classList.remove("hidden");

  uploadVariableSelect.innerHTML = data.variables.map((v) => `<option value="${v}">${v}</option>`).join("");
  renderUploadVariable(data.variables[0]);
}

function renderUploadVariable(variable) {
  const data = uploadResultCache;
  if (!data || !data.reports[variable]) return;
  const r = data.reports[variable];

  document.getElementById("upload-metric-cards").innerHTML = [
    metricCard("RMSE", fmtNum(r.rmse, 1)),
    metricCard("Normalized RMSE", `${fmtNum(r.nrmse_pct, 1)}%`),
    metricCard("Willmott's d", fmtNum(r.willmott_d, 3), r.willmott_d > 0.9 ? "good" : ""),
    metricCard("R²", fmtNum(r.r_squared, 3), r.r_squared > 0.9 ? "good" : ""),
  ].join("");

  const treatments = data.treatments_by_variable[variable];
  const labels = treatments.map((t) => `Trt ${t.treatment}`);
  const simulated = treatments.map((t) => t.simulated);
  const measured = treatments.map((t) => t.measured);

  if (uploadChart) uploadChart.destroy();
  uploadChart = new Chart(document.getElementById("upload-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Simulated", data: simulated, backgroundColor: "#4fb286" },
        { label: "Measured", data: measured, backgroundColor: "#e0a94f" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: { display: true, text: `${variable} — ${data.filename}`, color: "#e8edf2" },
        legend: { labels: { color: "#e8edf2" } },
      },
      scales: {
        x: { ticks: { color: "#8ea0b3" }, grid: { color: "#263544" } },
        y: { ticks: { color: "#8ea0b3" }, grid: { color: "#263544" } },
      },
    },
  });
}

uploadVariableSelect.addEventListener("change", () => renderUploadVariable(uploadVariableSelect.value));
runUploadBtn.addEventListener("click", runUpload);

runValidateBtn.addEventListener("click", runValidation);
runCalibrateBtn.addEventListener("click", runCalibration);

// --- Guided tour ---

const TOUR_STEPS = [
  {
    target: null,
    title: "Welcome 👋",
    text: "This tool tests whether a real crop-simulation model (DSSAT) predicts real harvests accurately, and can automatically tune it to fit better. This quick tour walks through every part in under a minute — click Next.",
  },
  {
    target: "experiment-controls-section",
    title: "1. Pick a real experiment",
    text: "This dropdown lists real field experiments — actual crop trials run by researchers decades ago, with real measured outcomes. Nothing here is synthetic data.",
  },
  {
    target: "run-validate-btn",
    title: "2. Run the real model",
    text: "Clicking this runs the actual DSSAT simulation engine (not a shortcut or approximation) using that experiment's real weather, soil, and management data, and asks it to predict the yield.",
  },
  {
    target: "validation-section",
    peek: "validation",
    title: "3. See how close it got",
    text: "Results appear here: the model's prediction next to what was really harvested, plus four different \"how close was it?\" scores. The full guide explains each one in plain English.",
  },
  {
    target: "calibration-controls-section",
    title: "4. Auto-tune the model",
    text: "Crop varieties have internal coefficients nobody knows exactly in advance. This searches many combinations automatically and keeps whichever one best matches the real measured results.",
  },
  {
    target: "calibration-section",
    peek: "calibration",
    title: "5. Calibration results",
    text: "After calibrating, you'll see the error shrink here, plus the specific coefficient values it landed on.",
  },
  {
    target: "upload-section",
    title: "6. Bring your own data",
    text: "Have a real DSSAT experiment file of your own (any crop)? Upload it here and it runs through this same real engine — on your data, not the built-in examples.",
  },
  {
    target: "upload-results-section",
    peek: "upload",
    title: "7. Your results",
    text: "Your uploaded experiment's results appear here the same way — predicted vs. measured, with the same scoring.",
  },
  {
    target: "open-guide-btn",
    title: "8. Full glossary, anytime",
    text: "If a term doesn't make sense later, this button has a complete plain-English explanation of everything on this page.",
  },
  {
    target: null,
    title: "That's it! 🌽",
    text: "You're ready to explore. Pick an experiment above and click Run Validation to see real results.",
  },
];

const tourOverlay = document.getElementById("tour-overlay");
const tourSpotlight = document.getElementById("tour-spotlight");
const tourTooltip = document.getElementById("tour-tooltip");
const tourStepCountEl = document.getElementById("tour-step-count");
const tourTitleEl = document.getElementById("tour-title");
const tourTextEl = document.getElementById("tour-text");
const tourBackBtn = document.getElementById("tour-back-btn");
const tourNextBtn = document.getElementById("tour-next-btn");
const tourSkipBtn = document.getElementById("tour-skip-btn");

let tourIndex = 0;
const tourPeeked = new Set();
const TOUR_PAD = 8;

function tourCleanupPeeks(exceptStepIndex) {
  const exceptPeek = TOUR_STEPS[exceptStepIndex]?.peek;
  tourPeeked.forEach((peekId) => {
    if (peekId === exceptPeek) return;
    if (renderedReal[peekId]) {
      tourPeeked.delete(peekId);
      return;
    }
    const sectionId =
      peekId === "validation"
        ? "validation-section"
        : peekId === "calibration"
        ? "calibration-section"
        : "upload-results-section";
    document.getElementById(sectionId).classList.add("hidden");
    tourPeeked.delete(peekId);
  });
}

function tourShowStep(index) {
  tourCleanupPeeks(index);
  const step = TOUR_STEPS[index];
  tourIndex = index;

  if (step.peek) {
    const sectionId =
      step.peek === "validation"
        ? "validation-section"
        : step.peek === "calibration"
        ? "calibration-section"
        : "upload-results-section";
    const section = document.getElementById(sectionId);
    if (section.classList.contains("hidden")) {
      section.classList.remove("hidden");
      tourPeeked.add(step.peek);
    }
  }

  tourStepCountEl.textContent = `Step ${index + 1} of ${TOUR_STEPS.length}`;
  tourTitleEl.textContent = step.title;
  tourTextEl.textContent = step.text;
  tourBackBtn.style.visibility = index === 0 ? "hidden" : "visible";
  tourNextBtn.textContent = index === TOUR_STEPS.length - 1 ? "Finish" : "Next";

  const target = step.target ? document.getElementById(step.target) : null;
  if (target) {
    target.scrollIntoView({ block: "center", behavior: "instant" });
  }
  // Let scroll + peek-reveal settle before measuring positions.
  requestAnimationFrame(() => tourPositionElements(target));
}

function tourPositionElements(target) {
  if (!target) {
    tourSpotlight.classList.add("tour-no-target");
    tourSpotlight.style.width = "0px";
    tourSpotlight.style.height = "0px";
    tourSpotlight.style.top = "-9999px";
    tourSpotlight.style.left = "-9999px";
    tourTooltip.style.top = "50%";
    tourTooltip.style.left = "50%";
    tourTooltip.style.transform = "translate(-50%, -50%)";
    return;
  }

  tourSpotlight.classList.remove("tour-no-target");
  const rect = target.getBoundingClientRect();
  tourSpotlight.style.top = `${rect.top - TOUR_PAD}px`;
  tourSpotlight.style.left = `${rect.left - TOUR_PAD}px`;
  tourSpotlight.style.width = `${rect.width + TOUR_PAD * 2}px`;
  tourSpotlight.style.height = `${rect.height + TOUR_PAD * 2}px`;

  tourTooltip.style.transform = "none";
  const tooltipWidth = tourTooltip.offsetWidth || 320;
  const spaceBelow = window.innerHeight - rect.bottom;
  const placeBelow = spaceBelow > 200 || rect.top < window.innerHeight / 2;

  if (placeBelow) {
    tourTooltip.style.top = `${rect.bottom + TOUR_PAD + 14}px`;
  } else {
    tourTooltip.style.top = `${Math.max(16, rect.top - TOUR_PAD - 14 - tourTooltip.offsetHeight)}px`;
  }
  const left = Math.min(Math.max(rect.left, 16), window.innerWidth - tooltipWidth - 16);
  tourTooltip.style.left = `${left}px`;
}

function tourStart() {
  tourOverlay.classList.remove("hidden");
  tourShowStep(0);
}

function tourEnd() {
  tourCleanupPeeks(-1);
  tourOverlay.classList.add("hidden");
  try {
    localStorage.setItem("dssat_tour_seen", "1");
  } catch {
    // Private browsing / storage disabled: no big deal, tour just replays each visit.
  }
}

tourNextBtn.addEventListener("click", () => {
  if (tourIndex >= TOUR_STEPS.length - 1) {
    tourEnd();
  } else {
    tourShowStep(tourIndex + 1);
  }
});
tourBackBtn.addEventListener("click", () => {
  if (tourIndex > 0) tourShowStep(tourIndex - 1);
});
tourSkipBtn.addEventListener("click", tourEnd);
document.getElementById("start-tour-btn").addEventListener("click", tourStart);
window.addEventListener("resize", () => {
  if (!tourOverlay.classList.contains("hidden")) {
    const step = TOUR_STEPS[tourIndex];
    tourPositionElements(step.target ? document.getElementById(step.target) : null);
  }
});

loadExperiments();

// Auto-start the tour once per browser for first-time visitors.
try {
  if (!localStorage.getItem("dssat_tour_seen")) {
    tourStart();
  }
} catch {
  // Storage unavailable — just skip the auto-start, manual button still works.
}
