"""SPOTPY setup for Raven model calibration.

Refactored from ``PWA/src/py/setup_spotpy.py`` (the ``spot_setup_rvn`` class).

What changed during extraction
------------------------------
* **MPI rank stability**: the original incremented ``self.rank`` on
  every ``simulation()`` call, eventually overrunning ``self.cores``
  and indexing past ``core_paths``. Rank is now a constant attribute
  set once in ``__init__``; a separate ``_call_count`` counter handles
  diagnostic logging.
* **NetCDF template lookup**: the original used a bare ``for`` loop
  to find the template and referenced ``filename`` outside the loop
  body — when no match was found this raised ``NameError``. Now uses
  :func:`_find_nc_template` which raises ``FileNotFoundError`` with a
  clear message.
* **Cross-platform paths**: all ``calib_dir + "\\input\\..."`` string
  concatenation (Windows-only on Linux/macOS) is now
  ``Path(calib_dir) / "input" / ...``.
* **Robust file copy**: ``robust_copy`` now raises ``IOError`` on
  failure instead of returning ``False`` and being ignored by every
  call site.
* **Deprecated splits removed**: ``split_areas`` no longer accepts
  ``"clrh"`` or ``"phydap"``. Both branches in the original just
  raised ``ValueError`` after a deprecation print — kept the error,
  removed the dead commented-out parameter lists.
* **Eval window is configurable**: the original hardcoded
  ``start_yr=1995, end_yr=2010`` inside ``simulation()``. Now passed
  in via :class:`CalibrationConfig`.
* **Inputs are pathlib**: ``calib_dir`` is normalized to a ``Path`` once.
* **Watershed name removed from setup**: replaced by the explicit
  ``model_name`` (already a parameter — just promoted to required and
  used consistently for all input-file naming).
* **Logging**: replaces 20+ ``print(... flush=True)`` calls.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from pwa_raven.io import netcdf
from pwa_raven.raven import files as raven_files
from pwa_raven.raven import hydrograph as raven_hydro
from pwa_raven.raven import runner as raven_runner

from .objectives import OBJECTIVES, evaluate as evaluate_objective

if TYPE_CHECKING:
    import spotpy as sp  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (extracted from setup_spotpy module level)
# ---------------------------------------------------------------------------


def calculate_checksum(file_path: Path | str) -> str:
    """MD5 checksum of *file_path*."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def robust_copy(
    source_path: Path | str,
    destination_path: Path | str,
    retries: int = 3,
    delay: float = 0.1,
) -> None:
    """Copy with checksum verification and exponential-backoff retries.

    Raises ``IOError`` after exhausting retries. The original returned
    ``True``/``False`` and every call site ignored the result, so a
    failed copy silently corrupted downstream calibration runs.
    """
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    last_err: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            shutil.copy2(source_path, destination_path)  # preserves metadata
            if calculate_checksum(source_path) == calculate_checksum(destination_path):
                return
            logger.warning(
                "Checksum mismatch %s → %s, retrying", source_path, destination_path
            )
            destination_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("Copy attempt %d failed: %s", attempt + 1, exc)
        time.sleep(delay * (attempt + 1))
    raise IOError(
        f"Failed to copy {source_path} → {destination_path} after {retries} "
        f"attempts."
    ) from last_err


_NC_TEMPLATE_SUFFIXES = ("_tpl.nc", "_template.nc")


def _find_nc_template(inputs_path: Path) -> Path:
    """Locate the PhyDAP NetCDF template in *inputs_path*.

    Raises ``FileNotFoundError`` with the expected suffixes when no
    match is found. The original used a bare ``for`` loop and crashed
    with ``NameError`` on the post-loop ``filename`` reference instead.
    """
    for filename in sorted(os.listdir(inputs_path)):
        if filename.endswith(_NC_TEMPLATE_SUFFIXES):
            return inputs_path / filename
    raise FileNotFoundError(
        f"No NetCDF template (*{_NC_TEMPLATE_SUFFIXES[0]} or "
        f"*{_NC_TEMPLATE_SUFFIXES[1]}) found in {inputs_path}."
    )


