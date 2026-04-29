"""Unit tests for pwa_raven.raven.calibration_templates."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pwa_raven.raven.calibration_templates import (
    extract_hru_areas,
    extract_subbasin_properties,
    extract_subids_from_rvh,
    generate_channel_rvp_template,
    generate_rvh_template,
    generate_rvp_template,
)
from pwa_raven.raven.rv_writers import write_rvh


@pytest.fixture
def real_rvh(tmp_path: Path) -> Path:
    """Build a concrete .rvh using the production writer to use as template input."""
    return write_rvh(
        tmp_path,
        watershed_name="grassmere",
        sub_ids=[101, 102],
        dow_sub_ids=[102, -1],
        riv_lengths_mod=[1.234, 2.5],
        has_gauge=[0, 1],
        q_ref=[0.5, 2.0],
        basin_area_km2=[1.5, 4.2],
        elevation=[450.0, 460.0],
        latitude=[50.123, 50.234],
        longitude=[-97.6, -97.5],
        slope=[1.5, 2.7],
        aspect=[180.0, 270.0],
        time_of_conc=[2.34, 5.67],
        time_to_peak=[1.40, 3.40],
    )


# ---------------------------------------------------------------------------
# generate_rvh_template
# ---------------------------------------------------------------------------

def test_rvh_template_appends_qreference_column(tmp_path: Path, real_rvh):
    out = generate_rvh_template(real_rvh, tmp_path / "templates" / "x.rvh.tpl")
    content = out.read_text()
    assert "Q_REFERENCE" in content
    assert "m3/s" in content


def test_rvh_template_replaces_per_basin_qref_placeholder(tmp_path: Path, real_rvh):
    out = generate_rvh_template(real_rvh, tmp_path / "templates" / "x.rvh.tpl")
    content = out.read_text()
    assert "qref_101" in content
    assert "qref_102" in content


def test_rvh_template_replaces_hru_area_placeholder(tmp_path: Path, real_rvh):
    out = generate_rvh_template(real_rvh, tmp_path / "templates" / "x.rvh.tpl")
    content = out.read_text()
    assert "H101_area" in content
    assert "H102_area" in content


def test_rvh_template_replaces_tc_tp_placeholders(tmp_path: Path, real_rvh):
    out = generate_rvh_template(real_rvh, tmp_path / "templates" / "x.rvh.tpl")
    content = out.read_text()
    # SubBasinProperties section uses tc_<id> / tp_<id>
    assert "tc_101" in content
    assert "tp_102" in content


def test_rvh_template_creates_output_directory(tmp_path: Path, real_rvh):
    """Output's parent dir doesn't exist yet → should be created."""
    nested = tmp_path / "deeply" / "nested" / "templates" / "x.rvh.tpl"
    out = generate_rvh_template(real_rvh, nested)
    assert out.exists()


def test_rvh_template_preserves_static_sections(tmp_path: Path, real_rvh):
    """End markers and the watershed-name comment should survive verbatim."""
    out = generate_rvh_template(real_rvh, tmp_path / "x.rvh.tpl")
    content = out.read_text()
    assert ":EndSubBasins" in content
    assert ":EndHRUs" in content
    assert ":EndSubBasinProperties" in content
    assert "# grassmere" in content


# ---------------------------------------------------------------------------
# generate_rvp_template
# ---------------------------------------------------------------------------

def test_rvp_template_includes_seep_and_dep_placeholders(tmp_path: Path):
    out = generate_rvp_template(
        tmp_path / "templates" / "x.rvp.tpl",
        watershed_name="grassmere",
        sub_ids=[101, 102],
    )
    content = out.read_text()
    # Default seep placeholder used for default + per-basin rows
    assert content.count("seep_fact") >= 3
    # Per-basin DEP placeholders
    assert "s101_dep" in content
    assert "s102_dep" in content
    # SUB101/102 LandUseClasses entries
    assert "SUB101" in content
    assert "SUB102" in content
    # Static structure preserved
    assert ":SoilClasses" in content
    assert ":EndLandUseParameterList" in content
    assert ":RedirectToFile         channel_properties.rvp" in content


def test_rvp_template_overrides_seep_placeholder(tmp_path: Path):
    out = generate_rvp_template(
        tmp_path / "x.rvp.tpl",
        watershed_name="x", sub_ids=[1],
        seep_placeholder="my_seep",
    )
    assert "my_seep" in out.read_text()


# ---------------------------------------------------------------------------
# generate_channel_rvp_template (literal copy)
# ---------------------------------------------------------------------------

def test_channel_rvp_template_is_byte_for_byte_copy(tmp_path: Path):
    src = tmp_path / "channel_properties.rvp"
    src.write_text("# placeholder content\n:ChannelProfile foo\n:EndChannelProfile\n")

    out = generate_channel_rvp_template(src, tmp_path / "templates" / "channel_properties.rvp.tpl")
    assert out.read_text() == src.read_text()


# ---------------------------------------------------------------------------
# extract_hru_areas
# ---------------------------------------------------------------------------

def test_extract_hru_areas_writes_csv(tmp_path: Path, real_rvh):
    out = extract_hru_areas(real_rvh, tmp_path / "input" / "hru_areas.csv")
    df = pd.read_csv(out, dtype=str)
    assert list(df.columns) == ["HRU", "AREA"]
    assert df["HRU"].tolist() == ["101", "102"]
    assert df["AREA"].tolist() == ["1.5", "4.2"]


def test_extract_hru_areas_skips_other_sections(tmp_path: Path, real_rvh):
    """Make sure non-HRU data lines (SubBasins, SubBasinProperties) aren't included."""
    out = extract_hru_areas(real_rvh, tmp_path / "h.csv")
    df = pd.read_csv(out)
    # Only 2 HRUs, not 6 (2 subbasins + 2 HRUs + 2 properties)
    assert len(df) == 2


# ---------------------------------------------------------------------------
# extract_subbasin_properties
# ---------------------------------------------------------------------------

def test_extract_subbasin_properties_writes_tc_tp_csv(tmp_path: Path, real_rvh):
    out = extract_subbasin_properties(real_rvh, tmp_path / "input" / "tp_tc.csv")
    df = pd.read_csv(out)
    assert list(df.columns) == ["SubId", "tc", "tp"]
    assert df["SubId"].tolist() == [101, 102]
    assert df["tc"].tolist() == [2.34, 5.67]
    assert df["tp"].tolist() == [1.4, 3.4]


# ---------------------------------------------------------------------------
# extract_subids_from_rvh
# ---------------------------------------------------------------------------

def test_extract_subids_from_rvh(real_rvh):
    sub_ids = extract_subids_from_rvh(real_rvh)
    assert sub_ids == [101, 102]
