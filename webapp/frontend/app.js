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

function setLoading(on, text) {
  loadingOverlay.classList.toggle("hidden", !on);
  if (text) loadingText.textContent = text;
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
  try {
    const code = experimentSelect.value;
    const res = await fetch(`${API_BASE}/api/validate?experiment_code=${encodeURIComponent(code)}`);
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderValidation(data);
  } catch (err) {
    alert(`Validation failed: ${err.message}`);
  } finally {
    setLoading(false);
    runValidateBtn.disabled = false;
  }
}

function renderValidation(data) {
  document.getElementById("validation-section").classList.remove("hidden");
  const r = data.report;
  document.getElementById("metric-cards").innerHTML = [
    metricCard("RMSE", `${r.rmse.toFixed(1)}`, ""),
    metricCard("Normalized RMSE", `${r.nrmse_pct.toFixed(1)}%`, ""),
    metricCard("Willmott's d", r.willmott_d.toFixed(3), r.willmott_d > 0.9 ? "good" : ""),
    metricCard("R²", r.r_squared.toFixed(3), r.r_squared > 0.9 ? "good" : ""),
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
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderCalibration(data);
  } catch (err) {
    alert(`Calibration failed: ${err.message}`);
  } finally {
    setLoading(false);
    runCalibrateBtn.disabled = false;
  }
}

function renderCalibration(data) {
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

runValidateBtn.addEventListener("click", runValidation);
runCalibrateBtn.addEventListener("click", runCalibration);

loadExperiments();
