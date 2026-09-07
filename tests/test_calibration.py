"""Integration test for the automated calibration pipeline against the real
DSSAT-CSM engine. Skipped if the engine hasn't been built (see docs/BUILD.md).
"""

from pathlib import Path

import pytest

from dssat_validator import SimulationEngine
from dssat_validator.calibration import CalibrationPipeline
from dssat_validator.validation.evaluate_parser import parse_evaluate_out
from dssat_validator.validation.metrics import rmse

REPO_ROOT = Path(__file__).resolve().parents[1]
DSSAT_HOME = REPO_ROOT / "dssat_home"
UFGA_EXPERIMENT = REPO_ROOT / "dssat-data" / "Maize" / "UFGA8201.MZX"
CULTIVAR_FILE = DSSAT_HOME / "Genotype" / "MZCER048.CUL"

pytestmark = pytest.mark.skipif(
    not (DSSAT_HOME / "bin" / "dscsm048").exists(),
    reason="DSSAT-CSM not built in this checkout; see docs/BUILD.md",
)


def _baseline_rmse() -> float:
    engine = SimulationEngine(DSSAT_HOME)
    result = engine.run_experiment(UFGA_EXPERIMENT)
    df = parse_evaluate_out(result.evaluate_out_path())
    hwam = df[df["variable"] == "HWAM"]
    return rmse(hwam["simulated"], hwam["measured"])


def test_calibration_improves_on_default_coefficients():
    baseline = _baseline_rmse()

    engine = SimulationEngine(DSSAT_HOME)
    pipeline = CalibrationPipeline(
        engine=engine,
        filex_path=UFGA_EXPERIMENT,
        cultivar_file=CULTIVAR_FILE,
        cultivar_code="IB0035",
        target_variable="HWAM",
        metric="rmse",
    )
    try:
        result = pipeline.calibrate(
            bounds={
                "P1": (200.0, 320.0),
                "P2": (0.3, 2.0),
                "P5": (700.0, 1000.0),
                "G2": (700.0, 1000.0),
                "G3": (6.0, 11.0),
            },
            maxiter=4,
            popsize=6,
            seed=7,
        )
    finally:
        pipeline.cleanup()

    assert result.best_score < baseline
    assert result.n_evaluations > 0


def test_calibration_does_not_mutate_shared_genotype_file():
    original = CULTIVAR_FILE.read_text()

    engine = SimulationEngine(DSSAT_HOME)
    pipeline = CalibrationPipeline(
        engine=engine,
        filex_path=UFGA_EXPERIMENT,
        cultivar_file=CULTIVAR_FILE,
        cultivar_code="IB0035",
        metric="rmse",
    )
    try:
        pipeline.calibrate(
            bounds={"P1": (200.0, 320.0), "G3": (6.0, 11.0)}, maxiter=2, popsize=4, seed=1
        )
    finally:
        pipeline.cleanup()

    assert CULTIVAR_FILE.read_text() == original
