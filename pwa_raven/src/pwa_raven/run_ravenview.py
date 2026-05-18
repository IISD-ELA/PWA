"""CLI: ``python -m pwa_raven.run_ravenview ...``.

Convert a watershed's subbasin + river shapefiles into the two
RavenView-compatible GeoJSON files and structurally validate them.

Example::

    python -m pwa_raven.run_ravenview \\
        --subbasins .../CLRH_basins_depression_depths.shp \\
        --rivers    .../finalcat_info_riv_v1-0.shp \\
        --output-dir .../RavenView \\
        --watershed-name grassmere_test_run

Writes ``<name>.json`` (subbasins) and ``<name>Rivers.json`` (rivers),
then runs :func:`pwa_raven.raven.ravenview.validate_ravenview_geojson`
on each. Validation conformance to the known-good Liard sample does not
*prove* RavenView will render the files — upload them at
https://raven.uwaterloo.ca/RavenView/RavenView.html to confirm — but it
catches every structural divergence from that sample.

The CLI is a thin wrapper around
:func:`pwa_raven.raven.ravenview.export_for_ravenview`; notebook callers
can import that function directly.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pwa_raven.raven.ravenview import export_for_ravenview, validate_ravenview_geojson

__all__ = ["main", "export_for_ravenview", "validate_ravenview_geojson"]

_RAVENVIEW_URL = "https://raven.uwaterloo.ca/RavenView/RavenView.html"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwa-ravenview",
        description=(
            "Convert a watershed's subbasin + river shapefiles into "
            "RavenView-compatible GeoJSON and structurally validate the output."
        ),
    )
    parser.add_argument(
        "--subbasins", type=Path, required=True,
        help="Path to the subbasin shapefile (Step 0/2 output for schema=clrh).",
    )
    parser.add_argument(
        "--rivers", type=Path, required=True,
        help="Path to the rivers shapefile.",
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Directory for <name>.json and <name>Rivers.json.",
    )
    parser.add_argument(
        "--watershed-name", required=True,
        help="Watershed name — used for the output filenames.",
    )
    parser.add_argument(
        "--schema", default="clrh", choices=["clrh", "liard"],
        help=(
            "Subbasin source schema: 'clrh' (default — the PWA pipeline's "
            "Step 0/2 output) or 'liard' (the Liard reference sample)."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level), format="%(message)s",
    )

    for label, path in (("subbasins", args.subbasins), ("rivers", args.rivers)):
        if not path.is_file():
            print(f"{label} shapefile not found: {path}", file=sys.stderr)
            return 1

    sub_path, riv_path = export_for_ravenview(
        subbasin_shapefile=args.subbasins,
        rivers_shapefile=args.rivers,
        output_dir=args.output_dir,
        watershed_name=args.watershed_name,
        schema=args.schema,
    )

    sub_problems = validate_ravenview_geojson(sub_path, kind="subbasins")
    riv_problems = validate_ravenview_geojson(riv_path, kind="rivers")

    print()
    print(f"Subbasins GeoJSON : {sub_path}")
    print(f"Rivers GeoJSON    : {riv_path}")
    print()

    if not sub_problems and not riv_problems:
        print(
            "Validation: OK — both files structurally match the RavenView "
            "format.\n"
            f"Upload them at {_RAVENVIEW_URL} to confirm they render."
        )
        return 0

    print("Validation found structural problems:")
    for label, problems in (("subbasins", sub_problems), ("rivers", riv_problems)):
        for problem in problems:
            print(f"  [{label}] {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
