"""Unit tests for pwa_raven.grid.weights."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pwa_raven.grid.weights import (
    compute_subbasin_to_grid_mapping,
    generate_grid_weights,
    write_grid_weights_file,
)


# ---------------------------------------------------------------------------
# Fixtures: a 2x2 PHyDAP grid (HYBAS_IDs 1001..1004) covering a small area
# in southern Manitoba, and three sub-basins at known interior points.
#
# Coordinates sit in EPSG:3158's valid zone (NAD83 / UTM 14N, central
# meridian -99°W) so the production code's reproject-to-3158 step
# transforms cleanly. Polygons defined at nominal small coordinates
# (e.g. (0, 0)-(1, 1)) get translated by (-98, 50) — _MB_LON / _MB_LAT —
# before being handed to the function.
# ---------------------------------------------------------------------------

_MB_LON = -98.0
_MB_LAT = 50.0


def _mb(x: float, y: float) -> tuple[float, float]:
    """Translate a 'nominal' coordinate into Manitoba (EPSG:3158-valid) lat/lon."""
    return (x + _MB_LON, y + _MB_LAT)


@pytest.fixture
def phydap_2x2() -> gpd.GeoDataFrame:
    cells = []
    hybas_ids = []
    for ix, x0 in enumerate([0, 1]):
        for iy, y0 in enumerate([0, 1]):
            cells.append(
                Polygon([
                    _mb(x0, y0),
                    _mb(x0 + 1, y0),
                    _mb(x0 + 1, y0 + 1),
                    _mb(x0, y0 + 1),
                ])
            )
            hybas_ids.append(1001 + ix * 2 + iy)
    return gpd.GeoDataFrame({"HYBAS_ID": hybas_ids}, geometry=cells, crs="EPSG:4326")


@pytest.fixture
def hybas_map_full() -> pd.DataFrame:
    return pd.DataFrame({
        "hybas_id": [1001, 1002, 1003, 1004],
        "grid_idx": [0, 1, 2, 3],
    })


def _subbasin_at(point_xy: tuple[float, float], sub_id: int) -> dict:
    """0.1° square polygon centred at ``_mb(*point_xy)``."""
    x, y = _mb(*point_xy)
    poly = Polygon([(x - 0.05, y - 0.05), (x + 0.05, y - 0.05),
                    (x + 0.05, y + 0.05), (x - 0.05, y + 0.05)])
    return {"SubId": sub_id, "geometry": poly}


# ---------------------------------------------------------------------------
# Happy path: every sub-basin lies inside a grid cell
# ---------------------------------------------------------------------------

def test_mapping_all_inside(phydap_2x2, hybas_map_full):
    """Three sub-basins, each centered in a different PHyDAP cell."""
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((0.5, 0.5), 1),    # in HYBAS 1001
         _subbasin_at((1.5, 0.5), 2),    # in HYBAS 1003
         _subbasin_at((1.5, 1.5), 3)],   # in HYBAS 1004
        crs="EPSG:4326",
    )

    result = compute_subbasin_to_grid_mapping(subbasins, phydap_2x2, hybas_map_full)

    assert list(result.columns) == ["SubId", "HYBAS_ID", "grid_idx"]
    assert len(result) == 3
    by_sub = result.set_index("SubId")
    assert by_sub.loc[1, "HYBAS_ID"] == 1001
    assert by_sub.loc[2, "HYBAS_ID"] == 1003
    assert by_sub.loc[3, "HYBAS_ID"] == 1004
    # grid_idx populated from hybas_map regardless of whether any
    # centroids fall outside PHyDAP — the notebook only set this column
    # inside the missing-centroid branch.
    assert by_sub.loc[1, "grid_idx"] == 0
    assert by_sub.loc[2, "grid_idx"] == 2
    assert by_sub.loc[3, "grid_idx"] == 3


def test_mapping_all_inside_no_kerror_in_writer(phydap_2x2, hybas_map_full, tmp_path):
    """When every subbasin centroid falls inside PHyDAP coverage, the
    writer must still find a grid_idx column. The original notebook only
    merged hybas_map inside the ``if missing > 0`` branch, so the
    happy path produced a frame missing grid_idx and the file writer
    raised KeyError downstream."""
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((0.5, 0.5), 1)],
        crs="EPSG:4326",
    )

    mapping = compute_subbasin_to_grid_mapping(subbasins, phydap_2x2, hybas_map_full)

    out = tmp_path / "GridWeights.txt"
    written = write_grid_weights_file(mapping, n_grid_cells=4, watershed_name="test", output_path=out)

    assert written.exists()
    content = written.read_text()
    assert ":NumberHRUs       1" in content
    assert ":NumberGridCells  4" in content
    assert ":EndGridWeights" in content


# ---------------------------------------------------------------------------
# CRS reprojection
# ---------------------------------------------------------------------------

def test_mapping_reprojects_subbasins_to_phydap_crs(phydap_2x2, hybas_map_full):
    """Sub-basins in EPSG:3857 should be reprojected to PHyDAP's EPSG:4326."""
    subbasins_4326 = gpd.GeoDataFrame(
        [_subbasin_at((0.5, 0.5), 1)],
        crs="EPSG:4326",
    )
    subbasins_3857 = subbasins_4326.to_crs("EPSG:3857")

    result = compute_subbasin_to_grid_mapping(subbasins_3857, phydap_2x2, hybas_map_full)
    assert result.iloc[0]["HYBAS_ID"] == 1001


