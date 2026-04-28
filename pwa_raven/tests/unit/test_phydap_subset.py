"""Unit tests for pwa_raven.io.phydap_subset."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from netCDF4 import Dataset
from shapely.geometry import Polygon

from pwa_raven.io.phydap_subset import (
    build_hybas_grid_map,
    find_basin_indices,
    find_target_hybas_ids,
    subset_phydap_for_watershed,
    subset_phydap_nc,
)


# ---------------------------------------------------------------------------
# Synthetic PHyDAP NetCDF: 5 basins × 24 timesteps
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_phydap_nc(tmp_path: Path) -> Path:
    """Build a tiny PHyDAP-shaped NetCDF for testing."""
    path = tmp_path / "phydap_synth.nc"
    nt, nh = 24, 5
    hybas_ids = np.array([1001, 1002, 1003, 1004, 1005], dtype=np.int64)

    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time_hrs", nt)
        ds.createDimension("HYBAS_ID", nh)

        time_var = ds.createVariable("time_hrs", "f8", ("time_hrs",))
        time_var.units = "hours since 1900-01-01 00:00:00"
        time_var[:] = np.arange(nt, dtype=np.float64) * 1000.0

        hybas_var = ds.createVariable("HYBAS_ID", "i8", ("HYBAS_ID",))
        hybas_var[:] = hybas_ids

        runoff = ds.createVariable("cropped_runoff", "f4", ("time_hrs", "HYBAS_ID"))
        # Distinctive values: runoff[t, h] = t*100 + h
        data = np.arange(nt, dtype=np.float32)[:, None] * 100 + np.arange(nh, dtype=np.float32)
        runoff[:, :] = data

    return path


@pytest.fixture
def phydap_polygons() -> gpd.GeoDataFrame:
    """5 PHyDAP polygons covering [0,5]x[0,1], one per HYBAS."""
    polys = [
        Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)])
        for i in range(5)
    ]
    return gpd.GeoDataFrame(
        {"HYBAS_ID": [1001, 1002, 1003, 1004, 1005]},
        geometry=polys,
        crs="EPSG:4326",
    )


# ---------------------------------------------------------------------------
# find_target_hybas_ids
# ---------------------------------------------------------------------------

def test_find_target_hybas_ids_intersects(phydap_polygons):
    """Sub-basin overlapping cells 1002 and 1003 returns those HYBAS_IDs."""
    subbasin = gpd.GeoDataFrame(
        [{"SubId": 7, "geometry": Polygon([(1.5, 0.2), (2.5, 0.2), (2.5, 0.8), (1.5, 0.8)])}],
        crs="EPSG:4326",
    )

    result = find_target_hybas_ids(phydap_polygons, subbasin)
    assert sorted(result) == [1002, 1003]


def test_find_target_hybas_ids_reprojects_subbasins(phydap_polygons):
    """Subbasin in a different CRS gets reprojected before intersection."""
    subbasin = gpd.GeoDataFrame(
        [{"SubId": 7, "geometry": Polygon([(0.1, 0.2), (0.9, 0.2), (0.9, 0.8), (0.1, 0.8)])}],
        crs="EPSG:4326",
    ).to_crs("EPSG:3857")

    result = find_target_hybas_ids(phydap_polygons, subbasin)
    assert result == [1001]


# ---------------------------------------------------------------------------
# find_basin_indices
# ---------------------------------------------------------------------------

def test_find_basin_indices_returns_positions():
    available = np.array([1001, 1002, 1003, 1004, 1005])
    assert find_basin_indices(available, [1003, 1001, 1005]) == [2, 0, 4]


def test_find_basin_indices_skips_missing():
    available = np.array([1001, 1002, 1003])
    assert find_basin_indices(available, [1002, 9999, 1001]) == [1, 0]


def test_find_basin_indices_returns_first_match_only():
    """If a HYBAS appears multiple times in source, return its first index."""
    available = np.array([1001, 1002, 1001, 1003])
    assert find_basin_indices(available, [1001]) == [0]


# ---------------------------------------------------------------------------
# build_hybas_grid_map
# ---------------------------------------------------------------------------

def test_build_hybas_grid_map_sequential_index():
    result = build_hybas_grid_map([1003, 1001, 1005])
    assert list(result.columns) == ["grid_idx", "hybas_id"]
    assert result["grid_idx"].tolist() == [0, 1, 2]
    assert result["hybas_id"].tolist() == [1003, 1001, 1005]


# ---------------------------------------------------------------------------
# subset_phydap_nc — file-level integration
# ---------------------------------------------------------------------------

def test_subset_phydap_nc_writes_correct_shape(synthetic_phydap_nc, tmp_path):
    out = tmp_path / "subset.nc"
    subset_phydap_nc(
        synthetic_phydap_nc,
        var_name="cropped_runoff",
        basin_indices=[1, 3],  # HYBAS 1002 and 1004
        output_path=out,
    )

    with Dataset(out, "r") as ds:
        # Dimensions: time, lat, lon
        assert ds.variables["runoff"].shape == (24, 1, 2)
        assert list(ds.variables["lon"][:]) == [1002, 1004]
        # Spot-check data: runoff[t=5, lat=0, lon=0] should be source[t=5, h=1] = 501
        assert ds.variables["runoff"][5, 0, 0] == pytest.approx(501.0)
        assert ds.variables["runoff"][5, 0, 1] == pytest.approx(503.0)


def test_subset_phydap_nc_rejects_empty_indices(synthetic_phydap_nc, tmp_path):
    with pytest.raises(ValueError, match="empty"):
        subset_phydap_nc(
            synthetic_phydap_nc,
            var_name="cropped_runoff",
            basin_indices=[],
            output_path=tmp_path / "out.nc",
        )


# ---------------------------------------------------------------------------
# subset_phydap_for_watershed — full pipeline
# ---------------------------------------------------------------------------

def test_subset_phydap_for_watershed_end_to_end(
    synthetic_phydap_nc, phydap_polygons, tmp_path,
):
    """Watershed overlapping HYBAS 1002 and 1003 → subset NC + hybas_map CSV."""
    phydap_shp = tmp_path / "phydap.shp"
    phydap_polygons.to_file(phydap_shp)

    subbasin = gpd.GeoDataFrame(
        [{"SubId": 7, "geometry": Polygon([(1.5, 0.2), (2.5, 0.2), (2.5, 0.8), (1.5, 0.8)])}],
        crs="EPSG:4326",
    )
    sub_shp = tmp_path / "subbasin.shp"
    subbasin.to_file(sub_shp)

    out_nc = tmp_path / "subset.nc"
    out_csv = tmp_path / "hybas_map.csv"

    hybas_map = subset_phydap_for_watershed(
        source_nc=synthetic_phydap_nc,
        var_name="cropped_runoff",
        phydap_shp=phydap_shp,
        subbasins_shp=sub_shp,
        output_nc=out_nc,
        output_hybas_map_csv=out_csv,
    )

    # NC contains the two intersecting basins
    with Dataset(out_nc, "r") as ds:
        assert sorted(ds.variables["lon"][:].tolist()) == [1002, 1003]

    # CSV is written and matches the returned DataFrame
    on_disk = pd.read_csv(out_csv)
    assert sorted(on_disk["hybas_id"].tolist()) == [1002, 1003]
    assert on_disk["grid_idx"].tolist() == sorted(on_disk["grid_idx"].tolist())
    assert sorted(hybas_map["hybas_id"].tolist()) == sorted(on_disk["hybas_id"].tolist())


def test_subset_phydap_for_watershed_raises_when_no_overlap(
    synthetic_phydap_nc, phydap_polygons, tmp_path,
):
    """Watershed entirely outside PHyDAP coverage → clear error."""
    phydap_shp = tmp_path / "phydap.shp"
    phydap_polygons.to_file(phydap_shp)

    far_away = gpd.GeoDataFrame(
        [{"SubId": 1, "geometry": Polygon([(100, 100), (101, 100), (101, 101), (100, 101)])}],
        crs="EPSG:4326",
    )
    sub_shp = tmp_path / "far.shp"
    far_away.to_file(sub_shp)

    with pytest.raises(ValueError, match="No PHyDAP basins"):
        subset_phydap_for_watershed(
            source_nc=synthetic_phydap_nc,
            var_name="cropped_runoff",
            phydap_shp=phydap_shp,
            subbasins_shp=sub_shp,
            output_nc=tmp_path / "out.nc",
            output_hybas_map_csv=tmp_path / "map.csv",
        )
