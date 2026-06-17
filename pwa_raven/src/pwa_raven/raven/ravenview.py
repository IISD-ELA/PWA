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
import math
import re
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd
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


def _json_safe(value: object) -> object:
    """Coerce a shapefile cell value to a strict-JSON-safe Python scalar.

    numpy scalars become plain Python; pandas NA / NaT and non-finite
    floats (``NaN``, ``inf``) become ``None``. The last part matters:
    ``json.dumps`` would otherwise emit the bare tokens ``NaN`` /
    ``Infinity``, which are invalid JSON — RavenView's browser-side
    ``JSON.parse`` rejects them and the whole file silently fails to load.
    """
    if hasattr(value, "item"):  # numpy scalar → plain Python
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # non-scalar (shouldn't happen for a cell) — leave as-is
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


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
    # allow_nan=False: refuse to emit the non-standard NaN / Infinity
    # tokens. Property values are sanitised by _json_safe upstream, so
    # this should never trigger — but if it does, failing loud here beats
    # writing a file that RavenView's JSON.parse silently rejects.
    output_path.write_text(
        json.dumps(payload, separators=(", ", ": "), allow_nan=False)
    )
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
        properties[key] = _json_safe(row[key])

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


def _build_subbasin_feature_clrh(
    row: gpd.GeoSeries,
    rmapshaperid: int,
    coord_precision: int,
) -> dict:
    """Build a RavenView subbasin feature from a CLRH-hydrofabric row.

    The CLRH schema — the PWA pipeline's own Step 0/2 subbasin output —
    already carries ``SubId``, ``DowSubId`` and ``BasArea`` under those
    exact names, so (unlike the Liard reference path) nothing is
    renamed. ``rvhName`` and ``rmapshaperid`` are derived; every other
    source column rides along verbatim as an extra property. RavenView
    ignores properties it doesn't use, so a superset is safe.
    """
    sub_id = _parse_sub_int(row["SubId"], field="SubId")
    dow_sub_id = _parse_sub_int(row["DowSubId"], field="DowSubId")

    properties: dict = {}
    for key in row.index:
        if key == "geometry":
            continue
        properties[key] = _json_safe(row[key])

    properties["SubId"] = sub_id
    # The Raven .rvh names each subbasin "sub<SubId>"; mirror that.
    properties["rvhName"] = f"sub{sub_id}"
    properties["DowSubId"] = str(dow_sub_id)
    # CLRH BasArea is carried through as-is. Its unit / derivation is the
    # subject of client-questions Q-002 — confirm against RavenView.
    properties["BasArea"] = int(round(float(row["BasArea"])))
    properties["rmapshaperid"] = rmapshaperid

    geom_mapping = mapping(row.geometry)
    if coord_precision is not None:
        geom_mapping = _round_coords(geom_mapping, coord_precision)

    return {
        "type": "Feature",
        "geometry": geom_mapping,
        "properties": properties,
    }


# Subbasin feature builders keyed by source-shapefile schema.
_SUBBASIN_BUILDERS = {
    "clrh": _build_subbasin_feature_clrh,   # PWA pipeline output
    "liard": _build_subbasin_feature,       # Liard reference sample
}


