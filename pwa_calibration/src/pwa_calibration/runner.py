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
from .setup import CalibrationConfig, SpotPySetup

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
    repetitions: int,
    db_suffix: str,
    db_format: str = "csv",
    save_sim: bool = True,
    algorithm: str = "mc",
    *,
    staging: Optional[StagingPaths] = None,
) -> str:
    """Run a SPOTPY sampler against the given calibration config.

    Parameters
    ----------
    config
        Calibration configuration (see :class:`CalibrationConfig`).
    repetitions
        Number of sampler iterations.
    db_suffix
        Trailing portion of the dbname (e.g. ``"results"``); the prefix
        is the current ``YYYYMMDD_HH`` timestamp.
    db_format
        SPOTPY database format (``"csv"``, ``"sql"``, ``"hdf5"``, ...).
    save_sim
        If True, persist the per-sample simulation series.
    algorithm
        Currently only ``"mc"`` is wired up (matches the legacy
        ``3_calibrate.py``). The script comment in the original noted
        that ROPE "flattens the parameter space and collapses",
        so MC was the intentional default.
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

    dbname = _build_dbname(db_suffix)
    logger.info("Starting calibration → dbname=%s.%s", dbname, db_format)

    setup = SpotPySetup(config)

    if algorithm != "mc":
        raise ValueError(
            f"Algorithm {algorithm!r} not wired up. Use 'mc' (matches "
            "the legacy 3_calibrate.py default)."
        )

    sampler = alg.mc(
        setup,
        parallel="mpi",
        dbname=dbname,
        dbformat=db_format,
        save_sim=save_sim,
    )
    sampler.sample(repetitions)
    logger.info("Calibration complete: %d repetitions written to %s", repetitions, dbname)
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
        "--model-name",
        required=True,
        help="Watershed/model name (used for input-file naming).",
    )
    parser.add_argument(
        "--calib-dir",
        required=True,
        type=Path,
        help="Calibration root directory (contains input/, output/, templates/).",
    )
    parser.add_argument("--obj-fn", default="kge_adj", choices=["kge_adj", "nse", "nse_pbias"])
    parser.add_argument("--eval-start-yr", type=int, default=1995)
    parser.add_argument("--eval-end-yr", type=int, default=2010)
    parser.add_argument("--mpi-cores", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=10)
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

    staging: Optional[StagingPaths] = None
    if args.stage_from is not None:
        staging = StagingPaths(
            watershed_name=args.model_name,
            data_root=args.stage_from,
            netcdf_category=args.netcdf_category,
        )

    config = CalibrationConfig(
        model_name=args.model_name,
        calib_dir=args.calib_dir,
        obj_fn=args.obj_fn,
        eval_start_yr=args.eval_start_yr,
        eval_end_yr=args.eval_end_yr,
        spring_eval=not args.no_spring_eval,
        low_seep=args.low_seep,
        routing=args.routing,
        dep_scaling=args.dep_scaling,
        runoff_scaling=args.runoff_scaling,
        channel_scaling=args.channel_scaling,
        phydap_adj=not args.no_phydap_adj,
        mpi_cores=args.mpi_cores,
    )
    run_calibration(
        config=config,
        repetitions=args.repetitions,
        db_suffix=args.db_suffix,
        staging=staging,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
