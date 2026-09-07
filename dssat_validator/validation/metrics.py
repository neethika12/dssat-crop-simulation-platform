"""Standard agronomic model-validation statistics.

These are the metrics DSSAT researchers conventionally use to judge whether a
crop model reproduces observed field-trial measurements: RMSE, normalized
RMSE, Willmott's index of agreement (d), and R-squared.
"""

from dataclasses import dataclass

import numpy as np


def _clean(simulated, measured):
    sim = np.asarray(simulated, dtype=float)
    meas = np.asarray(measured, dtype=float)
    mask = np.isfinite(sim) & np.isfinite(meas) & (meas != -99) & (sim != -99)
    if not mask.any():
        raise ValueError("No valid simulated/measured pairs to compare")
    return sim[mask], meas[mask]


def rmse(simulated, measured) -> float:
    sim, meas = _clean(simulated, measured)
    return float(np.sqrt(np.mean((sim - meas) ** 2)))


def normalized_rmse(simulated, measured) -> float:
    """RMSE normalized by the observed mean, expressed as a percentage."""
    sim, meas = _clean(simulated, measured)
    mean_obs = np.mean(meas)
    if mean_obs == 0:
        raise ValueError("Cannot normalize RMSE: mean of measured values is zero")
    return float(np.sqrt(np.mean((sim - meas) ** 2)) / mean_obs * 100)


def willmott_d(simulated, measured) -> float:
    """Willmott's (1981) index of agreement, in [0, 1]; 1 is a perfect fit."""
    sim, meas = _clean(simulated, measured)
    mean_obs = np.mean(meas)
    numerator = np.sum((sim - meas) ** 2)
    denominator = np.sum((np.abs(sim - mean_obs) + np.abs(meas - mean_obs)) ** 2)
    if denominator == 0:
        return 1.0
    return float(1 - numerator / denominator)


def r_squared(simulated, measured) -> float:
    sim, meas = _clean(simulated, measured)
    if len(sim) < 2:
        raise ValueError("Need at least 2 points to compute R-squared")
    corr = np.corrcoef(sim, meas)[0, 1]
    return float(corr**2)


@dataclass
class ValidationReport:
    """Full validation stats for one simulated-vs-measured variable."""

    variable: str
    n: int
    rmse: float
    nrmse_pct: float
    willmott_d: float
    r_squared: float
    mean_simulated: float
    mean_measured: float

    @classmethod
    def compute(cls, variable: str, simulated, measured) -> "ValidationReport":
        sim, meas = _clean(simulated, measured)
        return cls(
            variable=variable,
            n=len(sim),
            rmse=rmse(sim, meas),
            nrmse_pct=normalized_rmse(sim, meas),
            willmott_d=willmott_d(sim, meas),
            r_squared=r_squared(sim, meas) if len(sim) >= 2 else float("nan"),
            mean_simulated=float(np.mean(sim)),
            mean_measured=float(np.mean(meas)),
        )

    def __str__(self) -> str:
        return (
            f"{self.variable}: n={self.n}  RMSE={self.rmse:.2f}  "
            f"nRMSE={self.nrmse_pct:.1f}%  d={self.willmott_d:.3f}  "
            f"R2={self.r_squared:.3f}  (mean sim={self.mean_simulated:.1f}, "
            f"mean obs={self.mean_measured:.1f})"
        )
