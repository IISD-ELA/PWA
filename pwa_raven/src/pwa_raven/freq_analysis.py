"""Flood frequency analysis — Log-Pearson III via L-moments.

Replaces the R-subprocess workflow from ``local/flood_freq_report.ipynb``.
All statistical calculations use ``lmoments3`` (L-moment fitting) and
``scipy`` (distributions, GoF tests).

Public API
----------
``export_wy_summary(data_path, output_dir, ...)``
    Load daily flow data → water-year summary → LP3 analysis →
    return enriched table with an estimated return period for every year.
    Returns ``(FreqAnalysisResult, flow_df)``.

``generate_freq_report(flow_df, result, output_dir, watershed_name)``
    Generate diagnostic plots and a Markdown frequency analysis report.
    Returns the ``Path`` of the report file.

Private helpers (``_`` prefix) are module-level for direct testing and for
the R-comparison regression suite.
"""

from __future__ import annotations

import logging
import pathlib
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import pearson3

warnings.filterwarnings("ignore", category=RuntimeWarning)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MONTH_DAYS = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365])
_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan",
]

# Non-exceedance probability grid used for the frequency-curve plot and CI.
# Matches R lmomco::nonexceeds() closely.
_PLOT_NEP = np.array([
    0.001, 0.002, 0.005, 0.010, 0.020, 0.050,
    0.100, 0.200, 0.300, 0.400, 0.500, 0.600, 0.700,
    0.800, 0.900, 0.950, 0.975, 0.990, 0.995, 0.998,
])

# Standard return periods used in the recurrence table
_STANDARD_RPS = np.array([2, 5, 10, 20, 50])
_STANDARD_NEP = 1.0 - 1.0 / _STANDARD_RPS

# Months considered "spring" for peak-flow classification (March–June)
_SPRING_MONTHS = frozenset({3, 4, 5, 6})


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FreqAnalysisResult:
    """Bundled outputs from :func:`export_wy_summary`.

    Attributes
    ----------
    wy_summary
        Water-year summary with columns ``WaterYear``, ``PeakFlow``,
        ``TotalVolume``, ``Type``, ``IsPILF``, ``EstimatedReturnPeriod``.
    lp3_params
        Fitted PE3 parameters in log10 space: ``{'loc', 'scale', 'skew'}``.
    mgbt_threshold
        MGBT low-outlier threshold (original flow units).
    n_pilf
        Number of years identified as potentially influential low floods.
    bootstrap_ci
        Bootstrap confidence-interval DataFrame with columns
        ``{nonexceed_prob, lower, true, upper}`` at ``_PLOT_NEP``.
    gof
        Goodness-of-fit dict: ``{ad_stat, ad_pval, cvm_stat, cvm_pval}``.
    standard_return_periods
        Design-flow table at standard return periods:
        ``{ReturnPeriod, nep, Q, NearestEvent}``.
    """

    wy_summary: pd.DataFrame
    lp3_params: dict
    mgbt_threshold: float
    n_pilf: int
    bootstrap_ci: pd.DataFrame
    gof: dict
    standard_return_periods: pd.DataFrame


# ---------------------------------------------------------------------------
# Section 1: Load and clean flow data
# ---------------------------------------------------------------------------


def _calculate_water_year(date_series: pd.Series, origin_month: int = 10) -> pd.Series:
    """Return the water year for each date.

    Dates on or after *origin_month* belong to the *following* calendar year's
    water year (North American convention: October start → WY runs Oct–Sep).
    """
    return date_series.dt.year.where(
        date_series.dt.month < origin_month,
        date_series.dt.year + 1,
    )


