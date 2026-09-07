import shutil
from pathlib import Path

import pytest

from dssat_validator.calibration.cultivar import read_cultivar_params, write_cultivar_params

REPO_ROOT = Path(__file__).resolve().parents[1]
CULTIVAR_FILE = REPO_ROOT / "dssat_home" / "Genotype" / "MZCER048.CUL"


@pytest.fixture
def cultivar_copy(tmp_path):
    if not CULTIVAR_FILE.exists():
        pytest.skip("Real DSSAT genotype data not present in this checkout")
    dest = tmp_path / "MZCER048.CUL"
    shutil.copy(CULTIVAR_FILE, dest)
    return dest


def test_read_known_cultivar(cultivar_copy):
    params = read_cultivar_params(cultivar_copy, "IB0035", ["P1", "P2", "P5", "G2", "G3", "PHINT"])
    assert params["P1"] == pytest.approx(259.0)
    assert params["P2"] == pytest.approx(1.193)
    assert params["G3"] == pytest.approx(8.168)


def test_unknown_cultivar_raises(cultivar_copy):
    with pytest.raises(ValueError):
        read_cultivar_params(cultivar_copy, "ZZ9999", ["P1"])


def test_unknown_trait_raises(cultivar_copy):
    with pytest.raises(ValueError):
        read_cultivar_params(cultivar_copy, "IB0035", ["NOT_A_TRAIT"])


def test_write_then_read_round_trip(cultivar_copy):
    write_cultivar_params(cultivar_copy, "IB0035", {"P1": 275.5, "G2": 850.0})
    params = read_cultivar_params(cultivar_copy, "IB0035", ["P1", "G2", "P5"])
    assert params["P1"] == pytest.approx(275.5)
    assert params["G2"] == pytest.approx(850.0)
    # Untouched trait keeps its original value
    assert params["P5"] == pytest.approx(947.1)


def test_write_preserves_other_cultivars(cultivar_copy):
    before = cultivar_copy.read_text().splitlines()
    write_cultivar_params(cultivar_copy, "IB0035", {"P1": 300.0})
    after = cultivar_copy.read_text().splitlines()
    assert len(before) == len(after)
    # Only the IB0035 line should have changed
    changed = [i for i, (b, a) in enumerate(zip(before, after)) if b != a]
    assert len(changed) == 1
    assert after[changed[0]].startswith("IB0035")


def test_write_respects_field_width(cultivar_copy):
    write_cultivar_params(cultivar_copy, "IB0035", {"P1": 123.456789})
    params = read_cultivar_params(cultivar_copy, "IB0035", ["P1"])
    # Field is 6 chars wide; value must round-trip without corrupting layout
    assert 100 < params["P1"] < 150
