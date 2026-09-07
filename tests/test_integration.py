"""End-to-end test against the real compiled DSSAT-CSM engine.

Skipped automatically if the engine hasn't been built in this checkout
(see docs/BUILD.md) — these tests exercise the actual Fortran model on a
real 1982 University of Florida field-trial experiment, not a mock.
"""

from pathlib import Path

import pytest

from dssat_validator import SimulationEngine, ValidationReport
from dssat_validator.validation.evaluate_parser import parse_evaluate_out

REPO_ROOT = Path(__file__).resolve().parents[1]
DSSAT_HOME = REPO_ROOT / "dssat_home"
UFGA_EXPERIMENT = REPO_ROOT / "dssat-data" / "Maize" / "UFGA8201.MZX"

pytestmark = pytest.mark.skipif(
    not (DSSAT_HOME / "bin" / "dscsm048").exists(),
    reason="DSSAT-CSM not built in this checkout; see docs/BUILD.md",
)


@pytest.fixture(scope="module")
def engine():
    return SimulationEngine(DSSAT_HOME)


def test_engine_rejects_missing_install(tmp_path):
    with pytest.raises(FileNotFoundError):
        SimulationEngine(tmp_path)


def test_real_experiment_runs_successfully(engine):
    result = engine.run_experiment(UFGA_EXPERIMENT)
    assert result.ok, result.stderr


def test_all_six_treatments_present(engine):
    result = engine.run_experiment(UFGA_EXPERIMENT)
    summary = result.output_table("Summary")
    assert len(summary) == 6


def test_simulated_yield_validates_against_real_field_data(engine):
    result = engine.run_experiment(UFGA_EXPERIMENT)
    df = parse_evaluate_out(result.evaluate_out_path())
    hwam = df[df["variable"] == "HWAM"]

    assert len(hwam) == 6  # 6 treatments, all with observed yield data

    report = ValidationReport.compute("HWAM", hwam["simulated"], hwam["measured"])
    # Default (uncalibrated) CERES-Maize should be in the right ballpark for
    # this well-studied tutorial dataset, not exact.
    assert report.nrmse_pct < 25
    assert report.willmott_d > 0.8


def test_irrigated_high_nitrogen_treatment_is_highest_yielding(engine):
    result = engine.run_experiment(UFGA_EXPERIMENT)
    summary = result.output_table("Summary")
    summary["HWAM"] = summary["HWAM"].astype(float)
    best_treatment = summary.loc[summary["HWAM"].idxmax(), "TNAM"]
    assert "IRRIGATED HIGH NITROGEN" in best_treatment
