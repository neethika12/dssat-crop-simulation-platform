from pathlib import Path

from dssat_validator.validation.evaluate_parser import parse_evaluate_out

SAMPLE = """\
*EVALUATION : SAMPLE TEST                                                              DSSAT Cropping System Model Ver. 4.8.6.000

@RUN EXCODE        TN RN CR   HWAMS   HWAMM   LAIXS   LAIXM
   1 TEST0001MZ     1  1 MZ    2293    2929.    1.99    2.26
   2 TEST0001MZ     2  1 MZ    2293      -99    3.27      -99
"""


def test_parses_simulated_measured_pairs(tmp_path: Path):
    out_file = tmp_path / "Evaluate.OUT"
    out_file.write_text(SAMPLE)

    df = parse_evaluate_out(out_file)

    assert set(df["variable"]) == {"HWAM", "LAIX"}
    hwam = df[df["variable"] == "HWAM"]
    assert len(hwam) == 1  # second row's HWAMM is -99 (missing) and is dropped
    assert hwam.iloc[0]["simulated"] == 2293.0
    assert hwam.iloc[0]["measured"] == 2929.0


def test_missing_measured_rows_are_dropped(tmp_path: Path):
    out_file = tmp_path / "Evaluate.OUT"
    out_file.write_text(SAMPLE)

    df = parse_evaluate_out(out_file)
    laix = df[df["variable"] == "LAIX"]
    assert len(laix) == 1
    assert laix.iloc[0]["treatment"] == 1
