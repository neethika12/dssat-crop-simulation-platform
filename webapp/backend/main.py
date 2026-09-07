"""Web API for the DSSAT Crop Simulation Model Enhancement & Validation Platform.

Wraps the dssat_validator package (which drives the real, natively-compiled
DSSAT-CSM engine) behind a small FastAPI service so the dashboard can run
validations and calibration against real field-trial data interactively.
"""

from __future__ import annotations

import math
import re
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


def _safe(value: float) -> float | None:
    """NaN/inf isn't valid JSON; DSSAT variables with zero variance across
    treatments (e.g. every treatment planted the same day) produce a
    mathematically undefined R-squared, so this surfaces as null rather
    than crashing response serialization."""
    return value if math.isfinite(value) else None


def _report_dict(report: ValidationReport) -> dict:
    return {
        "n": report.n,
        "rmse": _safe(report.rmse),
        "nrmse_pct": _safe(report.nrmse_pct),
        "willmott_d": _safe(report.willmott_d),
        "r_squared": _safe(report.r_squared),
        "mean_simulated": _safe(report.mean_simulated),
        "mean_measured": _safe(report.mean_measured),
    }

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
        "report": _report_dict(report),
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


_FILEX_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z]{2}X$")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # DSSAT experiment files are plain text, KBs in size


async def _read_capped(upload: UploadFile, label: str) -> bytes:
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{label} is too large (max 2MB).")
    return data


@app.post("/api/upload/validate")
async def api_upload_validate(
    filex: UploadFile = File(..., description="A real DSSAT FileX experiment file, e.g. MYEXP01.MZX"),
    observed: UploadFile | None = File(
        None, description="Matching observed-data summary file (.xxA), optional"
    ),
    observed_timeseries: UploadFile | None = File(
        None, description="Matching observed-data time-series file (.xxT), optional"
    ),
):
    filename = filex.filename or ""
    if not _FILEX_NAME_RE.match(filename):
        raise HTTPException(
            status_code=400,
            detail=(
                "That doesn't look like a DSSAT FileX filename. It should look like "
                "'MYEXP01.MZX' (maize), 'MYEXP01.SBX' (soybean), 'MYEXP01.WHX' (wheat), "
                "etc. — a short code, then a 2-letter crop code, then X."
            ),
        )

    engine = get_engine()
    workdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="dssat_upload_"))
    try:
        filex_bytes = await _read_capped(filex, "Experiment file")
        filex_path = workdir / filename
        filex_path.write_bytes(filex_bytes)

        stem = filex_path.stem
        obs_prefix = filex_path.suffix[:-1]  # e.g. ".MZX" -> ".MZ"

        if observed is not None:
            data = await _read_capped(observed, "Observed-data file")
            (workdir / f"{stem}{obs_prefix}A").write_bytes(data)
        if observed_timeseries is not None:
            data = await _read_capped(observed_timeseries, "Observed time-series file")
            (workdir / f"{stem}{obs_prefix}T").write_bytes(data)

        result = engine.run_experiment(filex_path)
        if not result.ok:
            raise HTTPException(
                status_code=422,
                detail=(
                    "DSSAT-CSM could not run this file. This is the model's own error "
                    f"message, not a bug in this tool:\n\n{result.stderr[-1500:]}"
                ),
            )

        df = parse_evaluate_out(result.evaluate_out_path())
        if df.empty:
            summary = result.output_table("Summary")
            candidate_cols = [c for c in ("HWAM", "CWAM", "BWAH", "MDAT", "ADAT") if c in summary.columns]
            keep_cols = [c for c in ("TRNO", "TNAM", *candidate_cols) if c in summary.columns]
            return {
                "has_observed_data": False,
                "filename": filename,
                "simulated_summary": summary[keep_cols].to_dict(orient="records"),
                "message": (
                    "No matching observed-data file was recognized (or none was "
                    "uploaded), so these are simulated values only — nothing to "
                    "validate them against yet. Upload a .xxA observed-data file "
                    "alongside the experiment to get RMSE/R²/etc."
                ),
            }

        variables = sorted(df["variable"].unique().tolist())
        reports: dict = {}
        treatments_by_variable: dict = {}
        skipped: list[str] = []
        for var in variables:
            subset = df[df["variable"] == var]
            try:
                report = ValidationReport.compute(var, subset["simulated"], subset["measured"])
            except ValueError:
                skipped.append(var)
                continue
            reports[var] = _report_dict(report)
            treatments_by_variable[var] = [
                {
                    "treatment": int(row["treatment"]),
                    "simulated": row["simulated"],
                    "measured": row["measured"],
                }
                for _, row in subset.sort_values("treatment").iterrows()
            ]

        return {
            "has_observed_data": True,
            "filename": filename,
            "variables": list(reports.keys()),
            "reports": reports,
            "treatments_by_variable": treatments_by_variable,
            "skipped_variables": skipped,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
