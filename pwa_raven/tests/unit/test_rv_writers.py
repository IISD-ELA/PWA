"""Unit tests for pwa_raven.raven.rv_writers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from pwa_raven.raven.rv_writers import (
    write_channel_rvp,
    write_model_rvt,
    write_rvc,
    write_rvh,
    write_rvi,
    write_rvp,
)


MODEL_START = datetime(2010, 1, 1)
MODEL_END = datetime(2019, 12, 31)


# ---------------------------------------------------------------------------
# RVI
# ---------------------------------------------------------------------------

def test_write_rvi_basic(tmp_path: Path):
    out = write_rvi(tmp_path, watershed_name="grassmere", model_start=MODEL_START, model_end=MODEL_END)
    content = out.read_text()
    assert out.name == "grassmere.rvi"
    assert ":StartDate             2010-01-01 00:00:00" in content
    assert ":EndDate               2019-12-31 00:00:00" in content
    assert ":RunName               grassmere" in content
    assert ":HydrologicProcesses" in content
    assert ":EndHydrologicProcesses" in content


def test_write_rvi_uses_3h_timestep(tmp_path: Path):
    """3-hour timestep matches the upstream default (master commit
    1354657). Hourly (the old refactor default) produced different
    simulation output and made calibrations non-comparable to runs
    against current upstream master."""
    out = write_rvi(tmp_path, watershed_name="grassmere", model_start=MODEL_START, model_end=MODEL_END)
    content = out.read_text()
    assert ":TimeStep              03:00:00" in content
    assert ":TimeStep              01:00:00" not in content


def test_write_rvi_strips_spaces_from_filename(tmp_path: Path):
    """Raven file basenames cannot contain whitespace; sanitization handles that."""
    out = write_rvi(tmp_path, watershed_name="grass mere", model_start=MODEL_START, model_end=MODEL_END)
    assert out.name == "grassmere.rvi"
    # But the comment header preserves the human-readable name
    assert "# grass mere" in out.read_text()


# ---------------------------------------------------------------------------
# RVC
# ---------------------------------------------------------------------------

def test_write_rvc_default_initial_storage(tmp_path: Path):
    out = write_rvc(tmp_path, watershed_name="grassmere")
    content = out.read_text()
    assert out.name == "grassmere.rvc"
    assert ":UniformInitialConditions SOIL[0] 15.0" in content


def test_write_rvc_overrides_initial_storage(tmp_path: Path):
    out = write_rvc(tmp_path, watershed_name="x", initial_soil_storage_mm=42.5)
    assert ":UniformInitialConditions SOIL[0] 42.5" in out.read_text()


# ---------------------------------------------------------------------------
# RVP
# ---------------------------------------------------------------------------

def test_write_rvp_emits_per_bin_landuse_and_params(tmp_path: Path):
    """LandUseClasses is keyed by unique bin labels; LandUseParameterList
    has one row per source subbasin (per the upstream binning design —
    duplicate bin labels are tolerated as parameter-override redundancy)."""
    out = write_rvp(
        tmp_path,
        watershed_name="grassmere",
        bin_labels=["Bin_3", "Bin_3", "Bin_7"],   # two subbasins share Bin_3
        binned_deps=[5.0, 5.0, 8.7],
    )
    content = out.read_text()

    # LandUseClasses: unique bins + Bin_NA sentinel (always appended).
    lu_section = content.split(":LandUseClasses")[1].split(":EndLandUseClasses")[0]
    assert "Bin_3,              0,                        1" in lu_section
    assert "Bin_7,              0,                        1" in lu_section
    assert "Bin_NA,              0,                        1" in lu_section
    # Bin_3 appears once in LandUseClasses (deduplicated), even though
    # two subbasins share that label.
    assert lu_section.count("Bin_3,") == 1

    # LandUseParameterList: one row per source subbasin — Bin_3 appears
    # twice with the shared 5.0 depth.
    pl_section = content.split(":LandUseParameterList")[1]
    bin3_rows = [ln for ln in pl_section.splitlines() if "Bin_3" in ln]
    assert len(bin3_rows) == 2
    assert all("5.0000" in row for row in bin3_rows)
    bin7_rows = [ln for ln in pl_section.splitlines() if "Bin_7" in ln]
    assert len(bin7_rows) == 1
    assert "8.7000" in bin7_rows[0]

    # Static structure preserved.
    assert ":SoilClasses" in content
    assert ":AvgAnnualRunoff        75" in content
    assert ":RedirectToFile         channel_properties.rvp" in content


def test_write_rvp_normalizes_nan_to_bin_na(tmp_path: Path):
    """NaN labels or depths get mapped to Bin_NA / 0.0 on write —
    matches upstream's per-row write that falls back to Bin_NA for
    rows with NaN Deps_Depth."""
    import numpy as np
    out = write_rvp(
        tmp_path,
        watershed_name="ws",
        bin_labels=["Bin_1", None, "Bin_2"],
        binned_deps=[1.5, np.nan, 2.5],
    )
    content = out.read_text()

    pl_section = content.split(":LandUseParameterList")[1]
    # The None label normalizes to Bin_NA with depth 0.
    bin_na_rows = [ln for ln in pl_section.splitlines() if "Bin_NA" in ln]
    assert len(bin_na_rows) == 1
    assert "0.0000" in bin_na_rows[0]


def test_write_rvp_bin_na_in_landuse_classes_even_without_nan_rows(tmp_path: Path):
    """LandUseClasses always includes a Bin_NA entry even when no row
    in the input is NaN. Upstream reserves the class unconditionally."""
    out = write_rvp(
        tmp_path,
        watershed_name="ws",
        bin_labels=["Bin_1", "Bin_2"],
        binned_deps=[1.0, 2.0],
    )
    lu_section = out.read_text().split(":LandUseClasses")[1].split(":EndLandUseClasses")[0]
    assert "Bin_NA," in lu_section


def test_write_rvp_rejects_mismatched_lengths(tmp_path: Path):
    with pytest.raises(ValueError, match="must have the same length"):
        write_rvp(
            tmp_path, watershed_name="x",
            bin_labels=["Bin_1", "Bin_2"], binned_deps=[1.0],
        )


# ---------------------------------------------------------------------------
# Model RVT
# ---------------------------------------------------------------------------

def test_write_model_rvt(tmp_path: Path):
    out = write_model_rvt(
        tmp_path,
        watershed_name="grassmere",
        phydap_filename="phydap_subset.nc",
        wsc_station_id="05NF002",
    )
    content = out.read_text()
    assert out.name == "grassmere.rvt"
    assert ":FileNameNC           input/phydap_subset.nc" in content
    assert ":RedirectToFile       input/GridWeights.txt" in content
    assert ":RedirectToFile           WSC05NF002.rvt" in content
    assert ":LinearTransform      24.0     0.0" in content


def test_write_model_rvt_overrides_linear_transform(tmp_path: Path):
    out = write_model_rvt(
        tmp_path,
        watershed_name="x",
        phydap_filename="f.nc",
        wsc_station_id="abc",
        linear_transform=(1.0, 5.0),
    )
    assert ":LinearTransform      1.0     5.0" in out.read_text()


# ---------------------------------------------------------------------------
# RVH — large multi-section file
# ---------------------------------------------------------------------------

@pytest.fixture
def rvh_inputs():
    """Two subbasins with one ZERO- sentinel river length to exercise mixed type."""
    return dict(
        sub_ids=[101, 102],
        dow_sub_ids=[102, -1],
        riv_lengths_mod=["ZERO-", 1.234],
        has_gauge=[0, 1],
        q_ref=[0.5, 2.0],
        basin_area_km2=[1.5, 4.2],
        elevation=[450.123, 460.456],
        latitude=[50.123456, 50.234567],
        longitude=[-97.654321, -97.543210],
        slope=[1.5, 2.7],
        aspect=[180.0, 270.0],
        time_of_conc=[2.34, 5.67],
        time_to_peak=[1.40, 3.40],
    )


def test_write_rvh_three_sections(tmp_path: Path, rvh_inputs):
    out = write_rvh(tmp_path, watershed_name="grassmere", **rvh_inputs)
    content = out.read_text()

    assert out.name == "grassmere.rvh"
    # SubBasins section with ZERO- sentinel preserved
    assert ":SubBasins" in content
    assert "ZERO-" in content
    assert ":EndSubBasins" in content
    # HRUs section
    assert ":HRUs" in content
    assert "LandHRU_landuse_class" in content
    assert ":EndHRUs" in content
    # SubBasinProperties section
    assert ":SubBasinProperties" in content
    assert "TIME_CONC" in content
    assert ":EndSubBasinProperties" in content


def test_write_rvh_handles_string_reach_length(tmp_path: Path, rvh_inputs):
    """The 'ZERO-' string sentinel must format alongside numeric lengths."""
    out = write_rvh(tmp_path, watershed_name="x", **rvh_inputs)
    lines = out.read_text().splitlines()
    sub_lines = [ln for ln in lines if ln.lstrip().startswith(("101", "102")) and "chn_" in ln]
    assert len(sub_lines) == 2
    assert "ZERO-" in sub_lines[0]
    assert "1.234" in sub_lines[1]


def test_write_rvh_rejects_mismatched_lengths(tmp_path: Path, rvh_inputs):
    bad = {**rvh_inputs, "elevation": [1.0]}    # too short
    with pytest.raises(ValueError, match="elevation"):
        write_rvh(tmp_path, watershed_name="x", **bad)


def test_write_rvh_uses_bin_labels_for_hru_land_use_class(tmp_path: Path, rvh_inputs):
    """When bin_labels is provided, each HRU's LAND_USE_CLASS column
    is the row's bin label — required so the .rvh references match the
    bin-keyed classes declared by write_rvp. NaN/None labels become
    Bin_NA."""
    out = write_rvh(
        tmp_path, watershed_name="grassmere",
        bin_labels=["Bin_3", None],
        **rvh_inputs,
    )
    content = out.read_text()
    # The HRU rows are below the :HRUs marker.
    hru_section = content.split(":HRUs")[1].split(":EndHRUs")[0]
    assert "Bin_3" in hru_section
    assert "Bin_NA" in hru_section
    # The legacy default class must NOT appear in HRU rows when bin
    # labels are provided.
    assert "LandHRU_landuse_class" not in hru_section


def test_write_rvh_omits_bin_labels_falls_back_to_legacy_default(tmp_path: Path, rvh_inputs):
    """No bin_labels → every HRU defaults to LandHRU_landuse_class.
    Preserves back-compat for callers that haven't migrated."""
    out = write_rvh(tmp_path, watershed_name="x", **rvh_inputs)
    hru_section = out.read_text().split(":HRUs")[1].split(":EndHRUs")[0]
    assert "LandHRU_landuse_class" in hru_section
    assert "Bin_" not in hru_section


