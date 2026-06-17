"""I/O subpackage: NetCDF, shapefile, and PHyDAP subsetting helpers."""

from pwa_raven.io.netcdf import (
    PhydapDim,
    PhydapNC,
    PhydapVar,
    save_pd_to_nc,
    time_offset,
)
from pwa_raven.io.phydap_subset import (
    build_hybas_grid_map,
    find_basin_indices,
    find_target_hybas_ids,
    subset_phydap_for_watershed,
    subset_phydap_nc,
)

__all__ = [
    "PhydapDim",
    "PhydapNC",
    "PhydapVar",
    "build_hybas_grid_map",
    "find_basin_indices",
    "find_target_hybas_ids",
    "save_pd_to_nc",
    "subset_phydap_for_watershed",
    "subset_phydap_nc",
    "time_offset",
]