def _load_flow_data(
    filepath: str | Path,
    param_id: int = 1,
    start_year: int | None = None,
    end_year: int | None = None,
    wsc_id: str | None = None,
) -> pd.DataFrame:
    """Load and clean daily flow data from a WSC-style CSV.

    The file is expected to have one metadata/comment row followed by a
    header row with columns ``ID``, ``PARAM``, ``Date``, ``Value``, ``SYM``.

    Parameters
    ----------
    filepath:
        Path to the CSV.
    param_id:
        PARAM value to keep (1 = flow, 2 = water level, …).
    start_year, end_year:
        Inclusive year filters.
    wsc_id:
        WSC station ID to extract.  If ``None``, the file must contain
        exactly one distinct ID; otherwise a ``ValueError`` is raised
        listing the IDs found.

    Returns
    -------
    DataFrame with columns ``Date`` (datetime) and ``Value`` (float).
    """
    df = pd.read_csv(filepath, header=0, skiprows=1)
    df.columns = df.columns.str.strip()
    df = df[df["PARAM"] == param_id][["ID", "Date", "Value"]].copy()

    # --- Station ID resolution ---
    distinct_ids = df["ID"].unique().tolist()
    if wsc_id is not None:
        if wsc_id not in distinct_ids:
            raise ValueError(
                f"wsc_id '{wsc_id}' not found in the data. "
                f"Available station IDs: {distinct_ids}"
            )
        df = df[df["ID"] == wsc_id]
        logger.info("Filtering flow data to station ID '%s'", wsc_id)
    else:
        if len(distinct_ids) > 1:
            raise ValueError(
                f"The data contains {len(distinct_ids)} station IDs but no "
                f"wsc_id was specified. Please provide wsc_id. "
                f"Station IDs found: {distinct_ids}"
            )
        logger.info("Auto-selected single station ID '%s'", distinct_ids[0])

    df = df[["Date", "Value"]].copy()
    df["Date"] = pd.to_datetime(df["Date"], format="%Y/%m/%d")
    if start_year is not None:
        df = df[df["Date"].dt.year >= start_year]
    if end_year is not None:
        df = df[df["Date"].dt.year <= end_year]
    df = df.dropna(subset=["Value"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Section 1b: Flow event detection (Python port of hydroEvents::eventMinima)
# ---------------------------------------------------------------------------


def _local_min(data: np.ndarray) -> np.ndarray:
    """Indices of local minima in *data* (0-based).

    Mirrors hydroEvents::localMin (R package):
    - Repeated values → first index of each run.
    - Trailing boundary counts as a minimum if the series is still falling.
    - Leading boundary counts as a minimum only when the first value is not a
      repeat AND the series rises away from it.
    """
    x = np.asarray(data, dtype=float)
    n = len(x)
    if n < 2:
        return np.array([], dtype=int)

    # Collapse consecutive duplicates → first occurrence
    keep = np.ones(n, dtype=bool)
    keep[1:] = x[1:] != x[:-1]
    idx_unique = np.flatnonzero(keep)
    x_unique = x[idx_unique]
    m = len(x_unique)

    minima_positions: list[int] = []

    # Interior: strictly lower than both neighbours
    for k in range(1, m - 1):
        if x_unique[k - 1] > x_unique[k] < x_unique[k + 1]:
            minima_positions.append(k)

    # Trailing boundary
    if m >= 2 and x_unique[-1] < x_unique[-2]:
        minima_positions.append(m - 1)

    # Leading boundary: only if not a repeated first value
    if m >= 2 and x[0] != x[1] and x_unique[0] < x_unique[1]:
        minima_positions.insert(0, 0)

    minima_positions = sorted(set(minima_positions))
    return idx_unique[minima_positions]


def _calc_stats(
    srt: np.ndarray,
    end: np.ndarray,
    data: np.ndarray,
    f_vec: tuple = ("which.max", "max", "sum"),
) -> pd.DataFrame:
    """Per-event statistics for the subset of *data* in [srt, end] (inclusive).

    ``which.max`` is an absolute index into *data*, not relative to the window.
    """
    x = np.asarray(data, dtype=float)
    rows = []
    for s, e in zip(srt, end):
        window = x[s : e + 1]
        row: dict = {}
        for f in f_vec:
            if f == "which.max":
                row["which.max"] = s + int(np.argmax(window))
            elif f == "max":
                row["max"] = float(np.max(window))
            elif f == "min":
                row["min"] = float(np.min(window))
            elif f == "sum":
                row["sum"] = float(np.sum(window))
            else:
                raise ValueError(f"Unsupported stat: {f}")
        rows.append(row)
    return pd.DataFrame(rows, columns=list(f_vec))


def _event_minima(
    data,
    delta_y: float = 20,
    delta_x: float = 5,
    threshold: float = -1,
    out_style: str = "summary",
):
    """Identify flow events based on local minima (Python port of hydroEvents::eventMinima).

    Events are bounded by pairs of local minima satisfying:
    - ``(x2 - x1) > delta_x``  (far enough apart in time)
    - ``(y2 - y1) < delta_y``  (close enough in flow value)

    Parameters
    ----------
    data : array-like
    delta_y : float
        Maximum trough-value difference.
    delta_x : float
        Minimum index gap between bounding troughs.
    threshold : float
        Values at or below this level are trimmed from event edges and events
        whose max is below this level are dropped.  Negative → disabled.
    out_style : {"summary", "none"}
        "summary" adds which.max / max / sum columns.

    Returns
    -------
    pandas.DataFrame or None
    """
    x = np.asarray(data, dtype=float)
    minima = _local_min(x)
    n_minima = len(minima)

    srt_index: list[int] = []
    end_index: list[int] = []

    i, j = 0, 1
    while j < n_minima:
        x1, x2 = minima[i], minima[j]
        y1, y2 = x[x1], x[x2]

        if (x2 - x1) > delta_x and (y2 - y1) < delta_y:
            srt_index.append(x1)
            end_index.append(x2)
            i = j
            j = i + 1
        else:
            j += 1

    srt_arr = np.array(srt_index, dtype=int)
    end_arr = np.array(end_index, dtype=int)

    # Drop events whose max is below threshold
    if threshold > 0 and len(srt_arr) > 0:
        maxima = _calc_stats(srt_arr, end_arr, x, f_vec=("max",))["max"].to_numpy()
        keep = maxima >= threshold
        srt_arr = srt_arr[keep]
        end_arr = end_arr[keep]

    n_events = len(srt_arr)
    if n_events == 0:
        return None

    # Trim leading/trailing runs at-or-below threshold from each event
    if threshold >= 0:
        for i in range(n_events):
            event_data = x[srt_arr[i] : end_arr[i] + 1]
            below = event_data <= threshold

            if below[0]:
                run_len = len(below) if below.all() else int(np.argmax(~below))
                srt_arr[i] += run_len

            if below[-1]:
                run_len = len(below) if below.all() else int(np.argmax(~below[::-1]))
                end_arr[i] -= run_len

    if out_style == "summary":
        stats = _calc_stats(srt_arr, end_arr, x, f_vec=("which.max", "max", "sum"))
        return pd.concat(
            [pd.DataFrame({"srt": srt_arr, "end": end_arr}), stats], axis=1
        )
    else:
        return pd.DataFrame({"srt": srt_arr, "end": end_arr})


def _identify_flow_events(
    df: pd.DataFrame,
    delta_y: float = 20,
    delta_x: int = 5,
    threshold: float = 0,
) -> pd.DataFrame:
    """Identify discrete flow events in daily flow data.

    Wraps :func:`_event_minima` and enriches the result with date and volume
    columns derived from *df*.

    Parameters
    ----------
    df : DataFrame with columns ``Date`` (datetime) and ``Value`` (m³/s).
    delta_y : trough-value difference threshold.
    delta_x : minimum event length in days.
    threshold : flow threshold; events below this are dropped / trimmed.

    Returns
    -------
    DataFrame with columns:
        ``start_date``, ``end_date``, ``peak_date``, ``PeakFlow``,
        ``total_volume_m3``.
    Returns an empty DataFrame (not None) when no events are detected.
    """
    _EMPTY = pd.DataFrame(
        columns=["start_date", "end_date", "peak_date", "PeakFlow", "total_volume_m3"]
    )
    raw = _event_minima(
        df["Value"].to_numpy(),
        delta_y=delta_y,
        delta_x=delta_x,
        threshold=threshold,
        out_style="summary",
    )
    if raw is None:
        return _EMPTY

    events = raw.copy()
    dates = df["Date"].reset_index(drop=True)
    events["start_date"] = dates.iloc[events["srt"]].values
    events["end_date"] = dates.iloc[events["end"]].values
    events["peak_date"] = dates.iloc[events["which.max"]].values
    events["PeakFlow"] = events["max"]
    events["total_volume_m3"] = events["sum"] * 86_400  # daily m³/s → m³

    events.drop(columns=["srt", "end", "which.max", "max", "sum"], inplace=True)
    return events.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Section 2: Water-year summary
# ---------------------------------------------------------------------------


def _summarize_by_water_year(df: pd.DataFrame, origin_month: int = 10) -> pd.DataFrame:
    """Compute annual peak flow, total volume, and flow type by water year.

    Parameters
    ----------
    df:
        DataFrame with columns ``Date`` (datetime) and ``Value`` (m³/s).
    origin_month:
        Month the water year begins (default 10 for October).

    Returns
    -------
    DataFrame with columns:
    ``WaterYear``, ``PeakFlowDate``, ``PeakFlow``, ``TotalVolume``, ``Type``.
    """
    work = df.copy()
    work["WaterYear"] = _calculate_water_year(work["Date"], origin_month)

    rows = []
    for wy in sorted(work["WaterYear"].unique()):
        wy_data = work[work["WaterYear"] == wy]
        peak_idx = wy_data["Value"].idxmax()
        peak_flow = wy_data.loc[peak_idx, "Value"]
        peak_date = wy_data.loc[peak_idx, "Date"]
        total_vol = (wy_data["Value"] * 86_400).sum()
        flow_type = "Spring" if 3 <= peak_date.month <= 6 else "Annual"
        rows.append(
            {
                "WaterYear": wy,
                "PeakFlowDate": peak_date,
                "PeakFlow": peak_flow,
                "TotalVolume": total_vol,
                "Type": flow_type,
            }
        )
    return pd.DataFrame(rows)


def _summarize_wy_from_events(
    events_df: pd.DataFrame,
    flow_df: pd.DataFrame,
    origin_month: int = 10,
) -> pd.DataFrame:
    """Build a water-year summary from detected flow events.

    For each water year:

    - Finds the **annual peak event** (highest ``PeakFlow``, any date).
    - Finds the **spring peak event** (highest ``PeakFlow`` with ``peak_date``
      in March–June).
    - If they are the **same event**, includes it once (labelled "Spring" if
      the peak month is Mar–Jun, otherwise "Annual").
    - If they are **different events**, includes **both**.
    - If **no events** fall in the water year, falls back to the daily-maximum
      approach (one row, labelled by peak month).

    Parameters
    ----------
    events_df : DataFrame from :func:`_identify_flow_events`.
    flow_df : Cleaned daily flow DataFrame (``Date``, ``Value``); used for
        the fallback year calculation and fallback ``TotalVolume``.
    origin_month : First month of the water year (default 10).

    Returns
    -------
    DataFrame with columns:
        ``WaterYear``, ``PeakFlowDate``, ``PeakFlow``, ``TotalVolume``, ``Type``.
    """
    flow_work = flow_df.copy()
    flow_work["WaterYear"] = _calculate_water_year(flow_work["Date"], origin_month)
    all_wys = sorted(flow_work["WaterYear"].unique())

    # Assign a water year to every event based on peak_date
    ev = events_df.copy()
    if not ev.empty:
        ev["WaterYear"] = _calculate_water_year(
            pd.Series(pd.to_datetime(ev["peak_date"])), origin_month
        ).values

    rows: list[dict] = []
    for wy in all_wys:
        wy_events = pd.DataFrame() if ev.empty else ev[ev["WaterYear"] == wy]

        if wy_events.empty:
            # Fallback: daily maximum for this water year
            wy_daily = flow_work[flow_work["WaterYear"] == wy]
            peak_idx = wy_daily["Value"].idxmax()
            peak_flow = float(wy_daily.loc[peak_idx, "Value"])
            peak_date = wy_daily.loc[peak_idx, "Date"]
            total_vol = float((wy_daily["Value"] * 86_400).sum())
            flow_type = "Spring" if peak_date.month in _SPRING_MONTHS else "Annual"
            rows.append({
                "WaterYear": wy,
                "PeakFlowDate": peak_date,
                "PeakFlow": peak_flow,
                "TotalVolume": total_vol,
                "Type": flow_type,
                "EventStart": wy_daily["Date"].min(),
                "EventEnd": wy_daily["Date"].max(),
            })
            continue
        
        # Annual peak: highest PeakFlow regardless of date
        annual_row = wy_events.loc[wy_events["PeakFlow"].idxmax()]
        annual_is_spring = pd.to_datetime(annual_row["peak_date"]).month in _SPRING_MONTHS

        rows.append({
            "WaterYear": wy,
            "PeakFlowDate": pd.to_datetime(annual_row["peak_date"]),
            "PeakFlow": float(annual_row["PeakFlow"]),
            "TotalVolume": float(annual_row["total_volume_m3"]),
            "Type": "Spring" if annual_is_spring else "Annual",
            "EventStart": pd.to_datetime(annual_row["start_date"]),
            "EventEnd": pd.to_datetime(annual_row["end_date"]),
        })

        # Spring peak: highest PeakFlow in Mar–Jun, only if distinct from annual
        if not annual_is_spring:
            spring_events = wy_events[
                pd.to_datetime(wy_events["peak_date"]).dt.month.isin(_SPRING_MONTHS)
            ]
            if not spring_events.empty:
                spring_row = spring_events.loc[spring_events["PeakFlow"].idxmax()]
                rows.append({
                    "WaterYear": wy,
                    "PeakFlowDate": pd.to_datetime(spring_row["peak_date"]),
                    "PeakFlow": float(spring_row["PeakFlow"]),
                    "TotalVolume": float(spring_row["total_volume_m3"]),
                    "Type": "Spring",
                    "EventStart": pd.to_datetime(spring_row["start_date"]),
                    "EventEnd": pd.to_datetime(spring_row["end_date"]),
                })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Section 3: Multiple Grubbs-Beck Test (MGBT)
# ---------------------------------------------------------------------------


def _mgbt(series: np.ndarray, alpha: float = 0.10) -> float:
    """Multiple Grubbs-Beck Test for Potentially Influential Low Floods (PILFs).

    Tests annual peak flows iteratively from the smallest upward using a
    Bonferroni-corrected Grubbs critical value.  Returns the low-outlier
    threshold: the smallest value that is *not* a PILF.  Values strictly
    below the threshold should be treated as PILFs.

    Parameters
    ----------
    series:
        Annual peak-flow series (positive values, original flow units).
    alpha:
        Overall significance level (default 0.10).

    Returns
    -------
    float
        Low-outlier threshold in the original flow units.
    """
    log_s = np.log10(np.asarray(series, dtype=float))
    n = len(log_s)
    sorted_log = np.sort(log_s)

    mu = np.mean(log_s)
    sigma = np.std(log_s, ddof=1)

    if sigma <= 0 or n < 4:
        return 10.0 ** sorted_log[0]

    max_tests = max(n // 2, 1)

    # Bonferroni-corrected Grubbs critical value (one-sided lower tail).
    # K_crit = ((n-1)/√n) · t_{α/(2·max_tests), n-2} / √(n-2 + t²)
    alpha_adj = alpha / max_tests
    t_crit = stats.t.ppf(1.0 - alpha_adj / 2.0, df=n - 2)
    k_crit = ((n - 1) / np.sqrt(n)) * t_crit / np.sqrt(n - 2 + t_crit ** 2)

    lo_thresh_log = sorted_log[0]  # Default: no PILFs → threshold = minimum

    for k in range(max_tests):
        k_stat = (mu - sorted_log[k]) / sigma
        if k_stat > k_crit:
            # sorted_log[k] is a PILF; threshold is the next value above it
            lo_thresh_log = sorted_log[k + 1] if k + 1 < n else sorted_log[k]
        else:
            break

    return float(10.0 ** lo_thresh_log)


# ---------------------------------------------------------------------------
# Section 4: LP3 distribution fitting and inference (via lmoments3)
# ---------------------------------------------------------------------------


def _fit_lp3(series: np.ndarray) -> dict:
    """Fit a Log-Pearson III distribution to annual peak flows.

    Applies a log10 transform then fits a Pearson Type III (PE3) distribution
    using the method of L-moments (matching R's ``lmomco::lmom2par``).

    Parameters
    ----------
    series:
        Annual peak-flow series (positive, original flow units).

    Returns
    -------
    dict with keys ``'loc'`` (mean in log10 space), ``'scale'`` (std dev),
    ``'skew'`` (skewness coefficient).  These parameters are in log10 space.
    """
    from lmoments3 import distr, lmom_ratios  # lazy import

    log_s = np.log10(np.asarray(series, dtype=float))
    lmom = lmom_ratios(log_s, nmom=4)
    params = distr.pe3.lmom_fit(lmom_ratios=lmom)
    return dict(params)  # {'loc': ..., 'scale': ..., 'skew': ...}


def _lp3_quantiles(params: dict, nep: np.ndarray) -> np.ndarray:
    """Return LP3 flood quantiles (original flow units) at given NEP values.

    Parameters
    ----------
    params:
        PE3 parameters in log10 space (from :func:`_fit_lp3`).
    nep:
        Array of non-exceedance probabilities in (0, 1).
    """
    log_q = pearson3.ppf(nep, skew=params["skew"], loc=params["loc"], scale=params["scale"])
    return 10.0 ** log_q


def _lp3_return_period(flows: np.ndarray, params: dict) -> np.ndarray:
    """Estimate the LP3 return period for each observed flow value.

    Parameters
    ----------
    flows:
        Array of peak-flow values (original units).
    params:
        PE3 parameters in log10 space (from :func:`_fit_lp3`).

    Returns
    -------
    Array of return periods in years (same length as *flows*).
    """
    log_q = np.log10(np.asarray(flows, dtype=float))
    cdf = pearson3.cdf(log_q, skew=params["skew"], loc=params["loc"], scale=params["scale"])
    cdf = np.clip(cdf, 1e-9, 1.0 - 1e-9)
    return 1.0 / (1.0 - cdf)


# ---------------------------------------------------------------------------
# Section 5: Bootstrap confidence intervals
# ---------------------------------------------------------------------------


def _bootstrap_ci(
    series: np.ndarray,
    params: dict,
    nep: np.ndarray,
    n_resamples: int = 10_000,
    ci: float = 0.90,
    seed: int | None = None,
) -> pd.DataFrame:
    """Bootstrap 90 % confidence intervals for LP3 quantiles.

    Matches the approach in R's ``BootstrapCI``: samples from the fitted PE3
    distribution, refits L-moments for each resample, then collects the
    empirical CI of quantile estimates.

    Parameters
    ----------
    series:
        Original annual peak-flow series (original units; used for sample size).
    params:
        Fitted PE3 parameters in log10 space (from :func:`_fit_lp3`).
    nep:
        Non-exceedance probabilities at which to compute CI bounds.
    n_resamples:
        Number of bootstrap resamples.
    ci:
        Confidence level (default 0.90 for 90 % CI).
    seed:
        Random seed for reproducibility.

    Returns
    -------
    DataFrame with columns ``nonexceed_prob``, ``lower``, ``true``, ``upper``.
    """
    from lmoments3 import distr, lmom_ratios  # lazy import

    rng = np.random.default_rng(seed)
    n = len(series)
    nep = np.asarray(nep, dtype=float)

    true_q = _lp3_quantiles(params, nep)

    boot_list: list[np.ndarray] = []
    for _ in range(n_resamples):
        sample = pearson3.rvs(
            skew=params["skew"],
            loc=params["loc"],
            scale=params["scale"],
            size=n,
            random_state=rng,
        )
        try:
            lmom_i = lmom_ratios(sample, nmom=4)
            p_i = distr.pe3.lmom_fit(lmom_ratios=lmom_i)
            q_i = 10.0 ** pearson3.ppf(
                nep,
                skew=p_i["skew"],
                loc=p_i["loc"],
                scale=p_i["scale"],
            )
            if np.all(np.isfinite(q_i)):
                boot_list.append(q_i)
        except Exception:
            continue

    if boot_list:
        boot_arr = np.vstack(boot_list)
        p_lo = (1.0 - ci) / 2.0 * 100.0
        p_hi = (1.0 + ci) / 2.0 * 100.0
        lower = np.percentile(boot_arr, p_lo, axis=0)
        upper = np.percentile(boot_arr, p_hi, axis=0)
    else:
        lower = np.full(len(nep), np.nan)
        upper = np.full(len(nep), np.nan)

    return pd.DataFrame(
        {"nonexceed_prob": nep, "lower": lower, "true": true_q, "upper": upper}
    )


# ---------------------------------------------------------------------------
# Section 6: Goodness-of-fit tests (Anderson-Darling + Cramér-von Mises)
# ---------------------------------------------------------------------------


def _gof_tests(
    series: np.ndarray,
    params: dict,
    n_sim: int = 1_000,
    seed: int | None = None,
) -> dict:
    """Simulation-based Anderson-Darling and Cramér-von Mises GoF tests.

    Tests the LP3 (PE3 in log10 space) fit against the observed annual peak
    flows.  P-values are estimated by simulation from the fitted distribution,
    matching the approach in ``freq_analysis_src.R``.

    Parameters
    ----------
    series:
        Annual peak-flow series (original flow units).
    params:
        Fitted PE3 parameters in log10 space (from :func:`_fit_lp3`).
    n_sim:
        Number of Monte Carlo replicates for p-value estimation.
    seed:
        Random seed.

    Returns
    -------
    dict with keys ``ad_stat``, ``ad_pval``, ``cvm_stat``, ``cvm_pval``.
    """
    rng = np.random.default_rng(seed)
    log_s = np.sort(np.log10(np.asarray(series, dtype=float)))
    n = len(log_s)
    i_vec = np.arange(1, n + 1, dtype=float)

    def _theo_cdf(x: np.ndarray) -> np.ndarray:
        c = pearson3.cdf(x, skew=params["skew"], loc=params["loc"], scale=params["scale"])
        return np.clip(c, 1e-9, 1.0 - 1e-9)

    def _ad(sorted_x: np.ndarray, theo: np.ndarray) -> float:
        rev = theo[::-1]
        return float(-n - np.sum((2.0 * i_vec - 1.0) * (np.log(theo) + np.log(1.0 - rev))) / n)

    def _cvm(emp: np.ndarray, theo: np.ndarray) -> float:
        return float(np.sum((emp - theo) ** 2) + 1.0 / (12.0 * n))

    emp_cdf = i_vec / (n + 1)
    theo_obs = _theo_cdf(log_s)
    ad_obs = _ad(log_s, theo_obs)
    cvm_obs = _cvm(emp_cdf, theo_obs)

    ad_sim = np.empty(n_sim)
    cvm_sim = np.empty(n_sim)
    for i in range(n_sim):
        sim = np.sort(
            pearson3.rvs(
                skew=params["skew"],
                loc=params["loc"],
                scale=params["scale"],
                size=n,
                random_state=rng,
            )
        )
        theo_i = _theo_cdf(sim)
        ad_sim[i] = _ad(sim, theo_i)
        cvm_sim[i] = _cvm(emp_cdf, theo_i)

    return {
        "ad_stat": float(ad_obs),
        "ad_pval": float(np.mean(ad_sim >= ad_obs)),
        "cvm_stat": float(cvm_obs),
        "cvm_pval": float(np.mean(cvm_sim >= cvm_obs)),
    }


# ---------------------------------------------------------------------------
# Section 7: Diagnostic plots
# ---------------------------------------------------------------------------


def _plot_daily_statistics(
    df: pd.DataFrame,
    start_year: int | None = None,
    end_year: int | None = None,
    title: str = "Daily Flow Statistics",
) -> plt.Figure:
    """Plot multi-year daily min/median/max ribbon and Q25–Q75 band."""
    work = df.copy()
    if start_year is not None:
        work = work[work["Date"].dt.year >= start_year]
    if end_year is not None:
        work = work[work["Date"].dt.year <= end_year]

    work["DayOfYear"] = work["Date"].dt.dayofyear
    daily = work.groupby("DayOfYear")["Value"].agg(
        Minimum="min",
        Q25=lambda x: x.quantile(0.25),
        Median="median",
        Q75=lambda x: x.quantile(0.75),
        Maximum="max",
    ).reset_index()

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.fill_between(daily["DayOfYear"], daily["Minimum"], daily["Maximum"],
                    alpha=0.3, color="lightblue", label="Min-Max Range")
    ax.fill_between(daily["DayOfYear"], daily["Q25"], daily["Q75"],
                    alpha=0.3, color="steelblue", label="Q25–Q75")
    ax.plot(daily["DayOfYear"], daily["Median"], color="black", linewidth=2, label="Median")
    ax.set_xticks(_MONTH_DAYS)
    ax.set_xticklabels(_MONTH_LABELS)
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Flow (m³/s)", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    return fig


def _plot_annual_statistics(
    df: pd.DataFrame,
    title: str = "Annual Flow Statistics",
) -> plt.Figure:
    """Scatter plot of annual peak flows by water year, coloured by type."""
    fig, ax = plt.subplots(figsize=(12, 6))
    for flow_type, colour in (("Spring", "blue"), ("Annual", "red")):
        sub = df[df["Type"] == flow_type]
        if not sub.empty:
            ax.scatter(sub["WaterYear"], sub["PeakFlow"],
                       label=flow_type, alpha=0.6, s=60, color=colour)
    ax.set_xlabel("Water Year", fontsize=12)
    ax.set_ylabel("Peak Flow (m³/s)", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    return fig


def _plot_daily_minmax_with_overlay(
    df: pd.DataFrame,
    overlay_years: list[int] | None = None,
    title: str = "Daily Flow with Selected Years",
) -> plt.Figure:
    """Daily min/max ribbon with individual years highlighted."""
    overlay_years = overlay_years or []
    work = df.copy()
    work["DayOfYear"] = work["Date"].dt.dayofyear
    work["Year"] = work["Date"].dt.year

    daily = work.groupby("DayOfYear")["Value"].agg(
        Minimum="min", Median="median", Maximum="max"
    ).reset_index()

    palette = ["blue", "green", "orange", "purple", "red", "cyan"]
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.fill_between(daily["DayOfYear"], daily["Minimum"], daily["Maximum"],
                    alpha=0.3, color="lightblue", label="Min-Max Range")
    ax.plot(daily["DayOfYear"], daily["Median"], color="black", linewidth=2, label="Median")

    overlay = work[work["Year"].isin(overlay_years)]
    for i, yr in enumerate(overlay_years):
        yr_data = overlay[overlay["Year"] == yr].sort_values("DayOfYear")
        if not yr_data.empty:
            ax.plot(yr_data["DayOfYear"], yr_data["Value"],
                    color=palette[i % len(palette)], linewidth=1.5,
                    label=str(yr), alpha=0.8)

    ax.set_xticks(_MONTH_DAYS)
    ax.set_xticklabels(_MONTH_LABELS)
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Flow (m³/s)", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    return fig


def _plot_frequency_curve(
    wy_summary: pd.DataFrame,
    ci: pd.DataFrame,
    watershed_name: str = "",
) -> plt.Figure:
    """Flood frequency curve on a normal-probability (Gumbel) scale.

    Observed annual peak flows are plotted as points using the Weibull
    plotting position.  The fitted LP3 curve and 90 % CI band are overlaid.

    Parameters
    ----------
    wy_summary:
        Water-year summary with column ``PeakFlow``.
    ci:
        Bootstrap CI DataFrame with columns
        ``{nonexceed_prob, lower, true, upper}``.
    watershed_name:
        Used in the plot title.
    """
    from scipy.stats import norm

    series = np.sort(wy_summary["PeakFlow"].values)
    n = len(series)
    pp = np.arange(1, n + 1) / (n + 1)

    xbreaks = np.array([0.002, 0.01, 0.10, 0.25, 0.50, 0.80, 0.90, 0.95, 0.975, 0.99, 0.995, 0.998])
    rp_labels = 1.0 / (1.0 - xbreaks)

    all_vals = np.concatenate([series, ci[["lower", "upper"]].values.flatten()])
    all_vals = all_vals[all_vals > 0]
    log_lo = np.floor(np.log10(np.nanmin(all_vals)))
    log_hi = np.ceil(np.log10(np.nanmax(all_vals)))
    ybreaks: list[float] = []
    cap = 10.0 ** log_lo
    while cap < 10.0 ** log_hi:
        ybreaks.extend(np.arange(cap, cap * 10, cap).tolist())
        cap *= 10

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.scatter(norm.ppf(pp), series, s=50, alpha=0.6, color="black", label="Observed Data", zorder=3)
    ax.plot(norm.ppf(ci["nonexceed_prob"]), ci["true"], color="red", linewidth=2, label="Fitted LP3")
    ax.plot(norm.ppf(ci["nonexceed_prob"]), ci["lower"], color="red", linewidth=1, linestyle="--")
    ax.plot(norm.ppf(ci["nonexceed_prob"]), ci["upper"], color="red", linewidth=1, linestyle="--",
            label="90 % CI")
    ax.set_yscale("log")
    if ybreaks:
        ax.set_yticks(ybreaks)
        ax.get_yaxis().set_major_formatter(plt.ScalarFormatter())
    ax.set_xticks(norm.ppf(xbreaks))
    ax.set_xticklabels([f"{rp:.4g}" for rp in rp_labels])
    ax.set_xlabel("Return Period (years)", fontsize=12)
    ax.set_ylabel("Flow (m³/s)", fontsize=12)
    title = "Frequency Analysis — Flood Peak Flows"
    if watershed_name:
        title += f" ({watershed_name})"
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.legend(loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_wy_summary(
    data_path: str | Path,
    output_dir: str | Path,
    watershed_name: str = "",
    param_id: int = 1,
    start_year: int | None = None,
    end_year: int | None = None,
    origin_month: int = 10,
    n_bootstrap: int = 10_000,
    ci: float = 0.90,
    seed: int | None = None,
    wsc_id: str | None = None,
    event_delta_y: float = 20,
    event_delta_x: int = 5,
    event_threshold: float = 0,
) -> tuple[FreqAnalysisResult, pd.DataFrame]:
    """Load daily flow data and produce a water-year LP3 frequency analysis.

    Workflow (mirrors ``local/flood_freq_report.ipynb``):

    1. Load WSC-style daily flow CSV.
    1b. Identify discrete flow events using :func:`_event_minima`; save
        ``events.csv`` to *output_dir*.
    2. Summarise by water year from detected events (peak flow, total volume,
       flow type).  Years with no detected events fall back to the daily
       maximum.  Years with distinct spring and annual peak events contribute
       two rows each.
    3. Run MGBT on annual peaks to identify Potentially Influential Low Floods
       (PILFs).
    4. Fit Log-Pearson III via L-moments to the non-PILF annual series.
    5. Estimate return period for *every* row (incl. spring rows and PILFs).
    6. Bootstrap 90 % confidence intervals for the frequency curve.
    7. Compute standard design-flow quantiles (2, 5, 10, … yr).
    8. Run Anderson-Darling and Cramér-von Mises goodness-of-fit tests.
    9. Save ``wy_summary.csv`` to *output_dir*.

    Parameters
    ----------
    data_path:
        Path to the WSC-format daily flow CSV.
    output_dir:
        Directory for output files.  Created if it does not exist.
    watershed_name:
        Optional label used in report and plot titles.
    param_id:
        PARAM column value to extract (1 = flow).
    start_year, end_year:
        Inclusive year range filter on the raw data.
    origin_month:
        First month of the water year (default 10 for October).
    n_bootstrap:
        Bootstrap resamples for CI estimation (default 10 000).
    ci:
        Confidence level for the CI band (default 0.90).
    seed:
        Random seed for reproducibility.
    wsc_id:
        WSC station ID to extract from the input CSV.  If ``None``, the
        file must contain exactly one distinct station ID.
    event_delta_y:
        Maximum trough-value difference for event separation (default 20).
    event_delta_x:
        Minimum event length in days (default 5).
    event_threshold:
        Flow threshold; events below this are dropped / trimmed (default 0).

    Returns
    -------
    (FreqAnalysisResult, flow_df)
        ``FreqAnalysisResult`` contains all analysis outputs.
        ``flow_df`` is the cleaned daily flow DataFrame (needed by
        :func:`generate_freq_report` for daily-stats plots).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Catch incorrect input types early to avoid confusing downstream errors
    path_formats = (str, Path, pathlib.WindowsPath, pathlib.PosixPath)

    if not isinstance(data_path, path_formats):
        raise TypeError(f"Wrong input format: data_path must be str, Path, or WindowsPath, got {type(data_path)}")

    label = watershed_name or str(data_path)
    logger.info("Starting frequency analysis for '%s'", label)

    # 1. Load data
    flow_df = _load_flow_data(data_path, param_id=param_id,
                              start_year=start_year, end_year=end_year,
                              wsc_id=wsc_id)
    logger.info("Loaded %d daily flow records", len(flow_df))

    # 1b. Identify flow events
    logger.info(
        "Identifying flow events (delta_y=%s, delta_x=%s, threshold=%s)",
        event_delta_y, event_delta_x, event_threshold,
    )
    events_df = _identify_flow_events(
        flow_df, delta_y=event_delta_y, delta_x=event_delta_x,
        threshold=event_threshold,
    )
    events_df.to_csv(output_dir / "events.csv", index=False)
    logger.info("Identified %d flow events → %s", len(events_df), output_dir / "events.csv")

    # 2. Water-year summary (event-based; fallback to daily max when no events)
    wy = _summarize_wy_from_events(events_df, flow_df, origin_month=origin_month)
    logger.info(
        "Water-year summary: %d rows across %d water years",
        len(wy), wy["WaterYear"].nunique(),
    )

    # 3. MGBT — operate on one annual peak per year
    annual_peaks_df = wy.loc[wy.groupby("WaterYear")["PeakFlow"].idxmax()]
    mgbt_thresh = _mgbt(annual_peaks_df["PeakFlow"].values)
    pilf_mask = annual_peaks_df["PeakFlow"] < mgbt_thresh
    pilf_years = set(annual_peaks_df.loc[pilf_mask, "WaterYear"])
    wy["IsPILF"] = wy["WaterYear"].isin(pilf_years)
    n_pilf = int(len(pilf_years))
    logger.info("MGBT threshold: %.4f — %d PILF year(s) identified", mgbt_thresh, n_pilf)

    # 4. Fit LP3 on non-PILF annual peaks (one per year, never double-counting)
    non_pilf_annual = annual_peaks_df[~pilf_mask]
    annual_series = non_pilf_annual["PeakFlow"].values
    if len(annual_series) < 4:
        logger.warning(
            "MGBT removed too many records (%d remaining); falling back to full annual series",
            len(annual_series),
        )
        annual_series = annual_peaks_df["PeakFlow"].values
    lp3_params = _fit_lp3(annual_series)
    logger.info("LP3 fit: loc=%.4f, scale=%.4f, skew=%.4f",
                lp3_params["loc"], lp3_params["scale"], lp3_params["skew"])

    # 5. Return period for every water year
    wy["EstimatedReturnPeriod"] = _lp3_return_period(wy["PeakFlow"].values, lp3_params)

    # 6. Bootstrap CI (at plot-resolution NEP)
    logger.info("Running bootstrap CI (%d resamples)", n_bootstrap)
    ci_df = _bootstrap_ci(annual_series, lp3_params, _PLOT_NEP,
                          n_resamples=n_bootstrap, ci=ci, seed=seed)

    # 7. Standard design-flow table
    std_q = _lp3_quantiles(lp3_params, _STANDARD_NEP)
    nearest = [
        int(wy.iloc[(wy["PeakFlow"] - q).abs().argmin()]["WaterYear"])
        for q in std_q
    ]
    std_rps = pd.DataFrame({
        "ReturnPeriod": _STANDARD_RPS,
        "nep": _STANDARD_NEP,
        "Q": std_q,
        "NearestEvent": nearest,
    })

    # 8. Goodness-of-fit tests
    gof = _gof_tests(annual_series, lp3_params, seed=seed)
    logger.info("GoF — AD p=%.4f, CvM p=%.4f", gof["ad_pval"], gof["cvm_pval"])

    # 9. Save summary CSV
    wy.to_csv(output_dir / "wy_summary.csv", index=False)
    logger.info("Saved wy_summary.csv → %s", output_dir / "wy_summary.csv")

    result = FreqAnalysisResult(
        wy_summary=wy,
        lp3_params=lp3_params,
        mgbt_threshold=mgbt_thresh,
        n_pilf=n_pilf,
        bootstrap_ci=ci_df,
        gof=gof,
        standard_return_periods=std_rps,
    )
    return result, flow_df


def generate_freq_report(
    flow_df: pd.DataFrame,
    result: FreqAnalysisResult,
    output_dir: str | Path,
    watershed_name: str = "",
) -> Path:
    """Generate diagnostic plots and a Markdown frequency analysis report.

    Produces four PNG plots and a ``freq_analysis.md`` report populated from
    the bundled template.  All outputs are written to *output_dir*.

    Parameters
    ----------
    flow_df:
        Cleaned daily flow DataFrame (second element of :func:`export_wy_summary`
        return value).
    result:
        Analysis results bundle from :func:`export_wy_summary`.
    output_dir:
        Directory for report and plot files.  Created if absent.
    watershed_name:
        Watershed label for plot titles and the report header.

    Returns
    -------
    Path of the generated ``freq_analysis.md`` report.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    wy = result.wy_summary

    # Peak years for the overlay plot (top-3 peak flows)
    peak_years = wy.nlargest(3, "PeakFlow")["WaterYear"].tolist()

    # --- Plot 1: Daily statistics ---
    fig = _plot_daily_statistics(
        flow_df,
        title=f"Daily Flow Statistics — {watershed_name}" if watershed_name else "Daily Flow Statistics",
    )
    fig.savefig(output_dir / "daily_stats.png", dpi=150)
    plt.close(fig)

    # --- Plot 2: Annual peak flows ---
    fig = _plot_annual_statistics(
        wy,
        title=f"Annual Flow Statistics — {watershed_name}" if watershed_name else "Annual Flow Statistics",
    )
    fig.savefig(output_dir / "annual_stats.png", dpi=150)
    plt.close(fig)

    # --- Plot 3: Min/max with peak-year overlay ---
    fig = _plot_daily_minmax_with_overlay(
        flow_df,
        overlay_years=peak_years,
        title=f"Daily Flow with Flood Years Overlaid — {watershed_name}" if watershed_name else "Daily Flow with Flood Years Overlaid",
    )
    fig.savefig(output_dir / "overlay_years.png", dpi=150)
    plt.close(fig)

    # --- Plot 4: Frequency curve ---
    fig = _plot_frequency_curve(wy, result.bootstrap_ci, watershed_name=watershed_name)
    fig.savefig(output_dir / "frequency_plot.png", dpi=150)
    plt.close(fig)

    # --- Markdown report ---
    tpl_path = Path(__file__).parent / "freq_analysis_tpl.md"
    template = tpl_path.read_text(encoding="utf-8")

    # Build recurrence table:
    #   • Design-flow quantiles at 2, 5, 10, and 500 years
    #   • Top-3 observed events (by peak flow) with their LP3 return periods
    _REPORT_DESIGN_RPS = {2, 5, 10}
    std_entries = [
        {
            "rp": float(row["ReturnPeriod"]),
            "q": float(row["Q"]),
            "wy": int(row["NearestEvent"]),
        }
        for _, row in result.standard_return_periods[
            result.standard_return_periods["ReturnPeriod"].isin(_REPORT_DESIGN_RPS)
        ].iterrows()
    ]
    top3 = result.wy_summary.nlargest(3, "PeakFlow")
    obs_entries = [
        {
            "rp": float(row["EstimatedReturnPeriod"]),
            "q": float(row["PeakFlow"]),
            "wy": int(row["WaterYear"]),
        }
        for _, row in top3.iterrows()
    ]
    table_entries = sorted(std_entries + obs_entries, key=lambda x: x["rp"])
    rows = ["| Return Period (years) | Flow Estimate (m³/s) | Water Year |",
            "|---|---|---|"]
    for entry in table_entries:
        rp = entry["rp"]
        rp_str = str(int(rp)) if rp == int(rp) else f"{rp:.1f}"
        rows.append(f"| {rp_str} | {entry['q']:.2f} | {entry['wy']} |")
    event_returns = "\n".join(rows)

    # GoF summary string
    gof = result.gof
    if gof.get("ad_pval") is not None:
        gof_str = f"Anderson-Darling: p-value = {gof['ad_pval']:.4f}"
    else:
        gof_str = "Goodness of fit statistics not available"

    report_text = (
        template
        .replace("{watershed}", watershed_name)
        .replace("{event_returns}", event_returns)
        .replace("{mgbt_removed}", str(result.n_pilf))
        .replace("{mgbt_threshold}", f"{result.mgbt_threshold:.4f}")
        .replace("{peak_flow_goodness_fit}", gof_str)
        .replace("{warning_message}", "")
    )

    report_path = output_dir / "freq_analysis.md"
    report_path.write_text(report_text, encoding="utf-8")
    return report_path