# ---------------------------------------------------------------------------
# Nearest-neighbor fallback for centroids outside PHyDAP coverage
# ---------------------------------------------------------------------------

def test_mapping_nearest_for_outside_centroid(phydap_2x2, hybas_map_full):
    """A sub-basin centered well outside PHyDAP should map to the nearest cell."""
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((-1.0, 0.5), 99)],  # west of PHyDAP, nearest is HYBAS 1001
        crs="EPSG:4326",
    )

    result = compute_subbasin_to_grid_mapping(subbasins, phydap_2x2, hybas_map_full)

    assert len(result) == 1
    assert result.iloc[0]["SubId"] == 99
    assert result.iloc[0]["HYBAS_ID"] == 1001
    assert result.iloc[0]["grid_idx"] == 0


def test_mapping_appends_grid_idx_for_nearest_match_not_in_hybas_map(phydap_2x2):
    """If the nearest HYBAS isn't in hybas_map, a synthetic grid_idx is appended."""
    sparse_hybas = pd.DataFrame({
        "hybas_id": [1001, 1004],
        "grid_idx": [0, 1],
    })
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((1.5, 0.5), 7)],  # inside HYBAS 1003 (not in sparse map)
        crs="EPSG:4326",
    )

    result = compute_subbasin_to_grid_mapping(subbasins, phydap_2x2, sparse_hybas)

    assert result.iloc[0]["HYBAS_ID"] == 1003
    assert result.iloc[0]["grid_idx"] == 2  # next after max(0, 1) = 1


# ---------------------------------------------------------------------------
# write_grid_weights_file format
# ---------------------------------------------------------------------------

def test_write_grid_weights_file_format(tmp_path):
    mapping = pd.DataFrame({
        "SubId": [101, 102],
        "HYBAS_ID": [1001, 1002],
        "grid_idx": [0, 1],
    })
    out = tmp_path / "GridWeights.txt"

    write_grid_weights_file(mapping, n_grid_cells=4, watershed_name="grassmere", output_path=out)

    content = out.read_text()
    lines = content.splitlines()

    assert lines[0].startswith("# ---")
    assert "# grassmere" in content
    assert ":GridWeights" in content
    assert "   :NumberHRUs       2" in content
    assert "   :NumberGridCells  4" in content
    assert lines[-1] == ":EndGridWeights"

    # Each HRU row: "  {SubId:>10} {grid_idx:>10}{1.0:>10.3f}"
    hru_rows = [ln for ln in lines if ln.lstrip().startswith(("101", "102"))]
    assert len(hru_rows) == 2
    assert hru_rows[0].endswith("     1.000")


def test_write_grid_weights_file_returns_path(tmp_path):
    mapping = pd.DataFrame({"SubId": [1], "grid_idx": [0]})
    out = tmp_path / "GridWeights.txt"

    returned = write_grid_weights_file(mapping, n_grid_cells=1, watershed_name="x", output_path=out)
    assert returned == out


# ---------------------------------------------------------------------------
# generate_grid_weights — :NumberGridCells must be the subset cell count
# ---------------------------------------------------------------------------

