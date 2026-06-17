"""Stage files into the calibration directory.

Extracted from ``PWA/_notebooks/4_calibrate.ipynb`` sections 1.1–1.3.
The notebook walked through six numbered substeps, each copying a
different category of files from the watershed's processed-data folder
into ``Data/Calibration/{watershed}/``:

1.3.1 Raven binary
1.3.2 Depression-depths shapefile pieces
1.3.3 GridWeights.txt
1.3.4 Raven .rv* config files (with ``_adj`` injection in the .rvt)
1.3.5 SPOTPY template files + the .nc forcing file (renamed ``_tpl``)
1.3.6 Aspect ratios + HRU areas + tp/tc + WSC outlet

Refactor notes
--------------
* ``input()`` calls (watershed name, NetCDF category) are gone — both
  are now :class:`StagingPaths` arguments. Notebook code stays
  notebook code; library code does not block on stdin.
* Backslash path concatenation (``BS_DATA_PATH + "/{}/Raven/..."``)
  → ``pathlib.Path``.
* The .nc reference rewrite (``_adj`` injection) preserves the
  original regex (``r"(\\.nc)(?!_adj)"``) so produced .rvt files are
  byte-identical to the notebook's output.
* All copies are idempotent — re-staging an already-staged directory
  is a no-op.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


_DD_FILE_EXTENSIONS = (".cpg", ".dbf", ".prj", ".shp", ".shx")
_RAVEN_CONFIG_EXTENSIONS = (".rvp", ".rvh", ".rvi", ".rvt", ".rvc")
_OTHER_INPUT_SUFFIXES = ("_HRU_areas.csv", "_tp_tc.csv", "_WSC_outlet.txt")
_NC_REWRITE_PATTERN = re.compile(r"(\.nc)(?!_adj)")


@dataclass(frozen=True)
class StagingPaths:
    """Where to find source files and where to put staged copies.

    Parameters
    ----------
    watershed_name
        Name used in the Data subdirectory (e.g. ``"grassmere"``).
    data_root
        Root ``Data/`` folder containing both per-watershed source
        folders and the ``Calibration/`` destination tree.
    netcdf_category
        Subfolder name that holds the GridWeights and .nc files
        (one of ``"Runoff"``, ``"Snowmelt"``, ``"Rainfall"`` —
        notebook-prompted).
    """

    watershed_name: str
    data_root: Path
    netcdf_category: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", Path(self.data_root))

    # ---- source paths ----
    # These mirror the refactored pipeline's output layout:
    #   Step 0 (pwa_tools)   → <watershed>/HydroConditioning/Processed/
    #   Step 1 (pwa_raven)   → <watershed>/<category>/Processed/
    #   Step 2 (pwa_raven)   → <watershed>/Raven/Processed/ with .rv* files
    #                          flat and input/ + templates/ subdirectories.
    @property
    def raven_processed_dir(self) -> Path:
        return self.data_root / self.watershed_name / "Raven" / "Processed"

    @property
    def raven_input_dir(self) -> Path:
        """Step 2 nests HRU-areas / tp_tc / WSC-outlet / aspect-ratio
        files in an ``input/`` subdirectory of Raven/Processed/."""
        return self.raven_processed_dir / "input"

    @property
    def raven_templates_dir(self) -> Path:
        """Step 2 nests the SPOTPY ``.tpl`` templates in a ``templates/``
        subdirectory of Raven/Processed/."""
        return self.raven_processed_dir / "templates"

    @property
    def hydrocon_processed_dir(self) -> Path:
        """Step 0 writes the depression-depths shapefile here."""
        return self.data_root / self.watershed_name / "HydroConditioning" / "Processed"

    @property
    def nc_processed_dir(self) -> Path:
        return self.data_root / self.watershed_name / self.netcdf_category / "Processed"

    @property
    def raven_exe_source(self) -> Path:
        """Path to the Raven binary in the source folder.

        Tries the Linux/macOS convention (``Raven``) first, then the Windows
        convention (``Raven.exe``). Returns the first match. If neither
        exists, returns the platform-default name (``Raven.exe`` on Windows,
        ``Raven`` elsewhere) so the missing-source path in
        :func:`_copy_if_absent` reports a sensible filename.
        """
        import platform
        for name in ("Raven", "Raven.exe"):
            candidate = self.raven_processed_dir / name
            if candidate.is_file():
                return candidate
        default_name = "Raven.exe" if platform.system() == "Windows" else "Raven"
        return self.raven_processed_dir / default_name

    @property
    def aspect_ratios_source(self) -> Path:
        # aspect_ratios.csv is a Step 2 output, written into Raven/Processed/input/.
        return self.raven_input_dir / "aspect_ratios.csv"

    @property
    def grid_weights_source(self) -> Path:
        return self.nc_processed_dir / "GridWeights.txt"

    # ---- destination paths ----
    @property
    def calibration_root(self) -> Path:
        return self.data_root / "Calibration" / self.watershed_name

    @property
    def calibration_input_dir(self) -> Path:
        return self.calibration_root / "input"

    @property
    def calibration_output_dir(self) -> Path:
        return self.calibration_root / "output"

    @property
    def calibration_template_dir(self) -> Path:
        return self.calibration_root / "templates"


@dataclass
class StagingReport:
    """Summary of what was copied / skipped during staging."""

    copied: list[Path] = field(default_factory=list)
    skipped_existing: list[Path] = field(default_factory=list)
    missing_sources: list[Path] = field(default_factory=list)

    def total_copied(self) -> int:
        return len(self.copied)


# ---------------------------------------------------------------------------
# Folder + helpers
# ---------------------------------------------------------------------------


def create_calibration_folders(paths: StagingPaths) -> None:
    """Create ``calibration_root`` and the three subfolders if absent."""
    for folder in (
        paths.calibration_root,
        paths.calibration_input_dir,
        paths.calibration_output_dir,
        paths.calibration_template_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)


def _copy_if_absent(
    source: Path, destination: Path, report: StagingReport
) -> bool:
    """Copy *source* → *destination* unless *destination* already exists.

    Returns True if a copy happened. Records skipped/missing in *report*.
    """
    if destination.exists():
        report.skipped_existing.append(destination)
        return False
    if not source.exists():
        report.missing_sources.append(source)
        logger.warning("Source missing: %s", source)
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, destination)
    report.copied.append(destination)
    logger.info("Copied %s → %s", source, destination)
    return True


def _files_with_suffixes(folder: Path, suffixes: Iterable[str]) -> list[Path]:
    """Return files in *folder* whose name ends with any of *suffixes*."""
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.name.endswith(tuple(suffixes)))


# ---------------------------------------------------------------------------
# Per-substep staging
# ---------------------------------------------------------------------------


def stage_raven_binary(paths: StagingPaths, report: StagingReport) -> None:
    """1.3.1 — copy the Raven binary into the calibration root.

    Preserves the source filename (``Raven`` or ``Raven.exe``), so the
    destination matches whatever convention the source folder uses.
    On macOS/Linux the binary is just ``Raven``; on Windows it's ``Raven.exe``.
    """
    source = paths.raven_exe_source
    _copy_if_absent(source, paths.calibration_root / source.name, report)


def stage_depression_depths(paths: StagingPaths, report: StagingReport) -> None:
    """1.3.2 — copy all depression-depths sidecars into ``input/``.

    Source is Step 0's ``HydroConditioning/Processed/`` directory.
    """
    for source in _files_with_suffixes(paths.hydrocon_processed_dir, _DD_FILE_EXTENSIONS):
        _copy_if_absent(source, paths.calibration_input_dir / source.name, report)


def stage_grid_weights(paths: StagingPaths, report: StagingReport) -> None:
    """1.3.3 — copy ``GridWeights.txt`` into ``input/``."""
    _copy_if_absent(
        paths.grid_weights_source,
        paths.calibration_input_dir / "GridWeights.txt",
        report,
    )


def _inject_adj_into_rvt(rvt_path: Path) -> bool:
    """Append ``_adj`` to all ``.nc`` references in *rvt_path*.

    Returns True if any substitution was made. Idempotent — references
    that already end in ``_adj.nc`` are left alone (negative lookahead).
    """
    content = rvt_path.read_text(encoding="utf-8")
    updated = _NC_REWRITE_PATTERN.sub(r"_adj\1", content)
    if updated == content:
        return False
    rvt_path.write_text(updated, encoding="utf-8")
    logger.info("Injected '_adj' into .nc references in %s", rvt_path.name)
    return True


def stage_raven_configs(paths: StagingPaths, report: StagingReport) -> None:
    """1.3.4 — copy ``.rv*`` files into the calibration root.

    For ``.rvt`` files, also inject ``_adj`` before each ``.nc`` reference
    so Raven loads the SPOTPY-adjusted forcing file.
    """
    for source in _files_with_suffixes(paths.raven_processed_dir, _RAVEN_CONFIG_EXTENSIONS):
        destination = paths.calibration_root / source.name
        if _copy_if_absent(source, destination, report) and source.suffix == ".rvt":
            _inject_adj_into_rvt(destination)


def stage_template_files(paths: StagingPaths, report: StagingReport) -> None:
    """1.3.5 — copy SPOTPY ``.tpl`` templates and the ``_tpl.nc`` forcing.

    The forcing NetCDF is renamed ``<basename>_tpl.nc`` (matching the
    sentinel that :func:`pwa_calibration.setup._find_nc_template` looks
    for at simulation time).
    """
    for source in _files_with_suffixes(paths.raven_templates_dir, ("tpl",)):
        _copy_if_absent(source, paths.calibration_template_dir / source.name, report)

    for source in _files_with_suffixes(paths.nc_processed_dir, (".nc",)):
        destination = paths.calibration_input_dir / f"{source.stem}_tpl.nc"
        _copy_if_absent(source, destination, report)


def stage_other_inputs(paths: StagingPaths, report: StagingReport) -> None:
    """1.3.6 — aspect ratios, HRU areas, tp/tc, WSC outlet.

    All four are Step 2 outputs nested in ``Raven/Processed/input/``.
    """
    _copy_if_absent(
        paths.aspect_ratios_source,
        paths.calibration_input_dir / "aspect_ratios.csv",
        report,
    )
    for source in _files_with_suffixes(paths.raven_input_dir, _OTHER_INPUT_SUFFIXES):
        _copy_if_absent(source, paths.calibration_input_dir / source.name, report)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def prepare_calibration_directory(paths: StagingPaths) -> StagingReport:
    """Run all six staging substeps in notebook order.

    Returns a :class:`StagingReport` describing what was copied,
    what was skipped (because already present), and what sources were
    missing. Missing sources are logged as warnings, not errors —
    matches the notebook's tolerant behavior for partial setups.
    """
    create_calibration_folders(paths)
    report = StagingReport()
    stage_raven_binary(paths, report)
    stage_depression_depths(paths, report)
    stage_grid_weights(paths, report)
    stage_raven_configs(paths, report)
    stage_template_files(paths, report)
    stage_other_inputs(paths, report)
    return report
