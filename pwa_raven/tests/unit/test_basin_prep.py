"""Unit tests for pwa_raven.raven.basin_prep."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from pwa_raven.raven.basin_prep import (
    DEFAULT_CHANNEL_N,
    DEFAULT_FLOODPLAIN_N,
    MIN_BKF_DEPTH,
    MIN_RIV_SLOPE,
    MIN_RIV_SLOPE_REPLACEMENT,
    compute_time_of_concentration,
    filter_contributing_basins,
    find_watershed_outlet,
    prepare_basin_attributes,
    sanitize_bankfull_depths,
    sanitize_channel_manning_n,
    sanitize_floodplain_manning_n,
    sanitize_river_lengths,
    sanitize_river_slopes,
)


# ---------------------------------------------------------------------------
# Sentinel-value sanitizers (pure list functions, easy to test exhaustively)
# ---------------------------------------------------------------------------

def test_sanitize_river_lengths_replaces_neg_sentinel_with_string():
    """River lengths of -1m round to -0.001 km → 'ZERO-' marker for RVH."""
    # -1 m = -0.001 km exactly
    raw, num = sanitize_river_lengths([-1.0, 1500.0, 0.0])
    assert raw == ["ZERO-", 1.5, 0.0]
    # numeric variant doesn't catch this sentinel
    assert num == [-0.001, 1.5, 0.0]


def test_sanitize_river_lengths_numeric_sentinel():
    """Numeric variant catches -0.0012345 km exactly → 0.0."""
    raw, num = sanitize_river_lengths([-1.2345])  # -1.2345 m = -0.0012345 km
    assert num == [0.0]
    # raw variant rounded to 3 dp = -0.001, which IS the string sentinel
    assert raw == ["ZERO-"]


def test_sanitize_river_lengths_passes_through_normal_values():
    raw, num = sanitize_river_lengths([2500.0, 10000.0])
    assert raw == [2.5, 10.0]
    assert num == [2.5, 10.0]


def test_sanitize_river_slopes_replaces_below_threshold():
    out = sanitize_river_slopes([0.00005, MIN_RIV_SLOPE, 0.001, 0.05])
    assert out == [MIN_RIV_SLOPE_REPLACEMENT, MIN_RIV_SLOPE_REPLACEMENT, 0.001, 0.05]


def test_sanitize_bankfull_depths_clamps_below_one():
    out = sanitize_bankfull_depths([0.5, MIN_BKF_DEPTH, 1.5])
    assert out == [MIN_BKF_DEPTH, MIN_BKF_DEPTH, 1.5]


def test_sanitize_floodplain_manning_n_replaces_negative():
    out = sanitize_floodplain_manning_n([-1.0, 0.0, 0.05, 0.1])
    assert out == [DEFAULT_FLOODPLAIN_N, 0.0, 0.05, 0.1]


def test_sanitize_channel_manning_n_replaces_negative():
    out = sanitize_channel_manning_n([-0.01, 0.0, 0.025, 0.04])
    assert out == [DEFAULT_CHANNEL_N, 0.0, 0.025, 0.04]


# ---------------------------------------------------------------------------
# Time of concentration (NRCS TR-55 lag formula)
# ---------------------------------------------------------------------------

def _box(sub_id: int) -> Polygon:
    return Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])


@pytest.fixture
def basin_gdf() -> gpd.GeoDataFrame:
    """Two basins with different areas/slopes for TC computation."""
    return gpd.GeoDataFrame({
        "SubId": [1, 2],
        "Lake_Cat": [0, 1],
        "BasArea": [1_000_000.0, 4_000_000.0],   # 1 km², 4 km²
        "BasSlope": [2.0, 5.0],                   # degrees
        "RivLength": [1500.0, 3000.0],
        "RivSlope": [0.005, 0.01],
        "BkfDepth": [0.5, 2.0],
        "FloodP_n": [-1.0, 0.06],
        "Ch_n": [0.025, -1.0],
        "Has_POI": [0, 1],
        "DowSubId": [2, -1],
        "DrainArea": [1_000_000.0, 5_000_000.0],
        "geometry": [_box(1), _box(2)],
    }, crs="EPSG:4326")


def test_compute_time_of_concentration_adds_expected_columns(basin_gdf):
    result = compute_time_of_concentration(basin_gdf, curve_number=63)
    for col in ["BasinsArea_acres", "BasSlope_prcnt", "FlowLength_ft",
                "max_retention", "time_of_conc", "time_to_peak"]:
        assert col in result.columns


def test_compute_time_of_concentration_basic_invariants(basin_gdf):
    """Larger basins → longer flow length; steeper slopes → shorter TC."""
    result = compute_time_of_concentration(basin_gdf, curve_number=63)
    # Basin 2 (4x area) has longer flow length
    assert result.loc[1, "FlowLength_ft"] > result.loc[0, "FlowLength_ft"]
    # time_to_peak == 0.6 * time_of_conc (relation, not magic number)
    assert result["time_to_peak"].tolist() == pytest.approx(
        (result["time_of_conc"] * 0.6).tolist()
    )


def test_compute_time_of_concentration_does_not_mutate_input(basin_gdf):
    before = basin_gdf.copy()
    _ = compute_time_of_concentration(basin_gdf, curve_number=63)
    assert "time_of_conc" not in basin_gdf.columns
    assert basin_gdf.equals(before)


def test_compute_time_of_concentration_curve_number_affects_retention(basin_gdf):
    """Higher CN (less infiltration) → smaller max_retention → faster TC."""
    low_cn = compute_time_of_concentration(basin_gdf, curve_number=50)
    high_cn = compute_time_of_concentration(basin_gdf, curve_number=90)
    assert (low_cn["max_retention"] > high_cn["max_retention"]).all()
    assert (low_cn["time_of_conc"] > high_cn["time_of_conc"]).all()


# ---------------------------------------------------------------------------
# Lake-cat filtering
# ---------------------------------------------------------------------------

def test_filter_contributing_basins(basin_gdf):
    """Lake_Cat ≥ 2 is dropped."""
    extended = basin_gdf.copy()
    extended.loc[len(extended)] = {
        "SubId": 3, "Lake_Cat": 2, "BasArea": 1.0, "BasSlope": 1.0,
        "RivLength": 1.0, "RivSlope": 1.0, "BkfDepth": 1.0,
        "FloodP_n": 0.05, "Ch_n": 0.025, "Has_POI": 0, "DowSubId": 1,
        "DrainArea": 1.0, "geometry": _box(3),
    }
    out = filter_contributing_basins(extended)
    assert set(out["SubId"]) == {1, 2}


# ---------------------------------------------------------------------------
# Outlet identification
# ---------------------------------------------------------------------------

def test_find_outlet_single_gauged(basin_gdf):
    outlet = find_watershed_outlet(basin_gdf)
    assert outlet.sub_id == 2
    assert outlet.drainage_area_km2 == pytest.approx(5.0)


def test_find_outlet_multiple_gauged_picks_terminal():
    """Two POIs in series — pick the one not draining into another POI basin."""
    gdf = gpd.GeoDataFrame({
        "SubId": [1, 2, 3],
        "Has_POI": [1, 1, 0],
        "DowSubId": [2, -1, 2],         # 1 drains to 2, 2 is terminal
        "DrainArea": [1e6, 5e6, 2e6],
        "Lake_Cat": [0, 0, 0],
        "geometry": [_box(1), _box(2), _box(3)],
    }, crs="EPSG:4326")

    outlet = find_watershed_outlet(gdf)
    assert outlet.sub_id == 2


def test_find_outlet_raises_when_no_gauge():
    gdf = gpd.GeoDataFrame({
        "SubId": [1], "Has_POI": [0], "DowSubId": [-1],
        "DrainArea": [1e6], "Lake_Cat": [0], "geometry": [_box(1)],
    }, crs="EPSG:4326")

    with pytest.raises(ValueError, match="No gauged outlet"):
        find_watershed_outlet(gdf)


def test_find_outlet_raises_when_ambiguous_terminal():
    """Two terminal gauged basins (parallel) → ambiguous."""
    gdf = gpd.GeoDataFrame({
        "SubId": [1, 2],
        "Has_POI": [1, 1],
        "DowSubId": [-1, -2],     # both terminal
        "DrainArea": [1e6, 1e6],
        "Lake_Cat": [0, 0],
        "geometry": [_box(1), _box(2)],
    }, crs="EPSG:4326")

    with pytest.raises(ValueError, match="exactly one terminal"):
        find_watershed_outlet(gdf)


# ---------------------------------------------------------------------------
# End-to-end orchestrator
# ---------------------------------------------------------------------------

def test_prepare_basin_attributes_end_to_end(basin_gdf):
    result = prepare_basin_attributes(basin_gdf, curve_number=63)

    assert result.outlet.sub_id == 2
    assert result.outlet.drainage_area_km2 == pytest.approx(5.0)
    assert result.sub_ids == [1, 2]
    assert result.basin_area_km2 == pytest.approx([1.0, 4.0])
    # Sanitization applied
    assert result.bkf_depths == [MIN_BKF_DEPTH, 2.0]            # 0.5 → 1.0
    assert result.floodplain_n == [DEFAULT_FLOODPLAIN_N, 0.06]  # -1.0 → 0.05
    assert result.channel_n == [0.025, DEFAULT_CHANNEL_N]       # -1.0 → 0.025
    # Enriched columns are on the returned GDF
    assert "time_of_conc" in result.gdf.columns


# ---------------------------------------------------------------------------
# Aspect ratio (minimum-area bounding rectangle)
# ---------------------------------------------------------------------------


def test_aspect_ratio_square_is_one():
    """A square's MABR aspect ratio is 1.0."""
    from shapely.geometry import Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratio_bbox

    sq = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert compute_aspect_ratio_bbox(sq) == pytest.approx(1.0)


