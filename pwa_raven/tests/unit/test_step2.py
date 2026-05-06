"""Unit tests for pwa_raven.step2 — Step2Config + run_step2.

The e2e fixture builds a synthetic subbasins shapefile + Step-1-shaped
NetCDF + WSC metadata + WSC daily CSV with enough columns to satisfy
prepare_basin_attributes and the .rvh writer.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from netCDF4 import Dataset
from shapely.geometry import Polygon

from pwa_raven.step2 import Step2Config, Step2Result, run_step2


# ---------------------------------------------------------------------------
# Step2Config — construction + validation
# ---------------------------------------------------------------------------


def _minimal_config_kwargs(tmp_path: Path) -> dict:
    return {
        "watershed_name": "grassmere",
        "output_dir": tmp_path / "out",
        "subbasins_shapefile": tmp_path / "subbasins.shp",
        "phydap_nc": tmp_path / "adj.nc",
        "wsc_metadata_csv": tmp_path / "metadata.csv",
        "wsc_daily_csv": tmp_path / "daily.csv",
    }


def test_config_normalizes_paths(tmp_path: Path):
    cfg = Step2Config(**{
        k: str(v) if isinstance(v, Path) else v
        for k, v in _minimal_config_kwargs(tmp_path).items()
    })
    assert isinstance(cfg.output_dir, Path)
    assert isinstance(cfg.phydap_nc, Path)


def test_config_is_frozen(tmp_path: Path):
    cfg = Step2Config(**_minimal_config_kwargs(tmp_path))
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.watershed_name = "renamed"  # type: ignore[misc]


def test_config_derived_paths(tmp_path: Path):
    cfg = Step2Config(**_minimal_config_kwargs(tmp_path))
    assert cfg.processed_dir == tmp_path / "out" / "Raven" / "Processed"
    assert cfg.templates_dir == cfg.processed_dir / "templates"
    assert cfg.input_dir == cfg.processed_dir / "input"
    assert cfg.rvi_path.name == "grassmere.rvi"
    assert cfg.channel_rvp_path.name == "channel_properties.rvp"


def test_config_safe_name_strips_spaces(tmp_path: Path):
    cfg = Step2Config(
        **{**_minimal_config_kwargs(tmp_path), "watershed_name": "Long Name Here"}
    )
    assert cfg.safe_name == "LongNameHere"
    assert cfg.rvi_path.name == "LongNameHere.rvi"


# ---------------------------------------------------------------------------
# expected_input_files + validate_inputs_exist
# ---------------------------------------------------------------------------


def test_expected_input_files_lists_four(tmp_path: Path):
    cfg = Step2Config(**_minimal_config_kwargs(tmp_path))
    files = cfg.expected_input_files()
    assert {p.name for p in files} == {
        "subbasins.shp", "adj.nc", "metadata.csv", "daily.csv",
    }


def test_validate_inputs_exist_passes_when_all_present(tmp_path: Path):
    cfg = Step2Config(**_minimal_config_kwargs(tmp_path))
    for p in cfg.expected_input_files():
        p.touch()
    cfg.validate_inputs_exist()


def test_validate_inputs_exist_raises_listing_all_missing(tmp_path: Path):
    cfg = Step2Config(**_minimal_config_kwargs(tmp_path))
    cfg.phydap_nc.touch()
    with pytest.raises(FileNotFoundError) as exc:
        cfg.validate_inputs_exist()
    msg = str(exc.value)
    assert "subbasins.shp" in msg
    assert "metadata.csv" in msg
    assert "daily.csv" in msg


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def test_to_dict_round_trip(tmp_path: Path):
    cfg = Step2Config(
        **_minimal_config_kwargs(tmp_path),
        curve_number=70.0,
        user_start="2003-01-01 00:00:00",
        user_end="2021-12-31 00:00:00",
        write_calibration_templates=False,
        write_aspect_ratios=False,
    )
    rebuilt = Step2Config.from_dict(cfg.to_dict())
    assert rebuilt == cfg


def test_from_dict_minimal_uses_defaults(tmp_path: Path):
    cfg = Step2Config.from_dict({
        "watershed_name": "manning",
        "output_dir": str(tmp_path),
        "subbasins_shapefile": str(tmp_path / "s.shp"),
        "phydap_nc": str(tmp_path / "n.nc"),
        "wsc_metadata_csv": str(tmp_path / "m.csv"),
        "wsc_daily_csv": str(tmp_path / "d.csv"),
    })
    assert cfg.curve_number == 63.0
    assert cfg.write_calibration_templates is True
    assert cfg.write_aspect_ratios is True


def test_from_dict_rejects_missing_required(tmp_path: Path):
    with pytest.raises(ValueError, match="missing"):
        Step2Config.from_dict({
            "watershed_name": "x",
            "output_dir": str(tmp_path),
        })


def test_to_yaml_round_trip(tmp_path: Path):
    cfg = Step2Config(**_minimal_config_kwargs(tmp_path))
    out = tmp_path / "step2.yml"
    cfg.to_yaml(out)
    rebuilt = Step2Config.from_yaml(out)
    assert rebuilt == cfg


# ---------------------------------------------------------------------------
# run_step2 — end-to-end
# ---------------------------------------------------------------------------


def _build_subbasins_shp(path: Path) -> None:
    """3-basin synthetic that satisfies prepare_basin_attributes + writers.

    Layout: SUB_1 → SUB_3, SUB_2 → SUB_3, SUB_3 → -1 (outlet).
    SUB_3 is the only Has_POI=1 subbasin → unambiguous outlet.
    """
    polys = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
    ]
    gdf = gpd.GeoDataFrame({
        "SubId":      [1, 2, 3],
        "DowSubId":   [3, 3, -1],
        "Has_POI":    [0, 0, 1],
        "Lake_Cat":   [0, 0, 0],          # all contributing
        "BasArea":    [1.0e6, 2.0e6, 3.0e6],   # m²
        "BasSlope":   [0.5, 1.0, 0.8],         # degrees
        "BasAspect":  [10.0, 90.0, 180.0],
        "BkfWidth":   [3.0, 4.0, 5.0],
        "BkfDepth":   [0.5, 1.5, 2.0],          # 0.5 will be clamped to 1
        "RivLength":  [500.0, 1500.0, 2500.0],  # m
        "RivSlope":   [0.001, 0.002, 0.0001],   # the third triggers replacement
        "MeanElev":   [200.0, 210.0, 220.0],
        "FloodP_n":   [0.05, 0.06, 0.07],
        "Ch_n":       [0.025, 0.030, 0.035],
        "DrainArea":  [1.0e6, 3.0e6, 6.0e6],
        "Q_Mean":     [1.5, 3.0, 5.0],
        "Deps_Depth": [10.0, 20.0, 30.0],
        "centroid_x": [0.5, 1.5, 2.5],
        "centroid_y": [0.5, 0.5, 0.5],
        "geometry":   polys,
    }, crs="EPSG:4326")
    gdf.to_file(path)


def _build_phydap_adj_nc(path: Path) -> None:
    """Tiny NetCDF with a 'time' variable in hours since 1900-01-01."""
    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", 100)
        ds.createDimension("lat", 1)
        ds.createDimension("lon", 3)
        time_var = ds.createVariable("time", "f8", ("time",))
        time_var.units = "hours since 1900-01-01 00:00:00"
        # 100 hourly samples starting 2010-01-01 00:00:00 (110 years × 8766
        # hours/year ≈ 964260, +0..99 hourly steps from there)
        # 2010-01-01 = 1900-01-01 + 40177 days = 40177 * 24 = 964248 hrs
        time_var[:] = 964248.0 + np.arange(100, dtype=np.float64)
        runoff = ds.createVariable("runoff", "f4", ("time", "lat", "lon"))
        runoff[:, :, :] = 0.5


def _build_wsc_metadata_csv(path: Path) -> None:
    pd.DataFrame({
        "Station Name": ["GRASSMERE CREEK NEAR PINE BLUFF"],
        "Station Number": ["05NF002"],
    }).to_csv(path, index=False)


def _build_wsc_daily_csv(path: Path) -> None:
    """30 daily discharge readings from 2010-01-01 covering the NetCDF window."""
    dates = pd.date_range("2010-01-01", periods=30, freq="D")
    df = pd.DataFrame({
        "Date": dates.strftime("%Y-%m-%d"),
        "PARAM": [1] * 30,
        "Value": [3.5] * 30,
    })
    # WSC daily exports have a leading row stripped via skiprows=1
    with open(path, "w") as f:
        f.write("# WSC daily export header\n")
        df.to_csv(f, index=False)


@pytest.fixture
def synthetic_step2_inputs(tmp_path: Path) -> dict:
    sub_path = tmp_path / "subbasins.shp"
    nc_path = tmp_path / "adj.nc"
    meta_path = tmp_path / "metadata.csv"
    daily_path = tmp_path / "daily.csv"

    _build_subbasins_shp(sub_path)
    _build_phydap_adj_nc(nc_path)
    _build_wsc_metadata_csv(meta_path)
    _build_wsc_daily_csv(daily_path)

    return {
        "subbasins_shapefile": sub_path,
        "phydap_nc": nc_path,
        "wsc_metadata_csv": meta_path,
        "wsc_daily_csv": daily_path,
        "output_dir": tmp_path / "out",
    }


def _e2e_config(synthetic_step2_inputs: dict, **overrides) -> Step2Config:
    """Build a Step2Config with a model window that matches the synthetic NC."""
    return Step2Config(
        watershed_name="testwater",
        # Both NC and WSC start 2010-01-01. Use a wide user window so the
        # NC + WSC ranges become the binding constraints (per
        # resolve_model_window's intersect rule).
        user_start="2000-01-01 00:00:00",
        user_end="2025-12-31 00:00:00",
        **synthetic_step2_inputs,
        **overrides,
    )


def test_run_step2_writes_all_required_files(synthetic_step2_inputs: dict):
    cfg = _e2e_config(synthetic_step2_inputs)
    result = run_step2(cfg)

    assert isinstance(result, Step2Result)
    for path in (
        result.rvi, result.rvc, result.rvp, result.rvh, result.model_rvt,
        result.channel_rvp, result.wsc_rvt, result.wsc_outlet_txt,
    ):
        assert path.is_file(), f"missing required output: {path}"


def test_run_step2_writes_optional_files_by_default(synthetic_step2_inputs: dict):
    cfg = _e2e_config(synthetic_step2_inputs)
    result = run_step2(cfg)
    for path in (
        result.rvh_template, result.rvp_template, result.channel_rvp_template,
        result.hru_areas_csv, result.tp_tc_csv, result.aspect_ratios_csv,
    ):
        assert path is not None and path.is_file()


def test_run_step2_skips_calibration_templates_when_disabled(
    synthetic_step2_inputs: dict,
):
    cfg = _e2e_config(synthetic_step2_inputs, write_calibration_templates=False)
    result = run_step2(cfg)
    assert result.rvh_template is None
    assert result.rvp_template is None
    assert result.channel_rvp_template is None
    assert result.hru_areas_csv is None
    assert result.tp_tc_csv is None
    # templates dir not created
    assert not cfg.templates_dir.exists()


def test_run_step2_skips_aspect_ratios_when_disabled(synthetic_step2_inputs: dict):
    cfg = _e2e_config(synthetic_step2_inputs, write_aspect_ratios=False)
    result = run_step2(cfg)
    assert result.aspect_ratios_csv is None


def test_run_step2_writes_outlet_subid_to_text(synthetic_step2_inputs: dict):
    cfg = _e2e_config(synthetic_step2_inputs)
    result = run_step2(cfg)
    # Outlet is SUB_3 (the only Has_POI=1 row in the synthetic fixture)
    assert result.wsc_outlet_txt.read_text().strip() == "3"


def test_run_step2_wsc_rvt_filename_uses_station_id(synthetic_step2_inputs: dict):
    cfg = _e2e_config(synthetic_step2_inputs)
    result = run_step2(cfg)
    assert result.wsc_rvt.name == "WSC05NF002.rvt"


def test_run_step2_rvi_includes_watershed_name(synthetic_step2_inputs: dict):
    cfg = _e2e_config(synthetic_step2_inputs)
    result = run_step2(cfg)
    assert "testwater" in result.rvi.read_text()


def test_run_step2_validates_inputs_first(tmp_path: Path):
    """Missing inputs raise before any output is created."""
    cfg = Step2Config(
        watershed_name="x",
        output_dir=tmp_path / "out",
        subbasins_shapefile=tmp_path / "missing.shp",
        phydap_nc=tmp_path / "missing.nc",
        wsc_metadata_csv=tmp_path / "missing_m.csv",
        wsc_daily_csv=tmp_path / "missing_d.csv",
    )
    with pytest.raises(FileNotFoundError, match="missing"):
        run_step2(cfg)
    assert not (tmp_path / "out").exists()
