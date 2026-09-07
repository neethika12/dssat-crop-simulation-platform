import numpy as np
import pytest

from dssat_validator.validation.metrics import (
    ValidationReport,
    normalized_rmse,
    r_squared,
    rmse,
    willmott_d,
)


def test_rmse_perfect_fit():
    assert rmse([1, 2, 3], [1, 2, 3]) == 0.0


def test_rmse_known_value():
    assert rmse([2, 2], [0, 0]) == pytest.approx(2.0)


def test_normalized_rmse():
    result = normalized_rmse([110, 90], [100, 100])
    assert result == pytest.approx(10.0)


def test_normalized_rmse_zero_mean_raises():
    with pytest.raises(ValueError):
        normalized_rmse([1, -1], [1, -1])


def test_willmott_d_perfect_fit():
    assert willmott_d([5, 6, 7], [5, 6, 7]) == pytest.approx(1.0)


def test_willmott_d_bounded():
    d = willmott_d([1, 5, 2, 9], [3, 3, 3, 3])
    assert 0.0 <= d <= 1.0


def test_r_squared_perfect_linear_relationship():
    sim = np.array([1, 2, 3, 4])
    meas = 2 * sim + 1
    assert r_squared(sim, meas) == pytest.approx(1.0)


def test_missing_values_are_excluded():
    sim = [100, 200, -99]
    meas = [110, 190, -99]
    report = ValidationReport.compute("test", sim, meas)
    assert report.n == 2


def test_validation_report_str_contains_variable_name():
    report = ValidationReport.compute("HWAM", [100, 200], [110, 190])
    assert "HWAM" in str(report)


def test_no_valid_pairs_raises():
    with pytest.raises(ValueError):
        rmse([-99, -99], [-99, -99])
