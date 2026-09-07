"""Discovers and parses real DSSAT FileX experiments that have matching
observed field-trial data, so the web UI can offer a dropdown of real
datasets instead of a single hardcoded one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAIZE_DIR = Path(__file__).resolve().parents[2] / "dssat-data" / "Maize"


@dataclass
class ExperimentInfo:
    code: str
    title: str
    filex_path: Path
    cultivar_code: str
    cultivar_name: str
    n_treatments: int


def _parse_filex(path: Path) -> tuple[str, str, str, int]:
    text = path.read_text(errors="ignore")
    lines = text.splitlines()

    title = lines[0].split(":", 1)[1].strip() if lines and ":" in lines[0] else path.stem

    cultivar_code = cultivar_name = ""
    try:
        idx = next(i for i, line in enumerate(lines) if line.startswith("*CULTIVARS"))
        for line in lines[idx + 2 :]:
            if not line.strip() or line.startswith("*"):
                break
            parts = line.split(None, 3)
            if len(parts) >= 4:
                cultivar_code, cultivar_name = parts[2], parts[3].strip()
                break
    except StopIteration:
        pass

    n_treatments = 0
    try:
        idx = next(i for i, line in enumerate(lines) if line.startswith("*TREATMENTS"))
        for line in lines[idx + 2 :]:
            if not line.strip() or line.startswith("*"):
                break
            if re.match(r"^\s*\d+", line):
                n_treatments += 1
    except StopIteration:
        pass

    return title, cultivar_code, cultivar_name, n_treatments


def list_experiments() -> list[ExperimentInfo]:
    experiments = []
    for filex in sorted(MAIZE_DIR.glob("*.MZX")):
        obs_file = filex.with_suffix(".MZA")
        if not obs_file.exists():
            continue
        title, cultivar_code, cultivar_name, n_treatments = _parse_filex(filex)
        if not cultivar_code or n_treatments == 0:
            continue
        experiments.append(
            ExperimentInfo(
                code=filex.stem,
                title=title,
                filex_path=filex,
                cultivar_code=cultivar_code,
                cultivar_name=cultivar_name,
                n_treatments=n_treatments,
            )
        )
    return experiments


def get_experiment(code: str) -> ExperimentInfo:
    for exp in list_experiments():
        if exp.code == code:
            return exp
    raise KeyError(f"No experiment with data found for code {code!r}")
