"""CLI: ``python -m pwa_raven.run_nc_processing --config nc_processing.yml``.

Two equivalent ways to drive the NetCDF processing pipeline:

* **From the shell** (one-shot, after ``init_nc_processing_config``)::

    python -m pwa_raven.run_nc_processing --config nc_processing.yml
    python -m pwa_raven.run_nc_processing --config nc_processing.yml --log-level DEBUG

* **From Python (notebook or script)**::

    from pwa_raven.nc_processing import NcProcessingConfig, run_nc_processing
    config = NcProcessingConfig.from_yaml("nc_processing.yml")
    result = run_nc_processing(config)
    print(result.subset_nc, result.adjusted_nc, result.grid_weights)

The CLI is a thin wrapper around :func:`pwa_raven.nc_processing.run_nc_processing`
— no behaviour difference, just easier to script in ``mpirun``-style
pipelines. The :mod:`pwa_raven.run_step1` module is a backwards-
compatibility alias for this one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.nc_processing import NcProcessingConfig, run_nc_processing

# Re-export so notebooks can do `from pwa_raven.run_nc_processing import
# run_nc_processing` without caring whether the runner or the module
# hosts the callable.
__all__ = ["run_nc_processing", "NcProcessingConfig", "main"]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-run-nc-processing",
        description=(
            "Run the PWA NetCDF processing pipeline (PHyDAP subsetting + "
            "GridWeights + time offset)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("nc_processing.yml"),
        help="Path to the nc_processing.yml config file (default: ./nc_processing.yml).",
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
            "Generate one with: python -m pwa_raven.init_nc_processing_config "
            "nc_processing.yml",
            file=sys.stderr,
        )
        return 1

    config = NcProcessingConfig.from_yaml(args.config)
    result = run_nc_processing(config)

    print()
    print(f"Subsetted NetCDF : {result.subset_nc}")
    print(f"Adjusted NetCDF  : {result.adjusted_nc}")
    print(f"hybas_map.csv    : {result.hybas_map}")
    print(f"GridWeights.txt  : {result.grid_weights}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
