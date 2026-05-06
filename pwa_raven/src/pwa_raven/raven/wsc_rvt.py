"""WSC streamgauge RVT file generation for Raven.

Extracted from ``PWA/_notebooks/2_raven_input_gen.ipynb`` § 2.3.

The WSC (Water Survey of Canada) provides daily-mean streamflow CSVs. Raven
consumes these as ``:ObservationData HYDROGRAPH`` blocks in an ``.rvt`` file.
This module:

  1. Clips the WSC series to the model's simulation window.
  2. Identifies multi-day gaps (default >1.5 days) for the file header comment.
  3. Fills NaN discharge values with Raven's missing-value sentinel ``-1.2345``.
  4. Writes the .rvt file.

Behavioural improvement over the notebook: the original gated the entire
gap-formatting loop on ``if wsc_null_start:``, so the gap-comment string
came out empty unless the series happened to start with NaN. The check is
now lifted out — the ``wsc_null_start`` / ``wsc_null_end`` flags affect
only whether ``user_start`` / ``user_end`` get prepended/appended to the
gap list, not whether any gaps are reported at all.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_MISSING_SENTINEL = -1.2345
DEFAULT_GAP_THRESHOLD_DAYS = 1.5
PARAM_DISCHARGE = 1  # WSC PARAM code: 1 = discharge


def resolve_model_window(
    *,
    user_start: datetime | str,
    user_end: datetime | str,
    nc_dates: tuple[datetime, datetime] | None = None,
    wsc_dates: tuple[datetime, datetime] | None = None,
) -> tuple[datetime, datetime]:
    """Pick the largest model window covered by every input data source.

    The Raven model can only simulate a date range that all input sources
    cover. Returns:

      * ``start = max(user_start, nc_start, wsc_start)``
      * ``end   = min(user_end,   nc_end,   wsc_end)``

    Pass ``nc_dates`` and/or ``wsc_dates`` as ``(start, end)`` tuples
    when those sources are available; pass ``None`` to skip them
    (useful in tests).

    Raises ``ValueError`` if the resolved window is empty (start > end).

    Replaces the cell-34 inline ``max()/min()`` block in
    ``2_raven_input_gen.ipynb``.
    """
    starts: list[datetime] = [pd.to_datetime(user_start).to_pydatetime()]
    ends: list[datetime] = [pd.to_datetime(user_end).to_pydatetime()]

    if nc_dates is not None:
        starts.append(pd.to_datetime(nc_dates[0]).to_pydatetime())
        ends.append(pd.to_datetime(nc_dates[1]).to_pydatetime())

    if wsc_dates is not None:
        starts.append(pd.to_datetime(wsc_dates[0]).to_pydatetime())
        ends.append(pd.to_datetime(wsc_dates[1]).to_pydatetime())

    resolved_start = max(starts)
    resolved_end = min(ends)

    if resolved_start > resolved_end:
        raise ValueError(
            f"Resolved model window is empty: start={resolved_start} > "
            f"end={resolved_end}. Sources didn't overlap — check the "
            f"NetCDF time variable and WSC date range against your "
            f"requested user_start/user_end."
        )

    return resolved_start, resolved_end


def clip_to_model_window(
    wsc_raw: pd.DataFrame,
    model_start: datetime,
    model_end: datetime,
    *,
    date_col: str = "Date",
    param_col: str = "PARAM",
) -> pd.DataFrame:
    """Clip WSC raw frame to ``[model_start, model_end]`` and filter to discharge."""
    dates = pd.to_datetime(wsc_raw[date_col])
    in_window = (dates >= pd.to_datetime(model_start)) & (dates <= pd.to_datetime(model_end))
    clipped = wsc_raw[in_window]
    discharge = clipped[clipped[param_col] == PARAM_DISCHARGE].copy()
    logger.info(
        "WSC clip: %d raw rows → %d in window → %d discharge",
        len(wsc_raw), len(clipped), len(discharge),
    )
    return discharge


def find_data_gap_limits(
    discharge_df: pd.DataFrame,
    model_start: datetime,
    model_end: datetime,
    *,
    value_col: str = "Value",
    date_col: str = "Date",
    gap_threshold_days: float = DEFAULT_GAP_THRESHOLD_DAYS,
) -> pd.Series:
    """Identify the start/end timestamps of multi-day data gaps.

    Algorithm preserved verbatim from the notebook (Q-001 in
    project-review/client-questions.md — pending Thomas's confirmation that
    this is the intended behaviour). It compares *consecutive NaN
    timestamps* (not gaps between valid data) and flags NaN dates that are
    >*gap_threshold_days* apart from their neighbouring NaN. Implications:

      - **Contiguous NaN blocks are NOT detected** (consecutive nulls are
        always 1 day apart in a daily series). Only sparsely-distributed
        NaNs separated by valid data get flagged. This is a known limitation
        of the original notebook; the resulting "missing data" comment in
        the RVT header is therefore a partial inventory, not a complete one.
        It does not affect Raven's behaviour (the comment is informational).
      - If the series starts/ends with NaN, ``model_start`` / ``model_end``
        is prepended/appended to the limit list.

    Returns
    -------
    pandas.Series
        Sorted timestamps marking gap boundaries (always an even count, so
        :func:`format_gap_comment` can pair them).
    """
    null_dates = discharge_df.loc[discharge_df[value_col].isnull(), date_col]
    # Notebook hardcoded format='%Y/%m/%d' here, breaking ISO-formatted inputs.
    # pandas' default inference handles both YYYY/MM/DD and YYYY-MM-DD.
    null_dates = pd.to_datetime(null_dates)

    gap_threshold = pd.Timedelta(days=gap_threshold_days)
    forward_gap = (null_dates.shift(-1) - null_dates) > gap_threshold
    backward_gap = (null_dates - null_dates.shift(1)) > gap_threshold

    gap_limits = null_dates[forward_gap | backward_gap]
    isolated = null_dates[forward_gap & backward_gap]
    gap_limits = pd.concat([gap_limits, isolated]).sort_values().reset_index(drop=True)

    if len(discharge_df) > 0:
        if pd.isna(discharge_df[value_col].iloc[0]):
            gap_limits = pd.concat([pd.Series([pd.Timestamp(model_start)]), gap_limits])
        if pd.isna(discharge_df[value_col].iloc[-1]):
            gap_limits = pd.concat([gap_limits, pd.Series([pd.Timestamp(model_end)])])

    return gap_limits.reset_index(drop=True)


def format_gap_comment(gap_limits: pd.Series) -> str:
    """Format a Raven-RVT comment block listing missing-data periods.

    Pairs adjacent timestamps as ``(start, end)`` of each gap.

    The original notebook gated the loop body on ``wsc_null_start``,
    producing an empty string whenever the series started with valid
    data. We now always emit a comment line per pair, regardless of
    whether the series begins with NaN.
    """
    if len(gap_limits) == 0:
        return ""
    if len(gap_limits) % 2 != 0:
        raise ValueError(
            f"Gap limits must be even (start/end pairs); got {len(gap_limits)}."
        )

    lines: list[str] = []
    for i in range(0, len(gap_limits), 2):
        start_gap = gap_limits.iloc[i]
        end_gap = gap_limits.iloc[i + 1]
        lines.append(
            f"# Missing data period {i // 2 + 1} = "
            f"{start_gap.strftime('%Y-%m-%d')} - {end_gap.strftime('%Y-%m-%d')} "
        )
    return "\n".join(lines) + "\n"


def write_wsc_rvt_file(
    output_path: Path | str,
    *,
    station_name: str,
    station_id: str,
    drainage_area_km2: float,
    outlet_sub_id: int,
    model_start: datetime,
    model_end: datetime,
    discharge_values: list[float],
    gap_comment: str = "",
    missing_value_sentinel: float = DEFAULT_MISSING_SENTINEL,
) -> Path:
    """Write a Raven-format ``WSC<station_id>.rvt`` observation file.

    Format reference: Raven manual § 4.6 (:ObservationData).
    """
    output_path = Path(output_path)

    start_str = model_start.strftime("%Y-%m-%d")
    end_str = model_end.strftime("%Y-%m-%d")
    timestamp_str = model_start.strftime("%Y-%m-%d %H:%M:%S")
    n_points = len(discharge_values)

    header = (
        "#################################################################################\n"
        f"# Name = {station_name}\n"
        f"# ID = {station_id}\n"
        f"# Drainage Area = {int(drainage_area_km2)} km2\n"
        f"# Sub-basin ID = {outlet_sub_id}\n"
        "# Natural/Reference = Regulated\n"
        "# Country = CA\n"
        f"# Date Range = {start_str} - {end_str}\n"
        "# Data time-step = 24 hr\n"
        f"{gap_comment}"
        f"# Missing data are filled with {missing_value_sentinel}\n"
        "##################################################################################\n"
        f":ObservationData\tHYDROGRAPH\t{outlet_sub_id}\tm3/s\n"
        f"    {timestamp_str}\t1\t{n_points}\n"
    )

    body = "".join(f"\t{v:.4f}\n" for v in discharge_values)
    footer = ":EndObservationData"

    output_path.write_text(header + body + footer)
    logger.info("Wrote WSC RVT %s (%d points) → %s", station_id, n_points, output_path)
    return output_path


def generate_wsc_rvt(
    *,
    wsc_metadata_csv: Path | str,
    wsc_daily_csv: Path | str,
    output_path: Path | str,
    model_start: datetime,
    model_end: datetime,
    outlet_sub_id: int,
    outlet_drainage_area_km2: float,
    gap_threshold_days: float = DEFAULT_GAP_THRESHOLD_DAYS,
    missing_value_sentinel: float = DEFAULT_MISSING_SENTINEL,
) -> Path:
    """End-to-end: read WSC CSVs, clip + analyze gaps, write RVT.

    Parameters
    ----------
    wsc_metadata_csv
        WSC ``metadata_*.csv`` file containing station name + number.
    wsc_daily_csv
        WSC ``daily_*.csv`` file with discharge timeseries (skipped row 0).
    output_path
        Destination ``WSC<station_id>.rvt`` path.
    model_start, model_end
        Simulation window — discharge outside is dropped.
    outlet_sub_id, outlet_drainage_area_km2
        Identify the receiving sub-basin for the gauge (typically from
        :func:`pwa_raven.raven.basin_prep.find_watershed_outlet`).
    """
    metadata = pd.read_csv(str(wsc_metadata_csv))
    raw = pd.read_csv(str(wsc_daily_csv), skiprows=1)

    station_name = str(metadata["Station Name"].iloc[0])
    station_id = str(metadata["Station Number"].iloc[0])

    discharge = clip_to_model_window(raw, model_start, model_end)
    gap_limits = find_data_gap_limits(
        discharge, model_start, model_end,
        gap_threshold_days=gap_threshold_days,
    )
    gap_comment = format_gap_comment(gap_limits)

    discharge_filled = discharge["Value"].fillna(missing_value_sentinel)

    return write_wsc_rvt_file(
        output_path,
        station_name=station_name,
        station_id=station_id,
        drainage_area_km2=outlet_drainage_area_km2,
        outlet_sub_id=outlet_sub_id,
        model_start=model_start,
        model_end=model_end,
        discharge_values=list(discharge_filled),
        gap_comment=gap_comment,
        missing_value_sentinel=missing_value_sentinel,
    )
