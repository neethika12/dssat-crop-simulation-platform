"""
DSSAT Crop Simulation Model Enhancement & Validation Platform.

A computational framework for validating DSSAT crop simulation models against
field trial data, with an automated calibration pipeline for improving
cultivar coefficient accuracy.
"""

from dssat_validator.validation.metrics import (
    rmse,
    normalized_rmse,
    willmott_d,
    r_squared,
    ValidationReport,
)
from dssat_validator.simulation.engine import SimulationEngine, SimulationResult
from dssat_validator.calibration.optimizer import CalibrationPipeline, CalibrationResult

__all__ = [
    "rmse",
    "normalized_rmse",
    "willmott_d",
    "r_squared",
    "ValidationReport",
    "SimulationEngine",
    "SimulationResult",
    "CalibrationPipeline",
    "CalibrationResult",
]

__version__ = "0.1.0"