def _adj_path_from_template(template_path: Path) -> Path:
    """Derive the *_adj.nc output path from the *_tpl.nc / *_template.nc input."""
    name = template_path.name
    for suffix in _NC_TEMPLATE_SUFFIXES:
        if name.endswith(suffix):
            return template_path.with_name(name[: -len(suffix)] + "_adj.nc")
    raise ValueError(f"Path {template_path} does not have a recognized template suffix.")


def _round_sig(values, sig: int = 8) -> list[float]:
    """Round each non-zero element of *values* to *sig* significant figures."""
    out: list[float] = []
    for x in values:
        if x != 0:
            out.append(round(x, sig - int(np.floor(np.log10(abs(x)))) - 1))
        else:
            out.append(0.0)
    return out


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


# SPOTPY sampler algorithms wired up in run_calibration. Each name must be
# an attribute of `spotpy.algorithms`. Algorithm-specific knobs (e.g.
# `subsets` for rope, `nChains` for demcz) are passed through
# CalibrationConfig.algorithm_kwargs to the sampler's .sample() call.
ALGORITHMS = ("mc", "rope", "demcz")


@dataclass(frozen=True)
class CalibrationConfig:
    """Immutable calibration configuration.

    Replaces the kitchen-sink ``spot_setup_rvn.__init__`` argument list
    *and* the global ``proj_conf`` constants (``model_str``, ``DATA_CAL``).

    Parameters
    ----------
    model_name
        Watershed/model name (used for input-file naming, e.g.
        ``f"{model_name}_HRU_areas.csv"``).
    calib_dir
        Root calibration directory containing ``input/``, ``output/``,
        ``templates/`` and the Raven ``.rv*`` files.
    obj_fn
        Objective-function name. Must be a key in
        :data:`pwa_calibration.objectives.OBJECTIVES`.
    eval_start_yr, eval_end_yr
        Inclusive year range for hydrograph evaluation (was hardcoded
        1995–2010 in the original).
    spring_eval
        If True, restrict evaluation to spring months (Jan–May).
    low_seep
        If True, narrow the seepage-rate prior to ``[0.005, 0.03]``
        (default ``[0.005, 0.5]``).
    routing, dep_scaling, runoff_scaling, channel_scaling, phydap_adj
        Toggles for which parameter groups to calibrate.
    split_areas
        Spatial subdivision for runoff scaling. Currently the only
        supported values are ``"none"`` and ``"no_split"``; ``"clrh"``
        and ``"phydap"`` are deprecated and will raise ``ValueError``.
    mpi_cores
        ``0`` or ``1`` → serial (single working dir). ``>=2`` → each
        rank gets its own ``{calib_dir}_mpi/core{N}/`` working copy.
    raven_binary
        Optional absolute path to the Raven executable. When ``None``
        (the default), ``run_raven`` searches the per-iteration
        ``working_dir`` first, then the system PATH — so dropping
        ``Raven``/``Raven.exe`` into ``calib_dir`` (as the
        ``stage_raven_binary`` step already does) is sufficient. Set
        this only when the binary lives outside the calibration tree
        and isn't on PATH.
    """

    model_name: str
    calib_dir: Path
    obj_fn: str = "kge_adj"
    eval_start_yr: int = 1995
    eval_end_yr: int = 2010
    spring_eval: bool = True
    low_seep: bool = False
    routing: bool = False
    dep_scaling: bool = False
    runoff_scaling: bool = False
    channel_scaling: bool = False
    phydap_adj: bool = True
    split_areas: str = "none"
    mpi_cores: int = 0
    repetitions: int = 10
    algorithm: str = "mc"
    algorithm_kwargs: dict = field(default_factory=dict)
    raven_binary: Optional[Path] = None
    # Alternating train/test split over [eval_start_yr, eval_end_yr).
    # 0  → use every year for training (no split — original refactor behaviour).
    # 1  → hold out the first 5 years as test, train on the remainder.
    # >1 → every k-th year is test, the rest is training (k=4 was Thomas's
    # default in upstream master after 2026-04-29).
    tt_split_freq: int = 0
    # Realign each year's observed hydrograph to the simulated one by its
    # center-of-mass before computing the objective. New science from
    # upstream master 2026-05-04 (commit 230493c). Defaults to off until
    # we have unit tests demonstrating the lag-shift behaviour end-to-end.
    event_based: bool = False

    def __post_init__(self) -> None:
        # Force calib_dir to a Path with no trailing separator.
        object.__setattr__(self, "calib_dir", Path(str(self.calib_dir).rstrip("/\\")))
        # Coerce raven_binary to Path when supplied. None stays None and
        # signals "fall back to data-directory search + PATH".
        if self.raven_binary is not None:
            object.__setattr__(self, "raven_binary", Path(self.raven_binary))
        if self.obj_fn not in OBJECTIVES:
            raise ValueError(
                f"Unsupported obj_fn {self.obj_fn!r}. Choose from {sorted(OBJECTIVES)}."
            )
        if self.repetitions < 1:
            raise ValueError(
                f"repetitions must be >= 1, got {self.repetitions}."
            )
        if self.algorithm not in ALGORITHMS:
            raise ValueError(
                f"Unsupported algorithm {self.algorithm!r}. "
                f"Choose from {sorted(ALGORITHMS)}."
            )
        if self.tt_split_freq < 0:
            raise ValueError(
                f"tt_split_freq must be >= 0, got {self.tt_split_freq}."
            )
        if self.eval_end_yr < self.eval_start_yr:
            raise ValueError(
                f"eval_end_yr ({self.eval_end_yr}) must be >= eval_start_yr "
                f"({self.eval_start_yr})."
            )
        split = self.split_areas.lower()
        if split in ("clrh", "phydap"):
            raise ValueError(
                f"split_areas={self.split_areas!r} is deprecated. "
                "Use 'none' or 'no_split'."
            )
        if split not in ("none", "no_split"):
            raise ValueError(
                f"Unsupported split_areas={self.split_areas!r}. "
                "Use 'none' or 'no_split'."
            )

    @property
    def is_mpi(self) -> bool:
        return self.mpi_cores >= 2

    @property
    def input_dir(self) -> Path:
        return self.calib_dir / "input"

    @property
    def train_years(self) -> np.ndarray:
        """Years used for SPOTPY training, given the eval window and split.

        Returns a 1-D integer numpy array. The window is
        ``[eval_start_yr, eval_end_yr)`` — end-exclusive, matching
        upstream's ``range(start_year, end_year)`` semantics.
        """
        all_years = np.arange(self.eval_start_yr, self.eval_end_yr)
        if self.tt_split_freq == 0:
            return all_years
        if self.tt_split_freq == 1:
            # Hold out the first 5 years as test (legacy behaviour from
            # upstream's `tt_split_freq <= 1` branch).
            return all_years[5:] if all_years.size > 5 else all_years
        test_years = all_years[:: self.tt_split_freq]
        return all_years[~np.isin(all_years, test_years)]

    @property
    def test_years(self) -> np.ndarray:
        """Complement of :attr:`train_years` within the eval window."""
        all_years = np.arange(self.eval_start_yr, self.eval_end_yr)
        return all_years[~np.isin(all_years, self.train_years)]

    def expected_input_files(self) -> list[Path]:
        """Files load_calibration_inputs reads — use to fail fast.

        Returns paths to the WSC outlet text file, the aspect-ratios CSV,
        the per-watershed HRU-areas CSV, the per-watershed tp/tc CSV, and
        the depression-depths shapefile.
        """
        return [
            self.input_dir / f"{self.model_name}_WSC_outlet.txt",
            self.input_dir / "aspect_ratios.csv",
            self.input_dir / f"{self.model_name}_HRU_areas.csv",
            self.input_dir / f"{self.model_name}_tp_tc.csv",
            self.input_dir / "CLRH_basins_depression_depths.shp",
        ]

    def validate_inputs_exist(self) -> None:
        """Fail fast if expected calibration inputs are missing.

        Raises :class:`FileNotFoundError` listing every missing file in one
        message — saves the user the multiple round trips of
        re-running calibration just to discover the next missing file.
        Sidecars (.dbf/.shx/.prj/.cpg for the shapefile) aren't enumerated;
        geopandas raises clear errors when those are missing alongside a
        present .shp.
        """
        missing = [p for p in self.expected_input_files() if not p.is_file()]
        if missing:
            bullet_list = "\n  - ".join(str(p) for p in missing)
            raise FileNotFoundError(
                "Calibration cannot start; the following expected input "
                f"files are missing:\n  - {bullet_list}\n"
                f"Stage them into {self.input_dir} (typically via "
                "pwa_calibration.prepare.prepare_calibration_directory) "
                "and re-run."
            )

    # ---- serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize back to the same dict shape :meth:`from_dict` consumes.

        Round-trip property: ``CalibrationConfig.from_dict(c.to_dict()) == c``.
        Path is rendered as a string so the dict is YAML-safe.
        """
        return {
            "model_name": self.model_name,
            "calib_dir": str(self.calib_dir),
            "obj_fn": self.obj_fn,
            "eval_start_yr": self.eval_start_yr,
            "eval_end_yr": self.eval_end_yr,
            "spring_eval": self.spring_eval,
            "low_seep": self.low_seep,
            "routing": self.routing,
            "dep_scaling": self.dep_scaling,
            "runoff_scaling": self.runoff_scaling,
            "channel_scaling": self.channel_scaling,
            "phydap_adj": self.phydap_adj,
            "split_areas": self.split_areas,
            "mpi_cores": self.mpi_cores,
            "repetitions": self.repetitions,
            "algorithm": self.algorithm,
            "algorithm_kwargs": dict(self.algorithm_kwargs),
            "tt_split_freq": self.tt_split_freq,
            "event_based": self.event_based,
            "raven_binary": (
                str(self.raven_binary) if self.raven_binary is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationConfig":
        """Build from a plain dict — used by tests, programmatic callers,
        and as the intermediate step inside :meth:`from_yaml`.

        Required keys: ``model_name``, ``calib_dir``. Everything else
        falls back to the dataclass defaults if absent.
        """
        try:
            model_name = data["model_name"]
            calib_dir = data["calib_dir"]
        except KeyError as exc:
            raise ValueError(
                f"CalibrationConfig requires both 'model_name' and "
                f"'calib_dir'; missing {exc.args[0]!r}."
            ) from exc

        # Allow None / missing optionals to fall back to dataclass defaults.
        defaults = cls(model_name=model_name, calib_dir=calib_dir)
        return cls(
            model_name=model_name,
            calib_dir=calib_dir,
            obj_fn=data.get("obj_fn", defaults.obj_fn),
            eval_start_yr=data.get("eval_start_yr", defaults.eval_start_yr),
            eval_end_yr=data.get("eval_end_yr", defaults.eval_end_yr),
            spring_eval=data.get("spring_eval", defaults.spring_eval),
            low_seep=data.get("low_seep", defaults.low_seep),
            routing=data.get("routing", defaults.routing),
            dep_scaling=data.get("dep_scaling", defaults.dep_scaling),
            runoff_scaling=data.get("runoff_scaling", defaults.runoff_scaling),
            channel_scaling=data.get("channel_scaling", defaults.channel_scaling),
            phydap_adj=data.get("phydap_adj", defaults.phydap_adj),
            split_areas=data.get("split_areas", defaults.split_areas),
            mpi_cores=data.get("mpi_cores", defaults.mpi_cores),
            repetitions=data.get("repetitions", defaults.repetitions),
            algorithm=data.get("algorithm", defaults.algorithm),
            algorithm_kwargs=data.get("algorithm_kwargs") or {},
            tt_split_freq=data.get("tt_split_freq", defaults.tt_split_freq),
            event_based=data.get("event_based", defaults.event_based),
            raven_binary=data.get("raven_binary", defaults.raven_binary),
        )

    def to_yaml(self, path: Path | str) -> Path:
        """Write this config to *path* as YAML. Returns the resolved path.

        Output is human-readable: keys preserved in insertion order, no
        Python tags. Parent directory is created if needed.
        """
        import yaml  # local import keeps module-level deps light

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                self.to_dict(),
                sort_keys=False,
                default_flow_style=False,
            )
        )
        return path

    @classmethod
    def from_yaml(cls, config_path: Path | str) -> "CalibrationConfig":
        """Load configuration from a YAML file."""
        import yaml  # local import keeps module-level deps light

        with open(config_path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Input-file loading helpers
# ---------------------------------------------------------------------------


@dataclass
class CalibrationInputs:
    """Parsed input files needed by ``simulation()``."""
    outlet: int
    aspect_ratios: dict
    HRU_areas: dict
    tps: dict
    tcs: dict
    deps: dict
    qrefs: dict


def load_calibration_inputs(config: CalibrationConfig) -> CalibrationInputs:
    """Load all input CSVs / shapefile from ``config.input_dir``.

    Replaces the inline file-loading section of ``spot_setup_rvn.__init__``.
    All path joins go through ``Path``, so the legacy
    ``calib_dir + "\\input\\..."`` Windows-only string concatenation
    works on macOS and Linux too.
    """
    input_dir = config.input_dir
    model_name = config.model_name

    outlet_path = input_dir / f"{model_name}_WSC_outlet.txt"
    outlet = int(outlet_path.read_text().strip())
    logger.info("Outlet subid from WSC: %d", outlet)

    aspect_df = pd.read_csv(input_dir / "aspect_ratios.csv")
    hru_df = pd.read_csv(input_dir / f"{model_name}_HRU_areas.csv")
    tp_tc_df = pd.read_csv(input_dir / f"{model_name}_tp_tc.csv")
    deps_gdf = gpd.read_file(input_dir / "CLRH_basins_depression_depths.shp")

    return CalibrationInputs(
        outlet=outlet,
        aspect_ratios=aspect_df.set_index("SubId")["Aspect_Ratio"].to_dict(),
        HRU_areas=hru_df.set_index("HRU")["AREA"].to_dict(),
        tps=tp_tc_df.set_index("SubId")["tp"].to_dict(),
        tcs=tp_tc_df.set_index("SubId")["tc"].to_dict(),
        deps=dict(zip(deps_gdf["SubId"], deps_gdf["Deps_Depth"])),
        qrefs=dict(zip(deps_gdf["SubId"], deps_gdf["Q_Mean"])),
    )


# ---------------------------------------------------------------------------
# Parameter-distribution builders (split out of the original __init__)
# ---------------------------------------------------------------------------


def build_param_distributions(config: CalibrationConfig) -> tuple[list, str]:
    """Return ``(distributions, param_set_id)`` for the given config.

    ``param_set_id`` is the string consumed by ``RavenFile.rvp_update``
    / ``rvh_update`` (one of ``"no_split"`` / ``"no_runoff_scale"``).
    """
    import spotpy as sp

    seep_max, seep_opt = (0.03, 0.01) if config.low_seep else (0.5, 0.25)

    dists: list = []
    if config.dep_scaling:
        # Widened priors from upstream master 2026-05-04 (commit 230493c).
        dists.append(sp.parameter.Uniform("dep_fact", low=0.4, high=1.2, optguess=0.8))

    dists.append(sp.parameter.Uniform("seep_k", low=0.005, high=seep_max, optguess=seep_opt))

    if config.runoff_scaling:
        dists.append(sp.parameter.Uniform("basin_fact", low=0.90, high=1.20, optguess=1.10))
        param_set = "no_split"
    else:
        param_set = "no_runoff_scale"

    if config.routing:
        dists.append(sp.parameter.Uniform("tc_tp_fact", low=1.4, high=3.0))
        # Widened from [0.4, 1.2] in upstream master 2026-05-04 (commit 230493c).
        dists.append(sp.parameter.Uniform("t_peak_fact", low=0.2, high=5.0))
        dists.append(sp.parameter.Uniform("qref_scale", low=0.5, high=2.0))

    if config.channel_scaling:
        dists.append(sp.parameter.Uniform("bedslope_mult", low=0.8, high=5.0, optguess=1.5))

    if config.phydap_adj:
        dists.append(sp.parameter.Uniform("runoff_offset", low=0, high=100, optguess=60))

    return dists, param_set


# ---------------------------------------------------------------------------
# MPI worker-directory staging
# ---------------------------------------------------------------------------


# Top-level subdirectories of calib_dir that are NOT staged into each MPI
# worker. ``output/`` is Raven's per-iteration scratch directory; every
# worker regenerates it on its first iteration, so copying the stale
# contents is both pointless and unsafe — if a prior Raven run was killed
# mid-write, the file is in an inconsistent state and robust_copy will
# fail with "Checksum mismatch ... after 3 attempts" when source bytes
# change between the copy and the verify reads.
_WORKER_STAGE_EXCLUDE_DIRS = frozenset({"output"})


def _stage_worker_directory(source: Path, destination: Path) -> None:
    """Copy *source* tree into *destination* using ``robust_copy`` for files.

    Mirrors the original two-level loop but uses pathlib throughout and
    propagates copy failures via ``IOError`` (the original swallowed
    them). Excludes scratch directories listed in
    :data:`_WORKER_STAGE_EXCLUDE_DIRS` — currently just ``output/``.
    The worker's own empty ``output/`` is created here so Raven can
    write into it on the first iteration without depending on Raven's
    own directory-creation behaviour.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.is_dir() and entry.name in _WORKER_STAGE_EXCLUDE_DIRS:
            logger.debug("Skipping %s during worker staging (scratch dir)", entry)
            continue
        dest_entry = destination / entry.name
        if entry.is_dir():
            dest_entry.mkdir(exist_ok=True)
            for sub in entry.iterdir():
                sub_dest = dest_entry / sub.name
                if sub.is_dir():
                    shutil.copytree(sub, sub_dest, dirs_exist_ok=True)
                else:
                    robust_copy(sub, sub_dest)
        else:
            robust_copy(entry, dest_entry)
    # Ensure the worker has a fresh, empty output/ for Raven to write into.
    # Doing it here keeps the call site in SpotPySetup.__init__ a single line.
    (destination / "output").mkdir(exist_ok=True)