def test_generate_grid_weights_uses_subset_count_not_full_grid(tmp_path):
    """:NumberGridCells must equal the subset cell count (len(hybas_map)),
    NOT len(phydap). The forcing NetCDF Raven reads is the subset, so a
    full-grid count makes Raven abort with ':NumberGridCells given does
    not agree with NetCDF file content'."""
    # Full PHyDAP grid: 2x2 = 4 cells, translated to Manitoba so the
    # reproject-to-EPSG:3158 step inside the production code is valid.
    phydap = gpd.GeoDataFrame(
        {"HYBAS_ID": [1001, 1002, 1003, 1004]},
        geometry=[
            Polygon([_mb(0, 0), _mb(1, 0), _mb(1, 1), _mb(0, 1)]),  # 1001
            Polygon([_mb(0, 1), _mb(1, 1), _mb(1, 2), _mb(0, 2)]),  # 1002
            Polygon([_mb(1, 0), _mb(2, 0), _mb(2, 1), _mb(1, 1)]),  # 1003
            Polygon([_mb(1, 1), _mb(2, 1), _mb(2, 2), _mb(1, 2)]),  # 1004
        ],
        crs="EPSG:4326",
    )
    phydap_path = tmp_path / "phydap.shp"
    phydap.to_file(phydap_path)

    # hybas_map: the SUBSET — only 2 of the 4 cells.
    hybas_map_path = tmp_path / "hybas_map.csv"
    pd.DataFrame({"hybas_id": [1001, 1003], "grid_idx": [0, 1]}).to_csv(
        hybas_map_path, index=False
    )

    # Sub-basins, one in HYBAS 1001 and one in HYBAS 1003.
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((0.5, 0.5), 1), _subbasin_at((1.5, 0.5), 2)],
        crs="EPSG:4326",
    )
    subbasins_path = tmp_path / "subbasins.shp"
    subbasins.to_file(subbasins_path)

    out = generate_grid_weights(
        subbasins_shp=subbasins_path,
        phydap_shp=phydap_path,
        hybas_map_csv=hybas_map_path,
        watershed_name="test",
        output_path=tmp_path / "GridWeights.txt",
    )
    content = out.read_text()
    assert ":NumberGridCells  2" in content      # len(hybas_map) — the subset
    assert ":NumberGridCells  4" not in content  # NOT len(phydap) — the full grid


# ---------------------------------------------------------------------------
# generate_grid_weights — Lake_Cat >= 2 catchments must be excluded
# ---------------------------------------------------------------------------

def _subbasin_with_lake_cat(
    point_xy: tuple[float, float], sub_id: int, lake_cat: int,
) -> dict:
    base = _subbasin_at(point_xy, sub_id)
    base["Lake_Cat"] = lake_cat
    return base


def test_generate_grid_weights_excludes_lake_catchments(tmp_path):
    """Non-contributing lake catchments (Lake_Cat >= 2) don't route
    water in Raven; including them in GridWeights.txt forces Raven to
    read forcing for cells Step 2 later drops, causing forcing/coverage
    mismatches. Ports master commit af102c0 ("Removed lake catchments
    from gridweights file")."""
    phydap = gpd.GeoDataFrame(
        {"HYBAS_ID": [1001, 1003]},
        geometry=[
            Polygon([_mb(0, 0), _mb(1, 0), _mb(1, 1), _mb(0, 1)]),  # 1001
            Polygon([_mb(1, 0), _mb(2, 0), _mb(2, 1), _mb(1, 1)]),  # 1003
        ],
        crs="EPSG:4326",
    )
    phydap_path = tmp_path / "phydap.shp"
    phydap.to_file(phydap_path)

    hybas_map_path = tmp_path / "hybas_map.csv"
    pd.DataFrame({"hybas_id": [1001, 1003], "grid_idx": [0, 1]}).to_csv(
        hybas_map_path, index=False
    )

    # Three subbasins: SubId 1 contributes (Lake_Cat=0), 2 contributes
    # (Lake_Cat=1, which means a *contributing* lake reach), 3 is a
    # non-contributing lake catchment (Lake_Cat=2 — must be filtered).
    subbasins = gpd.GeoDataFrame(
        [
            _subbasin_with_lake_cat((0.5, 0.5), 1, lake_cat=0),
            _subbasin_with_lake_cat((1.2, 0.5), 2, lake_cat=1),
            _subbasin_with_lake_cat((1.7, 0.5), 3, lake_cat=2),
        ],
        crs="EPSG:4326",
    )
    subbasins_path = tmp_path / "subbasins.shp"
    subbasins.to_file(subbasins_path)

    out = generate_grid_weights(
        subbasins_shp=subbasins_path,
        phydap_shp=phydap_path,
        hybas_map_csv=hybas_map_path,
        watershed_name="lake_test",
        output_path=tmp_path / "GridWeights.txt",
    )
    content = out.read_text()
    # Data lines have the form: "<HRU_ID>  <cell>  <weight>" (right-aligned).
    # Parse out the leading integer per data row and assert which SubIds
    # appear. SubId 3 (Lake_Cat=2) must be filtered.
    hru_ids = []
    in_data = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(":GridWeights"):
            in_data = True
            continue
        if stripped.startswith(":EndGridWeights"):
            break
        if not in_data or not stripped or stripped.startswith(("#", ":")):
            continue
        hru_ids.append(int(stripped.split()[0]))

    assert 3 not in hru_ids, "Lake_Cat=2 subbasin leaked into GridWeights"
    assert sorted(hru_ids) == [1, 2]


