"""CLI: ``python -m pwa_calibration.init_config <output.yml>``.

Bridges the legacy "edit setup_spotpy.py and re-run" workflow with the
new declarative ``calibration.yml`` consumed by
:func:`pwa_calibration.runner.run_calibration`. Run once per
watershed/calibration variant; re-use across MPI runs.

The CLI prompts for the few fields that vary between runs (model name,
calibration directory, objective function, evaluation window, MPI core
count). All boolean toggles default to the ``CalibrationConfig``
defaults — most users edit those by hand in the YAML afterward,
which is faster than typing y/n at six prompts.

Example::

    $ python -m pwa_calibration.init_config calibration.yml
    Watershed / model name: grassmere
    Calibration root directory [./Data/Calibration/grassmere]:
    Objective function (kge_adj/nse/nse_pbias) [kge_adj]: nse_pbias
    Eval start year [1995]: 2003
    Eval end year [2010]: 2021
    MPI cores (0 or 1 = serial) [0]: 14
    Wrote calibration.yml

    $ mpirun -c 14 python -m pwa_calibration.runner results --config calibration.yml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_calibration.objectives import OBJECTIVES
from pwa_calibration.setup import CalibrationConfig

logger = logging.getLogger(__name__)


def _prompt(label: str, default: Optional[str] = None) -> str:
    """Prompt with a default in brackets. Returns the user's entry or
    the default when the user just presses Enter."""
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{label}{suffix}: ").strip()
    if raw:
        return raw
    if default is None:
        # Required field with no default — re-prompt.
        while not raw:
            raw = input(f"A value is required. {label}: ").strip()
        return raw
    return default


def prompt_for_calibration_config(
    *,
    base_calib_dir: Optional[Path] = None,
    defaults: Optional[dict] = None,
) -> CalibrationConfig:
    """Interactively collect the most-changed calibration fields.

    Boolean toggles (``routing``, ``dep_scaling``, etc.) and
    ``split_areas`` are not prompted — they default to the dataclass
    defaults. Users editing those should open the resulting YAML and
    flip them by hand; that's faster than typing y/n six times.
    """
    if defaults is None:
        defaults = {}

    model_name = _prompt(
        "Watershed / model name",
        default=defaults.get("model_name"),
    )

    if base_calib_dir is None:
        default_calib_dir = str(Path.cwd() / "Data" / "Calibration" / model_name)
    else:
        default_calib_dir = str(Path(base_calib_dir) / model_name)
    calib_dir = _prompt(
        "Calibration root directory",
        default=defaults.get("calib_dir", default_calib_dir),
    )

    obj_fn_choices = "/".join(sorted(OBJECTIVES))
    obj_fn = _prompt(
        f"Objective function ({obj_fn_choices})",
        default=defaults.get("obj_fn", "kge_adj"),
    )

    eval_start_yr = int(_prompt(
        "Eval start year",
        default=str(defaults.get("eval_start_yr", 1995)),
    ))
    eval_end_yr = int(_prompt(
        "Eval end year",
        default=str(defaults.get("eval_end_yr", 2010)),
    ))
    mpi_cores = int(_prompt(
        "MPI cores (0 or 1 = serial)",
        default=str(defaults.get("mpi_cores", 0)),
    ))

    return CalibrationConfig(
        model_name=model_name,
        calib_dir=calib_dir,
        obj_fn=obj_fn,
        eval_start_yr=eval_start_yr,
        eval_end_yr=eval_end_yr,
        mpi_cores=mpi_cores,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-init-calibration-config",
        description=(
            "Interactively build a calibration.yml suitable for "
            "pwa_calibration.runner.run_calibration."
        ),
    )
    parser.add_argument(
        "output_path",
        type=Path,
        help="Where to write the YAML file.",
    )
    parser.add_argument(
        "--base-calib-dir",
        type=Path,
        default=None,
        help=(
            "Default parent directory for the calib_dir prompt. "
            "Defaults to ./Data/Calibration/ relative to cwd."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output_path if it already exists.",
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
        format="%(message)s",
    )

    if args.output_path.exists() and not args.force:
        print(
            f"Refusing to overwrite existing file: {args.output_path}\n"
            "Pass --force to override.",
            file=sys.stderr,
        )
        return 1

    config = prompt_for_calibration_config(base_calib_dir=args.base_calib_dir)
    written = config.to_yaml(args.output_path)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