def _resolve_mpi_rank() -> int:
    """Get this process's MPI rank, or 0 if MPI is unavailable."""
    try:
        from mpi4py import MPI  # type: ignore

        return MPI.COMM_WORLD.Get_rank()
    except ImportError:
        logger.debug("mpi4py not installed; assuming serial rank=0")
        return 0


# ---------------------------------------------------------------------------
# SpotPy callback class
# ---------------------------------------------------------------------------


class SpotPySetup:
    """Calibration setup consumed by ``spotpy.algorithms.*``.

    Construct one per worker. SpotPy will call :meth:`parameters`,
    :meth:`simulation`, :meth:`evaluation`, and :meth:`objectivefunction`
    in its sampling loop.
    """

    def __init__(
        self,
        config: CalibrationConfig,
        inputs: Optional[CalibrationInputs] = None,
    ) -> None:
        self.config = config
        self.inputs = inputs if inputs is not None else load_calibration_inputs(config)

        self.rank = _resolve_mpi_rank()
        self._call_count = 0

        # Decide working directory (per-rank for MPI, shared for serial).
        if config.is_mpi:
            self.core_paths = [
                config.calib_dir.parent
                / f"{config.calib_dir.name}_mpi"
                / f"core{c}"
                for c in range(config.mpi_cores)
            ]
            self.working_dir = self.core_paths[self.rank]
            self.working_dir.mkdir(parents=True, exist_ok=True)
            logger.info("[rank %d] Created %s", self.rank, self.working_dir)
            _stage_worker_directory(config.calib_dir, self.working_dir)
        else:
            self.core_paths = [config.calib_dir]
            self.working_dir = config.calib_dir
        logger.info("Calibration core paths: %s", self.core_paths)

        self.param_distributions, self.param_set = build_param_distributions(config)

    # -- SPOTPY interface ----------------------------------------------------

    def parameters(self):
        import spotpy as sp

        generated = sp.parameter.generate(self.param_distributions)
        logger.debug("Generated parameters: %s", generated)
        return generated

    def simulation(self, param_vector, exts: Optional[list[str]] = None) -> list[float]:
        """Run one Raven simulation, return the objective-function value.

        ``param_vector`` is the SpotPy ``ParameterSet`` (has ``.random``
        and ``.name`` attributes).

        Returns a single-element ``[value]`` list, not a bare float —
        SPOTPY's database layer calls ``len()`` on the result.
        """
        if exts is None:
            exts = ["rvp", "rvh"]

        rounded = pd.Series(_round_sig(param_vector.random, sig=8), index=param_vector.name)

        self._call_count += 1
        if self.config.is_mpi:
            logger.info(
                "[rank %d] Simulation #%d in %s",
                self.rank,
                self._call_count,
                self.working_dir,
            )
            while not self.working_dir.exists():
                time.sleep(10)
                logger.info("[rank %d] Waiting for %s", self.rank, self.working_dir)

        sim_dir = self.working_dir
        for ext in exts:
            if ext == "rvp":
                if self.inputs.deps is None:
                    raise ValueError(
                        "Depression depths dictionary is not loaded; "
                        "cannot perform depth scaling."
                    )
                rvp = raven_files.RavenFile(
                    f"{self.config.model_name}.rvp", calib_dir=sim_dir, extension="rvp"
                )
                rvp_channel = raven_files.RavenFile(
                    "channel_properties.rvp", calib_dir=sim_dir, extension="rvp"
                )
                rvp.rvp_update(
                    self.param_set,
                    self.config.dep_scaling,
                    rounded,
                    _deps=self.inputs.deps,
                    _channel_scale=self.config.channel_scaling,
                )
                rvp_channel.rvp_update(
                    self.param_set,
                    self.config.dep_scaling,
                    rounded,
                    _deps=self.inputs.deps,
                    _channel_scale=self.config.channel_scaling,
                )
            elif ext == "rvh":
                rvh = raven_files.RavenFile(
                    f"{self.config.model_name}.rvh", calib_dir=sim_dir, extension="rvh"
                )
                rvh.rvh_update(
                    self.param_set,
                    self.config.routing,
                    self.config.channel_scaling,
                    rounded,
                    self.inputs.aspect_ratios,
                    self.inputs.HRU_areas,
                    self.inputs.tps,
                    self.inputs.tcs,
                    self.inputs.qrefs,
                )
            else:
                raise ValueError(f"Unsupported file extension: {ext}")

        # The .rvt always references the _adj.nc forcing file (the
        # calibration staging rewrites every .nc reference to _adj.nc),
        # so _adj.nc must always exist. When phydap_adj is on it is the
        # runoff-offset-shifted forcing; when off it is an unshifted
        # copy (offset 0). Skipping its creation — as the code used to
        # when phydap_adj was off — left the .rvt pointing at a file
        # that was never written.
        template_path = _find_nc_template(sim_dir / "input")
        adj_path = _adj_path_from_template(template_path)
        if self.config.phydap_adj:
            offset = float(np.round(rounded["runoff_offset"]))
            logger.info("Applying PhyDAP runoff offset %s h to %s", offset, template_path.name)
        else:
            offset = 0.0
            logger.info("phydap_adj off — writing unshifted forcing %s", adj_path.name)
        netcdf.time_offset(template_path, adj_path, offset=offset)

        raven_runner.run_raven(
            self.config.model_name,
            sim_dir,
            raven_binary=self.config.raven_binary,
        )

        subbasin_id = f"sub{self.inputs.outlet}"
        hydrograph = raven_hydro.RavenHydrograph(sim_dir)

        train_years = self.config.train_years
        logger.info(
            "Training on %d years: %s%s",
            train_years.size,
            train_years[:10].tolist(),
            " ..." if train_years.size > 10 else "",
        )
        sim = hydrograph.read_sim(
            subbasin_id,
            years=train_years,
            spring_only=self.config.spring_eval,
            refresh=True,
        )
        obs = hydrograph.read_obs(
            years=train_years,
            spring_only=self.config.spring_eval,
            refresh=True,
        )

        if self.config.event_based:
            from .objectives import shift_obs_by_yearly_lag

            obs = shift_obs_by_yearly_lag(obs, sim, train_years)

        value = evaluate_objective(self.config.obj_fn, sim, obs)
        logger.info(
            "Objective %s = %.6f for params %s",
            self.config.obj_fn,
            value,
            dict(rounded),
        )
        # Return the objective value wrapped in a single-element list.
        # This calibration uses the "simulation() returns the metric"
        # SPOTPY idiom (evaluation() returns the target, objectivefunction()
        # squeezes it through), but SPOTPY's database layer calls
        # len(simulations) to build its column header — a bare float has
        # no len(). The list makes it a one-column "simulation"; the
        # np.squeeze in objectivefunction still recovers the scalar.
        return [value]

    def evaluation(self):
        """Return the target value for SPOTPY's ``like`` interpretation.

        For maximization-style objectives (KGE, NSE) the target is 1.
        For ``nse_pbias`` the composite is centered on 0.
        """
        if self.config.obj_fn in ("kge_adj", "nse"):
            return pd.Series(1)
        if self.config.obj_fn == "nse_pbias":
            return pd.Series(0)
        raise ValueError(f"Unsupported obj_fn: {self.config.obj_fn}")

    def objectivefunction(self, simulation=None, evaluation=None):
        # SPOTPY signature; returns simulation as the likelihood scalar.
        return float(np.squeeze(simulation))