def test_aspect_ratio_rotated_square_still_one():
    """Rotating a square shouldn't change its aspect ratio (the MABR
    rotates with it — that's the whole point of the algorithm)."""
    from shapely.affinity import rotate
    from shapely.geometry import Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratio_bbox

    sq = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    rotated = rotate(sq, angle=37, use_radians=False)
    assert compute_aspect_ratio_bbox(rotated) == pytest.approx(1.0, abs=1e-9)


def test_aspect_ratio_axis_aligned_rectangle():
    """A 4×1 axis-aligned rectangle has aspect ratio 4."""
    from shapely.geometry import Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratio_bbox

    rect = Polygon([(0, 0), (4, 0), (4, 1), (0, 1)])
    assert compute_aspect_ratio_bbox(rect) == pytest.approx(4.0)


def test_aspect_ratio_rotated_rectangle():
    """The MABR algorithm finds the same 4:1 ratio under rotation —
    the axis-aligned bounding box would mistakenly report higher."""
    from shapely.affinity import rotate
    from shapely.geometry import Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratio_bbox

    rect = Polygon([(0, 0), (4, 0), (4, 1), (0, 1)])
    rotated = rotate(rect, angle=30, use_radians=False)
    assert compute_aspect_ratio_bbox(rotated) == pytest.approx(4.0, abs=1e-9)


