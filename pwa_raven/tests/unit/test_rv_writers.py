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

def test_write_rvp_emits_per_subbasin_landuse_and_params(tmp_path: Path):
    out = write_rvp(
        tmp_path,
        watershed_name="grassmere",
        sub_ids=[101, 102, 103],
        deps_depths=[12.5, 8.7, 0.0],
    )
    content = out.read_text()

    # LandUseClasses table has SUB101/102/103 entries
    assert "SUB101,              0,                        1" in content
    assert "SUB102,              0,                        1" in content
    # LandUseParameterList has DEP_MAX = depression depth per basin
    assert "SUB101" in content and "12.5000" in content
    assert "SUB103" in content and "0.0000" in content
    # Rows are individual lines and align under :LandUseParameterList
    pl_section = content.split(":LandUseParameterList")[1]
    assert "SUB101" in pl_section and "12.5000" in pl_section
    assert "SUB102" in pl_section and "8.7000" in pl_section
    # Static structure preserved
    assert ":SoilClasses" in content
    assert ":AvgAnnualRunoff        75" in content
    assert ":RedirectToFile         channel_properties.rvp" in content


def test_write_rvp_rejects_mismatched_lengths(tmp_path: Path):
    with pytest.raises(ValueError, match="must have the same length"):
        write_rvp(tmp_path, watershed_name="x", sub_ids=[1, 2], deps_depths=[1.0])


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


# ---------------------------------------------------------------------------
# Channel RVP — including BUG-021 regression
# ---------------------------------------------------------------------------

@pytest.fixture
def channel_inputs():
    """Two subbasins with DIFFERENT bankfull depths so BUG-021 is detectable."""
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
    """BUG-021 regression: last survey point Y must use this basin's bkf_depth,
    not basin 0's. With distinct bkf_depths [1.5, 4.0] and elevations [100, 200]:
      basin 0: first/last Y = 100 + 1.5 + 0.75 = 102.25
      basin 1: first/last Y = 200 + 4.0 + 2.0  = 206.0   (would be 206 + buggy 0.75 = 206.75 with bug)
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
