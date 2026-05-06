"""CLI: ``python -m pwa_raven.run_step1 --config step1.yml``.

Two equivalent ways to drive Step 1:

* **From the shell** (one-shot, after ``init_step1_config``)::

    python -m pwa_raven.run_step1 --config step1.yml
    python -m pwa_raven.run_step1 --config step1.yml --log-level DEBUG

* **From Python (notebook or script)**::

    from pwa_raven.step1 import Step1Config, run_step1
    config = Step1Config.from_yaml("step1.yml")
    result = run_step1(config)
    print(result.subset_nc, result.adjusted_nc, result.grid_weights)

The CLI is a thin wrapper around the same :func:`pwa_raven.step1.run_step1`
the notebook would import — no behaviour difference, just easier to
script in ``mpirun``-style pipelines.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.step1 import Step1Config, run_step1

# Re-export so notebooks can do `from pwa_raven.run_step1 import run_step1`
# without caring whether the runner or the module hosts the callable.
__all__ = ["run_step1", "Step1Config", "main"]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-run-step1",
        description=(
            "Run the PWA Step 1 pipeline (PHyDAP NetCDF subsetting + "
            "GridWeights + time offset)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("step1.yml"),
        help="Path to the step1.yml config file (default: ./step1.yml).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.config.is_file():
        print(
            f"Config file not found: {args.config}\n"
            "Generate one with: python -m pwa_raven.init_step1_config step1.yml",
            file=sys.stderr,
        )
        return 1

    config = Step1Config.from_yaml(args.config)
    result = run_step1(config)

    print()
    print(f"Subsetted NetCDF : {result.subset_nc}")
    print(f"Adjusted NetCDF  : {result.adjusted_nc}")
    print(f"hybas_map.csv    : {result.hybas_map}")
    print(f"GridWeights.txt  : {result.grid_weights}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
