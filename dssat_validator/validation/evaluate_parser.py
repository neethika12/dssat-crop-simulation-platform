"""Parser for DSSAT's Evaluate.OUT file.

DSSAT's own Evaluate module already pairs each simulated output with the
matching measured value from the experiment's observed-data file (the .xxA
file sitting next to FileX), when both are present in the run directory.
Evaluate.OUT stores that pairing as adjacent "<VAR>S" / "<VAR>M" columns
(e.g. HWAMS = simulated grain yield, HWAMM = measured grain yield). This
module turns that wide file into a tidy long-format DataFrame.
"""

from pathlib import Path

import pandas as pd

MISSING = -99
_ID_COLUMNS = {"RUN", "EXCODE", "TN", "RN", "CR"}


def parse_evaluate_out(path: str | Path) -> pd.DataFrame:
    """Parse Evaluate.OUT into a long-format DataFrame.

    Returns columns: run, excode, treatment, variable, simulated, measured.
    Rows where the measured value is DSSAT's missing-data code (-99) are
    dropped, since there's nothing to validate against.
    """
    path = Path(path)
    lines = path.read_text().splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("@RUN"))
    header = lines[header_idx].lstrip("@").split()
    data_lines = [
        line for line in lines[header_idx + 1 :] if line.strip() and not line.startswith("*")
    ]
    rows = [line.split() for line in data_lines]
    wide = pd.DataFrame(rows, columns=header)

    pairs = []
    for col in header:
        if col in _ID_COLUMNS or not col.endswith("S"):
            continue
        variable = col[:-1]
        measured_col = variable + "M"
        if measured_col in header:
            pairs.append((variable, col, measured_col))

    records = []
    for _, row in wide.iterrows():
        for variable, sim_col, meas_col in pairs:
            try:
                simulated = float(row[sim_col])
                measured = float(row[meas_col])
            except ValueError:
                continue
            if measured == MISSING:
                continue
            records.append(
                {
                    "run": int(row["RUN"]),
                    "excode": row["EXCODE"],
                    "treatment": int(row["TN"]),
                    "variable": variable,
                    "simulated": simulated,
                    "measured": measured,
                }
            )
    return pd.DataFrame.from_records(records)
