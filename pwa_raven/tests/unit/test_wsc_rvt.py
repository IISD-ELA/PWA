"""Unit tests for pwa_raven.raven.wsc_rvt."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pwa_raven.raven.wsc_rvt import (
    DEFAULT_MISSING_SENTINEL,
    clip_to_model_window,
    find_data_gap_limits,
    format_gap_comment,
    generate_wsc_rvt,
    write_wsc_rvt_file,
)

MODEL_START = datetime(2010, 1, 1)
MODEL_END = datetime(2010, 1, 31)


# ---------------------------------------------------------------------------
# clip_to_model_window
# ---------------------------------------------------------------------------

def _wsc_frame(dates: list[str], values: list, params: list[int] | None = None) -> pd.DataFrame:
    if params is None:
        params = [1] * len(dates)
    return pd.DataFrame({"Date": dates, "Value": values, "PARAM": params})


def test_clip_to_model_window_drops_out_of_range():
    raw = _wsc_frame(
        ["2009-12-31", "2010-01-01", "2010-01-15", "2010-01-31", "2010-02-01"],
        [1.0, 2.0, 3.0, 4.0, 5.0],
    )
    out = clip_to_model_window(raw, MODEL_START, MODEL_END)
    assert out["Value"].tolist() == [2.0, 3.0, 4.0]


def test_clip_to_model_window_filters_to_discharge_param():
    """PARAM != 1 (e.g. water level) is dropped."""
    raw = _wsc_frame(
        ["2010-01-05", "2010-01-06"],
        [1.5, 2.5],
        params=[1, 2],   # second row is not discharge
    )
    out = clip_to_model_window(raw, MODEL_START, MODEL_END)
    assert out["Value"].tolist() == [1.5]


# ---------------------------------------------------------------------------
# find_data_gap_limits
# ---------------------------------------------------------------------------

def test_find_data_gap_limits_no_nans():
    df = _wsc_frame(["2010-01-01", "2010-01-02"], [1.0, 2.0])
    result = find_data_gap_limits(df, MODEL_START, MODEL_END)
    assert len(result) == 0


def test_find_data_gap_limits_misses_contiguous_block():
    """Documents Q-001: contiguous NaN blocks are NOT flagged by the
    notebook's algorithm because consecutive nulls are 1 day apart and
    therefore never exceed gap_threshold_days. This test pins the surprising
    behaviour so we notice if future refactor changes it."""
    df = _wsc_frame(
        ["2010-01-02", "2010-01-05", "2010-01-06", "2010-01-07", "2010-01-08", "2010-01-09", "2010-01-12"],
        [1.0, np.nan, np.nan, np.nan, np.nan, np.nan, 2.0],
    )
    result = find_data_gap_limits(df, MODEL_START, MODEL_END)
    assert len(result) == 0


def test_find_data_gap_limits_two_separated_isolated_nans():
    """Two isolated NaN days >1.5d apart: each appears as both forward+backward
    gap (paired) AND as a 'single', producing 2 entries in result."""
    df = _wsc_frame(
        ["2010-01-02", "2010-01-05", "2010-01-08", "2010-01-15", "2010-01-20"],
        [1.0,          np.nan,       2.0,           np.nan,       3.0],
    )
    result = find_data_gap_limits(df, MODEL_START, MODEL_END)
    assert len(result) == 2
    assert result.iloc[0] == pd.Timestamp("2010-01-05")
    assert result.iloc[1] == pd.Timestamp("2010-01-15")


def test_find_data_gap_limits_prepends_user_start_when_series_starts_nan():
    df = _wsc_frame(
        ["2010-01-05", "2010-01-06", "2010-01-15"],
        [np.nan, np.nan, 3.0],
    )
    result = find_data_gap_limits(df, MODEL_START, MODEL_END)
    assert result.iloc[0] == pd.Timestamp(MODEL_START)


def test_find_data_gap_limits_appends_user_end_when_series_ends_nan():
    df = _wsc_frame(
        ["2010-01-05", "2010-01-25", "2010-01-26"],
        [3.0, np.nan, np.nan],
    )
    result = find_data_gap_limits(df, MODEL_START, MODEL_END)
    assert result.iloc[-1] == pd.Timestamp(MODEL_END)



# ---------------------------------------------------------------------------
# format_gap_comment
# ---------------------------------------------------------------------------

def test_format_gap_comment_emits_pairs_when_series_starts_with_data():
    """Gap comments must be emitted regardless of whether the series
    starts with NaN. The notebook gated the loop on ``wsc_null_start``,
    so a series with valid first/last values produced an empty comment
    string even when multi-day gaps existed in the middle."""
    gap_limits = pd.Series([pd.Timestamp("2010-01-10"), pd.Timestamp("2010-01-15")])
    out = format_gap_comment(gap_limits)
    assert "Missing data period 1" in out
    assert "2010-01-10" in out and "2010-01-15" in out


def test_format_gap_comment_empty_when_no_gaps():
    assert format_gap_comment(pd.Series([], dtype="datetime64[ns]")) == ""


def test_format_gap_comment_multiple_pairs():
    gap_limits = pd.Series([
        pd.Timestamp("2010-01-05"), pd.Timestamp("2010-01-07"),
        pd.Timestamp("2010-01-20"), pd.Timestamp("2010-01-25"),
    ])
    out = format_gap_comment(gap_limits)
    assert "Missing data period 1 = 2010-01-05 - 2010-01-07" in out
    assert "Missing data period 2 = 2010-01-20 - 2010-01-25" in out


def test_format_gap_comment_rejects_odd_length():
    with pytest.raises(ValueError, match="even"):
        format_gap_comment(pd.Series([pd.Timestamp("2010-01-05")]))


# ---------------------------------------------------------------------------
# write_wsc_rvt_file
# ---------------------------------------------------------------------------

def test_write_wsc_rvt_file_basic_format(tmp_path: Path):
    out = tmp_path / "WSC05NF002.rvt"
    written = write_wsc_rvt_file(
        out,
        station_name="GRASSMERE CREEK",
        station_id="05NF002",
        drainage_area_km2=128.5,
        outlet_sub_id=42,
        model_start=MODEL_START,
        model_end=MODEL_END,
        discharge_values=[1.234, 2.345, DEFAULT_MISSING_SENTINEL],
    )

    content = written.read_text()
    assert "# Name = GRASSMERE CREEK" in content
    assert "# ID = 05NF002" in content
    assert "# Drainage Area = 128 km2" in content   # int() truncation
    assert "# Sub-basin ID = 42" in content
    assert "# Date Range = 2010-01-01 - 2010-01-31" in content
    assert ":ObservationData\tHYDROGRAPH\t42\tm3/s" in content
    assert "    2010-01-01 00:00:00\t1\t3" in content
    assert "\t1.2340\n" in content
    assert "\t-1.2345\n" in content
    assert content.endswith(":EndObservationData")


def test_write_wsc_rvt_file_includes_gap_comment(tmp_path: Path):
    out = tmp_path / "WSC.rvt"
    write_wsc_rvt_file(
        out,
        station_name="X", station_id="Y",
        drainage_area_km2=1.0, outlet_sub_id=1,
        model_start=MODEL_START, model_end=MODEL_END,
        discharge_values=[1.0],
        gap_comment="# Missing data period 1 = 2010-01-10 - 2010-01-15 \n",
    )
    assert "Missing data period 1" in out.read_text()


# ---------------------------------------------------------------------------
# generate_wsc_rvt — end-to-end
# ---------------------------------------------------------------------------

def test_generate_wsc_rvt_end_to_end(tmp_path: Path):
    metadata = pd.DataFrame({
        "Station Name": ["GRASSMERE CREEK"],
        "Station Number": ["05NF002"],
    })
    metadata_csv = tmp_path / "metadata_05NF002.csv"
    metadata.to_csv(metadata_csv, index=False)

    # WSC daily files have a leading row that is skipped
    daily_path = tmp_path / "daily_05NF002.csv"
    with open(daily_path, "w") as f:
        f.write("# WSC export header\n")
        pd.DataFrame({
            "Date": ["2010-01-01", "2010-01-02", "2010-01-03"],
            "PARAM": [1, 1, 1],
            "Value": [1.5, np.nan, 2.5],
        }).to_csv(f, index=False)

    out = tmp_path / "WSC.rvt"
    generate_wsc_rvt(
        wsc_metadata_csv=metadata_csv,
        wsc_daily_csv=daily_path,
        output_path=out,
        model_start=MODEL_START,
        model_end=MODEL_END,
        outlet_sub_id=42,
        outlet_drainage_area_km2=128.5,
    )

    content = out.read_text()
    assert "# Name = GRASSMERE CREEK" in content
    assert "\t1.5000\n" in content
    assert "\t-1.2345\n" in content    # NaN replaced with sentinel
    assert "\t2.5000\n" in content


# ---------------------------------------------------------------------------
# resolve_model_window
# ---------------------------------------------------------------------------


from datetime import datetime
from pwa_raven.raven.wsc_rvt import resolve_model_window


def test_resolve_model_window_user_only():
    start, end = resolve_model_window(
        user_start="2010-01-01", user_end="2015-12-31",
    )
    assert start == datetime(2010, 1, 1)
    assert end == datetime(2015, 12, 31)


def test_resolve_model_window_intersect_with_nc():
    """NetCDF starts after user_start → resolved start = nc_start."""
    start, end = resolve_model_window(
        user_start="2000-01-01",
        user_end="2020-12-31",
        nc_dates=(datetime(2005, 1, 1), datetime(2018, 12, 31)),
    )
    assert start == datetime(2005, 1, 1)
    assert end == datetime(2018, 12, 31)


def test_resolve_model_window_intersect_with_wsc():
    start, end = resolve_model_window(
        user_start="2000-01-01",
        user_end="2025-12-31",
        wsc_dates=(datetime(2003, 6, 15), datetime(2019, 6, 15)),
    )
    assert start == datetime(2003, 6, 15)
    assert end == datetime(2019, 6, 15)


def test_resolve_model_window_intersect_with_both():
    """Tightest window wins on both ends."""
    start, end = resolve_model_window(
        user_start="2000-01-01",
        user_end="2025-12-31",
        nc_dates=(datetime(2005, 1, 1), datetime(2020, 12, 31)),
        wsc_dates=(datetime(2003, 1, 1), datetime(2018, 6, 30)),
    )
    assert start == datetime(2005, 1, 1)   # nc is tightest start
    assert end == datetime(2018, 6, 30)    # wsc is tightest end


def test_resolve_model_window_user_overrides_loose_sources():
    """User can request a tighter window even when sources span longer."""
    start, end = resolve_model_window(
        user_start="2010-01-01",
        user_end="2012-12-31",
        nc_dates=(datetime(2000, 1, 1), datetime(2020, 12, 31)),
        wsc_dates=(datetime(2000, 1, 1), datetime(2020, 12, 31)),
    )
    assert start == datetime(2010, 1, 1)
    assert end == datetime(2012, 12, 31)


def test_resolve_model_window_raises_on_empty_window():
    with pytest.raises(ValueError, match="empty"):
        resolve_model_window(
            user_start="2020-01-01",
            user_end="2025-12-31",
            nc_dates=(datetime(2000, 1, 1), datetime(2010, 12, 31)),
        )


def test_resolve_model_window_accepts_string_or_datetime():
    start, end = resolve_model_window(
        user_start=datetime(2010, 1, 1),
        user_end="2015-12-31",
    )
    assert start == datetime(2010, 1, 1)
    assert end == datetime(2015, 12, 31)


# ---------------------------------------------------------------------------
# resolve_model_window — forcing_margin_hours
# ---------------------------------------------------------------------------

from datetime import timedelta


def test_resolve_model_window_forcing_margin_pulls_nc_end_back():
    """720h (30d) margin should pull the resolved end ~30 days inside
    the NetCDF's last timestamp — the calibration runoff_offset shifts
    the forcing later in time, and the model must stop before the
    shifted forcing runs out."""
    nc_end = datetime(2018, 12, 28)
    start, end = resolve_model_window(
        user_start="1990-01-01",
        user_end="2030-01-01",
        nc_dates=(datetime(2003, 1, 1), nc_end),
        forcing_margin_hours=720.0,
    )
    assert start == datetime(2003, 1, 1)
    assert end == nc_end - timedelta(hours=720)
    # Sanity: 720h is 30 days, so end should land in late November 2018.
    assert end.month == 11 and end.year == 2018


def test_resolve_model_window_margin_zero_matches_unmargined():
    """Default 0 must reproduce the historical no-margin behaviour."""
    args = dict(
        user_start="2000-01-01",
        user_end="2025-12-31",
        nc_dates=(datetime(2005, 1, 1), datetime(2018, 12, 31)),
        wsc_dates=(datetime(2003, 6, 15), datetime(2019, 6, 15)),
    )
    no_margin = resolve_model_window(**args)
    with_zero = resolve_model_window(**args, forcing_margin_hours=0.0)
    assert no_margin == with_zero


def test_resolve_model_window_margin_doesnt_apply_when_wsc_is_tighter():
    """The margin protects against the forcing constraint specifically.
    When WSC's end already sits inside ``nc_end − margin``, WSC wins
    the intersect and the margin has no effect — that's the correct
    semantic, since the forcing has plenty of headroom anyway."""
    _start, end = resolve_model_window(
        user_start="2000-01-01",
        user_end="2025-12-31",
        nc_dates=(datetime(2005, 1, 1), datetime(2020, 12, 31)),
        wsc_dates=(datetime(2003, 1, 1), datetime(2018, 6, 30)),
        forcing_margin_hours=720.0,
    )
    assert end == datetime(2018, 6, 30)  # WSC end, not nc_end - 30d


def test_resolve_model_window_margin_noop_without_nc_dates():
    """No NetCDF in the constraint → nothing to reserve headroom from,
    margin is silently ignored."""
    _start, end = resolve_model_window(
        user_start="2010-01-01",
        user_end="2015-12-31",
        forcing_margin_hours=720.0,
    )
    assert end == datetime(2015, 12, 31)  # unchanged


def test_resolve_model_window_margin_can_empty_the_window():
    """A margin large enough to pull nc_end before nc_start (or before
    user_start) must raise the standard empty-window ValueError, with
    a hint pointing at the margin so the user knows what to lower."""
    with pytest.raises(ValueError, match="forcing_margin_hours"):
        resolve_model_window(
            user_start="2018-12-01",
            user_end="2020-01-01",
            nc_dates=(datetime(2003, 1, 1), datetime(2018, 12, 28)),
            forcing_margin_hours=24 * 365 * 20,  # 20 years of margin
        )


def test_resolve_model_window_margin_rejects_negative():
    """A negative margin would *extend* the model past the forcing —
    exactly the bug we're preventing. Reject at the boundary."""
    with pytest.raises(ValueError, match="forcing_margin_hours must be"):
        resolve_model_window(
            user_start="2010-01-01",
            user_end="2015-12-31",
            forcing_margin_hours=-1.0,
        )