def test_aspect_ratio_returns_none_for_non_polygon():
    """Points and lines aren't polygons; return None rather than crash."""
    from shapely.geometry import Point
    from pwa_raven.raven.basin_prep import compute_aspect_ratio_bbox

    assert compute_aspect_ratio_bbox(Point(0, 0)) is None


def test_aspect_ratio_multipolygon_picks_largest_component():
    """When given a MultiPolygon, use the largest member polygon —
    matches the legacy notebook behaviour."""
    from shapely.geometry import MultiPolygon, Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratio_bbox

    small_square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    big_rectangle = Polygon([(10, 10), (16, 10), (16, 12), (10, 12)])  # 6×2 ratio = 3
    mp = MultiPolygon([small_square, big_rectangle])
    assert compute_aspect_ratio_bbox(mp) == pytest.approx(3.0)


def test_compute_aspect_ratios_dataframe_schema():
    """The convenience wrapper returns a 2-column DataFrame matching
    aspect_ratios.csv's schema."""
    import geopandas as gpd
    from shapely.geometry import Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratios

    gdf = gpd.GeoDataFrame({
        "SubId": [101, 102, 103],
        "geometry": [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),                # square → 1.0
            Polygon([(0, 0), (2, 0), (2, 1), (0, 1)]),                # 2:1 → 2.0
            Polygon([(0, 0), (4, 0), (4, 1), (0, 1)]),                # 4:1 → 4.0
        ],
    }, crs="EPSG:4326")

    out = compute_aspect_ratios(gdf)
    assert list(out.columns) == ["SubId", "Aspect_Ratio"]
    assert out["SubId"].tolist() == [101, 102, 103]
    assert out["Aspect_Ratio"].tolist() == pytest.approx([1.0, 2.0, 4.0])


def test_compute_aspect_ratios_raises_on_missing_subid_column():
    import geopandas as gpd
    from shapely.geometry import Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratios

    gdf = gpd.GeoDataFrame(
        {"geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]},
        crs="EPSG:4326",
    )
    with pytest.raises(KeyError, match="SubId"):
        compute_aspect_ratios(gdf)


def test_compute_aspect_ratios_preserves_nan_for_unparseable_geom():
    """Geometries that the bbox computation can't handle (e.g., points)
    show up as NaN rather than raising — the caller decides what to do."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point, Polygon
    from pwa_raven.raven.basin_prep import compute_aspect_ratios

    gdf = gpd.GeoDataFrame({
        "SubId": [1, 2],
        "geometry": [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Point(5, 5),
        ],
    }, crs="EPSG:4326")
    out = compute_aspect_ratios(gdf)
    assert out["Aspect_Ratio"].iloc[0] == pytest.approx(1.0)
    assert pd.isna(out["Aspect_Ratio"].iloc[1])
