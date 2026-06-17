"""NetCDF I/O for PHyDAP climate data.

Replaces ``PWA/src/py/phydap.py`` (220 lines).

Key changes:
  - ``lat_value=49.43`` hardcoded default → required parameter (no default)
  - ``add_dimension()`` stub → raises ``NotImplementedError``
  - ``phydap_nc`` now supports context manager (``with`` statement)
  - ``pathlib.Path`` throughout
  - Logging instead of print
  - Trailing ``pass`` statements removed
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from netCDF4 import Dataset

logger = logging.getLogger(__name__)


class PhydapNC:
    """Handle PHyDAP NetCDF files — open, extract, modify, close.

    Supports context-manager usage::

        with PhydapNC("forcing.nc", var_name="cropped_runoff") as nc:
            data = nc.extract_to_pd("cropped_runoff", lat_value=50.2)
    """

    def __init__(
        self,
        filepath: Path | str,
        var_name: str = "cropped_runoff",
        file_setting: str = "r",
    ) -> None:
        self.filepath = Path(filepath)
        self.var_name = var_name
        self.file = Dataset(str(self.filepath), file_setting)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self) -> None:
        self.file.close()
        logger.info("Closed %s", self.filepath.name)

    def add_dimension(self, dim_name: str, dim_size: int) -> None:
        raise NotImplementedError(
            "add_dimension is a stub from the original phydap.py. "
            "Implement if needed for your workflow."
        )

    def extract_to_pd(
        self,
        var_name: str,
        lat_value: float,
        dim1_name: str = "time_hrs",
        dim2_name: str = "HYBAS_ID",
    ) -> dict[str, Any]:
        """Extract a variable from the NetCDF, reshape to (nt, nlat, nh).

        Parameters
        ----------
        var_name
            Name of the data variable to extract.
        lat_value
            Latitude value for the artificial latitude dimension. This was
            hardcoded to 49.43 in the original — now required explicitly.
        dim1_name
            Name of the time dimension (default ``time_hrs``).
        dim2_name
            Name of the basin-ID dimension (default ``HYBAS_ID``).

        Returns
        -------
        dict
            Keys: ``var_data``, ``HYBAS_ID``, ``reshaped``, ``nt``, ``nlat``,
            ``nh``, ``lat``.
        """
        lat = np.array([lat_value])
        nlat = lat.shape[0]

        var_data = self.file.variables[dim1_name][:]
        nt = var_data.shape[0]

        hybas_id = self.file.variables[dim2_name][:]
        nh = hybas_id.shape[0]

        raw_data = self.file.variables[var_name][:]
        flat_data = raw_data.flatten()
        reshaped = flat_data.reshape((nt, nlat, nh))

        logger.info(
            "Extracted %s: nt=%d, nlat=%d, nh=%d (%s)",
            var_name, nt, nlat, nh, reshaped.shape,
        )
        return {
            "var_data": var_data,
            "HYBAS_ID": hybas_id,
            "reshaped": reshaped,
            "nt": nt,
            "nlat": nlat,
            "nh": nh,
            "lat": lat,
        }

    def extract_variable(self, var_name: str) -> None:
        """Extract a variable and store it as an attribute on this instance."""
        setattr(self, var_name, self.file.variables[var_name][:])

    def import_variable(self, var_name: str, var_data=None) -> None:
        """Write data back into the NetCDF variable.

        If *var_data* is provided, writes that. Otherwise writes the
        attribute with the same name from this instance.
        """
        if var_data is not None:
            self.file.variables[var_name][:] = var_data
        else:
            self.file.variables[var_name][:] = getattr(self, var_name)


class PhydapDim:
    """Metadata container for a NetCDF dimension."""

    def __init__(self, dim_name: str, dim_units: str, dim_size: int, dim_axis: str, dim_data) -> None:
        self.name = dim_name
        self.units = dim_units
        self.size = dim_size
        self.axis = dim_axis
        self.data = dim_data


class PhydapVar:
    """Metadata container for a NetCDF variable."""

    def __init__(self, var_name: str, var_units: str, var_data, fill_value: float = 1e32) -> None:
        self.name = var_name
        self.units = var_units
        self.fill = fill_value
        self.data = var_data


def save_pd_to_nc(
    new_filepath: Path | str,
    dims_list: list[PhydapDim],
    var_data: PhydapVar,
) -> None:
    """Save data to a new NetCDF file with specified dimensions.

    Parameters
    ----------
    new_filepath
        Output NetCDF path.
    dims_list
        List of :class:`PhydapDim` instances defining the dimensions.
    var_data
        A :class:`PhydapVar` instance containing the data and metadata.
    """
    new_filepath = Path(new_filepath)

    ncout = Dataset(str(new_filepath), "w", format="NETCDF4")

    for dim in dims_list:
        if not isinstance(dim, PhydapDim):
            raise ValueError("Dimensions must be instances of PhydapDim class.")
        ncout.createDimension(dim.name, dim.size)
        dim_var = ncout.createVariable(dim.name, "f8", (dim.name,))
        dim_var.units = dim.units
        dim_var.axis = dim.axis
        dim_var[:] = dim.data.astype(np.float64)

    if not isinstance(var_data, PhydapVar):
        raise ValueError("var_data must be an instance of PhydapVar class.")

    ndims = len(dims_list)
    if ndims not in (2, 3):
        raise ValueError("This function currently supports only 2D or 3D data.")

    var = ncout.createVariable(
        var_data.name, "f8",
        tuple(dim.name for dim in dims_list),
        fill_value=var_data.fill,
    )
    var.long_name = var_data.name
    var.units = var_data.units

    # Write data, chunked if very large (>2GB limit for single write)
    chunk_threshold = 2**31 - 1
    if var_data.data.size < chunk_threshold:
        var[:] = var_data.data
    else:
        last_dim_size = dims_list[-1].size
        for period in range(last_dim_size // 100000 + 1):
            start = period * 100000
            end = min(last_dim_size, (period + 1) * 100000)
            if ndims == 2:
                var[:, start:end] = var_data.data[:, start:end]
            else:
                var[:, :, start:end] = var_data.data[:, :, start:end]

    ncout.close()
    logger.info("Saved NetCDF → %s", new_filepath.name)


def time_offset(
    old_path: Path | str,
    new_path: Path | str,
    offset: float,
) -> None:
    """Apply a time offset (in hours) to the ``time`` variable in a NetCDF file.

    Copies *old_path* to *new_path*, then modifies the time variable in-place.
    """
    old_path = Path(old_path)
    new_path = Path(new_path)

    if new_path.exists():
        os.remove(new_path)
    shutil.copy(old_path, new_path)

    with PhydapNC(new_path, var_name="time", file_setting="r+") as nc:
        nc.extract_variable("time")
        nc.time = nc.time - offset
        nc.import_variable("time")

    logger.info("Applied time offset of %s hours: %s → %s", offset, old_path.name, new_path.name)
