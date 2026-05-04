"""Convert Raven model geometry into RavenView-compatible GeoJSON.

RavenView (the IISD-ELA web visualizer) consumes two GeoJSON
FeatureCollections per watershed:

* **Subbasins** — polygons with Raven-specific properties
  (``SubId``, ``rvhName``, ``DowSubId``, ``BasArea``, plus the
  source-shapefile attributes carried verbatim).
* **Rivers** — linestrings with the source-shapefile properties,
  reprojected to WGS84.

Reference inputs are the Liard model files Thomas shared on 2026-05-04
(``data/LiardRiverModel/Liard.json`` and ``LiardRivers.json``) — see
``project-review/client-questions.md`` for the open clarification on
``BasArea`` derivation (Q-002).

What this module does NOT do
----------------------------
* Doesn't package time-series outputs (Hydrographs.csv / Diagnostics.csv).
  Those appear to be loaded by RavenView directly from the Raven output
  folder; whether a transformed format is required is open with Thomas.
* Doesn't simplify geometry. The sample appears to have been passed
  through mapshaper.org for vertex reduction; we leave geometry as-is
  to keep the converter deterministic. Add simplification later if
  display performance demands it.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import shapely
from shapely.geometry import mapping

logger = logging.getLogger(__name__)


WGS84 = "EPSG:4326"
DEFAULT_COORD_PRECISION = 4
SUB_ID_PATTERN = re.compile(r"SUB_(-?\d+)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sub_int(value: object, *, field: str) -> int:
    """Extract the integer suffix from a ``SUB_<n>`` string.

    Outlet sentinels like ``"-1"`` and bare ints are passed through.
    """
    if value is None:
        raise ValueError(f"{field}: cannot parse None")
    s = str(value)
    if s.lstrip("-").isdigit():
        return int(s)
    match = SUB_ID_PATTERN.match(s)
    if match is None:
        raise ValueError(f"{field}: cannot parse {s!r} as 'SUB_<int>'")
    return int(match.group(1))


def _round_coords(geom_mapping: dict, precision: int) -> dict:
    """Recursively round all coordinate floats in a GeoJSON geometry mapping."""

    def _walk(obj):
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        if isinstance(obj, tuple):
            return [_walk(x) for x in obj]
        if isinstance(obj, float):
            return round(obj, precision)
        return obj

    out = dict(geom_mapping)
    out["coordinates"] = _walk(out["coordinates"])
    return out


def _write_geojson(features: list[dict], output_path: Path | str) -> Path:
    """Write a GeoJSON FeatureCollection to *output_path*."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "features": features}
    output_path.write_text(json.dumps(payload, separators=(", ", ": ")))
    logger.info("Wrote %d features → %s", len(features), output_path)
    return output_path


def _load_and_reproject(
    shapefile_path: Path | str, target_crs: str = WGS84
) -> gpd.GeoDataFrame:
    """Read a shapefile, reproject to *target_crs*, and force 2D geometry.

    Some Raven-adjacent shapefiles (e.g. the Liard ``Rivers.shp``) carry
    Z=0 elevation data. RavenView's GeoJSON spec uses 2D coordinates,
    so we drop the Z component up front.
    """
    gdf = gpd.read_file(shapefile_path)
    if gdf.crs is None:
        raise ValueError(
            f"Shapefile {shapefile_path} has no CRS. RavenView needs WGS84 — "
            "set the source CRS before conversion."
        )
    gdf = gdf.to_crs(target_crs)
    gdf["geometry"] = gdf.geometry.apply(shapely.force_2d)
    return gdf


# ---------------------------------------------------------------------------
# Subbasin → RavenView GeoJSON
# ---------------------------------------------------------------------------


# Subbasin shapefile properties carried through verbatim (in the order
# the sample uses; non-listed attributes are dropped).
_SUBBASIN_PASSTHROUGH_PROPERTIES: tuple[str, ...] = (
    "Area", "BBasin", "Sub_B", "Downstream", "Gauged",
    "Reach", "Checked", "B",
)