def test_write_rvh_rejects_mismatched_bin_labels_length(tmp_path: Path, rvh_inputs):
    with pytest.raises(ValueError, match="bin_labels"):
        write_rvh(
            tmp_path, watershed_name="x",
            bin_labels=["Bin_3"],   # only one — should be two
            **rvh_inputs,
        )


# ---------------------------------------------------------------------------
# Channel RVP — last survey point must use this basin's bkf_depth
# ---------------------------------------------------------------------------

@pytest.fixture
def channel_inputs():
    """Two subbasins with DIFFERENT bankfull depths so any cross-basin
    contamination (notebook bug applied basin 0's depth to all profiles)
    shows up as a numeric mismatch."""
    return dict(
        sub_ids=[101, 102],
        basin_area_km2=[1.5, 4.2],
        riv_lengths_mod_n=[2.5, 3.7],
        elevation=[100.0, 200.0],
        bkf_widths=[5.0, 8.0],
        bkf_depths=[1.5, 4.0],     # distinct
        riv_slopes=[0.001, 0.002],
        floodplain_n=[0.05, 0.06],
        channel_n=[0.025, 0.030],
    )


def test_write_channel_rvp_emits_one_profile_per_basin(tmp_path: Path, channel_inputs):
    out = write_channel_rvp(tmp_path, watershed_name="grassmere", **channel_inputs)
    content = out.read_text()
    assert out.name == "channel_properties.rvp"
    assert ":ChannelProfile       chn_101" in content
    assert ":ChannelProfile       chn_102" in content
    assert content.count(":EndChannelProfile") == 2