def test_generate_grid_weights_no_op_when_lake_cat_column_missing(tmp_path):
    """Watersheds whose subbasin layer doesn't carry a Lake_Cat column
    must still run. The filter is a no-op when the column is absent."""
    phydap = gpd.GeoDataFrame(
        {"HYBAS_ID": [1001]},
        geometry=[Polygon([_mb(0, 0), _mb(1, 0), _mb(1, 1), _mb(0, 1)])],
        crs="EPSG:4326",
    )
    phydap_path = tmp_path / "phydap.shp"
    phydap.to_file(phydap_path)

    hybas_map_path = tmp_path / "hybas_map.csv"
    pd.DataFrame({"hybas_id": [1001], "grid_idx": [0]}).to_csv(
        hybas_map_path, index=False
    )
    # _subbasin_at returns dicts WITHOUT a Lake_Cat column.
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((0.5, 0.5), 1)], crs="EPSG:4326",
    )
    subbasins_path = tmp_path / "subbasins.shp"
    subbasins.to_file(subbasins_path)

    out = generate_grid_weights(
        subbasins_shp=subbasins_path,
        phydap_shp=phydap_path,
        hybas_map_csv=hybas_map_path,
        watershed_name="no_lake_col",
        output_path=tmp_path / "GridWeights.txt",
    )
    assert out.is_file()
    # The one subbasin should appear as a data row (right-aligned format).
    data_rows = [
        ln for ln in out.read_text().splitlines()
        if ln.strip() and ln.strip()[0].isdigit()
    ]
    assert len(data_rows) == 1
    assert data_rows[0].split()[0] == "1"


# ---------------------------------------------------------------------------
# R1 — reprojection to EPSG:3158 (metres) before nearest-distance math
# ---------------------------------------------------------------------------

def test_nearest_distance_picks_correct_cell_at_high_latitude(tmp_path):
    """Reprojection regression (R1 in regression review): the legacy
    notebook explicitly reprojected both layers to EPSG:3158 (metres)
    before nearest-neighbour distance math, but the new code only
    aligned subbasins to phydap.crs. If phydap is EPSG:4326 (degrees,
    the WGS84 layer the engagement ships against), Euclidean distance
    at 50°N is anisotropic — a degree of longitude (~71 km) is much
    shorter than a degree of latitude (~111 km) — so idxmin() picks
    a different cell than a metre-based calc would.

    Fixture is a sub-basin centroid in the gap between two PHyDAP
    cells with deliberately-different lon vs lat distances. Under
    degree math the wrong cell wins; under metre math (post EPSG:3158
    reprojection) the right cell wins."""
    # PHyDAP cells placed in Manitoba (so the EPSG:3158 reprojection
    # inside the production code is valid). Cell A: 1 degree longitude
    # west of the test sub-basin (~71 km in metres at 50°N).  Cell B:
    # 0.95 degrees latitude north (~105 km in metres).  Cell A is
    # geometrically closer in metres, but in lat/lon degrees Cell B
    # looks closer (0.95 < 1.0). With the legacy reproject-to-3158
    # step the metre-based math picks Cell A; without it the test
    # would pick Cell B.
    base_lon, base_lat = _MB_LON, _MB_LAT   # -98, 50
    phydap = gpd.GeoDataFrame(
        {"HYBAS_ID": [10, 20]},
        geometry=[
            Polygon([                                            # A: 1° west
                (base_lon - 1.05, base_lat - 0.05),
                (base_lon - 0.95, base_lat - 0.05),
                (base_lon - 0.95, base_lat + 0.05),
                (base_lon - 1.05, base_lat + 0.05),
            ]),
            Polygon([                                            # B: ~0.95° north
                (base_lon - 0.05, base_lat + 0.90),
                (base_lon + 0.05, base_lat + 0.90),
                (base_lon + 0.05, base_lat + 1.00),
                (base_lon - 0.05, base_lat + 1.00),
            ]),
        ],
        crs="EPSG:4326",
    )
    phydap_path = tmp_path / "phydap.shp"
    phydap.to_file(phydap_path)

    hybas_map_path = tmp_path / "hybas_map.csv"
    pd.DataFrame({"hybas_id": [10, 20], "grid_idx": [0, 1]}).to_csv(
        hybas_map_path, index=False
    )

    # Sub-basin centroid at the origin (base_lat°N, base_lon°E),
    # outside both cells, so the nearest-distance branch fires.
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((0.0, 0.0), 1)], crs="EPSG:4326",  # _subbasin_at adds _MB_LON/_MB_LAT
    )
    subbasins_path = tmp_path / "subbasins.shp"
    subbasins.to_file(subbasins_path)

    out = generate_grid_weights(
        subbasins_shp=subbasins_path,
        phydap_shp=phydap_path,
        hybas_map_csv=hybas_map_path,
        watershed_name="anisotropy",
        output_path=tmp_path / "GridWeights.txt",
    )
    content = out.read_text()
    # Cell A (HYBAS 10, grid_idx 0) is closer in metres; correct pick.
    # If reprojection is broken, the test would see grid_idx 1.
    data_lines = [
        ln for ln in content.splitlines()
        if ln.strip() and ln.strip()[0].isdigit()
    ]
    assert len(data_lines) == 1
    cell_idx = int(data_lines[0].split()[1])
    assert cell_idx == 0, (
        "Nearest-cell picked under (probably) degree-distance: got "
        f"grid_idx={cell_idx}, expected 0. Reprojection to a metric "
        "CRS before idxmin() is the fix."
    )


