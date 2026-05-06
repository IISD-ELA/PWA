"""Basin attribute preparation for Raven RVH/RVP file generation.

Extracted from ``PWA/_notebooks/2_raven_input_gen.ipynb`` § 2.1–2.2.

Loads the depression-depths shapefile, filters out non-contributing lake
catchments, computes NRCS time-of-concentration / time-to-peak, sanitizes
sentinel values (invalid river lengths, slopes, bankfull depths, Manning n),
and identifies the watershed outlet.

Source-of-magic-numbers reference (preserved verbatim from the notebook):
  - Curve number is per-watershed (e.g. 63 for Manning, varies for grassmere)
  - Flow-length formula: ``209 * area_acres ** 0.6``
  - Time-of-concentration: ``L^0.8 * (S+1)^0.7 / (1140 * slope_pct^0.5)``
    (NRCS TR-55 lag equation, in hours)
  - Time-to-peak: ``0.6 * time_of_concentration``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Conversion + NRCS constants
SQM_TO_ACRES = 0.00024710538
M_TO_KM = 1 / 1000
SQM_TO_SQKM = 1 / 1_000_000

FLOW_LENGTH_COEF = 209.0          # NRCS TR-55 flow-length empirical coefficient
FLOW_LENGTH_EXP = 0.6
TC_FLOW_LENGTH_EXP = 0.8
TC_RETENTION_EXP = 0.7
TC_DENOMINATOR_COEF = 1140.0
TC_SLOPE_EXP = 0.5
TIME_TO_PEAK_RATIO = 0.6

# Sentinel values flagged as "invalid" by upstream pre-processing
INVALID_RIV_LENGTH_NEG = -0.001         # → "ZERO-" string sentinel for RVH
INVALID_RIV_LENGTH_NUMERIC = -0.0012345  # → 0.0 (numeric replacement)
MIN_RIV_SLOPE = 0.0001
MIN_RIV_SLOPE_REPLACEMENT = 0.0001234
MIN_BKF_DEPTH = 1.0
DEFAULT_FLOODPLAIN_N = 0.05
DEFAULT_CHANNEL_N = 0.025


@dataclass(frozen=True)
class WatershedOutlet:
    """Identified outlet sub-basin for a watershed."""
    sub_id: int
    drainage_area_km2: float


def filter_contributing_basins(
    gdf: gpd.GeoDataFrame,
    *,
    lake_cat_col: str = "Lake_Cat",
    threshold: int = 2,
) -> gpd.GeoDataFrame:
    """Drop non-contributing lake catchments (Lake_Cat ≥ 2)."""
    before = len(gdf)
    out = gdf[gdf[lake_cat_col] < threshold].copy()
    logger.info("Filtered lake catchments: %d → %d basins", before, len(out))
    return out


def compute_time_of_concentration(
    gdf: gpd.GeoDataFrame,
    curve_number: float,
    *,
    area_col: str = "BasArea",
    slope_col: str = "BasSlope",
) -> gpd.GeoDataFrame:
    """Add ``time_of_conc`` (hours) and ``time_to_peak`` (hours) columns.

    Uses NRCS TR-55 lag-time formulation. Mutates a copy of *gdf* and returns
    it; also adds intermediate columns ``BasinsArea_acres``,
    ``BasSlope_prcnt``, ``FlowLength_ft``, and ``max_retention``.
    """
    cn_retention = (1000.0 / curve_number) - 10.0

    out = gdf.copy()
    out["BasinsArea_acres"] = out[area_col] * SQM_TO_ACRES
    out["BasSlope_prcnt"] = np.tan(np.radians(out[slope_col])) * 100.0
    out["FlowLength_ft"] = FLOW_LENGTH_COEF * out["BasinsArea_acres"] ** FLOW_LENGTH_EXP
    out["max_retention"] = cn_retention

    out["time_of_conc"] = (
        out["FlowLength_ft"] ** TC_FLOW_LENGTH_EXP
        * (cn_retention + 1) ** TC_RETENTION_EXP
    ) / (TC_DENOMINATOR_COEF * out["BasSlope_prcnt"] ** TC_SLOPE_EXP)

    out["time_to_peak"] = out["time_of_conc"] * TIME_TO_PEAK_RATIO

    return out


def sanitize_river_lengths(rivlengths_m: list[float]) -> tuple[list, list[float]]:
    """Sanitize raw river lengths into RVH-ready values.

    Returns
    -------
    rivlengths_mod : list
        Mixed list of floats and the string ``"ZERO-"``. Lengths equal to
        the sentinel ``-0.001`` (m → -0.001 m, rounded to 3 decimals) become
        the string ``"ZERO-"``, signalling "no river segment" to the RVH writer.
    rivlengths_mod_n : list of float
        All-numeric variant: lengths equal to the sentinel ``-0.0012345``
        become ``0.0``. Used by code paths that require numeric input.
    """
    rivlengths_km = [x * M_TO_KM for x in rivlengths_m]
    rivlengths_km_rounded = [round(v, 3) for v in rivlengths_km]

    rivlengths_mod: list = [
        "ZERO-" if x == INVALID_RIV_LENGTH_NEG else x
        for x in rivlengths_km_rounded
    ]
    rivlengths_mod_n: list[float] = [
        0.0 if x == INVALID_RIV_LENGTH_NUMERIC else x
        for x in rivlengths_km
    ]
    return rivlengths_mod, rivlengths_mod_n


def sanitize_river_slopes(rivslopes: list[float]) -> list[float]:
    """Replace near-zero slopes with a small positive sentinel."""
    return [
        MIN_RIV_SLOPE_REPLACEMENT if x <= MIN_RIV_SLOPE else x
        for x in rivslopes
    ]


def sanitize_bankfull_depths(bkfdepths: list[float]) -> list[float]:
    """Clamp bankfull depths below 1m up to 1m."""
    return [MIN_BKF_DEPTH if x < MIN_BKF_DEPTH else x for x in bkfdepths]


def sanitize_floodplain_manning_n(values: list[float]) -> list[float]:
    """Replace negative floodplain Manning's n with the default ``0.05``."""
    return [DEFAULT_FLOODPLAIN_N if x < 0 else x for x in values]


