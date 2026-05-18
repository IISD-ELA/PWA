"""Parallel calibration entry point.

Refactored from ``PWA/3_calibrate.py`` (78 lines).

What changed during extraction
------------------------------
* The hardcoded ``raven_name = "grassmere"`` is gone — driven by
  :class:`~pwa_calibration.setup.CalibrationConfig.model_name`.
* The wildcard imports (``from src.py.proj_conf import *``,
  ``from src.py.setup_spotpy import *``) and the ``sys.path.insert``
  are gone — runner imports directly from :mod:`pwa_calibration.setup`.
* The ROPE ``get_best_runs`` monkeypatch is now applied via
  :func:`patch_rope_get_best_runs`, called from :func:`run_calibration`.
  The patch checks the attribute exists before overwriting so it
  silently no-ops on spotpy versions that have already fixed the issue.
* The CLI is in :func:`main`. The legacy
  ``mpirun -c 14 python 3_calibrate.py results`` invocation is
  preserved by ``mpirun -c 14 python -m pwa_calibration.runner results``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .prepare import StagingPaths, prepare_calibration_directory
from .setup import ALGORITHMS, CalibrationConfig, SpotPySetup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ROPE algorithm patch
# ---------------------------------------------------------------------------


def safe_get_best_runs(self, likes, pars, runs, percentage):
    """Drop-in replacement for ``spotpy.algorithms.rope.get_best_runs``.

    Restores correct behavior when ``pars`` contains numpy arrays
    (which can't be sorted as tuples). The original spotpy
    implementation crashes with ``ValueError: The truth value of an
    array with more than one element is ambiguous`` in this case.

    Why monkeypatch instead of subclass: ``spotpy.algorithms.rope`` is
    instantiated by string name elsewhere in spotpy, so subclassing
    requires re-registering the algorithm. A patched method is the
    smaller change.
    """
    import numpy as np

    try:
        if isinstance(pars[0], np.ndarray):
            pars = [list(par) for par in pars]
        result = [
            new_pars
            for (_new_likes, new_pars) in sorted(zip(likes, pars))[
                int(len(likes) * (1 - percentage)) :
            ]
        ]
        logger.debug("safe_get_best_runs returned %d parameter sets", len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("safe_get_best_runs failed: %s", exc)
        raise


def patch_rope_get_best_runs() -> bool:
    """Apply :func:`safe_get_best_runs` to the spotpy ROPE algorithm.

    Returns True if the patch was applied, False if the target method
    was missing (e.g. spotpy refactored the API). Never raises — a
    missing target means the underlying issue was likely fixed
    upstream and we don't need to patch anymore.
    """
    try:
        from spotpy.algorithms import rope
    except ImportError:
        logger.warning("spotpy.algorithms.rope not importable; skipping patch.")
        return False

    if not hasattr(rope, "get_best_runs"):
        logger.info(
            "spotpy.algorithms.rope.get_best_runs not present; "
            "skipping patch (likely fixed upstream)."
        )
        return False

    rope.get_best_runs = safe_get_best_runs  # type: ignore[attr-defined]
    logger.debug("Patched spotpy.algorithms.rope.get_best_runs")
    return True


# ---------------------------------------------------------------------------
# Calibration runner
# ---------------------------------------------------------------------------


def _build_dbname(suffix: str) -> str:
    """Match the legacy ``YYYYMMDD_HH<suffix>`` naming."""
    return datetime.now().strftime("%Y%m%d_%H") + suffix


def run_calibration(
    config: CalibrationConfig,
    db_suffix: str,
    *,
    repetitions: Optional[int] = None,
    db_format: str = "csv",
    save_sim: bool = True,
    staging: Optional[StagingPaths] = None,
) -> str:
    """Run a SPOTPY sampler against the given calibration config.

    Parameters
    ----------
    config
        Calibration configuration (see :class:`CalibrationConfig`). The
        sampler algorithm, per-algorithm kwargs, repetition count, and
        serial/MPI mode are all read from here.
    db_suffix
        Trailing portion of the dbname (e.g. ``"results"``); the prefix
        is the current ``YYYYMMDD_HH`` timestamp.
    repetitions
        Number of sampler iterations. When ``None`` (the default), uses
        ``config.repetitions``. An explicit value overrides the config —
        convenient for a quick notebook re-run without rebuilding the
        config object.
    db_format
        SPOTPY database format (``"csv"``, ``"sql"``, ``"hdf5"``, ...).
    save_sim
        If True, persist the per-sample simulation series.
    staging
        Optional :class:`~pwa_calibration.prepare.StagingPaths`. When
        provided, runs :func:`prepare_calibration_directory` to copy
        Raven binary, .rv* files, GridWeights, depression-depths
        shapefile, etc. from the watershed source folders into
        ``config.calib_dir`` before validating inputs. This mirrors the
        legacy notebook 4 §1.1–1.3 staging-then-calibrate workflow.
        Leave as None when the calibration directory is already
        populated (the default — staging is opt-in, not implicit, so
        re-running calibration on a hand-tuned ``config.calib_dir``
        doesn't unexpectedly overwrite local edits).

    Returns
    -------
    The dbname used (timestamp + suffix), so the caller can locate the
    output file.
    """
    import spotpy.algorithms as alg

    if staging is not None:
        logger.info("Staging calibration inputs from %s", staging.data_root)
        report = prepare_calibration_directory(staging)
        logger.info(
            "Staging report: %d files copied, %d skipped (already present), "
            "%d sources missing",
            len(report.copied),
            len(report.skipped_existing),
            len(report.missing_sources),
        )

    # Fail fast if expected input files are missing — saves a 24-hour
    # AWS calibration job from crashing on a missing CSV partway through.
    config.validate_inputs_exist()

    patch_rope_get_best_runs()

    reps = repetitions if repetitions is not None else config.repetitions
    dbname = _build_dbname(db_suffix)

    # spotpy's parallel="mpi" path requires the process to be launched
    # under mpirun. A serial run (mpi_cores 0 or 1) must use "seq" — using
    # "mpi" there either crashes (mpi4py not installed) or hangs forever
    # waiting for worker ranks that were never spawned.
    parallel = "mpi" if config.is_mpi else "seq"

    try:
        sampler_cls = getattr(alg, config.algorithm)
    except AttributeError as exc:
        raise ValueError(
            f"spotpy.algorithms has no {config.algorithm!r}; "
            f"supported algorithms: {sorted(ALGORITHMS)}."
        ) from exc

    logger.info(
        "Starting %s calibration (parallel=%s) → dbname=%s.%s",
        config.algorithm, parallel, dbname, db_format,
    )

    setup = SpotPySetup(config)
    sampler = sampler_cls(
        setup,
        parallel=parallel,
        dbname=dbname,
        dbformat=db_format,
        save_sim=save_sim,
    )
    # Algorithm-specific knobs (rope's `subsets`, demcz's `nChains`, ...)
    # ride along via config.algorithm_kwargs — mc takes none.
    sampler.sample(reps, **config.algorithm_kwargs)
    logger.info("Calibration complete: %d repetitions written to %s", reps, dbname)
    return dbname


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-calibrate",
        description=(
            "Parallel SPOTPY calibration of a Raven model. Run under MPI: "
            "mpirun -c <N> python -m pwa_calibration.runner <SUFFIX> "
            "--model-name <NAME> --calib-dir <DIR> [...]"
        ),
    )
    parser.add_argument(
        "db_suffix",
        help="Trailing portion of the SPOTPY dbname (timestamp prepended).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a calibration.yml file (see "
            "'python -m pwa_calibration.init_config'). When given, the "
            "config fields are read from this file and the per-field CLI "
            "flags below become unnecessary (per-field flags still "
            "override the YAML when both are present)."
        ),
    )
    parser.add_argument(
        "--model-name",
        help=(
            "Watershed/model name (used for input-file naming). "
            "Required unless --config provides it."
        ),
    )
    parser.add_argument(
        "--calib-dir",
        type=Path,
        help=(
            "Calibration root directory (contains input/, output/, templates/). "
            "Required unless --config provides it."
        ),
    )
    parser.add_argument("--obj-fn", default=None, choices=["kge_adj", "nse", "nse_pbias"])
    parser.add_argument("--algorithm", default=None, choices=list(ALGORITHMS))
    parser.add_argument("--eval-start-yr", type=int, default=None)
    parser.add_argument("--eval-end-yr", type=int, default=None)
    parser.add_argument("--mpi-cores", type=int, default=None)
    # Default None (not 10) so an explicit --repetitions can be told apart
    # from "not passed" — only then does it override the YAML value.
    parser.add_argument("--repetitions", type=int, default=None)
    parser.add_argument("--no-spring-eval", action="store_true")
    parser.add_argument("--low-seep", action="store_true")
    parser.add_argument("--routing", action="store_true")
    parser.add_argument("--dep-scaling", action="store_true")
    parser.add_argument("--runoff-scaling", action="store_true")
    parser.add_argument("--channel-scaling", action="store_true")
    parser.add_argument("--no-phydap-adj", action="store_true")
    parser.add_argument(
        "--stage-from",
        type=Path,
        default=None,
        help=(
            "Path to the watershed Data root. When given, the runner stages "
            "Raven binary, .rv* files, GridWeights, etc. from the source "
            "folders under <stage-from>/<model-name>/ into <calib-dir> "
            "before validating inputs. Requires --netcdf-category."
        ),
    )
    parser.add_argument(
        "--netcdf-category",
        default=None,
        help=(
            "NetCDF data category subfolder name "
            "(e.g. 'Runoff', 'Snowmelt', 'Rainfall'). "
            "Required when --stage-from is set."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def _build_config_from_args(args: argparse.Namespace) -> CalibrationConfig:
    """Merge ``--config <yaml>`` (if any) with per-field CLI overrides.

    Per-field flags take precedence over YAML values when both are
    present — explicit user input wins. Boolean toggles use a "store_true"
    pattern, so they only override when the user actually passed the flag.
    """
    if args.config is not None:
        base_dict = CalibrationConfig.from_yaml(args.config).to_dict()
    else:
        # All required-field validation lives in CalibrationConfig — let
        # it raise if model_name / calib_dir are missing.
        if not args.model_name or args.calib_dir is None:
            raise SystemExit(
                "--model-name and --calib-dir are required unless --config "
                "is provided."
            )
        base_dict = {}

    overrides: dict = {}
    if args.model_name is not None:
        overrides["model_name"] = args.model_name
    if args.calib_dir is not None:
        overrides["calib_dir"] = args.calib_dir
    if args.obj_fn is not None:
        overrides["obj_fn"] = args.obj_fn
    if args.algorithm is not None:
        overrides["algorithm"] = args.algorithm
    if args.repetitions is not None:
        overrides["repetitions"] = args.repetitions
    if args.eval_start_yr is not None:
        overrides["eval_start_yr"] = args.eval_start_yr
    if args.eval_end_yr is not None:
        overrides["eval_end_yr"] = args.eval_end_yr
    if args.mpi_cores is not None:
        overrides["mpi_cores"] = args.mpi_cores
    # Boolean store_true flags: only override when set (you can't undo a
    # YAML True with a CLI flag — there's no --no-routing). To turn a
    # toggle off, edit the YAML.
    if args.no_spring_eval:
        overrides["spring_eval"] = False
    if args.low_seep:
        overrides["low_seep"] = True
    if args.routing:
        overrides["routing"] = True
    if args.dep_scaling:
        overrides["dep_scaling"] = True
    if args.runoff_scaling:
        overrides["runoff_scaling"] = True
    if args.channel_scaling:
        overrides["channel_scaling"] = True
    if args.no_phydap_adj:
        overrides["phydap_adj"] = False

    merged = {**base_dict, **overrides}
    return CalibrationConfig.from_dict(merged)


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if (args.stage_from is None) != (args.netcdf_category is None):
        parser.error(
            "--stage-from and --netcdf-category must be given together "
            "(or both omitted to skip staging)."
        )

    config = _build_config_from_args(args)

    staging: Optional[StagingPaths] = None
    if args.stage_from is not None:
        staging = StagingPaths(
            watershed_name=config.model_name,
            data_root=args.stage_from,
            netcdf_category=args.netcdf_category,
        )

    # repetitions / algorithm already merged into `config` by
    # _build_config_from_args — run_calibration reads them from there.
    run_calibration(
        config=config,
        db_suffix=args.db_suffix,
        staging=staging,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
