"""CLI: ``python -m pwa_raven.init_nc_processing_config <output.yml>``.

Interactive prompts for the 5 fields needed to run the NetCDF
processing pipeline (PHyDAP subsetting + GridWeights generation).
Optional fields default to the dataclass defaults — edit the
resulting YAML by hand to override them.

Example::

    $ python -m pwa_raven.init_nc_processing_config nc_processing.yml
    Watershed name: grassmere
    Output root directory [./Data]:
    Path to raw PHyDAP NetCDF: ./Data/phydap_raw/PHyDAP_RDRS21_hourly_runoff.nc
    Path to PHyDAP grid shapefile: ./Data/phydap_raw/prairie_hydrosheds_true_WGS84.shp
    Path to subbasins shapefile (hydro-conditioning output):
        ./Data/grassmere/HydroConditioning/Processed/CLRH_basins_depression_depths.shp
    Wrote nc_processing.yml

    $ python -m pwa_raven.run_nc_processing --config nc_processing.yml

The :mod:`pwa_raven.init_step1_config` module is a backwards-
compatibility alias for this one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.nc_processing import NcProcessingConfig

logger = logging.getLogger(__name__)


def _prompt(label: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{label}{suffix}: ").strip()
    if raw:
        return raw
    if default is None:
        while not raw:
            raw = input(f"A value is required. {label}: ").strip()
        return raw
    return default


def prompt_for_nc_processing_config(
    *, defaults: Optional[dict] = None,
) -> NcProcessingConfig:
    """Interactively collect the 5 required fields."""
    if defaults is None:
        defaults = {}

    watershed_name = _prompt(
        "Watershed name", default=defaults.get("watershed_name"),
    )
    output_dir = _prompt(
        "Output root directory",
        default=defaults.get("output_dir", "./Data"),
    )
    phydap_nc = _prompt(
        "Path to raw PHyDAP NetCDF", default=defaults.get("phydap_nc"),
    )
    phydap_shapefile = _prompt(
        "Path to PHyDAP grid shapefile",
        default=defaults.get("phydap_shapefile"),
    )
    subbasins_shapefile = _prompt(
        "Path to subbasins shapefile (hydro-conditioning output)",
        default=defaults.get("subbasins_shapefile"),
    )

    return NcProcessingConfig(
        watershed_name=watershed_name,
        output_dir=Path(output_dir),
        phydap_nc=Path(phydap_nc),
        phydap_shapefile=Path(phydap_shapefile),
        subbasins_shapefile=Path(subbasins_shapefile),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-init-nc-processing-config",
        description=(
            "Interactively build an nc_processing.yml suitable for "
            "pwa_raven.run_nc_processing."
        ),
    )
    parser.add_argument(
        "output_path", type=Path, help="Where to write the YAML file.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite output_path if it already exists.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level), format="%(message)s",
    )

    if args.output_path.exists() and not args.force:
        print(
            f"Refusing to overwrite existing file: {args.output_path}\n"
            "Pass --force to override.",
            file=sys.stderr,
        )
        return 1

    config = prompt_for_nc_processing_config()
    written = config.to_yaml(args.output_path)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
