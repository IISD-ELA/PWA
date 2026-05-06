"""Unit tests for pwa_raven.grid.weights."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pwa_raven.grid.weights import (
    compute_subbasin_to_grid_mapping,
    write_grid_weights_file,
)


# ---------------------------------------------------------------------------
# Fixtures: a 2x2 PHyDAP grid (HYBAS_IDs 1001..1004) covering [0,2] x [0,2],
# and three sub-basins at known interior points.
# ---------------------------------------------------------------------------

@pytest.fixture
def phydap_2x2() -> gpd.GeoDataFrame:
    cells = []
    hybas_ids = []
    for ix, x0 in enumerate([0, 1]):
        for iy, y0 in enumerate([0, 1]):
            cells.append(Polygon([(x0, y0), (x0 + 1, y0), (x0 + 1, y0 + 1), (x0, y0 + 1)]))
            hybas_ids.append(1001 + ix * 2 + iy)
    return gpd.GeoDataFrame({"HYBAS_ID": hybas_ids}, geometry=cells, crs="EPSG:4326")


@pytest.fixture
def hybas_map_full() -> pd.DataFrame:
    return pd.DataFrame({
        "hybas_id": [1001, 1002, 1003, 1004],
        "grid_idx": [0, 1, 2, 3],
    })


def _subbasin_at(point_xy: tuple[float, float], sub_id: int) -> dict:
    x, y = point_xy
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
