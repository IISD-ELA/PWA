"""GridWeights.txt generation for Raven hydrologic model input.

Extracted from ``PWA/_notebooks/1_nc_processing.ipynb`` § 4.

Maps watershed sub-basins to PHyDAP forcing-grid cells (1:1 weights, since each
sub-basin's representative point falls inside exactly one PHyDAP polygon — or is
assigned to the nearest one when it falls outside the PHyDAP coverage area).

Bug fix (BUG-019): the original notebook only merged ``hybas_map`` into
``mapping_df`` inside the ``if len(missing) > 0:`` branch. When every
sub-basin centroid landed inside a PHyDAP polygon, the resulting frame was
missing the ``grid_idx`` column and the file writer raised KeyError. We now
merge unconditionally.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


def compute_subbasin_to_grid_mapping(
    subbasins: gpd.GeoDataFrame,
    phydap: gpd.GeoDataFrame,
    hybas_map: pd.DataFrame,
    *,
    subbasin_id_col: str = "SubId",
    hybas_id_col: str = "HYBAS_ID",
) -> pd.DataFrame:
    """Map watershed sub-basins to PHyDAP forcing-grid cells.

    For each sub-basin, takes a representative interior point and finds the
    PHyDAP polygon containing it. Sub-basins whose centroid falls outside any
    PHyDAP polygon are assigned to the nearest PHyDAP polygon (by centroid
    distance), and a new ``grid_idx`` is appended to ``hybas_map`` for any
    PHyDAP cells not previously seen.

    Parameters
    ----------
    subbasins
        Sub-basin polygons (typically the depression-depths shapefile from
        Step 0). Must contain a ``SubId`` column.
    phydap
        PHyDAP forcing-grid polygons. Must contain a ``HYBAS_ID`` column.
    hybas_map
        DataFrame with columns ``hybas_id`` (int) and ``grid_idx`` (int),
        produced earlier in the NetCDF processing step. Will be extended
        in-memory if any sub-basins map to PHyDAP cells not already indexed.

    Returns
    -------
    pandas.DataFrame
        Columns: ``SubId``, ``HYBAS_ID``, ``grid_idx``. One row per sub-basin.
    """
    if subbasins.crs != phydap.crs:
        logger.info("Reprojecting sub-basins from %s to %s", subbasins.crs, phydap.crs)
        subbasins = subbasins.to_crs(phydap.crs)

    phydap = phydap[phydap.geometry.is_valid & ~phydap.geometry.is_empty].copy()

    centroids = gpd.GeoDataFrame(
        subbasins[[subbasin_id_col]].copy(),
        geometry=subbasins.geometry.representative_point(),
        crs=subbasins.crs,
    )

    joined = gpd.sjoin(centroids, phydap, how="left", predicate="within")
    mapping = joined[[subbasin_id_col, hybas_id_col]].copy()

    missing_mask = mapping[hybas_id_col].isna()
    n_missing = int(missing_mask.sum())
    logger.info(
        "Sub-basin centroids inside PHyDAP: %d, outside: %d",
        len(mapping) - n_missing, n_missing,
    )

    if n_missing > 0:
        unmatched_ids = mapping.loc[missing_mask, subbasin_id_col]
        unmatched = centroids[centroids[subbasin_id_col].isin(unmatched_ids)]
        nearest = _assign_nearest_phydap(unmatched, phydap, subbasin_id_col, hybas_id_col)
        mapping = pd.concat(
            [mapping[~missing_mask], nearest],
            ignore_index=True,
        )

    mapping[hybas_id_col] = mapping[hybas_id_col].astype(int)
    hybas_map = hybas_map[["hybas_id", "grid_idx"]].copy()
    hybas_map["hybas_id"] = hybas_map["hybas_id"].astype(int)

    new_hybas = set(mapping[hybas_id_col]) - set(hybas_map["hybas_id"])
    if new_hybas:
        next_idx = int(hybas_map["grid_idx"].max()) + 1
        appended = pd.DataFrame({
            "hybas_id": sorted(new_hybas),
            "grid_idx": range(next_idx, next_idx + len(new_hybas)),
        })
        hybas_map = pd.concat([hybas_map, appended], ignore_index=True)
        logger.info("Appended %d synthetic grid_idx entries for nearest-match HYBAS_IDs", len(new_hybas))

    mapping = mapping.merge(
        hybas_map,
        left_on=hybas_id_col,
        right_on="hybas_id",
        how="left",
    ).drop(columns=["hybas_id"])

    duplicate_subids = mapping[subbasin_id_col].duplicated(keep=False)
    if duplicate_subids.any():
        logger.warning(
            "Duplicate %s entries found after mapping: %d rows",
            subbasin_id_col, int(duplicate_subids.sum()),
        )

    return mapping[[subbasin_id_col, hybas_id_col, "grid_idx"]]


def _assign_nearest_phydap(
    unmatched_centroids: gpd.GeoDataFrame,
    phydap: gpd.GeoDataFrame,
    subbasin_id_col: str,
    hybas_id_col: str,
) -> pd.DataFrame:
    """For each unmatched centroid, return the HYBAS_ID of the nearest PHyDAP polygon."""
    phydap_centroids = phydap.copy()
    phydap_centroids = phydap_centroids.set_geometry(phydap_centroids.geometry.centroid)
    phydap_centroids = phydap_centroids[phydap_centroids.geometry.notna()]

    matches = []
    for _, row in unmatched_centroids.iterrows():
        distances = phydap_centroids.geometry.distance(row.geometry)
        nearest_hybas = phydap_centroids.loc[distances.idxmin(), hybas_id_col]
        matches.append({subbasin_id_col: row[subbasin_id_col], hybas_id_col: nearest_hybas})

    return pd.DataFrame(matches)


def write_grid_weights_file(
    mapping: pd.DataFrame,
    n_grid_cells: int,
    watershed_name: str,
    output_path: Path | str,
    *,
    subbasin_id_col: str = "SubId",
    grid_idx_col: str = "grid_idx",
    weight: float = 1.0,
) -> Path:
    """Write the Raven ``GridWeights.txt`` file.

    Format reference: Raven manual § 6.6 (Grid Weights).

    Parameters
    ----------
    mapping
        DataFrame with at least ``SubId`` and ``grid_idx`` columns.
    n_grid_cells
        Total number of grid cells in the source PHyDAP forcing file. Note:
        this is the *full* grid extent, not just the cells referenced by
        ``mapping`` — Raven needs to allocate buffers for the whole grid.
    watershed_name
        Used in the header comment.
    output_path
        Destination path for the GridWeights.txt file.

    Returns
    -------
    pathlib.Path
        The path that was written.
    """
    output_path = Path(output_path)
    n_hrus = len(mapping)

    lines = [
        "# ----------------------------------------------",
        "# Raven Input file",
        f"# {watershed_name}",
        "# ----------------------------------------------",
        "",
        ":GridWeights",
        "   #",
        "   # [# HRUs]",
        f"   :NumberHRUs       {n_hrus}",
        f"   :NumberGridCells  {n_grid_cells}",
        "   #",
        "   # [HRU ID] [Cell #] [w_kl]",
    ]
    for _, row in mapping.iterrows():
        lines.append(
            f"  {int(row[subbasin_id_col]):>10} {int(row[grid_idx_col]):>10}{weight:>10.3f}"
        )
    lines.append(":EndGridWeights")

    output_path.write_text("\n".join(lines))
    logger.info("Wrote GridWeights.txt with %d HRUs → %s", n_hrus, output_path)
    return output_path


def generate_grid_weights(
    subbasins_shp: Path | str,
    phydap_shp: Path | str,
    hybas_map_csv: Path | str,
    watershed_name: str,
    output_path: Path | str,
    *,
    n_grid_cells: int | None = None,
) -> Path:
    """End-to-end: load shapefiles, compute mapping, write GridWeights.txt.

    Convenience wrapper combining :func:`compute_subbasin_to_grid_mapping` and
    :func:`write_grid_weights_file` for use from a notebook or runner script.

    If *n_grid_cells* is None, defaults to ``len(phydap)``.
    """
    subbasins = gpd.read_file(str(subbasins_shp))
    phydap = gpd.read_file(str(phydap_shp))
    hybas_map = pd.read_csv(str(hybas_map_csv))

    mapping = compute_subbasin_to_grid_mapping(subbasins, phydap, hybas_map)

    if n_grid_cells is None:
        n_grid_cells = len(phydap)

    return write_grid_weights_file(mapping, n_grid_cells, watershed_name, output_path)
