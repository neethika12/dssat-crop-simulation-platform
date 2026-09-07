"""Read/write genetic coefficients in a DSSAT cultivar (.CUL) file.

DSSAT genotype files use fixed-width columns: each numeric trait occupies a
6-character, right-justified field, with the field's position determined by
where its name appears in the "@VAR#..." header line. This is the same
convention DSSAT's own XBuild tool and GLUE calibration utility rely on, so
reading the header rather than hardcoding offsets keeps this working across
different crop models (CERES-Maize, CROPGRO, etc.) without changes.
"""

from __future__ import annotations

from pathlib import Path

FIELD_WIDTH = 6


def _load(path: str | Path) -> list[str]:
    return Path(path).read_text().splitlines()


def _header_line(lines: list[str]) -> tuple[int, str]:
    idx = next(i for i, line in enumerate(lines) if line.startswith("@VAR#"))
    return idx, lines[idx]


def _cultivar_line(lines: list[str], header_idx: int, cultivar_code: str) -> int:
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if line[:6].strip() == cultivar_code:
            return i
    raise ValueError(f"Cultivar {cultivar_code!r} not found")


def _field_span(header: str, trait: str) -> tuple[int, int]:
    idx = header.rfind(trait)
    if idx == -1:
        raise ValueError(f"Trait {trait!r} not found in cultivar file header")
    end = idx + len(trait)
    return end - FIELD_WIDTH, end


def read_cultivar_params(
    path: str | Path, cultivar_code: str, traits: list[str]
) -> dict[str, float]:
    """Read named genetic coefficients (e.g. ["P1", "P2", "P5", "G2", "G3"])."""
    lines = _load(path)
    header_idx, header = _header_line(lines)
    data_idx = _cultivar_line(lines, header_idx, cultivar_code)
    line = lines[data_idx]
    values = {}
    for trait in traits:
        start, end = _field_span(header, trait)
        values[trait] = float(line[start:end])
    return values


def write_cultivar_params(
    path: str | Path,
    cultivar_code: str,
    values: dict[str, float],
    out_path: str | Path | None = None,
) -> None:
    """Write new genetic coefficient values for one cultivar, preserving layout."""
    lines = _load(path)
    header_idx, header = _header_line(lines)
    data_idx = _cultivar_line(lines, header_idx, cultivar_code)
    line = lines[data_idx]

    for trait, value in values.items():
        start, end = _field_span(header, trait)
        original = line[start:end]
        decimals = len(original.split(".")[1]) if "." in original else 0
        formatted = f"{value:.{decimals}f}"
        if len(formatted) > FIELD_WIDTH:
            for d in range(decimals - 1, -1, -1):
                formatted = f"{value:.{d}f}"
                if len(formatted) <= FIELD_WIDTH:
                    break
        line = line[:start] + formatted.rjust(FIELD_WIDTH) + line[end:]

    lines[data_idx] = line
    Path(out_path or path).write_text("\n".join(lines) + "\n")