def test_write_channel_rvp_first_and_last_survey_points_match_per_basin(
    tmp_path: Path, channel_inputs,
):
    """Each basin's :SurveyPoints block must terminate with that same
    basin's bkf_depth. The original notebook hardcoded ``bkfdepth_mod[0]``
    for the last point, so every channel profile inherited basin 0's
    depth.

    With distinct bkf_depths [1.5, 4.0] and elevations [100, 200]:
      basin 0: first/last Y = 100 + 1.5 + 0.75 = 102.25
      basin 1: first/last Y = 200 + 4.0 + 2.0  = 206.0
                              (would be 206 + 0.75 = 206.75 with the bug)
    """
    out = write_channel_rvp(tmp_path, watershed_name="x", **channel_inputs)
    content = out.read_text()

    # Isolate basin 102's :SurveyPoints block
    chn_102_block = content.split(":ChannelProfile       chn_102")[1].split(":EndChannelProfile")[0]
    survey_block = chn_102_block.split(":SurveyPoints")[1].split(":EndSurveyPoints")[0]
    survey_lines = [ln.strip() for ln in survey_block.splitlines() if ln.strip()]

    # First and last survey points should both have Y = 206.0 (200 + 4.0 + 2.0)
    first_y = float(survey_lines[0].split()[1])
    last_y = float(survey_lines[-1].split()[1])
    assert first_y == pytest.approx(206.0)
    assert last_y == pytest.approx(206.0)
    # And they should be EQUAL — the bug would have made last = 200 + 4.0 + 0.75 = 204.75
    assert first_y == last_y


def test_write_channel_rvp_rejects_mismatched_lengths(tmp_path: Path, channel_inputs):
    bad = {**channel_inputs, "bkf_widths": [1.0]}
    with pytest.raises(ValueError, match="bkf_widths"):
        write_channel_rvp(tmp_path, watershed_name="x", **bad)
