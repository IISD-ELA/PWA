"""Raven model input-file writers (RVI, RVC, RVP, RVH, RVT, channel RVP).

Extracted from ``PWA/_notebooks/2_raven_input_gen.ipynb`` § 2.4–2.9.

Each writer is a pure function: takes a destination path + the inputs it
needs as keyword arguments, writes the file, returns the path. Templates
are inlined as f-strings (no Jinja dependency) since the format is fixed
and the placeholders are simple.

Behavioural improvement over the notebook: cell 49 wrote the *last*
channel-profile survey point's Y coordinate as
``elev[i] + bkfdepth_mod[i] + bkfdepth_mod[0] / 2`` — a hardcoded
``[0]`` index where ``[i]`` was intended, so every channel profile
after subbasin 0 had the wrong terminal survey-point elevation. The
writer now uses ``bkfdepth_mod[i]`` consistently with the first
survey point.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _sanitize_watershed_name(name: str) -> str:
    """Strip spaces — Raven file basenames cannot contain whitespace."""
    return name.replace(" ", "")


# ---------------------------------------------------------------------------
# 2.4 — .rvi (model run configuration)
# ---------------------------------------------------------------------------

def write_rvi(
    output_dir: Path | str,
    *,
    watershed_name: str,
    model_start: datetime,
    model_end: datetime,
) -> Path:
    """Write the ``.rvi`` Raven model-run-configuration file.

    Most of the body is the static prairie-routing template (PRECIP_RAVEN,
    ABST_FILL, RAVEN_DEFAULT, SEEP_LINEAR). Only the watershed name and
    simulation window are parameterised.
    """
    output_dir = Path(output_dir)
    out = output_dir / f"{_sanitize_watershed_name(watershed_name)}.rvi"

    start_str = model_start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = model_end.strftime("%Y-%m-%d %H:%M:%S")

    out.write_text(f"""\
# ----------------------------------------------
# Raven Input file
# {watershed_name}
# ----------------------------------------------
:StartDate             {start_str :<30} # Model run start time, format in yyyy-mm-dd hh:mm:ss
:EndDate               {end_str :<30} # Model run end time, format in yyyy-mm-dd hh:mm:ss
:Method                ORDERED_SERIES                # Numerical method used for simulation
:TimeStep              03:00:00                      # 3-hour timestep matches the upstream default; halves simulation cost vs hourly without meaningfully degrading daily-flow calibration. Use hh:mm:ss format (e.g., 24:00:00 = 1 day).
:RunName               {watershed_name:<30}# The name of model run. It will be added as a prefix of model output files.

:CatchmentRoute        ROUTE_TRI_CONVOLUTION         # Catchment routing method, used to convey water from the catchment tributaries and rivulets to the subbasin outlets. DEFAULT ROUTE_DUMP, which instantly 'dumps' all water in the subbasin stream reach.
:Routing               ROUTE_DIFFUSIVE_WAVE          # Channel routing method which is used to transport water from upstream to downstream within the main subbasin channels. DEFAULT ROUTE_DIFFUSIVE_WAVE, which analytically solves the diffusive wave equation along the reach using a constant reference celerity.
:PrecipIceptFract      PRECIP_ICEPT_NONE             # Estimation of the precipitation interception fraction. In this routing model, stream input(s) are "pretending" to be precipitation going into Raven, thus using DEFAULT PRECIP_ICEPT_NONE to indicate no interception processes are adopted.
:PotentialMeltMethod   POTMELT_NONE                  # Estimation of the potential snow melt. In this routing model, snow melt processes are not relevant, thus using DEFAULT POTMELT_NONE method.
:SWRadiationMethod     SW_RAD_NONE                   # Estimation of shortwave incoming radiation. This is turned off for a routing-only model.
:SoilModel             SOIL_ONE_LAYER                # In this routing model, use DEFAULT SOIL_ONE_LAYER to define single soil layer structure.