def sanitize_channel_manning_n(values: list[float]) -> list[float]:
    """Replace negative channel Manning's n with the default ``0.025``."""
    return [DEFAULT_CHANNEL_N if x < 0 else x for x in values]


def find_watershed_outlet(
    gdf: gpd.GeoDataFrame,
    *,
    has_poi_col: str = "Has_POI",
    sub_id_col: str = "SubId",
    dow_sub_id_col: str = "DowSubId",
    drain_area_col: str = "DrainArea",
) -> WatershedOutlet:
    """Identify the gauged outlet basin and its drainage area (km²).

    The outlet is the basin with ``Has_POI == 1``; if multiple are gauged
    (e.g. multiple POIs in series), it's the one that doesn't drain into any
    other basin in the watershed.
    """
    gauged = gdf.loc[gdf[has_poi_col] == 1]
    if len(gauged) == 0:
        raise ValueError(
            f"No gauged outlet found in shapefile (no rows with {has_poi_col} == 1)."
        )

    if len(gauged) == 1:
        sub_id = gauged[sub_id_col].item()
        drain_area = gauged[drain_area_col].item()
    else:
        terminal = gauged[~gauged[dow_sub_id_col].isin(gdf[sub_id_col])]
        if len(terminal) != 1:
            raise ValueError(
                f"Expected exactly one terminal gauged basin, found {len(terminal)}. "
                f"Cannot disambiguate watershed outlet."
            )
        sub_id = terminal[sub_id_col].item()
        drain_area = terminal[drain_area_col].item()

    return WatershedOutlet(
        sub_id=int(sub_id),
        drainage_area_km2=float(drain_area) * SQM_TO_SQKM,
    )


@dataclass(frozen=True)
class PreparedBasinAttributes:
    """All sanitized per-basin lists ready for RVH/RVP template writing."""
    gdf: gpd.GeoDataFrame
    sub_ids: list[int]
    riv_lengths_mod: list           # may contain "ZERO-" strings
    riv_lengths_mod_n: list[float]  # all-numeric variant
    riv_slopes: list[float]
    bkf_depths: list[float]
    floodplain_n: list[float]
    channel_n: list[float]
    basin_area_km2: list[float]
    outlet: WatershedOutlet