def subbasins_to_ravenview_geojson(
    shapefile_path: Path | str,
    output_path: Path | str,
    *,
    schema: str = "clrh",
    coord_precision: int = DEFAULT_COORD_PRECISION,
) -> Path:
    """Convert a Raven subbasin shapefile to RavenView GeoJSON.

    Parameters
    ----------
    shapefile_path
        Path to a subbasin ``.shp``.
    output_path
        Where to write the resulting ``.json`` (parent is created).
    schema
        Source-shapefile schema: ``"clrh"`` (default — the PWA pipeline's
        Step 0/2 output, with native ``SubId``/``DowSubId``/``BasArea``)
        or ``"liard"`` (the Liard reference sample, with ``Sub_B``/
        ``Downstream``/``Area``).
    coord_precision
        Decimal places to round each coordinate to (default 4 — matches
        the sample). Pass ``None`` to keep full precision.

    Returns
    -------
    The output path written.
    """
    try:
        builder = _SUBBASIN_BUILDERS[schema]
    except KeyError:
        raise ValueError(
            f"Unknown subbasin schema {schema!r}; "
            f"choose from {sorted(_SUBBASIN_BUILDERS)}."
        )
    gdf = _load_and_reproject(shapefile_path)
    features = [
        builder(row, rmapshaperid=idx, coord_precision=coord_precision)
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
        properties[key] = _json_safe(row[key])

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
    schema: str = "clrh",
    coord_precision: int = DEFAULT_COORD_PRECISION,
) -> tuple[Path, Path]:
    """Run both converters and write to ``<output_dir>/{name,Rivers}.json``.

    *schema* selects the subbasin source schema (``"clrh"`` for PWA
    pipeline output, ``"liard"`` for the reference sample). Rivers are
    schema-agnostic — their properties pass through verbatim.

    Returns ``(subbasin_path, rivers_path)``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sub_path = subbasins_to_ravenview_geojson(
        subbasin_shapefile,
        output_dir / f"{watershed_name}.json",
        schema=schema,
        coord_precision=coord_precision,
    )
    riv_path = rivers_to_ravenview_geojson(
        rivers_shapefile,
        output_dir / f"{watershed_name}Rivers.json",
        coord_precision=coord_precision,
    )
    return sub_path, riv_path


def export_for_ravenview_from_config(
    config,
    *,
    rivers_shapefile: Path | str | None = None,
    output_dir: Path | str | None = None,
    coord_precision: int = DEFAULT_COORD_PRECISION,
) -> tuple[Path, Path]:
    """Convenience wrapper — pull subbasins, output dir, and watershed name
    from a :class:`pwa_raven.raven_inputs.RavenInputsConfig`.

    The standalone :func:`export_for_ravenview` needs four arguments;
    this helper needs at most one (``rivers_shapefile``), and zero if
    the config already carries it.

    Parameters
    ----------
    config
        A ``RavenInputsConfig``. Provides ``subbasins_shapefile``,
        ``watershed_name``, ``ravenview_dir`` (default output target),
        and — if set — ``rivers_shapefile``.
    rivers_shapefile
        Override for the config's rivers path. Required if the config
        doesn't carry one.
    output_dir
        Override for the default ``<output_dir>/Raven/RavenView/``
        target. Useful when generating a one-off comparison export.

    Returns ``(subbasin_path, rivers_path)``.

    Raises ``ValueError`` if no rivers shapefile is available from
    either source.
    """
    rivers = rivers_shapefile if rivers_shapefile is not None else config.rivers_shapefile
    if rivers is None:
        raise ValueError(
            "No rivers shapefile available — set rivers_shapefile on the "
            "RavenInputsConfig or pass it explicitly to this function."
        )
    target = Path(output_dir) if output_dir is not None else config.ravenview_dir
    return export_for_ravenview(
        subbasin_shapefile=config.subbasins_shapefile,
        rivers_shapefile=rivers,
        output_dir=target,
        watershed_name=config.safe_name,
        schema="clrh",
        coord_precision=coord_precision,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


# Geometry types RavenView accepts, per the known-good Liard sample.
_VALID_GEOMETRY_TYPES = {
    "subbasins": {"Polygon", "MultiPolygon"},
    "rivers": {"LineString", "MultiLineString"},
}

# Properties every subbasin feature in the Liard sample carries. RavenView
# relies on these; extra properties are harmless, but a missing one is a
# structural divergence from the confirmed-working sample.
_REQUIRED_SUBBASIN_PROPERTIES = (
    "SubId", "rvhName", "DowSubId", "BasArea", "rmapshaperid",
)


def _coord_problems(coords: object, path: str) -> list[str]:
    """Recursively check that every [lon, lat] pair sits in WGS84 range."""
    if (
        isinstance(coords, list)
        and len(coords) == 2
        and all(isinstance(c, (int, float)) for c in coords)
    ):
        lon, lat = coords
        out: list[str] = []
        if not -180 <= lon <= 180:
            out.append(f"{path}: longitude {lon} outside [-180, 180]")
        if not -90 <= lat <= 90:
            out.append(f"{path}: latitude {lat} outside [-90, 90]")
        return out
    if isinstance(coords, list):
        nested: list[str] = []
        for i, item in enumerate(coords):
            nested.extend(_coord_problems(item, f"{path}[{i}]"))
        return nested
    return [f"{path}: expected a coordinate list, got {type(coords).__name__}"]


def validate_ravenview_geojson(path: Path | str, *, kind: str) -> list[str]:
    """Structurally validate a RavenView GeoJSON file.

    Checks conformance to the shape of the known-good Liard sample —
    the only confirmed-working RavenView input we have: a
    ``FeatureCollection`` of ``Feature`` objects with valid geometry,
    WGS84 coordinates, and (for subbasins) the required property keys.

    Parameters
    ----------
    path
        The ``.json`` file to validate.
    kind
        ``"subbasins"`` or ``"rivers"`` — selects the allowed geometry
        types and whether subbasin properties are required.

    Returns
    -------
    A list of human-readable problem strings; an empty list means the
    file is structurally valid. This does NOT prove RavenView will
    render it — only an actual RavenView load confirms that — but it
    catches every structural divergence from the known-good sample.
    """
    if kind not in _VALID_GEOMETRY_TYPES:
        raise ValueError(
            f"kind must be one of {sorted(_VALID_GEOMETRY_TYPES)}, got {kind!r}"
        )

    # Python's json.loads accepts NaN / Infinity by default; a browser's
    # JSON.parse does not. parse_constant fires for exactly those tokens,
    # so we can flag a file that would silently fail to load in RavenView.
    invalid_constants: list[str] = []
    try:
        payload = json.loads(
            Path(path).read_text(),
            parse_constant=lambda c: invalid_constants.append(c) or None,
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read/parse {path}: {exc}"]

    if not isinstance(payload, dict):
        return [f"top level is {type(payload).__name__}, expected an object"]

    problems: list[str] = []
    if invalid_constants:
        problems.append(
            f"file contains non-standard JSON tokens "
            f"{sorted(set(invalid_constants))} — RavenView's JSON.parse "
            "rejects NaN / Infinity; the file will not load"
        )
    if payload.get("type") != "FeatureCollection":
        problems.append(
            f"top-level 'type' is {payload.get('type')!r}, expected 'FeatureCollection'"
        )
    features = payload.get("features")
    if not isinstance(features, list):
        problems.append("'features' is missing or not a list")
        return problems
    if not features:
        problems.append("'features' is empty")

    allowed_geom = _VALID_GEOMETRY_TYPES[kind]
    for i, feat in enumerate(features):
        fp = f"features[{i}]"
        if not isinstance(feat, dict):
            problems.append(f"{fp}: not an object")
            continue
        if feat.get("type") != "Feature":
            problems.append(f"{fp}.type is {feat.get('type')!r}, expected 'Feature'")

        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            problems.append(f"{fp}.geometry: missing or not an object")
        else:
            gtype = geom.get("type")
            if gtype not in allowed_geom:
                problems.append(
                    f"{fp}.geometry.type is {gtype!r}, expected one of "
                    f"{sorted(allowed_geom)}"
                )
            if "coordinates" in geom:
                problems.extend(
                    _coord_problems(geom["coordinates"], f"{fp}.geometry.coordinates")
                )
            else:
                problems.append(f"{fp}.geometry: no 'coordinates'")

        props = feat.get("properties")
        if not isinstance(props, dict):
            problems.append(f"{fp}.properties: missing or not an object")
        elif kind == "subbasins":
            for key in _REQUIRED_SUBBASIN_PROPERTIES:
                if key not in props:
                    problems.append(
                        f"{fp}.properties: missing required key {key!r}"
                    )
    return problems
