"""End-to-end demo: run a real field-trial experiment through DSSAT-CSM,
validate it against real observed data, then calibrate cultivar
coefficients to improve the fit.

Usage:
    python examples/run_validation_demo.py
"""

from pathlib import Path

from dssat_validator import CalibrationPipeline, SimulationEngine, ValidationReport
from dssat_validator.validation.evaluate_parser import parse_evaluate_out

REPO_ROOT = Path(__file__).resolve().parents[1]
DSSAT_HOME = REPO_ROOT / "dssat_home"
EXPERIMENT = REPO_ROOT / "dssat-data" / "Maize" / "UFGA8201.MZX"
CULTIVAR_FILE = DSSAT_HOME / "Genotype" / "MZCER048.CUL"


def main() -> None:
    print(f"Simulating {EXPERIMENT.name} (UF Gainesville, 1982 N x irrigation maize trial)\n")

    engine = SimulationEngine(DSSAT_HOME)
    result = engine.run_experiment(EXPERIMENT)
    if not result.ok:
        raise SystemExit(f"Simulation failed:\n{result.stderr}")

    df = parse_evaluate_out(result.evaluate_out_path())
    hwam = df[df["variable"] == "HWAM"]

    baseline = ValidationReport.compute("HWAM (grain yield, kg/ha) - default cultivar", hwam["simulated"], hwam["measured"])
    print("Baseline validation (default IB0035 cultivar coefficients):")
    print(f"  {baseline}\n")

    print("Running automated calibration (differential evolution over P1, P2, P5, G2, G3)...")
    pipeline = CalibrationPipeline(
        engine=engine,
        filex_path=EXPERIMENT,
        cultivar_file=CULTIVAR_FILE,
        cultivar_code="IB0035",
        target_variable="HWAM",
        metric="rmse",
    )
    try:
        calibration = pipeline.calibrate(
            bounds={
                "P1": (200.0, 320.0),
                "P2": (0.3, 2.0),
                "P5": (700.0, 1000.0),
                "G2": (700.0, 1000.0),
                "G3": (6.0, 11.0),
            },
            maxiter=8,
            popsize=8,
        )
    finally:
        pipeline.cleanup()

    print(f"\nCalibrated RMSE: {calibration.best_score:.1f} kg/ha "
          f"(baseline was {baseline.rmse:.1f} kg/ha, "
          f"{(1 - calibration.best_score / baseline.rmse) * 100:.1f}% improvement)")
    print(f"Best coefficients: {calibration.best_params}")
    print(f"Total DSSAT-CSM runs evaluated: {calibration.n_evaluations}")


if __name__ == "__main__":
    main()