def prepare_basin_attributes(
    gdf: gpd.GeoDataFrame,
    curve_number: float,
) -> PreparedBasinAttributes:
    """End-to-end: filter, compute TC/TTP, sanitize, identify outlet."""
    filtered = filter_contributing_basins(gdf)
    enriched = compute_time_of_concentration(filtered, curve_number)

    sub_ids = [int(x) for x in enriched["SubId"]]
    riv_lengths_mod, riv_lengths_mod_n = sanitize_river_lengths(
        list(enriched["RivLength"])
    )
    riv_slopes = sanitize_river_slopes(list(enriched["RivSlope"]))
    bkf_depths = sanitize_bankfull_depths(list(enriched["BkfDepth"]))
    floodplain_n = sanitize_floodplain_manning_n(list(enriched["FloodP_n"]))
    channel_n = sanitize_channel_manning_n(list(enriched["Ch_n"]))
    basin_area_km2 = [x * SQM_TO_SQKM for x in enriched["BasArea"]]

    outlet = find_watershed_outlet(enriched)

    return PreparedBasinAttributes(
        gdf=enriched,
        sub_ids=sub_ids,
        riv_lengths_mod=riv_lengths_mod,
        riv_lengths_mod_n=riv_lengths_mod_n,
        riv_slopes=riv_slopes,
        bkf_depths=bkf_depths,
        floodplain_n=floodplain_n,
        channel_n=channel_n,
        basin_area_km2=basin_area_km2,
        outlet=outlet,
    )


# ---------------------------------------------------------------------------
# Aspect ratio (minimum-area bounding rectangle)
# ---------------------------------------------------------------------------


def compute_aspect_ratio_bbox(geom) -> float | None:
    """Aspect ratio of a polygon's minimum-area bounding rectangle.

    Returns ``longest_side / shortest_side`` of the smallest rectangle
    that contains *geom* (the minimum-area bounding rectangle, MABR).
    A near-square basin returns ~1.0; an elongated basin returns a
    larger value.

    Returns ``None`` for non-Polygon / non-MultiPolygon geometries and
    for polygons whose MABR has a zero-length side (degenerate).

    For MultiPolygon input the largest component polygon is used —
    matches the legacy notebook behaviour.

    Note on numerics: this uses shapely's ``minimum_rotated_rectangle``
    rather than the rotating-calipers loop in the original notebook
    (cell 78). The notebook's loop applies its rotation matrix in the
    wrong direction (row-vector multiplication of a column-rotation
    matrix inverts the rotation), so it does not actually find the
    minimum area in the general case — the produced ``aspect_ratios.csv``
    values for the grassmere watershed differ from the geometric
    answer. See ``project-review/client-questions.md`` Q-004 for the
    open question about whether to honour those legacy values.
    """
    # Local import keeps the heavy shapely dep out of module scope for
    # callers who don't need geometry math.
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geom, MultiPolygon):
        geom = max(geom.geoms, key=lambda g: g.area)
    if not isinstance(geom, Polygon):
        return None

    mabr = geom.minimum_rotated_rectangle
    if not isinstance(mabr, Polygon):
        return None

    coords = np.array(mabr.exterior.coords[:-1])
    if len(coords) < 4:
        return None

    # MABR is a rectangle: 4 vertices, 2 distinct edge lengths
    side_a = float(np.linalg.norm(coords[1] - coords[0]))
    side_b = float(np.linalg.norm(coords[2] - coords[1]))
    if min(side_a, side_b) == 0:
        return None
    return max(side_a, side_b) / min(side_a, side_b)


def compute_aspect_ratios(
    gdf: gpd.GeoDataFrame, *, sub_id_col: str = "SubId",
) -> pd.DataFrame:
    """Per-subbasin aspect ratios as a 2-column DataFrame.

    Returns a frame with ``sub_id_col`` and ``Aspect_Ratio`` columns —
    matches the legacy ``aspect_ratios.csv`` schema (the SPOTPY
    calibration setup reads it back via ``pd.read_csv``).

    Rows whose geometry returns ``None`` (non-Polygon, degenerate, etc.)
    are kept with NaN — the caller decides whether to drop or impute.
    """
    if sub_id_col not in gdf.columns:
        raise KeyError(
            f"Subbasin GeoDataFrame is missing the required column "
            f"{sub_id_col!r}. Available: {list(gdf.columns)}"
        )

    return pd.DataFrame({
        sub_id_col: gdf[sub_id_col].tolist(),
        "Aspect_Ratio": [compute_aspect_ratio_bbox(g) for g in gdf.geometry],
    })
