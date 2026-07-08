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

import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import pearson3

warnings.filterwarnings("ignore", category=RuntimeWarning)

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
_STANDARD_RPS = np.array([2, 5, 10, 20, 50, 100, 200, 500])
_STANDARD_NEP = 1.0 - 1.0 / _STANDARD_RPS


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

    Returns
    -------
    DataFrame with columns ``Date`` (datetime) and ``Value`` (float).
    """
    df = pd.read_csv(filepath, header=0, skiprows=1)
    df = df[df["PARAM"] == param_id][["Date", "Value"]].copy()
    df["Date"] = pd.to_datetime(df["Date"], format="%Y/%m/%d")
    if start_year is not None:
        df = df[df["Date"].dt.year >= start_year]
    if end_year is not None:
        df = df[df["Date"].dt.year <= end_year]
    df = df.dropna(subset=["Value"]).reset_index(drop=True)
    return df


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
) -> tuple[FreqAnalysisResult, pd.DataFrame]:
    """Load daily flow data and produce a water-year LP3 frequency analysis.

    Workflow (mirrors ``local/flood_freq_report.ipynb``):

    1. Load WSC-style daily flow CSV.
    2. Summarise by water year (peak flow, total volume, flow type).
    3. Run MGBT to identify Potentially Influential Low Floods (PILFs).
    4. Fit Log-Pearson III via L-moments to the non-PILF annual series.
    5. Estimate return period for *every* water year (incl. PILFs).
    6. Bootstrap 90 % confidence intervals for the frequency curve.
    7. Compute standard design-flow quantiles (2, 5, 10, … 500 yr).
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

    Returns
    -------
    (FreqAnalysisResult, flow_df)
        ``FreqAnalysisResult`` contains all analysis outputs.
        ``flow_df`` is the cleaned daily flow DataFrame (needed by
        :func:`generate_freq_report` for daily-stats plots).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load data
    flow_df = _load_flow_data(data_path, param_id=param_id,
                              start_year=start_year, end_year=end_year)

    # 2. Water-year summary
    wy = _summarize_by_water_year(flow_df, origin_month=origin_month)

    # 3. MGBT
    mgbt_thresh = _mgbt(wy["PeakFlow"].values)
    wy["IsPILF"] = wy["PeakFlow"] < mgbt_thresh
    n_pilf = int(wy["IsPILF"].sum())

    # 4. Fit LP3 on non-PILF series
    annual_series = wy.loc[~wy["IsPILF"], "PeakFlow"].values
    if len(annual_series) < 4:
        # Fall back to full series if MGBT removed too many records
        annual_series = wy["PeakFlow"].values
    lp3_params = _fit_lp3(annual_series)

    # 5. Return period for every water year
    wy["EstimatedReturnPeriod"] = _lp3_return_period(wy["PeakFlow"].values, lp3_params)

    # 6. Bootstrap CI (at plot-resolution NEP)
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

    # 9. Save summary CSV
    wy.to_csv(output_dir / "wy_summary.csv", index=False)

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

    # Build recurrence table
    rows = ["| Return Period (years) | Flow Estimate (m³/s) | Nearest Event (Water Year) |",
            "|---|---|---|"]
    for _, row in result.standard_return_periods.iterrows():
        rows.append(
            f"| {int(row['ReturnPeriod'])} | {row['Q']:.2f} | {int(row['NearestEvent'])} |"
        )
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
