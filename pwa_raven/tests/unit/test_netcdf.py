"""Tests for pwa_raven.io.netcdf — PHyDAP NetCDF handling.

Uses synthetic NetCDF files in tmp_path. No real data needed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from netCDF4 import Dataset

from pwa_raven.io.netcdf import (
    PhydapDim,
    PhydapNC,
    PhydapVar,
    save_pd_to_nc,
    time_offset,
)


# ============ Helpers ============


def _create_synthetic_nc(path: Path, nt: int = 10, nh: int = 3) -> Path:
    """Create a tiny PHyDAP-style NetCDF with time_hrs, HYBAS_ID, and cropped_runoff."""
    ds = Dataset(str(path), "w", format="NETCDF4")
    ds.createDimension("time_hrs", nt)
    ds.createDimension("HYBAS_ID", nh)

    time_var = ds.createVariable("time_hrs", "f8", ("time_hrs",))
    time_var[:] = np.arange(nt, dtype=np.float64)
    time_var.units = "hours since 2003-01-01"

    hybas_var = ds.createVariable("HYBAS_ID", "i4", ("HYBAS_ID",))
    hybas_var[:] = np.array([310015403, 310015404, 310015405])

    # Also add a "time" variable for time_offset tests
    time_plain = ds.createVariable("time", "f8", ("time_hrs",))
    time_plain[:] = np.arange(nt, dtype=np.float64) * 3600.0
    time_plain.units = "seconds since 2003-01-01"

    runoff = ds.createVariable("cropped_runoff", "f4", ("time_hrs", "HYBAS_ID"))
    runoff[:] = np.random.RandomState(42).rand(nt, nh).astype(np.float32)

    ds.close()
    return path


# ============ PhydapNC ============


def test_phydap_nc_context_manager(tmp_path: Path) -> None:
    nc_path = _create_synthetic_nc(tmp_path / "test.nc")
    with PhydapNC(nc_path) as nc:
        assert nc.file.isopen()
    # After exiting context, file should be closed
    assert not nc.file.isopen()


def test_extract_to_pd_shape(tmp_path: Path) -> None:
    nc_path = _create_synthetic_nc(tmp_path / "test.nc", nt=10, nh=3)
    with PhydapNC(nc_path) as nc:
        result = nc.extract_to_pd("cropped_runoff", lat_value=50.2)

    assert result["nt"] == 10
    assert result["nlat"] == 1
    assert result["nh"] == 3
    assert result["reshaped"].shape == (10, 1, 3)
    assert result["lat"][0] == pytest.approx(50.2)


def test_extract_to_pd_requires_lat_value(tmp_path: Path) -> None:
    """lat_value is now required — no hardcoded 49.43 default."""
    nc_path = _create_synthetic_nc(tmp_path / "test.nc")
    with PhydapNC(nc_path) as nc:
        # Should fail because lat_value is required
        with pytest.raises(TypeError):
            nc.extract_to_pd("cropped_runoff")


def test_extract_variable_stores_attribute(tmp_path: Path) -> None:
    nc_path = _create_synthetic_nc(tmp_path / "test.nc", nt=5)
    with PhydapNC(nc_path, file_setting="r") as nc:
        nc.extract_variable("time")
        assert hasattr(nc, "time")
        assert len(nc.time) == 5


def test_add_dimension_raises(tmp_path: Path) -> None:
    nc_path = _create_synthetic_nc(tmp_path / "test.nc")
    with PhydapNC(nc_path) as nc:
        with pytest.raises(NotImplementedError):
            nc.add_dimension("new_dim", 10)


# ============ save_pd_to_nc ============


def test_save_pd_to_nc_roundtrip(tmp_path: Path) -> None:
    """Create dims + var, save to NC, re-read and verify."""
    nt, nh = 5, 2
    time_data = np.arange(nt, dtype=np.float64)
    hybas_data = np.arange(nh, dtype=np.float64)
    var_data = np.random.RandomState(0).rand(nt, nh).astype(np.float64)

    dims = [
        PhydapDim("time", "hours", nt, "T", time_data),
        PhydapDim("basin", "1", nh, "X", hybas_data),
    ]
    var = PhydapVar("runoff", "mm/hr", var_data)

    out_path = tmp_path / "output.nc"
    save_pd_to_nc(out_path, dims, var)

    assert out_path.exists()

    # Re-read and verify
    ds = Dataset(str(out_path), "r")
    assert ds.dimensions["time"].size == nt
    assert ds.dimensions["basin"].size == nh
    written = ds.variables["runoff"][:]
    np.testing.assert_array_almost_equal(written, var_data)
    ds.close()


def test_save_pd_to_nc_rejects_bad_dims(tmp_path: Path) -> None:
    var = PhydapVar("x", "1", np.zeros((5,)))
    with pytest.raises(ValueError, match="2D or 3D"):
        save_pd_to_nc(tmp_path / "bad.nc", [PhydapDim("a", "1", 5, "X", np.arange(5))], var)


# ============ time_offset ============


def test_time_offset_applies_correctly(tmp_path: Path) -> None:
    src = _create_synthetic_nc(tmp_path / "original.nc", nt=5)

    # Read original time values
    ds = Dataset(str(src), "r")
    original_time = ds.variables["time"][:].copy()
    ds.close()

    # Apply offset
    dst = tmp_path / "offset.nc"
    time_offset(src, dst, offset=6.0)

    # Verify offset was applied
    ds = Dataset(str(dst), "r")
    offset_time = ds.variables["time"][:]
    ds.close()

    np.testing.assert_array_almost_equal(offset_time, original_time - 6.0)


def test_time_offset_overwrites_existing(tmp_path: Path) -> None:
    src = _create_synthetic_nc(tmp_path / "original.nc")
    dst = tmp_path / "offset.nc"
    dst.write_text("placeholder")  # pre-existing file

    time_offset(src, dst, offset=1.0)
    # Should have overwritten — file should be a valid NC now
    ds = Dataset(str(dst), "r")
    ds.close()
