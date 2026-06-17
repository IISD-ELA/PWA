"""NetCDF processing pipeline: PHyDAP subset + GridWeights generation.

Replaces ``PWA/_notebooks/1_nc_processing.ipynb`` (the production
sections — diagnostic plots stay in the notebook). This is "Step 1"
of the wider PWA pipeline (after hydro-conditioning, before Raven
input generation).

End-to-end flow:
  1. Spatial-join the PHyDAP polygon grid with the watershed
     subbasins, identifying the HYBAS_IDs that overlap.
  2. Subset the raw PHyDAP NetCDF to those basins; write
     ``<output_dir>/<datacat>/Processed/<output_nc_name>``.
  3. Write the auxiliary ``hybas_map.csv`` for downstream
     GridWeights generation.
  4. Build the spatial mapping (subbasin centroids → PHyDAP grid
     cells, with nearest-neighbour fallback for centroids outside
     PHyDAP coverage) and write ``GridWeights.txt``.
  5. Apply the time offset to produce the ``_adj.nc`` that the
     Raven input generation step and the calibration consume.

Usage::

    from pwa_raven.nc_processing import NcProcessingConfig, run_nc_processing

    config = NcProcessingConfig.from_yaml("nc_processing.yml")
    result = run_nc_processing(config)
    print(result.subset_nc)         # subsetted NetCDF
    print(result.adjusted_nc)       # time-shifted NetCDF
    print(result.grid_weights)      # GridWeights.txt

The names ``Step1Config`` / ``run_step1`` are also exported (via the
``pwa_raven.step1`` alias module) so existing scripts keep working.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


_VALID_DATA_CATEGORIES = ("Runoff", "Snowmelt", "Rainfall")


@dataclass(frozen=True)
class NcProcessingConfig:
    """Configuration for the NetCDF processing pipeline (subset + GridWeights).

    Required fields
    ---------------
    watershed_name
        Used for output filenames + log messages.
    output_dir
        Root output directory. The pipeline writes outputs to
        ``<output_dir>/<data_category>/Processed/``.
    phydap_nc
        Path to the raw PHyDAP NetCDF.
    phydap_shapefile
        Path to the PHyDAP grid polygon shapefile.
    subbasins_shapefile
        Path to the watershed subbasins shapefile (typically the
        depression-depths output from Step 0).

    Optional fields
    ---------------
    data_category
        ``"Runoff"`` (default), ``"Snowmelt"``, or ``"Rainfall"``.
        Determines the output subdirectory name and the GridWeights
        watershed-name comment line.
    nc_variable
        Variable name to extract from the PHyDAP NetCDF (default
        ``"cropped_runoff"``, the RDRS21-derived variable name).
    nc_var_units
        Units string for the new variable in the subsetted NetCDF
        (default ``"mm/h"``).
    output_nc_name
        Filename for the subsetted NetCDF. If ``None`` (default),
        derived as ``f"{watershed_name}_{data_category.lower()}.nc"``.
    time_offset_hours
        Hours to shift the time axis for the ``_adj.nc`` output
        (default 10, matches the notebook's hardcoded value).
    lat_value
        Synthetic latitude value for the false ``lat`` dimension that
        Raven needs (default 49.43, the notebook's hardcoded value
        for the Manitoba prairie watersheds).
    """

    watershed_name: str
    output_dir: Path
    phydap_nc: Path
    phydap_shapefile: Path
    subbasins_shapefile: Path
    data_category: str = "Runoff"
    nc_variable: str = "cropped_runoff"
    nc_var_units: str = "mm/h"
    output_nc_name: Optional[str] = None
    time_offset_hours: int = 10
    lat_value: float = 49.43

    def __post_init__(self) -> None:
        # Normalize paths
        for field in ("output_dir", "phydap_nc", "phydap_shapefile", "subbasins_shapefile"):
            object.__setattr__(self, field, Path(getattr(self, field)))

        # Validate data category
        if self.data_category not in _VALID_DATA_CATEGORIES:
            raise ValueError(
                f"Unsupported data_category {self.data_category!r}. "
                f"Choose from {_VALID_DATA_CATEGORIES}."
            )

    # ---- derived paths ----------------------------------------------------

    @property
    def category_dir(self) -> Path:
        return self.output_dir / self.data_category

    @property
    def processed_dir(self) -> Path:
        return self.category_dir / "Processed"

    @property
    def subset_nc_path(self) -> Path:
        name = self.output_nc_name or f"{self.watershed_name}_{self.data_category.lower()}.nc"
        return self.processed_dir / name

    @property
    def adjusted_nc_path(self) -> Path:
        stem = self.subset_nc_path.stem
        return self.processed_dir / f"{stem}_adj.nc"

    @property
    def hybas_map_path(self) -> Path:
        return self.processed_dir / "hybas_map.csv"

    @property
    def grid_weights_path(self) -> Path:
        return self.processed_dir / "GridWeights.txt"

    # ---- input validation -------------------------------------------------

    def expected_input_files(self) -> list[Path]:
        """Files run_nc_processing reads — use to fail fast."""
        return [self.phydap_nc, self.phydap_shapefile, self.subbasins_shapefile]

    def validate_inputs_exist(self) -> None:
        """Fail fast if expected input files are missing.

        Raises ``FileNotFoundError`` listing every missing path in one
        message. Sidecars (.dbf/.shx/.prj/.cpg for shapefiles) aren't
        enumerated; geopandas raises clear errors when those are
        missing alongside a present .shp.
        """
        missing = [p for p in self.expected_input_files() if not p.is_file()]
        if missing:
            bullet_list = "\n  - ".join(str(p) for p in missing)
            raise FileNotFoundError(
                "NetCDF processing cannot start; the following expected input files "
                f"are missing:\n  - {bullet_list}"
            )

    # ---- serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize back to the dict shape :meth:`from_dict` consumes."""
        return {
            "watershed_name": self.watershed_name,
            "output_dir": str(self.output_dir),
            "phydap_nc": str(self.phydap_nc),
            "phydap_shapefile": str(self.phydap_shapefile),
            "subbasins_shapefile": str(self.subbasins_shapefile),
            "data_category": self.data_category,
            "nc_variable": self.nc_variable,
            "nc_var_units": self.nc_var_units,
            "output_nc_name": self.output_nc_name,
            "time_offset_hours": self.time_offset_hours,
            "lat_value": self.lat_value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NcProcessingConfig":
        """Build from a dict. Required keys: watershed_name, output_dir,
        phydap_nc, phydap_shapefile, subbasins_shapefile."""
        required = (
            "watershed_name", "output_dir", "phydap_nc",
            "phydap_shapefile", "subbasins_shapefile",
        )
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(
                f"NcProcessingConfig requires {required}; missing {missing!r}."
            )

        defaults = cls(**{k: data[k] for k in required})
        return cls(
            **{k: data[k] for k in required},
            data_category=data.get("data_category", defaults.data_category),
            nc_variable=data.get("nc_variable", defaults.nc_variable),
            nc_var_units=data.get("nc_var_units", defaults.nc_var_units),
            output_nc_name=data.get("output_nc_name", defaults.output_nc_name),
            time_offset_hours=data.get("time_offset_hours", defaults.time_offset_hours),
            lat_value=data.get("lat_value", defaults.lat_value),
        )

    def to_yaml(self, path: Path | str) -> Path:
        """Write this config to *path* as YAML."""
        import yaml

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, default_flow_style=False)
        )
        return path

    @classmethod
    def from_yaml(cls, config_path: Path | str) -> "NcProcessingConfig":
        """Load configuration from a YAML file."""
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Result + runner
# ---------------------------------------------------------------------------


