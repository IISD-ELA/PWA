"""CLI: ``python -m pwa_raven.init_raven_inputs_config <output.yml>``.

Interactive prompts for the 6 fields needed to run the Raven input
file generation pipeline. Optional fields (curve_number,
write_calibration_templates, etc.) default to the dataclass defaults
— edit the resulting YAML by hand to override them.

Example::

    $ python -m pwa_raven.init_raven_inputs_config raven_inputs.yml
    Watershed name: grassmere
    Output root directory [./Data]:
    Path to subbasins shapefile (hydro-conditioning output):
        ./Data/grassmere/HydroConditioning/Processed/CLRH_basins_depression_depths.shp
    Path to NetCDF processing _adj.nc:
        ./Data/grassmere/Runoff/Processed/grassmere_runoff_adj.nc
    Path to WSC metadata CSV: ./Data/grassmere/Raven/Raw/metadata_05NF002.csv
    Path to WSC daily-discharge CSV: ./Data/grassmere/Raven/Raw/daily_05NF002.csv
    Wrote raven_inputs.yml

    $ python -m pwa_raven.run_raven_inputs --config raven_inputs.yml

The :mod:`pwa_raven.init_step2_config` module is a backwards-
compatibility alias for this one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.raven_inputs import RavenInputsConfig

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


def prompt_for_raven_inputs_config(
    *, defaults: Optional[dict] = None,
) -> RavenInputsConfig:
    """Interactively collect the 6 required fields."""
    if defaults is None:
        defaults = {}

    watershed_name = _prompt(
        "Watershed name", default=defaults.get("watershed_name"),
    )
    output_dir = _prompt(
        "Output root directory",
        default=defaults.get("output_dir", "./Data"),
    )
    subbasins_shapefile = _prompt(
        "Path to subbasins shapefile (hydro-conditioning output)",
        default=defaults.get("subbasins_shapefile"),
    )
    phydap_nc = _prompt(
        "Path to NetCDF processing _adj.nc",
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
    # Optional — empty input skips RavenView visualization export.
    rivers_default = defaults.get("rivers_shapefile", "")
    rivers_shapefile = _prompt(
        "Path to rivers shapefile (optional, for RavenView export — "
        "leave blank to skip)",
        default=rivers_default,
    )

    return RavenInputsConfig(
        watershed_name=watershed_name,
        output_dir=Path(output_dir),
        subbasins_shapefile=Path(subbasins_shapefile),
        phydap_nc=Path(phydap_nc),
        wsc_metadata_csv=Path(wsc_metadata_csv),
        wsc_daily_csv=Path(wsc_daily_csv),
        rivers_shapefile=Path(rivers_shapefile) if rivers_shapefile else None,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-init-raven-inputs",
        description=(
            "Interactively build a raven_inputs.yml suitable for "
            "pwa_raven.run_raven_inputs."
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

    config = prompt_for_raven_inputs_config()
    written = config.to_yaml(args.output_path)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