:HydrologicProcesses
  :Precipitation     PRECIP_RAVEN            ATMOS_PRECIP     MULTIPLE          # Moves stream input(s) from ATMOS_PRECIP to PONDED_WATER storage (waiting for runoff). Use DEFAULT PRECIP_RAVEN method.
  :Abstraction       ABST_FILL               PONDED_WATER     DEPRESSION
  :Flush             RAVEN_DEFAULT           PONDED_WATER     SURFACE_WATER         # Moves water from PONDED_WATER to SURFACE_WATER (routed to outlet). Use DEFAULT RAVEN_DEFAULT method.
  :Seepage           SEEP_LINEAR             DEPRESSION       SOIL[0]
:EndHydrologicProcesses

# Defines the hydrograph performance metrics output by Raven. Either one or multiple is acceptable.
:EvaluationMetrics           NASH_SUTCLIFFE    PCT_BIAS    KLING_GUPTA
""")
    logger.info("Wrote RVI → %s", out)
    return out


# ---------------------------------------------------------------------------
# 2.5 — .rvc (initial conditions)
# ---------------------------------------------------------------------------

def write_rvc(
    output_dir: Path | str,
    *,
    watershed_name: str,
    initial_soil_storage_mm: float = 15.0,
) -> Path:
    """Write the ``.rvc`` Raven initial-conditions file.

    The prairie-routing model has a single uniform soil-storage initial
    condition; default 15 mm matches the notebook.
    """
    output_dir = Path(output_dir)
    out = output_dir / f"{_sanitize_watershed_name(watershed_name)}.rvc"
    out.write_text(f"""\
# ----------------------------------------------
# Raven Input file
# {watershed_name}
# ----------------------------------------------

