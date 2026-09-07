# DSSAT Crop Simulation Model Enhancement & Validation Platform

A computational framework for validating [DSSAT](https://dssat.net/) crop
simulation models against real field-trial data, with an automated
calibration pipeline for improving cultivar genetic-coefficient accuracy.

This drives the **real DSSAT-CSM Fortran engine** — compiled natively from
official source, not a mock or a Python re-implementation — against **real
field-trial data** from DSSAT's own example dataset: a 1982 University of
Florida (Gainesville) nitrogen x irrigation maize experiment (`UFGA8201`).

## Why this exists

The public `DSSATTools` Python package only ships a precompiled Linux
x86-64 binary, so it doesn't run natively on Apple Silicon or any
non-Linux host. This project instead:

1. Compiles [DSSAT-CSM](https://github.com/DSSAT/dssat-csm-os) from its
   official Fortran source for the local platform (see
   [docs/BUILD.md](docs/BUILD.md)).
2. Works around DSSAT's fixed 80-character path-buffer limit, which
   otherwise crashes the model when installed under a normal (long)
   directory path.
3. Wraps it in a Python framework for validation and calibration that
   researchers can drop into an existing analysis pipeline.

## Architecture

```
dssat_validator/
  simulation/engine.py     Orchestrates DSSAT-CSM runs: builds a scratch
                            workspace, generates the DSSATPRO.L48 config,
                            invokes the compiled binary, parses output.
  validation/
    evaluate_parser.py      Parses DSSAT's own Evaluate.OUT (simulated vs.
                             measured pairs) into a tidy DataFrame.
    metrics.py               RMSE, normalized RMSE, Willmott's d,
                              R-squared — the standard agronomic model-
                              validation statistics.
  calibration/
    cultivar.py               Reads/writes genetic coefficients (P1, P2,
                               P5, G2, G3, ...) in a DSSAT .CUL file,
                               using its fixed-width column convention.
    optimizer.py               Differential-evolution search over cultivar
                                coefficients that minimizes simulated-vs-
                                measured error, using an isolated scratch
                                copy of the genotype database per run so
                                calibration never mutates shared data.
```

## Real results

Running the uncalibrated `IB0035` (McCurdy 84aa) cultivar against all six
treatments of the real UFGA8201 experiment:

```
HWAM (grain yield, kg/ha): n=6  RMSE=970.3  nRMSE=14.4%  d=0.980  R2=0.951
```

Automated calibration (differential evolution over P1, P2, P5, G2, G3,
360 real DSSAT-CSM simulation runs, ~60s):

```
Calibrated RMSE: 547.1 kg/ha (44% improvement over baseline)
```

## Usage

```python
from dssat_validator import SimulationEngine, CalibrationPipeline, ValidationReport
from dssat_validator.validation.evaluate_parser import parse_evaluate_out

engine = SimulationEngine("dssat_home")
result = engine.run_experiment("dssat-data/Maize/UFGA8201.MZX")

df = parse_evaluate_out(result.evaluate_out_path())
hwam = df[df.variable == "HWAM"]
print(ValidationReport.compute("HWAM", hwam.simulated, hwam.measured))
```

See [examples/run_validation_demo.py](examples/run_validation_demo.py) for
the full validate-then-calibrate workflow.

## Web dashboard

A FastAPI + vanilla-JS dashboard (`webapp/`) puts validation and
calibration behind a browser UI instead of a script: pick any of the 10
real field-trial experiments with observed data bundled in
`dssat-csm-data`, run a live DSSAT-CSM simulation, see simulated-vs-measured
yield per treatment and the RMSE/nRMSE/d/R² report, then kick off
calibration and watch the convergence chart and best coefficients come
back.

```bash
source venv/bin/activate
python -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8420
```

Then open http://localhost:8420. `webapp/backend/main.py` exposes
`GET /api/experiments`, `GET /api/validate`, `POST /api/calibrate`, and
`POST /api/upload/validate`, all backed directly by the `dssat_validator`
package above — no separate simulation logic, just a thin API layer over
the same real engine.

The dashboard includes an in-app **"How This Works"** guide (plain-English,
no DSSAT background assumed) and a **"Test With Your Own Data"** upload
form: upload any real DSSAT FileX experiment file (any crop — the engine's
model-lookup table covers the full DSSAT crop list, not just maize) plus
an optional observed-data file, and it runs through the same real
DSSAT-CSM engine as the bundled examples. If DSSAT can't run the uploaded
file, the model's own error message is surfaced rather than a generic
failure. Calibration is currently wired up only for the bundled reference
experiments (it needs to know which cultivar/genotype file to adjust).

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

Then follow [docs/BUILD.md](docs/BUILD.md) to compile the real DSSAT-CSM
engine and pull the example field-trial data (the engine binary isn't
checked into the repo — it's platform-specific).

## Testing

```bash
pytest tests/ -v
```

Unit tests (metrics, cultivar-file parsing) always run. Integration tests
that exercise the real compiled engine are skipped automatically if it
hasn't been built in the current checkout.
