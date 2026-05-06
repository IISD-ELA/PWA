"""CLI: ``python -m pwa_raven.init_step2_config <output.yml>``.

Interactive prompts for the 6 fields needed to run Step 2 (Raven
input file generation). Optional fields (curve_number,
write_calibration_templates, etc.) default to the dataclass
defaults — edit the resulting YAML by hand to override them.

Example::

    $ python -m pwa_raven.init_step2_config step2.yml
    Watershed name: grassmere
    Output root directory [./Data]:
    Path to subbasins shapefile (Step 0 output):
        ./Data/grassmere/HydroConditioning/Processed/CLRH_basins_depression_depths.shp
    Path to Step 1 _adj.nc:
        ./Data/grassmere/Runoff/Processed/grassmere_runoff_adj.nc
    Path to WSC metadata CSV: ./Data/grassmere/Raven/Raw/metadata_05NF002.csv
    Path to WSC daily-discharge CSV: ./Data/grassmere/Raven/Raw/daily_05NF002.csv
    Wrote step2.yml

    $ python -m pwa_raven.run_step2 --config step2.yml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.step2 import Step2Config

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


def prompt_for_step2_config(*, defaults: Optional[dict] = None) -> Step2Config:
    """Interactively collect the 6 required Step 2 fields."""
    if defaults is None:
        defaults = {}

    watershed_name = _prompt(
        "Watershed name",
        default=defaults.get("watershed_name"),
    )
    output_dir = _prompt(
        "Output root directory",
        default=defaults.get("output_dir", "./Data"),
    )
    subbasins_shapefile = _prompt(
        "Path to subbasins shapefile (Step 0 output)",
        default=defaults.get("subbasins_shapefile"),
    )
    phydap_nc = _prompt(
        "Path to Step 1 _adj.nc",
        default=defaults.get("phydap_nc"),
    )
    wsc_metadata_csv = _prompt(
        "Path to WSC metadata CSV",
        default=defaults.get("wsc_metadata_csv"),
    )
    wsc_daily_csv = _prompt(
        "Path to WSC daily-discharge CSV",
        default=defaults.get("wsc_daily_csv"),
    )

    return Step2Config(
        watershed_name=watershed_name,
        output_dir=Path(output_dir),
        subbasins_shapefile=Path(subbasins_shapefile),
        phydap_nc=Path(phydap_nc),
        wsc_metadata_csv=Path(wsc_metadata_csv),
        wsc_daily_csv=Path(wsc_daily_csv),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-init-step2-config",
        description=(
            "Interactively build a step2.yml suitable for "
            "pwa_raven.step2.run_step2."
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

    config = prompt_for_step2_config()
    written = config.to_yaml(args.output_path)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