:UniformInitialConditions SOIL[0] {initial_soil_storage_mm}            # Initial conditions for the groundwater storage, in mm. DEFAULT 15 mm.
""")
    logger.info("Wrote RVC → %s", out)
    return out


# ---------------------------------------------------------------------------
# 2.6 — .rvp (soil/veg/landuse classes)
# ---------------------------------------------------------------------------

def write_rvp(
    output_dir: Path | str,
    *,
    watershed_name: str,
    bin_labels: list[str | None],
    binned_deps: list[float],
    avg_annual_runoff: float = 75.0,
    default_dep_seep_k: float = 0.01,
    default_dep_max: float = 20.0,
) -> Path:
    """Write the ``.rvp`` soil/vegetation/land-use class definition file.

    Per-bin entries are written for the ``:LandUseClasses`` table (one
    class per unique bin label plus a ``Bin_NA`` sentinel), and one
    ``:LandUseParameterList`` row per input element (per subbasin in
    the source gdf — duplicate bin labels are allowed and Raven
    tolerates them as parameter-override redundancy, matching upstream
    ``ae706d6`` / ``e138d9d`` exactly).

    Parameters
    ----------
    bin_labels
        Bin label for each subbasin in source order. ``None`` and
        non-string values (NaN) are mapped to ``"Bin_NA"`` on write.
    binned_deps
        Binned depression depth for each subbasin in source order.
        NaN is written as ``0.0`` (Raven's no-depression value).
    """
    if len(bin_labels) != len(binned_deps):
        raise ValueError(
            f"bin_labels ({len(bin_labels)}) and binned_deps ({len(binned_deps)}) "
            f"must have the same length."
        )

    def _label(lbl: object) -> str:
        """Normalize labels: None, NaN, '' → 'Bin_NA'."""
        if lbl is None:
            return "Bin_NA"
        try:
            if pd.isna(lbl):  # type: ignore[arg-type]
                return "Bin_NA"
        except (TypeError, ValueError):
            pass
        return str(lbl) or "Bin_NA"

    def _depth(d: float) -> float:
        try:
            if pd.isna(d):
                return 0.0
        except (TypeError, ValueError):
            pass
        return float(d)

    # Unique bin labels (preserve first-occurrence order) — drives the
    # :LandUseClasses table. Bin_NA is appended unconditionally to
    # match upstream (the writer always reserves a class for NaN rows
    # even when no NaN rows are present in this run).
    unique_bins: list[str] = []
    seen: set[str] = set()
    for lbl in bin_labels:
        norm = _label(lbl)
        if norm == "Bin_NA":
            continue  # appended at the end regardless
        if norm not in seen:
            unique_bins.append(norm)
            seen.add(norm)
    unique_bins.append("Bin_NA")

    output_dir = Path(output_dir)
    out = output_dir / f"{_sanitize_watershed_name(watershed_name)}.rvp"

    parts: list[str] = [f"""\
# ----------------------------------------------
# Raven Input file
# {watershed_name}
# ----------------------------------------------

# Soil/Vegetation/Land use class definitions ------
:SoilClasses
  AQUIFER      # only one soil class used here
:EndSoilClasses

:SoilProfiles
  # name, number of layers, soil class, thickness [m]
  LandHRU_soil_profile,    1,    AQUIFER, 5
:EndSoilProfiles

# The vegetation and land use parameters unused in routing
:VegetationClasses
  :Attributes,                MAX_HT,       MAX_LAI,    MAX_LEAF_COND
  :Units,                       m,            none,       mm_per_s
  LandHRU_vege_class,          25,           5.0,          5.0
:EndVegetationClasses

:LandUseClasses
  :Attributes,        IMPERMEABLE_FRAC,         FOREST_COVERAGE
  :Units,                     fract,                    fract
  LandHRU_landuse_class,      0,                        1"""]

    for bin_lbl in unique_bins:
        parts.append(f"\n  {bin_lbl},              0,                        1")

    parts.append(f"""
:EndLandUseClasses

# Global Parameters-----------------------------
:AvgAnnualRunoff        {avg_annual_runoff}

:LandUseParameterList
  :Parameters     ,          DEP_SEEP_K,             DEP_MAX
  :Units          ,               1/d,                   mm
    [DEFAULT]     ,             {default_dep_seep_k},              {default_dep_max:.4f}""")

    for lbl, depth in zip(bin_labels, binned_deps):
        parts.append(
            f"\n {_label(lbl):<12},             {default_dep_seep_k},          {_depth(depth):.4f}"
        )

    parts.append("""
:EndLandUseClasses

# redirects to channel properties file
:RedirectToFile         channel_properties.rvp
""")

    out.write_text("".join(parts))
    logger.info(
        "Wrote RVP → %s (%d subbasins, %d unique bin labels)",
        out, len(bin_labels), len(unique_bins),
    )
    return out


# ---------------------------------------------------------------------------
# 2.7 — model .rvt (forcing pointers)
# ---------------------------------------------------------------------------

def write_model_rvt(
    output_dir: Path | str,
    *,
    watershed_name: str,
    phydap_filename: str,
    wsc_station_id: str,
    forcing_var_name: str = "runoff",
    grid_weights_filename: str = "GridWeights.txt",
    linear_transform: tuple[float, float] = (24.0, 0.0),
) -> Path:
    """Write the model-level ``.rvt`` file pointing at gridded forcing + WSC.

    Note that both ``StreamInputs`` (PRECIP) and ``Averagetemp`` (TEMP_AVE)
    GriddedForcing blocks reference the same ``runoff`` variable in the
    PHyDAP file. The notebook has it that way; preserving verbatim. (This
    is unusual and may warrant a Q-002 follow-up — see basin_prep.py for
    style — but it is what the existing pipeline produces.)
    """
    output_dir = Path(output_dir)
    out = output_dir / f"{_sanitize_watershed_name(watershed_name)}.rvt"
    a, b = linear_transform

    out.write_text(f"""\
# ----------------------------------------------
# Raven Input file
# {watershed_name}
# ----------------------------------------------

:GriddedForcing           StreamInputs
    :ForcingType          PRECIP
    :FileNameNC           input/{phydap_filename}
    :VarNameNC            {forcing_var_name}
    :DimNamesNC           lon lat time     # must be in the order of (x,y,t)
    :LinearTransform      {a}     {b}
    :RedirectToFile       input/{grid_weights_filename}
:EndGriddedForcing

# NOTE: the Linear Transform converts mm/1hr --> mm/d

:GriddedForcing           Averagetemp
    :ForcingType          TEMP_AVE
    :FileNameNC           input/{phydap_filename}
    :VarNameNC            {forcing_var_name}
    :DimNamesNC           lon lat time
    :RedirectToFile       input/{grid_weights_filename}
:EndGriddedForcing

# Observed Discharge Data-----------------------
:RedirectToFile           WSC{wsc_station_id}.rvt
""")
    logger.info("Wrote model RVT → %s", out)
    return out


# ---------------------------------------------------------------------------
# 2.8 — .rvh (subbasin + HRU + subbasin properties)
# ---------------------------------------------------------------------------

def write_rvh(
    output_dir: Path | str,
    *,
    watershed_name: str,
    sub_ids: list[int],
    dow_sub_ids: list[int],
    riv_lengths_mod: list,           # mixed list: floats or "ZERO-" strings
    has_gauge: list[int],
    q_ref: list[float],
    basin_area_km2: list[float],
    elevation: list[float],
    latitude: list[float],
    longitude: list[float],
    slope: list[float],
    aspect: list[float],
    time_of_conc: list[float],
    time_to_peak: list[float],
    bin_labels: list[str | None] | None = None,
) -> Path:
    """Write the ``.rvh`` SubBasin / HRU / SubBasinProperties file.

    When *bin_labels* is given, each HRU row's ``LAND_USE_CLASS`` is
    the row's bin label (mapped to ``Bin_NA`` for None/NaN). When
    omitted, every HRU defaults to ``LandHRU_landuse_class`` — kept
    for back-compat with callers that haven't migrated to binning yet.
    """
    n = len(sub_ids)
    for label, lst in [
        ("dow_sub_ids", dow_sub_ids), ("riv_lengths_mod", riv_lengths_mod),
        ("has_gauge", has_gauge), ("q_ref", q_ref),
        ("basin_area_km2", basin_area_km2), ("elevation", elevation),
        ("latitude", latitude), ("longitude", longitude),
        ("slope", slope), ("aspect", aspect),
        ("time_of_conc", time_of_conc), ("time_to_peak", time_to_peak),
    ]:
        if len(lst) != n:
            raise ValueError(
                f"All per-basin lists must have length {n} (sub_ids); "
                f"{label} has length {len(lst)}."
            )
    if bin_labels is not None and len(bin_labels) != n:
        raise ValueError(
            f"bin_labels must have length {n} (sub_ids); got {len(bin_labels)}."
        )

    output_dir = Path(output_dir)
    out = output_dir / f"{_sanitize_watershed_name(watershed_name)}.rvh"

    parts: list[str] = [f"""\
# ----------------------------------------------
# Raven Input file
# {watershed_name}
# ----------------------------------------------

## SubBasin List---------------------------------------------------------------------
# ID:            A positive long integer identifier unique to this subbasin.
# NAME:          A nickname for subbasin. DEFAULT string("sub_" + ID).
# DOWNSTREAM_ID: The ID of the subbasin that receives this subbasin's outflowing waters.
# PROFILE:       The representative channel profile code (defined in channel_properties.rvp).
# REACH_LENGTH:  The length of the primary reach channel in the basin (in km).
# GAUGED:        Flag to indicate whether hydrographs for this subbasin are output (1 = yes, 0 = no).
#                In this routing model, both subbasins with reservoirs and flow gauges are GAUGED = 1.

:SubBasins
  :Attributes     ID     NAME     DOWNSTREAM_ID     PROFILE     REACH_LENGTH     GAUGED     Q_REFERENCE
  :Units          none   none     none              none        km              none        m3/s
"""]

    for i in range(n):
        sub_id = sub_ids[i]
        reach_length = riv_lengths_mod[i]
        # reach_length may be the string "ZERO-" (sentinel) or a float
        parts.append(
            f"{sub_id:>10}  "
            f"{'sub' + str(sub_id):<15}  "
            f"{dow_sub_ids[i]:>10}  "
            f"{f'chn_{sub_id}':<15}  "
            f"{reach_length:>10}  "
            f"{has_gauge[i]:>10}   "
            f"{q_ref[i]:>5}\n"
        )

    parts.append(
        ":EndSubBasins\n\n"
        "## HRU List ---------------------------------------------------------------------\n"
        "# HRU ID:          A positive integer unique to this HRU. Note that more than one HRUs\n"
        "#                 may have the same subbasin ID, but HRU ID is unique.\n"
        "# AREA:            HRU area value, in km².\n"
        "# ELEVATION:       HRU mean elevation, in m.\n"
        "# LATITUDE:        Latitude of HRU centroid, in decimal degrees.\n"
        "# LONGITUDE:       Longitude of HRU centroid, in decimal degrees.\n"
        "# BASIN_ID:        ID of the subbasin in which the HRU is located.\n"
        "# LAND_USE_CLASS:  Land use class defined in .rvp file. DEFAULT LandHRU_landuse_class.\n"
        "# VEG_CLASS:       Vegetation class defined in .rvp file. DEFAULT LandHRU_vege_class.\n"
        "# SOIL_PROFILE:    Soil profile defined in .rvp file. DEFAULT LandHRU_soil_profile.\n"
        "# AQUIFER_PROFILE: Aquifer class. DEFAULT [NONE] in this routing model.\n"
        "# TERRAIN_CLASS:   Terrain class. DEFAULT [NONE] in this routing model.\n"
        "# SLOPE:           HRU mean slope, in degrees.\n"
        "# ASPECT:          HRU mean aspect, in degrees. North: 0°, West: 90°, South: 180°, East: 270°.\n"
        "#\n"
        ":HRUs\n"
        "  :Attributes     AREA     ELEVATION     LATITUDE     LONGITUDE     BASIN_ID     LAND_USE_CLASS         "
        "VEG_CLASS          SOIL_PROFILE     AQUIFER_PROFILE     TERRAIN_CLASS     SLOPE     ASPECT\n"
        "  :Units          km2      m             deg          deg           none         none                   "
        "none                none             none               none              deg       degN\n"
    )

    def _hru_land_use(i: int) -> str:
        """Per-row LAND_USE_CLASS: row's bin label when binning is in
        play, otherwise the legacy single-class default."""
        if bin_labels is None:
            return "LandHRU_landuse_class"
        lbl = bin_labels[i]
        if lbl is None:
            return "Bin_NA"
        try:
            if pd.isna(lbl):  # type: ignore[arg-type]
                return "Bin_NA"
        except (TypeError, ValueError):
            pass
        return str(lbl) or "Bin_NA"

    for i in range(n):
        sub_id = sub_ids[i]
        parts.append(
            f"{sub_id:>15}"
            f"{round(basin_area_km2[i], 4):>10}"
            f"{round(elevation[i], 2):>10}"
            f"{round(latitude[i], 6):>15}"
            f"{round(longitude[i], 6):>15}"
            f"{sub_id:>15}"
            f"{_hru_land_use(i):>30}"
            f"{'LandHRU_vege_class':>25}"
            f"{'LandHRU_soil_profile':>30}"
            f"{'[NONE]':>10}"
            f"{'[NONE]':>10}"
            f"{round(slope[i], 2):>10}"
            f"{round(aspect[i], 2):>10}\n"
        )

    parts.append(":EndHRUs\n")

    parts.append(
        "\n# SubBasin Properties ----------------------------------------------------\n"
        ":SubBasinProperties\n"
        "  :Parameters      TIME_CONC  TIME_TO_PEAK\n"
        "  :Units               hrs           hrs\n"
    )
    for i in range(n):
        parts.append(
            f"{sub_ids[i]:>15}{round(time_of_conc[i], 2):>10}{round(time_to_peak[i], 2):>14}\n"
        )
    parts.append(":EndSubBasinProperties\n")

    out.write_text("".join(parts))
    logger.info("Wrote RVH → %s (%d subbasins)", out, n)
    return out


# ---------------------------------------------------------------------------
# 2.9 — channel_properties.rvp (per-subbasin channel transects)
# ---------------------------------------------------------------------------

def write_channel_rvp(
    output_dir: Path | str,
    *,
    watershed_name: str,
    sub_ids: list[int],
    basin_area_km2: list[float],
    riv_lengths_mod_n: list[float],
    elevation: list[float],
    bkf_widths: list[float],
    bkf_depths: list[float],     # already sanitized (min 1m)
    riv_slopes: list[float],     # already sanitized
    floodplain_n: list[float],   # already sanitized
    channel_n: list[float],      # already sanitized
) -> Path:
    """Write ``channel_properties.rvp`` with a ChannelProfile block per subbasin.

    The original notebook used ``bkfdepth_mod[0]`` (basin 0) instead of
    ``bkfdepth_mod[i]`` for the *last* survey point's Y coordinate,
    applying basin 0's bankfull depth to every channel profile. The
    writer now uses ``[i]`` consistently with the first survey point.
    """
    n = len(sub_ids)
    for label, lst in [
        ("basin_area_km2", basin_area_km2),
        ("riv_lengths_mod_n", riv_lengths_mod_n),
        ("elevation", elevation), ("bkf_widths", bkf_widths),
        ("bkf_depths", bkf_depths), ("riv_slopes", riv_slopes),
        ("floodplain_n", floodplain_n), ("channel_n", channel_n),
    ]:
        if len(lst) != n:
            raise ValueError(
                f"All per-basin lists must have length {n} (sub_ids); "
                f"{label} has length {len(lst)}."
            )

    output_dir = Path(output_dir)
    out = output_dir / "channel_properties.rvp"

    parts: list[str] = [
        "# ----------------------------------------------\n"
        "# Raven Input file\n"
        f"# {watershed_name}\n"
        "# ----------------------------------------------\n"
    ]

    for i in range(n):
        sub_id = sub_ids[i]
        bkf_depth = bkf_depths[i]
        bkf_width = bkf_widths[i]
        elev = elevation[i]

        x1 = 0
        x2 = bkf_depth * 2
        x3 = bkf_width * 2
        x4 = x2 + x3 * 1.5
        x5 = x2 + x3 * 2
        x6 = x2 * 2 + x3 * 2
        x7 = x3 * 3 + x2
        x8 = x3 * 3 + x2 * 2

        parts.append(
            f"\n###################################chn_{sub_id}"
            f"\n## Subbasin ID:        {sub_id}"
            f"\n## Subbasin area:      {round(basin_area_km2[i], 2)} km2"
            f"\n## Channel length:     {round(riv_lengths_mod_n[i], 2)} km"
            f"\n## Channel elevation:  {round(elev, 3)} m"
            f"\n## Bankfull width:     {round(bkf_width, 4)} m"
            f"\n## Bankfull depth:     {round(bkf_depth, 2)} m"
            f"\n:ChannelProfile       chn_{sub_id}"
            f"\n    :Bedslope         {round(riv_slopes[i], 7)}"
            f"\n    :SurveyPoints"
            f"\n        {x1: >5}  {round(elev + bkf_depth + (bkf_depth / 2), 2)}"
            f"\n        {round(x2, 2): >5}  {round(elev + bkf_depth, 2)}"
            f"\n        {round(x3, 2): >5}  {round(elev + bkf_depth, 2)}"
            f"\n        {round(x4, 2): >5}  {round(elev, 2)}"
            f"\n        {round(x5, 2): >5}  {round(elev, 2)}"
            f"\n        {round(x6, 2): >5}  {round(elev + bkf_depth, 2)}"
            f"\n        {round(x7, 2): >5}  {round(elev + bkf_depth, 2)}"
            f"\n        {round(x8, 2): >5}  {round(elev + bkf_depth + (bkf_depth / 2), 2)}"  # use this basin's bkf_depth — original used bkfdepth_mod[0]
            f"\n    :EndSurveyPoints"
            f"\n    :RoughnessZones"
            f"\n        {0: >5} {round(floodplain_n[i], 6)}"
            f"\n        {round(x3, 2): >5} {round(channel_n[i], 6)}"
            f"\n        {round(x6, 2): >5} {round(floodplain_n[i], 6)}"
            f"\n    :EndRoughnessZones"
            f"\n:EndChannelProfile\n"
        )

    out.write_text("".join(parts))
    logger.info("Wrote channel RVP → %s (%d profiles)", out, n)
    return out
