"""Automated cultivar-coefficient calibration.

Searches DSSAT genetic coefficients (e.g. P1, P2, P5, G2, G3 for
CERES-Maize) to minimize the error between simulated and observed yield (or
another target variable) across every treatment in a field-trial experiment.
Each trial writes candidate coefficients into an isolated scratch copy of
the genotype database, so calibration never mutates the shared DSSAT
install and repeated/parallel calibration runs stay independent.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from scipy.optimize import differential_evolution

from dssat_validator.calibration.cultivar import write_cultivar_params
from dssat_validator.simulation.engine import SimulationEngine
from dssat_validator.validation.evaluate_parser import parse_evaluate_out
from dssat_validator.validation.metrics import normalized_rmse, rmse, willmott_d

_METRICS = {
    "rmse": (rmse, False),
    "nrmse": (normalized_rmse, False),
    "willmott_d": (willmott_d, True),  # maximize
}


@dataclass
class CalibrationResult:
    best_params: dict[str, float]
    best_score: float
    metric: str
    n_evaluations: int
    history: list[dict] = field(default_factory=list)


class CalibrationPipeline:
    def __init__(
        self,
        engine: SimulationEngine,
        filex_path: str | Path,
        cultivar_file: str | Path,
        cultivar_code: str,
        target_variable: str = "HWAM",
        metric: str = "rmse",
    ):
        if metric not in _METRICS:
            raise ValueError(f"Unknown metric {metric!r}; choose from {list(_METRICS)}")
        self.engine = engine
        self.filex_path = Path(filex_path)
        self.cultivar_code = cultivar_code
        self.target_variable = target_variable
        self.metric_name = metric
        self._metric_fn, self._maximize = _METRICS[metric]
        self.history: list[dict] = []

        self._scratch_genotype = Path(tempfile.mkdtemp(dir="/tmp", prefix="dssat_geno_"))
        shutil.copytree(
            Path(engine.dssat_home) / "Genotype", self._scratch_genotype, dirs_exist_ok=True
        )
        self._scratch_cultivar_file = self._scratch_genotype / Path(cultivar_file).name
        self._workdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="dssat_calib_"))

    def _objective(self, x, param_names: list[str]) -> float:
        values = dict(zip(param_names, x))
        write_cultivar_params(self._scratch_cultivar_file, self.cultivar_code, values)

        result = self.engine.run_experiment(
            self.filex_path, genotype_dir=self._scratch_genotype, workdir=self._workdir
        )
        penalty = 1e6
        if not result.ok:
            self.history.append({**values, "score": penalty, "failed": True})
            return penalty

        df = parse_evaluate_out(result.evaluate_out_path())
        subset = df[df["variable"] == self.target_variable]
        if subset.empty:
            self.history.append({**values, "score": penalty, "failed": True})
            return penalty

        score = self._metric_fn(subset["simulated"], subset["measured"])
        self.history.append({**values, "score": score, "failed": False})
        return -score if self._maximize else score

    def calibrate(
        self,
        bounds: dict[str, tuple[float, float]],
        maxiter: int = 15,
        popsize: int = 10,
        seed: int = 42,
    ) -> CalibrationResult:
        param_names = list(bounds.keys())
        bound_list = [bounds[p] for p in param_names]

        result = differential_evolution(
            self._objective,
            bound_list,
            args=(param_names,),
            maxiter=maxiter,
            popsize=popsize,
            seed=seed,
            polish=False,
            workers=1,
        )
        best_score = -result.fun if self._maximize else result.fun
        return CalibrationResult(
            best_params=dict(zip(param_names, result.x)),
            best_score=best_score,
            metric=self.metric_name,
            n_evaluations=result.nfev,
            history=self.history,
        )

    def cleanup(self) -> None:
        shutil.rmtree(self._scratch_genotype, ignore_errors=True)
        shutil.rmtree(self._workdir, ignore_errors=True)
