"""Subset PHyDAP forcing NetCDF files to a watershed's basins of interest.

Extracted from ``PWA/_notebooks/1_nc_processing.ipynb`` § 3.

The PHyDAP forcing files cover the entire prairie region (~12k basins). For
each watershed run we need a much smaller subset (typically <1000 basins). This
module:

  1. Finds which PHyDAP basins overlap a watershed (spatial intersection of
     PHyDAP polygons with sub-basin polygons).
  2. Subsets the source NetCDF to those basins.
  3. Writes a new NetCDF with an artificial latitude dimension (Raven expects
     2-D forcing grids; PHyDAP is effectively 1-D in basin index).
  4. Returns a ``hybas_id → grid_idx`` mapping table that downstream code
     (GridWeights generation) consumes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd

from pwa_raven.io.netcdf import (
    PhydapDim,
    PhydapNC,
    PhydapVar,
    save_pd_to_nc,
)

logger = logging.getLogger(__name__)


def find_target_hybas_ids(
    phydap: gpd.GeoDataFrame,
    subbasins: gpd.GeoDataFrame,
    *,
    hybas_id_col: str = "HYBAS_ID",
) -> list[int]:
    """Identify the PHyDAP basins that overlap a watershed.

    Spatial-clips *phydap* to the *subbasins* extent and returns the unique
    HYBAS_ID values of cells that intersect at all.
    """
    if subbasins.crs != phydap.crs:
        logger.info("Reprojecting sub-basins from %s to %s for intersection", subbasins.crs, phydap.crs)
        subbasins = subbasins.to_crs(phydap.crs)

    intersection = gpd.clip(phydap, subbasins)
    hybas_ids = intersection[hybas_id_col].unique().tolist()
    logger.info("Watershed intersects %d PHyDAP basins", len(hybas_ids))
    return [int(h) for h in hybas_ids]


def find_basin_indices(
    available_hybas_ids: np.ndarray,
    target_hybas_ids: Iterable[int],
) -> list[int]:
    """Map a list of HYBAS_IDs to their positional indices in the source NC.

    Returns the *first* matching index per target ID. Targets that do not
    appear in *available_hybas_ids* are silently skipped (matching the
    behaviour of the original notebook).
    """
    indices: list[int] = []
    for hybas_id in target_hybas_ids:
        idx = (available_hybas_ids == hybas_id).nonzero()[0]
        if len(idx) > 0:
            indices.append(int(idx[0]))
    return indices


def build_hybas_grid_map(hybas_ids: Iterable[int]) -> pd.DataFrame:
    """Build the ``grid_idx → hybas_id`` lookup for the subsetted NC.

    ``grid_idx`` is the position in the *new* NC's longitude dimension
    (sequential 0..N-1), not the original PHyDAP index.
    """
    hybas_arr = np.asarray(list(hybas_ids), dtype=np.int64)
    return pd.DataFrame({
        "grid_idx": np.arange(len(hybas_arr), dtype=np.int64),
        "hybas_id": hybas_arr,
    })


def subset_phydap_nc(
    source_path: Path | str,
    var_name: str,
    basin_indices: list[int],
    output_path: Path | str,
    *,
    var_units: str = "mm/h",
    lat_value: float = 49.43,
    time_dim_name: str = "time_hrs",
    hybas_dim_name: str = "HYBAS_ID",
) -> None:
    """Subset *source_path* to the given basin indices and write a new NetCDF.

    The output file has dimensions ``(time, lat, lon)`` where:

      - ``time`` matches the source time axis,
      - ``lat`` is a single artificial latitude (so Raven sees a 2-D grid),
      - ``lon`` indexes the selected basins (one per target sub-basin),
      - the data variable has units of *var_units* (default ``mm/h``).

    Parameters
    ----------
    source_path
        Source PHyDAP NetCDF file (read-only).
    var_name
        Name of the data variable to extract (e.g. ``cropped_runoff``).
    basin_indices
        Positional indices into the source NC's HYBAS_ID array. Use
        :func:`find_basin_indices` to compute these from a list of HYBAS_IDs.
    output_path
        Destination for the subsetted NetCDF.
    var_units
        Units string written to the output variable's metadata.
    lat_value
        Numerical value for the artificial latitude dimension.
    time_dim_name, hybas_dim_name
        Source NC dimension names; defaults match PHyDAP convention.
    """
    if not basin_indices:
        raise ValueError("basin_indices is empty — nothing to subset.")

    with PhydapNC(source_path, var_name=var_name) as nc:
        extracted = nc.extract_to_pd(
            var_name,
            lat_value=lat_value,
            dim1_name=time_dim_name,
            dim2_name=hybas_dim_name,
        )

    time_dim = PhydapDim(
        "time", "hours since 1900-01-01 00:00:00",
        extracted["nt"], "T", extracted["var_data"],
    )
    lat_dim = PhydapDim(
        "lat", "degrees_north",
        extracted["nlat"], "Y", extracted["lat"],
    )
    lon_dim = PhydapDim(
        "lon", "degrees_east",
        len(basin_indices), "X",
        extracted["HYBAS_ID"][basin_indices],
    )

    runoff = PhydapVar(
        "runoff", var_units,
        extracted["reshaped"][:, :, basin_indices],
    )

    save_pd_to_nc(output_path, dims_list=[time_dim, lat_dim, lon_dim], var_data=runoff)


def subset_phydap_for_watershed(
    source_nc: Path | str,
    var_name: str,
    phydap_shp: Path | str,
    subbasins_shp: Path | str,
    output_nc: Path | str,
    output_hybas_map_csv: Path | str,
    *,
    var_units: str = "mm/h",
    lat_value: float = 49.43,
) -> pd.DataFrame:
    """End-to-end: shapefile intersection → NC subset → hybas_map CSV.

    Replaces the inline notebook code that wired sections 3.1–3.3 together.
    Returns the ``hybas_map`` DataFrame (also written to *output_hybas_map_csv*
    for downstream GridWeights generation).
    """
    phydap = gpd.read_file(str(phydap_shp))
    subbasins = gpd.read_file(str(subbasins_shp))

    target_hybas = find_target_hybas_ids(phydap, subbasins)

    with PhydapNC(source_nc, var_name=var_name) as nc:
        available_hybas = nc.file.variables["HYBAS_ID"][:]

    basin_indices = find_basin_indices(available_hybas, target_hybas)
    if not basin_indices:
        raise ValueError(
            f"No PHyDAP basins from the watershed shapefile were found in "
            f"the source NC {source_nc}."
        )

    subset_phydap_nc(
        source_nc, var_name, basin_indices, output_nc,
        var_units=var_units, lat_value=lat_value,
    )

    selected_hybas = np.asarray(available_hybas)[basin_indices]
    hybas_map = build_hybas_grid_map(selected_hybas)
    hybas_map.to_csv(output_hybas_map_csv, index=False)
    logger.info("Wrote hybas_map → %s (%d basins)", output_hybas_map_csv, len(hybas_map))

    return hybas_map
