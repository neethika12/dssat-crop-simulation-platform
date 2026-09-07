"""Web API for the DSSAT Crop Simulation Model Enhancement & Validation Platform.

Wraps the dssat_validator package (which drives the real, natively-compiled
DSSAT-CSM engine) behind a small FastAPI service so the dashboard can run
validations and calibration against real field-trial data interactively.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dssat_validator import CalibrationPipeline, SimulationEngine, ValidationReport  # noqa: E402
from dssat_validator.validation.evaluate_parser import parse_evaluate_out  # noqa: E402
from experiments import ExperimentInfo, get_experiment, list_experiments  # noqa: E402

DSSAT_HOME = REPO_ROOT / "dssat_home"
CULTIVAR_FILE = DSSAT_HOME / "Genotype" / "MZCER048.CUL"

DEFAULT_BOUNDS = {
    "P1": (150.0, 400.0),
    "P2": (0.1, 2.0),
    "P5": (600.0, 1100.0),
    "G2": (600.0, 1100.0),
    "G3": (5.0, 13.0),
}

app = FastAPI(title="DSSAT Crop Simulation Validation Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine: SimulationEngine | None = None


def get_engine() -> SimulationEngine:
    global _engine
    if _engine is None:
        if not (DSSAT_HOME / "bin" / "dscsm048").exists():
            raise HTTPException(
                status_code=503,
                detail="DSSAT-CSM engine not built. See docs/BUILD.md.",
            )
        _engine = SimulationEngine(DSSAT_HOME)
    return _engine


class CalibrateRequest(BaseModel):
    experiment_code: str
    target_variable: str = "HWAM"
    metric: str = "rmse"
    maxiter: int = Field(default=2, ge=1, le=8)
    popsize: int = Field(default=3, ge=2, le=6)


@app.get("/api/experiments")
def api_list_experiments():
    return [
        {
            "code": e.code,
            "title": e.title,
            "cultivar_code": e.cultivar_code,
            "cultivar_name": e.cultivar_name,
            "n_treatments": e.n_treatments,
        }
        for e in list_experiments()
    ]


def _run_and_validate(experiment: ExperimentInfo, target_variable: str, genotype_dir=None):
    engine = get_engine()
    result = engine.run_experiment(experiment.filex_path, genotype_dir=genotype_dir)
    if not result.ok:
        raise HTTPException(status_code=500, detail=f"DSSAT run failed: {result.stderr[-800:]}")

    df = parse_evaluate_out(result.evaluate_out_path())
    subset = df[df["variable"] == target_variable]
    if subset.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No observed data for variable {target_variable!r} in this experiment.",
        )
    report = ValidationReport.compute(target_variable, subset["simulated"], subset["measured"])
    return subset, report


@app.get("/api/validate")
def api_validate(experiment_code: str, target_variable: str = "HWAM"):
    try:
        experiment = get_experiment(experiment_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    subset, report = _run_and_validate(experiment, target_variable)

    return {
        "experiment": experiment.title,
        "cultivar": f"{experiment.cultivar_code} ({experiment.cultivar_name})",
        "variable": target_variable,
        "treatments": [
            {
                "treatment": int(row["treatment"]),
                "simulated": row["simulated"],
                "measured": row["measured"],
            }
            for _, row in subset.sort_values("treatment").iterrows()
        ],
        "report": {
            "n": report.n,
            "rmse": report.rmse,
            "nrmse_pct": report.nrmse_pct,
            "willmott_d": report.willmott_d,
            "r_squared": report.r_squared,
            "mean_simulated": report.mean_simulated,
            "mean_measured": report.mean_measured,
        },
    }


MAX_CALIBRATION_EVALUATIONS = 70  # keeps worst case under ~2 min on a slow free-tier host


@app.post("/api/calibrate")
def api_calibrate(req: CalibrateRequest):
    try:
        experiment = get_experiment(req.experiment_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    n_params = len(DEFAULT_BOUNDS)
    estimated_evaluations = req.popsize * n_params * (req.maxiter + 1)
    if estimated_evaluations > MAX_CALIBRATION_EVALUATIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Generations x population is too high for this host "
                f"(~{estimated_evaluations} simulation runs requested, "
                f"{MAX_CALIBRATION_EVALUATIONS} max). Lower one or both."
            ),
        )

    engine = get_engine()
    _, baseline_report = _run_and_validate(experiment, req.target_variable)

    pipeline = CalibrationPipeline(
        engine=engine,
        filex_path=experiment.filex_path,
        cultivar_file=CULTIVAR_FILE,
        cultivar_code=experiment.cultivar_code,
        target_variable=req.target_variable,
        metric=req.metric,
    )
    try:
        result = pipeline.calibrate(
            bounds=DEFAULT_BOUNDS, maxiter=req.maxiter, popsize=req.popsize
        )
    finally:
        pipeline.cleanup()

    baseline_score = getattr(baseline_report, req.metric if req.metric != "nrmse" else "nrmse_pct")
    improvement_pct = (
        (1 - result.best_score / baseline_score) * 100
        if req.metric != "willmott_d"
        else (result.best_score - baseline_score) / max(abs(baseline_score), 1e-9) * 100
    )

    history = [
        {k: v for k, v in h.items() if k != "failed"}
        for h in result.history
        if not h.get("failed")
    ]

    return {
        "experiment": experiment.title,
        "cultivar": f"{experiment.cultivar_code} ({experiment.cultivar_name})",
        "metric": req.metric,
        "baseline_score": baseline_score,
        "calibrated_score": result.best_score,
        "improvement_pct": improvement_pct,
        "best_params": result.best_params,
        "n_evaluations": result.n_evaluations,
        "history": history,
    }


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
