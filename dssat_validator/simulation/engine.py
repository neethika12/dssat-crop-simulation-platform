"""Thin orchestration layer around the real DSSAT-CSM Fortran engine.

DSSAT-CSM's file I/O uses fixed 80-character path buffers (see
InputModule/PATH.for in the DSSAT source). An install placed under a long
path silently overflows that buffer and crashes with a Fortran
"Substring out of bounds" error instead of a helpful message. We work around
this transparently by maintaining a short-named symlink under /tmp that
points at the real (possibly long) install directory, and by always running
DSSAT from a short-named scratch working directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

_SHORT_LINK_ROOT = Path("/tmp")
_PROFILE_TEMPLATE = """\
*** *  DSSAT PROFILE LINUX* ***
DDB // {home}
DTB // {home}
DTE // {home}
DTO // {home}
DAT // {home}
DPT // {home}
DIM // {home}
DTP // {home}
DPF // {home}
DFO // {home}
DIS // {home}
DDW // {home}
DWG // {home}
DWC // {home}
DDS // {home}
DTS // {home}
DDG // {home}
DPM // {home}
DDE // {home}

MMZ // {home}/bin dscsm048 MZCER048
MWH // {home}/bin dscsm048 CSCER048
MSB // {home}/bin dscsm048 CRGRO048
MOT // {home}
MU1 // {home}
MU2 // {home}
MIO // {home}
MLO // {home}

MGR // {home}
NSH // {home}
TOE // / NOTEPAD.EXE
TOS // /
TOM // /
STD // {home}/StandardData
WED // {home}/Weather
WGD // {home}/Weather/Gen
CLD // {home}/Weather/Climate
WMD // {home}/Weather/Month
SLD // {home}/Soil
CRD // {genotype}
FID // {home}
MZD // {home}/Maize
OTD // /
ASD // {home}
AQD // {home}
APD // {home}
PSD // {home}/Pest
ECD // {home}
TOD // /
"""


@dataclass
class SimulationResult:
    """The outcome of one DSSAT-CSM invocation."""

    workdir: Path
    returncode: int
    stdout: str
    stderr: str
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and (self.workdir / "Evaluate.OUT").exists()

    def output_table(self, name: str) -> pd.DataFrame:
        """Load one of DSSAT's fixed-width *.OUT files as a DataFrame.

        `name` is the file stem, e.g. "PlantGro" for PlantGro.OUT. Parses by
        column position (derived from the header line) rather than
        whitespace-splitting, since some columns (e.g. Summary.OUT's
        treatment name) contain embedded spaces.
        """
        path = self.workdir / f"{name}.OUT"
        lines = path.read_text().splitlines()
        header_idx = next(i for i, line in enumerate(lines) if line.startswith("@"))
        header_line = lines[header_idx]
        token_ends = [m.end() for m in re.finditer(r"\S+", header_line)]
        names = [
            header_line[(token_ends[i - 1] if i > 0 else 0) : end].strip().strip(".")
            for i, end in enumerate(token_ends)
        ]
        names[0] = names[0].lstrip("@").strip()
        # DSSAT right-justifies numeric fields, so a field can extend left of
        # its header label into the preceding whitespace gap (e.g. a 5-digit
        # value under a 4-character "HWAM" label). Column boundaries must
        # therefore run from the end of the previous label to the end of
        # this one, not just span the label's own characters.
        spans = [(token_ends[i - 1] if i > 0 else 0, end) for i, end in enumerate(token_ends)]

        rows = []
        for line in lines[header_idx + 1 :]:
            if not line.strip() or line.startswith("*"):
                continue
            padded = line.ljust(len(header_line))
            rows.append([padded[s:e].strip() for s, e in spans])
        return pd.DataFrame(rows, columns=names)

    def evaluate_out_path(self) -> Path:
        return self.workdir / "Evaluate.OUT"


class SimulationEngine:
    """Runs DSSAT-CSM experiments against a real DSSAT data install."""

    def __init__(self, dssat_home: str | Path):
        self.dssat_home = Path(dssat_home).resolve()
        if not (self.dssat_home / "bin" / "dscsm048").exists():
            raise FileNotFoundError(
                f"No dscsm048 executable found under {self.dssat_home}/bin. "
                "Build DSSAT-CSM from source first (see docs/BUILD.md)."
            )
        self._home_link = self._short_symlink(self.dssat_home, "dssat48home")

    @staticmethod
    def _short_symlink(target: Path, name: str) -> Path:
        link = _SHORT_LINK_ROOT / name
        if link.is_symlink() or link.exists():
            if link.resolve() != target:
                link.unlink()
                link.symlink_to(target)
        else:
            link.symlink_to(target)
        return link

    def run_experiment(
        self,
        filex_path: str | Path,
        run_mode: str = "A",
        genotype_dir: str | Path | None = None,
        workdir: str | Path | None = None,
        timeout: float = 120,
    ) -> SimulationResult:
        """Run every treatment in a FileX experiment file through DSSAT-CSM.

        If a matching observed-data file (.xxA / .xxT, same basename as
        FileX) exists next to it, it's copied into the run directory so
        DSSAT's built-in Evaluate module produces simulated-vs-measured
        pairs in Evaluate.OUT.

        `genotype_dir` overrides where DSSAT looks up cultivar/species files
        (used by the calibration pipeline to test trial coefficients without
        touching the shared genotype database).
        """
        filex_path = Path(filex_path).resolve()
        workdir = Path(workdir) if workdir else Path(
            tempfile.mkdtemp(dir="/tmp", prefix="dssat_run_")
        )
        workdir.mkdir(parents=True, exist_ok=True)

        genotype_link = self._home_link / "Genotype"
        if genotype_dir is not None:
            genotype_link = self._short_symlink(
                Path(genotype_dir).resolve(), f"dssat48geno_{uuid.uuid4().hex[:8]}"
            )

        profile = _PROFILE_TEMPLATE.format(home=self._home_link, genotype=genotype_link)
        (workdir / "DSSATPRO.L48").write_text(profile)

        for cde_file in self.dssat_home.glob("*.CDE"):
            shutil.copy(cde_file, workdir / cde_file.name)
        ctr = self.dssat_home / "DSCSM048.CTR"
        if ctr.exists():
            shutil.copy(ctr, workdir / ctr.name)

        shutil.copy(filex_path, workdir / filex_path.name)
        stem, ext = filex_path.stem, filex_path.suffix  # e.g. UFGA8201, .MZX
        for obs_letter in ("A", "T"):
            obs_path = filex_path.with_name(f"{stem}{ext[:-1]}{obs_letter}")
            if obs_path.exists():
                shutil.copy(obs_path, workdir / obs_path.name)

        binary = self._home_link / "bin" / "dscsm048"
        proc = subprocess.run(
            [str(binary), run_mode, filex_path.name],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return SimulationResult(
            workdir=workdir, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
        )