# ---------------------------------------------------------------------------
# R4 — nearest pool must be filtered to the subset NetCDF
# ---------------------------------------------------------------------------

def test_nearest_pool_excludes_phydap_basins_outside_netcdf_subset(tmp_path):
    """The legacy notebook restricted the nearest-neighbour pool to
    PHyDAP cells present in the subset NetCDF (hybas_map), so a
    nearest pick could never land on a cell Raven's forcing file
    doesn't have. The new _assign_nearest_phydap receives the full
    PHyDAP layer, can pick a HYBAS_ID outside the subset, and then
    invents synthetic grid_idx values past n_grid_cells — Raven
    reads out-of-range. This test pins the legacy guarantee."""
    # Three PHyDAP cells: two are in the subset NetCDF, ONE is not.
    # The non-subset cell (HYBAS 999) is placed closest to the
    # sub-basin centroid, so without filtering it would win idxmin().
    phydap = gpd.GeoDataFrame(
        {"HYBAS_ID": [10, 20, 999]},
        geometry=[
            Polygon([_mb(0, 0), _mb(1, 0), _mb(1, 1), _mb(0, 1)]),               # in subset, far
            Polygon([_mb(5, 5), _mb(6, 5), _mb(6, 6), _mb(5, 6)]),               # in subset, far
            Polygon([_mb(1.5, 1.5), _mb(1.6, 1.5), _mb(1.6, 1.6), _mb(1.5, 1.6)]),  # NOT in subset, near
        ],
        crs="EPSG:4326",
    )
    phydap_path = tmp_path / "phydap.shp"
    phydap.to_file(phydap_path)

    # hybas_map: subset of PHyDAP — HYBAS 10 and 20 only, NOT 999.
    hybas_map_path = tmp_path / "hybas_map.csv"
    pd.DataFrame({"hybas_id": [10, 20], "grid_idx": [0, 1]}).to_csv(
        hybas_map_path, index=False
    )

    # Sub-basin centroid at (2, 2) — outside all cells, with HYBAS 999
    # geometrically closest. Filtering MUST happen so 999 is excluded.
    subbasins = gpd.GeoDataFrame(
        [_subbasin_at((2.0, 2.0), 1)], crs="EPSG:4326",
    )
    subbasins_path = tmp_path / "subbasins.shp"
    subbasins.to_file(subbasins_path)

    out = generate_grid_weights(
        subbasins_shp=subbasins_path,
        phydap_shp=phydap_path,
        hybas_map_csv=hybas_map_path,
        watershed_name="subset_filter",
        output_path=tmp_path / "GridWeights.txt",
    )
    content = out.read_text()
    # NumberGridCells must equal hybas_map length (2). The data line's
    # grid_idx must reference a cell in [0, 2) — never the synthetic
    # value the unfiltered pool would create.
    assert ":NumberGridCells  2" in content
    data_lines = [
        ln for ln in content.splitlines()
        if ln.strip() and ln.strip()[0].isdigit()
    ]
    assert len(data_lines) == 1
    cell_idx = int(data_lines[0].split()[1])
    assert 0 <= cell_idx < 2, (
        "Nearest pick landed on a HYBAS_ID not in the subset NetCDF; "
        f"got grid_idx={cell_idx}, expected in [0, 2). Restoring the "
        "valid_phydap = phydap[HYBAS_ID.isin(hybas_map.hybas_id)] "
        "filter in _assign_nearest_phydap fixes this."
    )