@dataclass
class NcProcessingResult:
    """Paths to the key outputs of an NC-processing run."""
    subset_nc: Path
    adjusted_nc: Path
    hybas_map: Path
    grid_weights: Path


def run_nc_processing(config: NcProcessingConfig) -> NcProcessingResult:
    """Run the full NetCDF processing pipeline (PHyDAP subset + GridWeights + time offset).

    Outputs land in ``config.processed_dir``. The directory is created
    if absent; existing files at the output paths are overwritten.
    """
    # Local imports keep module-level deps light for callers that just
    # want the dataclass.
    from pwa_raven.grid.weights import generate_grid_weights
    from pwa_raven.io.netcdf import time_offset
    from pwa_raven.io.phydap_subset import subset_phydap_for_watershed

    logger.info(
        "Starting NetCDF processing for watershed '%s' (data_category=%s)",
        config.watershed_name, config.data_category,
    )

    # 0. Fail fast on missing inputs.
    config.validate_inputs_exist()

    # 1. Create output directory tree.
    config.processed_dir.mkdir(parents=True, exist_ok=True)

    # 2. Subset PHyDAP NetCDF + write hybas_map.csv.
    logger.info("Subsetting PHyDAP NetCDF → %s", config.subset_nc_path)
    subset_phydap_for_watershed(
        source_nc=config.phydap_nc,
        var_name=config.nc_variable,
        phydap_shp=config.phydap_shapefile,
        subbasins_shp=config.subbasins_shapefile,
        output_nc=config.subset_nc_path,
        output_hybas_map_csv=config.hybas_map_path,
        var_units=config.nc_var_units,
        lat_value=config.lat_value,
    )

    # 3. Generate GridWeights.txt.
    logger.info("Generating GridWeights → %s", config.grid_weights_path)
    generate_grid_weights(
        subbasins_shp=config.subbasins_shapefile,
        phydap_shp=config.phydap_shapefile,
        hybas_map_csv=config.hybas_map_path,
        watershed_name=config.watershed_name,
        output_path=config.grid_weights_path,
    )

    # 4. Apply time offset → _adj.nc.
    logger.info(
        "Applying %d-hour time offset → %s",
        config.time_offset_hours, config.adjusted_nc_path,
    )
    time_offset(
        old_path=config.subset_nc_path,
        new_path=config.adjusted_nc_path,
        offset=float(config.time_offset_hours),
    )

    logger.info(
        "NetCDF processing complete. Outputs in %s", config.processed_dir,
    )
    return NcProcessingResult(
        subset_nc=config.subset_nc_path,
        adjusted_nc=config.adjusted_nc_path,
        hybas_map=config.hybas_map_path,
        grid_weights=config.grid_weights_path,
    )