def _build_subbasin_feature(
    row: gpd.GeoSeries,
    rmapshaperid: int,
    coord_precision: int,
) -> dict:
    """Build a single RavenView subbasin GeoJSON feature."""
    sub_id = _parse_sub_int(row["Sub_B"], field="Sub_B")
    dow_sub_id = _parse_sub_int(row["Downstream"], field="Downstream")
    properties: dict = {}
    for key in _SUBBASIN_PASSTHROUGH_PROPERTIES:
        if key not in row.index:
            raise KeyError(
                f"Subbasin shapefile is missing required column: {key!r}"
            )
        value = row[key]
        # geopandas hands us numpy scalars; coerce to plain Python types
        # so json.dumps doesn't choke.
        if hasattr(value, "item"):
            value = value.item()
        properties[key] = value

    properties["SubId"] = sub_id
    properties["rvhName"] = str(row["Sub_B"])
    properties["DowSubId"] = str(dow_sub_id)
    # See module docstring + Q-002: derivation differs slightly from the
    # sample's BasArea (likely computed on the post-simplification
    # geometry). Using Area * 1e6 keeps the rule simple and stable.
    properties["BasArea"] = int(round(float(row["Area"]) * 1e6))
    properties["rmapshaperid"] = rmapshaperid

    geom_mapping = mapping(row.geometry)
    if coord_precision is not None:
        geom_mapping = _round_coords(geom_mapping, coord_precision)

    return {
        "type": "Feature",
        "geometry": geom_mapping,
        "properties": properties,
    }


def subbasins_to_ravenview_geojson(
    shapefile_path: Path | str,
    output_path: Path | str,
    *,
    coord_precision: int = DEFAULT_COORD_PRECISION,
) -> Path:
    """Convert a Raven subbasin shapefile to RavenView GeoJSON.

    Parameters
    ----------
    shapefile_path
        Path to a ``.shp`` whose attribute table includes the columns
        listed in :data:`_SUBBASIN_PASSTHROUGH_PROPERTIES`.
    output_path
        Where to write the resulting ``.json`` (parent is created).
    coord_precision
        Decimal places to round each coordinate to (default 4 — matches
        the sample). Pass ``None`` to keep full precision.

    Returns
    -------
    The output path written.
    """
    gdf = _load_and_reproject(shapefile_path)
    features = [
        _build_subbasin_feature(row, rmapshaperid=idx, coord_precision=coord_precision)
        for idx, (_, row) in enumerate(gdf.iterrows())
    ]
    return _write_geojson(features, output_path)


# ---------------------------------------------------------------------------
# Rivers → RavenView GeoJSON
# ---------------------------------------------------------------------------


def _build_river_feature(row: gpd.GeoSeries, coord_precision: int) -> dict:
    """Build a single RavenView river GeoJSON feature.

    Properties are passed through verbatim from the source shapefile —
    the Liard sample had no derived fields on rivers.
    """
    properties: dict = {}
    for key in row.index:
        if key == "geometry":
            continue
        value = row[key]
        if hasattr(value, "item"):
            value = value.item()
        properties[key] = value

    geom_mapping = mapping(row.geometry)
    if coord_precision is not None:
        geom_mapping = _round_coords(geom_mapping, coord_precision)

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": geom_mapping,
    }


def rivers_to_ravenview_geojson(
    shapefile_path: Path | str,
    output_path: Path | str,
    *,
    coord_precision: int = DEFAULT_COORD_PRECISION,
    drop_columns: Iterable[str] = (),
) -> Path:
    """Convert a rivers shapefile to RavenView GeoJSON.

    Parameters
    ----------
    shapefile_path
        Path to a ``.shp`` of LineString features (e.g. the
        Canadian Hydrographic Service river network).
    output_path
        Where to write the resulting ``.json``.
    coord_precision
        Decimal places to round each coordinate to (default 4).
    drop_columns
        Optional column names to omit from the output properties (the
        sample carried all source columns; this is here for callers
        whose shapefile has extra attributes).
    """
    gdf = _load_and_reproject(shapefile_path)
    if drop_columns:
        gdf = gdf.drop(columns=list(drop_columns), errors="ignore")
    features = [
        _build_river_feature(row, coord_precision=coord_precision)
        for _, row in gdf.iterrows()
    ]
    return _write_geojson(features, output_path)


# ---------------------------------------------------------------------------
# Top-level convenience
# ---------------------------------------------------------------------------


def export_for_ravenview(
    *,
    subbasin_shapefile: Path | str,
    rivers_shapefile: Path | str,
    output_dir: Path | str,
    watershed_name: str,
    coord_precision: int = DEFAULT_COORD_PRECISION,
) -> tuple[Path, Path]:
    """Run both converters and write to ``<output_dir>/{name,Rivers}.json``.

    Returns ``(subbasin_path, rivers_path)``.
    """
    output_dir = Path(output_dir)
    sub_path = subbasins_to_ravenview_geojson(
        subbasin_shapefile,
        output_dir / f"{watershed_name}.json",
        coord_precision=coord_precision,
    )
    riv_path = rivers_to_ravenview_geojson(
        rivers_shapefile,
        output_dir / f"{watershed_name}Rivers.json",
        coord_precision=coord_precision,
    )
    return sub_path, riv_path
