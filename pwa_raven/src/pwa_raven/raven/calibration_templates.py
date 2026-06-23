"""Calibration template generators for Raven + SpotPy workflow.

Extracted from ``PWA/_notebooks/2_raven_input_gen.ipynb`` § 3.

These produce ``.tpl`` files that SpotPy uses for parameter substitution
during calibration (Step 3). The pattern is: produce the "real" RV* files
first via :mod:`pwa_raven.raven.rv_writers`, then run these helpers to
emit templated versions where calibrated values become string
placeholders (e.g. ``qref_<subid>``, ``tc_<subid>``, ``s<subid>_dep``).

Also provides two CSV extractors used by the SpotPy harness for HRU
area weights and TIME_CONC / TIME_TO_PEAK lookup.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 3.1 — .rvh template (line-by-line transform of the real .rvh)
# ---------------------------------------------------------------------------

def generate_rvh_template(real_rvh_path: Path | str, output_path: Path | str) -> Path:
    """Convert a concrete ``.rvh`` file into a SpotPy ``.rvh.tpl`` template.

    Three sections are transformed:

      - **SubBasins**: replace the per-row reference flow with a
        placeholder ``qref_<subid>``. The ``Q_REFERENCE`` column header
        is already written into the base ``.rvh`` by
        ``rv_writers.write_rvh`` and is left untouched.
      - **HRUs**: replace the area column with ``H<hruid>_area`` placeholder.
      - **SubBasinProperties**: replace ``TIME_CONC`` / ``TIME_TO_PEAK``
        values with placeholders ``tc_<subid>`` / ``tp_<subid>``.

    Other lines (comments, headers, end-section markers, soil/veg blocks)
    pass through unchanged.
    """
    real_rvh_path = Path(real_rvh_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    template_lines: list[str] = []
    in_subbasins = in_hrus = in_props = False

    with real_rvh_path.open("r") as f:
        for line in f:
            stripped = line.strip()

            # Section state machine
            if stripped.startswith(":SubBasins"):
                in_subbasins = True
                in_hrus = in_props = False
            elif stripped.startswith(":HRUs"):
                in_hrus = True
                in_subbasins = in_props = False
            elif stripped.startswith(":SubBasinProperties"):
                in_props = True
                in_subbasins = in_hrus = False
            elif stripped.startswith(":EndSubBasins") \
                    or stripped.startswith(":EndHRUs") \
                    or stripped.startswith(":EndSubBasinProperties"):
                in_subbasins = in_hrus = in_props = False

            if in_subbasins and _is_data_line(stripped):
                # The base .rvh already carries the Q_REFERENCE column with a
                # concrete value. Swap that value for the qref_<subid>
                # placeholder; leave the :Attributes / :Units headers alone
                # (appending here would duplicate the column and leave Raven
                # reading a phantom empty 8th column → "Reference flow must
                # be non-zero and positive").
                parts = line.split()
                sub_id, _name, downstream, _profile, reach_length, gauged = parts[:6]
                line = (
                    f"{int(sub_id):>10}  sub{sub_id:<10}  {int(downstream):>10}  "
                    f"chn_{sub_id:<10}  {reach_length:>10}  {gauged:>5}   qref_{sub_id}\n"
                )

            if in_hrus and _is_data_line(stripped):
                parts = line.split()
                if len(parts) >= 13:
                    (hru_id, _area, elev, lat, lon, basin_id, _land_use,
                     veg_class, soil_profile, aquifer_profile,
                     terrain_class, slope, aspect) = parts[:13]
                    line = (
                        f"{int(hru_id):12d}      "
                        f"H{hru_id}_area     "
                        f"{float(elev):10.2f}      "
                        f"{float(lat):14.6f}     "
                        f"{float(lon):14.6f}      "
                        f"{int(basin_id):>8}           "
                        f"SUB{basin_id:<10}      "
                        f"{veg_class:>20}           "
                        f"{soil_profile:>25}   "
                        f"{aquifer_profile:>10}   "
                        f"{terrain_class:>10}       "
                        f"{float(slope):10.2f}     "
                        f"{float(aspect):10.2f}\n"
                    )

            if in_props and _is_data_line(stripped):
                parts = line.split()
                if parts:
                    sub_id = parts[0]
                    line = f"{int(sub_id):>10}     tc_{sub_id:<10}    tp_{sub_id}\n"

            template_lines.append(line)

    output_path.write_text("".join(template_lines))
    logger.info("Wrote RVH template → %s", output_path)
    return output_path


def _is_data_line(stripped: str) -> bool:
    """A non-directive, non-comment, non-empty line is a data row."""
    return bool(stripped) and not stripped.startswith(":") and not stripped.startswith("#")


# ---------------------------------------------------------------------------
# 3.2 — .rvp template (built from scratch, not by transforming the real one)
# ---------------------------------------------------------------------------

def generate_rvp_template(
    output_path: Path | str,
    *,
    watershed_name: str,
    bin_labels: list[str | None],
    channel_props_filename: str = "channel_properties",
    seep_placeholder: str = "seep_fact",
    dep_placeholder_format: str = "{bin_label}_dep",
    default_dep_max: float = 20.0,
    avg_annual_runoff: float = 75.0,
) -> Path:
    """Write the calibration ``.rvp.tpl`` file.

    Mirrors ``rv_writers.write_rvp``'s bin-keyed structure but with
    SpotPy placeholders:
      - ``DEP_SEEP_K`` is the placeholder ``seep_fact`` (one global
        parameter, calibrated across all classes).
      - ``DEP_MAX`` is the placeholder ``{bin_label}_dep`` (e.g.
        ``Bin_3_dep``, ``Bin_NA_dep``) so the calibrator can scale
        each bin's depth via ``dep_fact``.

    Note vs. upstream notebook: upstream hard-codes the binned depth
    values in the template, which effectively disables ``dep_scaling``
    at calibration time. We keep the placeholder so the per-bin scale
    knob still works — set ``dep_scaling=False`` on the calibration
    config to skip the substitution if you specifically want the
    upstream behaviour.
    """
    if not bin_labels:
        raise ValueError("bin_labels is empty; need at least one row to template.")

    def _label(lbl: object) -> str:
        if lbl is None:
            return "Bin_NA"
        try:
            if pd.isna(lbl):  # type: ignore[arg-type]
                return "Bin_NA"
        except (TypeError, ValueError):
            pass
        return str(lbl) or "Bin_NA"

    # Unique bin labels for :LandUseClasses — Bin_NA always appended,
    # matching write_rvp.
    unique_bins: list[str] = []
    seen: set[str] = set()
    for lbl in bin_labels:
        norm = _label(lbl)
        if norm == "Bin_NA":
            continue
        if norm not in seen:
            unique_bins.append(norm)
            seen.add(norm)
    unique_bins.append("Bin_NA")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    parts: list[str] = [
        "# ----------------------------------------------\n",
        "# Raven Input file\n",
        f"# {watershed_name}\n",
        "# ----------------------------------------------\n\n",
        "# Soil/Vegetation/Land use class definitions ------\n",
        ":SoilClasses\n",
        "  AQUIFER      # only one soil class used here\n",
        ":EndSoilClasses\n\n",
        ":SoilProfiles\n",
        "  # name, number of layers, soil class, thickness [m]\n",
        "  LandHRU_soil_profile,    1,    AQUIFER, 5\n",
        ":EndSoilProfiles\n\n",
        "# the vegetation and land use parameters unused in routing\n",
        ":VegetationClasses\n",
        "  :Attributes,                MAX_HT,       MAX_LAI,    MAX_LEAF_COND\n",
        "  :Units,                       m,            none,       mm_per_s\n",
        "  LandHRU_vege_class,           25,           5.0,          5.0\n",
        ":EndVegetationClasses\n\n",
        ":LandUseClasses\n",
        "  :Attributes,        IMPERMEABLE_FRAC,         FOREST_COVERAGE\n",
        "  :Units,                     fract,                    fract\n",
        "  LandHRU_landuse_class,      0,                        1\n",
    ]
    for bin_lbl in unique_bins:
        parts.append(f"  {bin_lbl},\t      0,                        1\n")
    parts.extend([
        ":EndLandUseClasses\n\n",
        "# Global Parameters-----------------------------\n",
        f":AvgAnnualRunoff \t\t{avg_annual_runoff}\n\n",
        ":LandUseParameterList\n",
        "  :Parameters,\tDEP_SEEP_K,\t\tDEP_MAX\n",
        "  :Units     ,\t       1/d,\t\t     mm\n",
        f"    [DEFAULT],          {seep_placeholder},        {default_dep_max:.3f}\n",
    ])
    # One row per source-gdf row, matching write_rvp. Each row's bin
    # label drives both the class key and the placeholder name; rows
    # in the same bin share a placeholder so a single substitution
    # updates them all together.
    for lbl in bin_labels:
        norm = _label(lbl)
        dep_placeholder = dep_placeholder_format.format(bin_label=norm)
        parts.append(
            f"    {norm}   ,\t{seep_placeholder},\t      {dep_placeholder}\n"
        )
    parts.extend([
        ":EndLandUseParameterList\n\n",
        "# redirects to channel properties file\n",
        f":RedirectToFile         {channel_props_filename}.rvp\n",
    ])

    output_path.write_text("".join(parts))
    logger.info(
        "Wrote RVP template → %s (%d source rows, %d unique bin labels)",
        output_path, len(bin_labels), len(unique_bins),
    )
    return output_path


# ---------------------------------------------------------------------------
# 3.3 — channel_properties.rvp template (literal copy)
# ---------------------------------------------------------------------------

def generate_channel_rvp_template(
    real_rvp_path: Path | str,
    output_path: Path | str,
) -> Path:
    """Create a ``channel_properties.rvp.tpl`` file by copying the real .rvp.

    The notebook copies the file verbatim with no parameter substitution —
    SpotPy treats the ``.tpl`` as a non-templated file in this case.
    Preserving that behaviour.
    """
    real_rvp_path = Path(real_rvp_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy(real_rvp_path, output_path)
    logger.info("Copied channel RVP template → %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# 3.4 — Auxiliary CSVs from the .rvh
# ---------------------------------------------------------------------------

def extract_hru_areas(rvh_path: Path | str, output_csv: Path | str) -> Path:
    """Read ``:HRUs`` block from an .rvh file and write ``HRU,AREA`` CSV."""
    rvh_path = Path(rvh_path)
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: list[list[str]] = []
    in_hrus = False
    with rvh_path.open() as f:
        for raw_line in f:
            line = raw_line.strip()
            if line.startswith(":HRUs"):
                in_hrus = True
                continue
            if line.startswith(":EndHRUs"):
                in_hrus = False
                continue
            if not in_hrus:
                continue
            if not line or line.startswith(":") or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                rows.append([parts[0], parts[1]])

    pd.DataFrame(rows, columns=["HRU", "AREA"]).to_csv(output_csv, index=False)
    logger.info("Wrote HRU areas CSV → %s (%d rows)", output_csv, len(rows))
    return output_csv


def extract_subbasin_properties(rvh_path: Path | str, output_csv: Path | str) -> Path:
    """Read ``:SubBasinProperties`` block and write ``SubId,tc,tp`` CSV."""
    rvh_path = Path(rvh_path)
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: list[list[str]] = []
    in_props = False
    with rvh_path.open() as f:
        for raw_line in f:
            line = raw_line.strip()
            if line.startswith(":SubBasinProperties"):
                in_props = True
                continue
            if line.startswith(":EndSubBasinProperties"):
                in_props = False
                continue
            if not in_props:
                continue
            if not line or line.startswith(":") or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                rows.append([parts[0], parts[1], parts[2]])

    pd.DataFrame(rows, columns=["SubId", "tc", "tp"]).to_csv(output_csv, index=False)
    logger.info("Wrote SubBasin properties CSV → %s (%d rows)", output_csv, len(rows))
    return output_csv


def extract_subids_from_rvh(rvh_path: Path | str) -> list[int]:
    """Extract the unique sub-basin IDs from any ``.rvh`` data section."""
    rvh_path = Path(rvh_path)
    sub_ids: set[int] = set()
    with rvh_path.open() as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(":") or line.startswith("#"):
                continue
            parts = line.split()
            if parts and parts[0].isdigit():
                sub_ids.add(int(parts[0]))
    return sorted(sub_ids)
