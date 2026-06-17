"""Unit tests for pwa_raven.nc_processing — NcProcessingConfig + run_nc_processing.

Config tests use plain paths in tmp_path. The run_nc_processing e2e test
builds a tiny synthetic PHyDAP NetCDF + polygon shapefile + subbasin
shapefile so we can exercise the full pipeline without external data.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from netCDF4 import Dataset
from shapely.geometry import Polygon

from pwa_raven.nc_processing import NcProcessingConfig, NcProcessingResult, run_nc_processing


# ---------------------------------------------------------------------------
# NcProcessingConfig — construction + validation
# ---------------------------------------------------------------------------


def _minimal_config_kwargs(tmp_path: Path) -> dict:
    return {
        "watershed_name": "grassmere",
        "output_dir": tmp_path / "out",
        "phydap_nc": tmp_path / "phydap.nc",
        "phydap_shapefile": tmp_path / "phydap.shp",
        "subbasins_shapefile": tmp_path / "subbasins.shp",
    }


def test_config_normalizes_paths(tmp_path: Path):
    """String paths get coerced to Path."""
    kw = _minimal_config_kwargs(tmp_path)
    kw = {k: str(v) if isinstance(v, Path) else v for k, v in kw.items()}
    cfg = NcProcessingConfig(**kw)
    assert isinstance(cfg.output_dir, Path)
    assert isinstance(cfg.phydap_nc, Path)


def test_config_rejects_unknown_data_category(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported data_category"):
        NcProcessingConfig(**_minimal_config_kwargs(tmp_path), data_category="Sleet")


def test_config_accepts_known_data_categories(tmp_path: Path):
    for cat in ("Runoff", "Snowmelt", "Rainfall"):
        cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path), data_category=cat)
        assert cfg.data_category == cat


def test_config_is_frozen(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path))
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.watershed_name = "renamed"  # type: ignore[misc]


def test_config_default_subset_nc_name_uses_watershed_and_category(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path), data_category="Runoff")
    assert cfg.subset_nc_path.name == "grassmere_runoff.nc"
    assert cfg.adjusted_nc_path.name == "grassmere_runoff_adj.nc"


def test_config_explicit_output_nc_name_overrides(tmp_path: Path):
    cfg = NcProcessingConfig(
        **_minimal_config_kwargs(tmp_path),
        output_nc_name="custom_name.nc",
    )
    assert cfg.subset_nc_path.name == "custom_name.nc"
    assert cfg.adjusted_nc_path.name == "custom_name_adj.nc"


def test_config_processed_dir_uses_data_category(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path), data_category="Snowmelt")
    assert cfg.processed_dir == tmp_path / "out" / "Snowmelt" / "Processed"


# ---------------------------------------------------------------------------
# expected_input_files + validate_inputs_exist
# ---------------------------------------------------------------------------


def test_expected_input_files_lists_three(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path))
    files = cfg.expected_input_files()
    assert {p.name for p in files} == {"phydap.nc", "phydap.shp", "subbasins.shp"}


def test_validate_inputs_exist_passes_when_all_present(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path))
    for p in cfg.expected_input_files():
        p.touch()
    cfg.validate_inputs_exist()  # should not raise


def test_validate_inputs_exist_raises_listing_all_missing(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path))
    cfg.phydap_nc.touch()  # only one of three present
    with pytest.raises(FileNotFoundError) as exc:
        cfg.validate_inputs_exist()
    msg = str(exc.value)
    assert "phydap.shp" in msg
    assert "subbasins.shp" in msg
    assert "phydap.nc" not in msg  # was created → not in the missing list


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def test_to_dict_round_trip(tmp_path: Path):
    original = NcProcessingConfig(
        **_minimal_config_kwargs(tmp_path),
        data_category="Snowmelt",
        nc_variable="snow_water_eq",
        nc_var_units="mm",
        output_nc_name="custom.nc",
        time_offset_hours=6,
        lat_value=51.0,
    )
    rebuilt = NcProcessingConfig.from_dict(original.to_dict())
    assert rebuilt == original


def test_from_dict_minimal_uses_defaults(tmp_path: Path):
    cfg = NcProcessingConfig.from_dict({
        "watershed_name": "grassmere",
        "output_dir": str(tmp_path),
        "phydap_nc": str(tmp_path / "p.nc"),
        "phydap_shapefile": str(tmp_path / "p.shp"),
        "subbasins_shapefile": str(tmp_path / "s.shp"),
    })
    assert cfg.data_category == "Runoff"
    assert cfg.nc_variable == "cropped_runoff"
    assert cfg.time_offset_hours == 10


def test_from_dict_rejects_missing_required(tmp_path: Path):
    with pytest.raises(ValueError, match="missing"):
        NcProcessingConfig.from_dict({
            "watershed_name": "x",
            "output_dir": str(tmp_path),
            # missing the three required path fields
        })


def test_to_yaml_round_trip(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path))
    out = tmp_path / "nc_processing.yml"
    cfg.to_yaml(out)
    rebuilt = NcProcessingConfig.from_yaml(out)
    assert rebuilt == cfg


def test_to_yaml_creates_parent_dir(tmp_path: Path):
    cfg = NcProcessingConfig(**_minimal_config_kwargs(tmp_path))
    out = tmp_path / "deeply" / "nested" / "nc_processing.yml"
    cfg.to_yaml(out)
    assert out.is_file()


# ---------------------------------------------------------------------------
# run_nc_processing — end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_nc_inputs(tmp_path: Path) -> dict:
    """Build a tiny PHyDAP NetCDF + polygon shapefile + subbasin shapefile.

    Layout:
      * 5 PHyDAP polygons covering [0,5]×[0,1], one per HYBAS_ID.
      * NetCDF with 24 timesteps × 5 basins.
      * 1 subbasin polygon overlapping cells 1002 + 1003.
    """
    # NetCDF
    nc_path = tmp_path / "phydap.nc"
    nt, nh = 24, 5
    hybas_ids = np.array([1001, 1002, 1003, 1004, 1005], dtype=np.int64)
    with Dataset(nc_path, "w", format="NETCDF4") as ds:
        ds.createDimension("time_hrs", nt)
        ds.createDimension("HYBAS_ID", nh)
        time_var = ds.createVariable("time_hrs", "f8", ("time_hrs",))
        time_var.units = "hours since 1900-01-01 00:00:00"
        time_var[:] = np.arange(nt, dtype=np.float64) * 1000.0
        hybas_var = ds.createVariable("HYBAS_ID", "i8", ("HYBAS_ID",))
        hybas_var[:] = hybas_ids
        runoff = ds.createVariable("cropped_runoff", "f4", ("time_hrs", "HYBAS_ID"))
        runoff[:, :] = (
            np.arange(nt, dtype=np.float32)[:, None] * 100
            + np.arange(nh, dtype=np.float32)
        )

    # PHyDAP polygons
    phydap_shp_path = tmp_path / "phydap.shp"
    polys = [
        Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)])
        for i in range(5)
    ]
    gpd.GeoDataFrame(
        {"HYBAS_ID": hybas_ids.tolist()},
        geometry=polys,
        crs="EPSG:4326",
    ).to_file(phydap_shp_path)

    # Subbasin polygon overlapping cells 1002 + 1003
    subbasins_shp_path = tmp_path / "subbasins.shp"
    gpd.GeoDataFrame(
        [{"SubId": 7, "geometry": Polygon([(1.5, 0.2), (2.5, 0.2), (2.5, 0.8), (1.5, 0.8)])}],
        crs="EPSG:4326",
    ).to_file(subbasins_shp_path)

    return {
        "phydap_nc": nc_path,
        "phydap_shapefile": phydap_shp_path,
        "subbasins_shapefile": subbasins_shp_path,
        "output_dir": tmp_path / "out",
    }


def test_run_nc_processing_produces_all_four_outputs(synthetic_nc_inputs: dict):
    cfg = NcProcessingConfig(
        watershed_name="testwater",
        **synthetic_nc_inputs,
    )
    result = run_nc_processing(cfg)

    assert isinstance(result, NcProcessingResult)
    assert result.subset_nc.is_file()
    assert result.adjusted_nc.is_file()
    assert result.hybas_map.is_file()
    assert result.grid_weights.is_file()


def test_run_nc_processing_subset_nc_has_expected_basins(synthetic_nc_inputs: dict):
    """The subbasin overlaps PHyDAP cells 1002 + 1003, so the subsetted
    NetCDF should retain exactly those two basins along the lon dim."""
    cfg = NcProcessingConfig(watershed_name="testwater", **synthetic_nc_inputs)
    result = run_nc_processing(cfg)

    with Dataset(result.subset_nc) as ds:
        # The subsetted file uses 'lon' as the basin dimension (per
        # subset_phydap_nc's contract). Check size matches the 2 overlap.
        assert ds.dimensions["lon"].size == 2


def test_run_nc_processing_grid_weights_includes_watershed_name(synthetic_nc_inputs: dict):
    cfg = NcProcessingConfig(watershed_name="testwater", **synthetic_nc_inputs)
    result = run_nc_processing(cfg)
    assert "testwater" in result.grid_weights.read_text()


def test_run_nc_processing_adjusted_nc_time_is_offset(synthetic_nc_inputs: dict):
    """The adjusted NetCDF's time variable equals subset_nc time minus offset."""
    cfg = NcProcessingConfig(
        watershed_name="testwater",
        time_offset_hours=10,
        **synthetic_nc_inputs,
    )
    result = run_nc_processing(cfg)

    with Dataset(result.subset_nc) as orig, Dataset(result.adjusted_nc) as adj:
        orig_time = orig.variables["time"][:]
        adj_time = adj.variables["time"][:]
        np.testing.assert_allclose(adj_time, orig_time - 10)


def test_run_nc_processing_creates_processed_dir_if_absent(synthetic_nc_inputs: dict):
    """run_nc_processing should mkdir parents=True on the processed output dir."""
    out_dir = synthetic_nc_inputs["output_dir"]
    assert not out_dir.exists()
    cfg = NcProcessingConfig(watershed_name="testwater", **synthetic_nc_inputs)
    run_nc_processing(cfg)
    assert (out_dir / "Runoff" / "Processed").is_dir()


def test_run_nc_processing_validates_inputs_first(tmp_path: Path):
    """If inputs are missing, run_nc_processing raises before touching the FS."""
    cfg = NcProcessingConfig(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        phydap_nc=tmp_path / "doesnt_exist.nc",
        phydap_shapefile=tmp_path / "doesnt_exist.shp",
        subbasins_shapefile=tmp_path / "doesnt_exist.shp",
    )
    with pytest.raises(FileNotFoundError, match="missing"):
        run_nc_processing(cfg)
    # No output dir created either — validation runs before mkdir
    assert not (tmp_path / "out").exists()
