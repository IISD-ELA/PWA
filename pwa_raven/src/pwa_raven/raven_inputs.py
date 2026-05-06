"""Raven input file generation pipeline.

Replaces ``PWA/_notebooks/2_raven_input_gen.ipynb`` (the production
sections — diagnostic prints/plots stay in the notebook). This is
"Step 2" of the wider PWA pipeline (after NetCDF processing).

End-to-end flow (matches notebook §2.2 → §3 → aspect-ratio post-step):
  1. Load + filter subbasins shapefile (drop non-contributing lake catchments).
  2. Compute time-of-concentration / time-to-peak; sanitize per-basin lists;
     identify watershed outlet.
  3. Write ``<watershed>_WSC_outlet.txt`` for the calibration setup.
  4. Resolve model window as intersect of (user range, NetCDF range, WSC range).
  5. Generate the WSC ``.rvt`` (clip, gap-detect, format).
  6. Write ``.rvi``, ``.rvc``, ``.rvp``, model ``.rvt``, ``.rvh``,
     and ``channel_properties.rvp``.
  7. Optionally (default on): generate calibration templates
     (``.rvh.tpl``, ``.rvp.tpl``, ``channel_properties.rvp.tpl``)
     and extract ``<watershed>_HRU_areas.csv`` + ``<watershed>_tp_tc.csv``.
  8. Optionally (default on): compute basin aspect ratios →
     ``aspect_ratios.csv``.

Usage::

    from pwa_raven.raven_inputs import RavenInputsConfig, run_raven_inputs

    config = RavenInputsConfig.from_yaml("raven_inputs.yml")
    result = run_raven_inputs(config)
    print(result.rvi)            # .rvi path
    print(result.wsc_rvt)        # WSC<station>.rvt path

The names ``Step2Config`` / ``run_step2`` are also exported (via the
``pwa_raven.step2`` alias module) so existing scripts keep working.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RavenInputsConfig:
    """Configuration for the Raven input file generation pipeline.

    Required fields
    ---------------
    watershed_name
        Used for output filenames + log messages.
    output_dir
        Root output directory. The pipeline writes outputs to
        ``<output_dir>/Raven/Processed/`` (with ``templates/`` and
        ``input/`` subfolders).
    subbasins_shapefile
        Watershed depression-depths shapefile (Step 0 output, with
        ``BasArea``, ``BkfDepth``, ``BkfWidth``, ``RivLength``,
        ``RivSlope``, ``MeanElev``, ``BasAspect``, ``BasSlope``,
        ``Has_POI``, ``Lake_Cat``, ``DowSubId``, ``Q_Mean``,
        ``Deps_Depth``, ``centroid_x``, ``centroid_y``, ``DrainArea``,
        ``FloodP_n``, ``Ch_n`` columns).
    phydap_nc
        The Step 1 output ``_adj.nc`` (time-shifted PHyDAP). The
        ``.rvt`` references this filename and the runner reads its
        time-axis range.
    wsc_metadata_csv, wsc_daily_csv
        WSC streamgauge metadata + daily-discharge CSVs.

    Optional fields
    ---------------
    curve_number
        NRCS TR-55 curve number for time-of-concentration (default 63,
        the Manning-watershed value from the notebook).
    user_start, user_end
        User-requested simulation window. Resolved with NC + WSC ranges
        via :func:`pwa_raven.raven.wsc_rvt.resolve_model_window`.
    avg_annual_runoff_mm
        Goes into the ``.rvp`` ``:AvgAnnualRunoff`` line (default 75).
    initial_soil_storage_mm
        Goes into the ``.rvc`` (default 15).
    write_calibration_templates
        If True (default), generate ``.rvh.tpl`` / ``.rvp.tpl`` /
        ``channel_properties.rvp.tpl`` + ``HRU_areas.csv`` + ``tp_tc.csv``.
    write_aspect_ratios
        If True (default), compute per-basin aspect ratios and write
        ``aspect_ratios.csv`` (consumed by the SPOTPY calibration setup).
    forcing_var_name
        NetCDF variable name referenced by the ``.rvt`` GriddedForcing
        block (default ``"runoff"``).
    """

    watershed_name: str
    output_dir: Path
    subbasins_shapefile: Path
    phydap_nc: Path
    wsc_metadata_csv: Path
    wsc_daily_csv: Path
    curve_number: float = 63.0
    user_start: str = "1990-01-01 00:00:00"
    user_end: str = "2019-12-30 00:00:00"
    avg_annual_runoff_mm: float = 75.0
    initial_soil_storage_mm: float = 15.0
    write_calibration_templates: bool = True
    write_aspect_ratios: bool = True
    forcing_var_name: str = "runoff"

    def __post_init__(self) -> None:
        for f in (
            "output_dir", "subbasins_shapefile", "phydap_nc",
            "wsc_metadata_csv", "wsc_daily_csv",
        ):
            object.__setattr__(self, f, Path(getattr(self, f)))

    # ---- derived paths ----------------------------------------------------

    @property
    def raven_dir(self) -> Path:
        return self.output_dir / "Raven"

    @property
    def processed_dir(self) -> Path:
        return self.raven_dir / "Processed"

    @property
    def templates_dir(self) -> Path:
        return self.processed_dir / "templates"

    @property
    def input_dir(self) -> Path:
        return self.processed_dir / "input"

    @property
    def safe_name(self) -> str:
        return self.watershed_name.replace(" ", "")

    @property
    def rvi_path(self) -> Path:
        return self.processed_dir / f"{self.safe_name}.rvi"

    @property
    def rvc_path(self) -> Path:
        return self.processed_dir / f"{self.safe_name}.rvc"

    @property
    def rvp_path(self) -> Path:
        return self.processed_dir / f"{self.safe_name}.rvp"

    @property
    def rvh_path(self) -> Path:
        return self.processed_dir / f"{self.safe_name}.rvh"

    @property
    def model_rvt_path(self) -> Path:
        return self.processed_dir / f"{self.safe_name}.rvt"

    @property
    def channel_rvp_path(self) -> Path:
        return self.processed_dir / "channel_properties.rvp"

    # ---- input validation -------------------------------------------------

    def expected_input_files(self) -> list[Path]:
        return [
            self.subbasins_shapefile,
            self.phydap_nc,
            self.wsc_metadata_csv,
            self.wsc_daily_csv,
        ]

    def validate_inputs_exist(self) -> None:
        missing = [p for p in self.expected_input_files() if not p.is_file()]
        if missing:
            bullet_list = "\n  - ".join(str(p) for p in missing)
            raise FileNotFoundError(
                "Raven input generation cannot start; the following expected input files "
                f"are missing:\n  - {bullet_list}"
            )

    # ---- serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "watershed_name": self.watershed_name,
            "output_dir": str(self.output_dir),
            "subbasins_shapefile": str(self.subbasins_shapefile),
            "phydap_nc": str(self.phydap_nc),
            "wsc_metadata_csv": str(self.wsc_metadata_csv),
            "wsc_daily_csv": str(self.wsc_daily_csv),
            "curve_number": self.curve_number,
            "user_start": self.user_start,
            "user_end": self.user_end,
            "avg_annual_runoff_mm": self.avg_annual_runoff_mm,
            "initial_soil_storage_mm": self.initial_soil_storage_mm,
            "write_calibration_templates": self.write_calibration_templates,
            "write_aspect_ratios": self.write_aspect_ratios,
            "forcing_var_name": self.forcing_var_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RavenInputsConfig":
        required = (
            "watershed_name", "output_dir", "subbasins_shapefile",
            "phydap_nc", "wsc_metadata_csv", "wsc_daily_csv",
        )
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(
                f"RavenInputsConfig requires {required}; missing {missing!r}."
            )
        defaults = cls(**{k: data[k] for k in required})
        return cls(
            **{k: data[k] for k in required},
            curve_number=data.get("curve_number", defaults.curve_number),
            user_start=data.get("user_start", defaults.user_start),
            user_end=data.get("user_end", defaults.user_end),
            avg_annual_runoff_mm=data.get("avg_annual_runoff_mm", defaults.avg_annual_runoff_mm),
            initial_soil_storage_mm=data.get("initial_soil_storage_mm", defaults.initial_soil_storage_mm),
            write_calibration_templates=data.get(
                "write_calibration_templates", defaults.write_calibration_templates
            ),
            write_aspect_ratios=data.get(
                "write_aspect_ratios", defaults.write_aspect_ratios
            ),
            forcing_var_name=data.get("forcing_var_name", defaults.forcing_var_name),
        )

    def to_yaml(self, path: Path | str) -> Path:
        import yaml

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, default_flow_style=False)
        )
        return path

    @classmethod
    def from_yaml(cls, config_path: Path | str) -> "RavenInputsConfig":
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class RavenInputsResult:
    """Paths to every file run_raven_inputs produces."""
    rvi: Path
    rvc: Path
    rvp: Path
    rvh: Path
    model_rvt: Path
    channel_rvp: Path
    wsc_rvt: Path
    wsc_outlet_txt: Path
    rvh_template: Optional[Path] = None
    rvp_template: Optional[Path] = None
    channel_rvp_template: Optional[Path] = None
    hru_areas_csv: Optional[Path] = None
    tp_tc_csv: Optional[Path] = None
    aspect_ratios_csv: Optional[Path] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_nc_date_range(nc_path: Path) -> tuple[datetime, datetime]:
    """Read the first/last timestamp of a NetCDF time variable.

    Assumes ``time`` variable with units ``hours since 1900-01-01``
    (matches the Step 1 subset_phydap_nc output format).
    """
    from netCDF4 import Dataset, num2date

    with Dataset(str(nc_path), "r") as ds:
        time_var = ds.variables["time"]
        # cftime → datetime (allows comparison with stdlib datetime)
        first = num2date(time_var[0], time_var.units)
        last = num2date(time_var[-1], time_var.units)

    # cftime.DatetimeGregorian → datetime
    return (
        datetime(first.year, first.month, first.day, first.hour, first.minute, first.second),
        datetime(last.year, last.month, last.day, last.hour, last.minute, last.second),
    )


def _read_wsc_date_range(daily_csv: Path) -> tuple[datetime, datetime]:
    """Read the first/last Date in a WSC daily-discharge CSV (skipping
    the leading export-header row)."""
    import pandas as pd

    raw = pd.read_csv(str(daily_csv), skiprows=1)
    dates = pd.to_datetime(raw["Date"])
    return (dates.iloc[0].to_pydatetime(), dates.iloc[-1].to_pydatetime())


def _read_wsc_station_id(metadata_csv: Path) -> str:
    """Pull the station number out of the WSC metadata CSV."""
    import pandas as pd

    return str(pd.read_csv(str(metadata_csv))["Station Number"].iloc[0])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_raven_inputs(config: RavenInputsConfig) -> RavenInputsResult:
    """Run the full Raven input file generation pipeline.

    Outputs land in ``config.processed_dir`` (with ``templates/`` and
    ``input/`` subfolders). All directories are created if absent;
    existing files at the output paths are overwritten.
    """
    # Local imports — keep module-level deps light so importing the
    # config dataclass doesn't pay for geopandas + netCDF4.
    import geopandas as gpd

    from pwa_raven.raven.basin_prep import (
        compute_aspect_ratios,
        prepare_basin_attributes,
    )
    from pwa_raven.raven.calibration_templates import (
        extract_hru_areas,
        extract_subbasin_properties,
        generate_channel_rvp_template,
        generate_rvh_template,
        generate_rvp_template,
    )
    from pwa_raven.raven.rv_writers import (
        write_channel_rvp,
        write_model_rvt,
        write_rvc,
        write_rvh,
        write_rvi,
        write_rvp,
    )
    from pwa_raven.raven.wsc_rvt import generate_wsc_rvt, resolve_model_window

    logger.info("Starting Raven input generation for watershed '%s'", config.watershed_name)

    # 0. Fail fast on missing inputs.
    config.validate_inputs_exist()

    # 1. Create directory tree.
    config.processed_dir.mkdir(parents=True, exist_ok=True)
    config.input_dir.mkdir(parents=True, exist_ok=True)
    if config.write_calibration_templates:
        config.templates_dir.mkdir(parents=True, exist_ok=True)

    # 2. Load + prepare subbasin attributes.
    logger.info("Loading subbasins from %s", config.subbasins_shapefile)
    raw_gdf = gpd.read_file(str(config.subbasins_shapefile))
    prep = prepare_basin_attributes(raw_gdf, curve_number=config.curve_number)
    enriched = prep.gdf

    # 3. Write WSC outlet ID for calibration.
    wsc_outlet_txt = config.input_dir / f"{config.watershed_name}_WSC_outlet.txt"
    wsc_outlet_txt.write_text(str(prep.outlet.sub_id))
    logger.info("Wrote outlet sub_id=%d → %s", prep.outlet.sub_id, wsc_outlet_txt)

    # 4. Resolve model window (user × nc × wsc intersect).
    nc_dates = _read_nc_date_range(config.phydap_nc)
    wsc_dates = _read_wsc_date_range(config.wsc_daily_csv)
    model_start, model_end = resolve_model_window(
        user_start=config.user_start,
        user_end=config.user_end,
        nc_dates=nc_dates,
        wsc_dates=wsc_dates,
    )
    logger.info("Model window: %s → %s", model_start, model_end)

    # 5. Generate WSC RVT.
    station_id = _read_wsc_station_id(config.wsc_metadata_csv)
    wsc_rvt_path = config.processed_dir / f"WSC{station_id}.rvt"
    generate_wsc_rvt(
        wsc_metadata_csv=config.wsc_metadata_csv,
        wsc_daily_csv=config.wsc_daily_csv,
        output_path=wsc_rvt_path,
        model_start=model_start,
        model_end=model_end,
        outlet_sub_id=prep.outlet.sub_id,
        outlet_drainage_area_km2=prep.outlet.drainage_area_km2,
    )

    # 6. Write the .rvi/.rvc/.rvp/.rvt/.rvh/channel_properties.rvp.
    rvi = write_rvi(
        config.processed_dir,
        watershed_name=config.watershed_name,
        model_start=model_start,
        model_end=model_end,
    )
    rvc = write_rvc(
        config.processed_dir,
        watershed_name=config.watershed_name,
        initial_soil_storage_mm=config.initial_soil_storage_mm,
    )
    rvp = write_rvp(
        config.processed_dir,
        watershed_name=config.watershed_name,
        sub_ids=prep.sub_ids,
        deps_depths=list(enriched["Deps_Depth"]),
        avg_annual_runoff=config.avg_annual_runoff_mm,
    )
    model_rvt = write_model_rvt(
        config.processed_dir,
        watershed_name=config.watershed_name,
        phydap_filename=config.phydap_nc.name,
        wsc_station_id=station_id,
        forcing_var_name=config.forcing_var_name,
    )
    rvh = write_rvh(
        config.processed_dir,
        watershed_name=config.watershed_name,
        sub_ids=prep.sub_ids,
        dow_sub_ids=[int(x) for x in enriched["DowSubId"]],
        riv_lengths_mod=prep.riv_lengths_mod,
        has_gauge=[int(x) for x in enriched["Has_POI"]],
        q_ref=list(enriched["Q_Mean"]),
        basin_area_km2=prep.basin_area_km2,
        elevation=list(enriched["MeanElev"]),
        latitude=list(enriched["centroid_y"]),
        longitude=list(enriched["centroid_x"]),
        slope=list(enriched["BasSlope"]),
        aspect=list(enriched["BasAspect"]),
        time_of_conc=list(enriched["time_of_conc"]),
        time_to_peak=list(enriched["time_to_peak"]),
    )
    channel_rvp = write_channel_rvp(
        config.processed_dir,
        watershed_name=config.watershed_name,
        sub_ids=prep.sub_ids,
        basin_area_km2=prep.basin_area_km2,
        riv_lengths_mod_n=prep.riv_lengths_mod_n,
        elevation=list(enriched["MeanElev"]),
        bkf_widths=list(enriched["BkfWidth"]),
        bkf_depths=prep.bkf_depths,
        riv_slopes=prep.riv_slopes,
        floodplain_n=prep.floodplain_n,
        channel_n=prep.channel_n,
    )

    # 7. Optional: calibration templates + auxiliary CSVs.
    rvh_template = rvp_template = channel_rvp_template = None
    hru_areas_csv = tp_tc_csv = None
    if config.write_calibration_templates:
        rvh_template = generate_rvh_template(
            real_rvh_path=rvh,
            output_path=config.templates_dir / f"{config.safe_name}.rvh.tpl",
        )
        rvp_template = generate_rvp_template(
            output_path=config.templates_dir / f"{config.safe_name}.rvp.tpl",
            watershed_name=config.watershed_name,
            sub_ids=prep.sub_ids,
            channel_props_filename="channel_properties",
        )
        channel_rvp_template = generate_channel_rvp_template(
            real_rvp_path=channel_rvp,
            output_path=config.templates_dir / "channel_properties.rvp.tpl",
        )
        hru_areas_csv = extract_hru_areas(
            rvh_path=rvh,
            output_csv=config.input_dir / f"{config.watershed_name}_HRU_areas.csv",
        )
        tp_tc_csv = extract_subbasin_properties(
            rvh_path=rvh,
            output_csv=config.input_dir / f"{config.watershed_name}_tp_tc.csv",
        )

    # 8. Optional: aspect ratios.
    aspect_ratios_csv = None
    if config.write_aspect_ratios:
        aspect_ratios_csv = config.input_dir / "aspect_ratios.csv"
        # Aspect ratios are computed on the FULL shapefile (including
        # filtered-out lake catchments) — the legacy notebook reads the
        # source shapefile a second time after filtering.
        compute_aspect_ratios(raw_gdf).to_csv(aspect_ratios_csv, index=False)
        logger.info("Wrote aspect ratios → %s", aspect_ratios_csv)

    logger.info("Raven input generation complete. Outputs in %s", config.processed_dir)
    return RavenInputsResult(
        rvi=rvi,
        rvc=rvc,
        rvp=rvp,
        rvh=rvh,
        model_rvt=model_rvt,
        channel_rvp=channel_rvp,
        wsc_rvt=wsc_rvt_path,
        wsc_outlet_txt=wsc_outlet_txt,
        rvh_template=rvh_template,
        rvp_template=rvp_template,
        channel_rvp_template=channel_rvp_template,
        hru_areas_csv=hru_areas_csv,
        tp_tc_csv=tp_tc_csv,
        aspect_ratios_csv=aspect_ratios_csv,
    )
