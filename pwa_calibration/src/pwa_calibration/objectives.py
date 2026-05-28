"""Objective functions for SPOTPY calibration of Raven models.

Extracted from ``PWA/src/py/setup_spotpy.py`` (the body of
``spot_setup_rvn.simulation`` that branched on ``self.obj_fn``).

All functions take 1-D array-like inputs and return a Python ``float``.
They drop NaN observations pairwise so callers don't have to pre-clean.
The original notebook code wrapped every result in ``pd.Series(...)``
before returning to SPOTPY; SPOTPY's API only requires a numeric scalar,
so callers wanting a Series should wrap the result themselves.

This module also hosts the event-based timing-realignment helpers
(``center_of_mass_date``, ``shift_obs_by_yearly_lag``) added in upstream
commit 230493c — they sit alongside the objectives because the
realignment runs immediately before objective evaluation.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np
import pandas as pd


def _align_and_drop_nulls(
    sim: "pd.Series | np.ndarray", obs: "pd.Series | np.ndarray"
) -> Tuple[np.ndarray, np.ndarray]:
    """Return matched arrays with positions where ``obs`` is NaN dropped.

    Mirrors the ``non_null = obs.notnull(); valid_sim = sim[non_null]``
    block from ``spot_setup_rvn.simulation``. Raises ``ValueError`` for
    length mismatch (matching the original) and for an empty result.
    """
    sim_arr = np.asarray(sim, dtype=float)
    obs_arr = np.asarray(obs, dtype=float)
    if sim_arr.shape != obs_arr.shape:
        raise ValueError(
            f"Simulation length {sim_arr.shape} differs from observation "
            f"length {obs_arr.shape}."
        )
    mask = ~np.isnan(obs_arr)
    valid_sim = sim_arr[mask]
    valid_obs = obs_arr[mask]
    if valid_sim.size == 0:
        raise ValueError(
            "Simulation and observation arrays contain no overlapping "
            "non-null values."
        )
    return valid_sim, valid_obs


def kge_adjusted(sim, obs) -> float:
    """Adjusted Kling-Gupta Efficiency.

    Returns ``1 - sqrt(2*(r-1))**2 + (1 - mu_s/mu_o)**2 + ((1 - sd_s/sd_o)/2)**2``.
    The factor of 2 on ``(r-1)`` and the ``/2`` on the variability term
    are preserved verbatim from the notebook formulation; this is *not*
    the canonical KGE'.
    """
    valid_sim, valid_obs = _align_and_drop_nulls(sim, obs)
    r = float(np.corrcoef(valid_sim, valid_obs)[0, 1])
    mean_ratio = float(np.mean(valid_sim) / np.mean(valid_obs))
    std_ratio = float(np.std(valid_sim) / np.std(valid_obs))
    return float(
        1.0
        - np.sqrt(
            (2.0 * (r - 1.0)) ** 2
            + (1.0 - mean_ratio) ** 2
            + ((1.0 - std_ratio) / 2.0) ** 2
        )
    )


def nse(sim, obs) -> float:
    """Nash-Sutcliffe Efficiency.

    Returns ``1 - SSR / SST`` where SSR is the sum of squared residuals
    and SST is the variance of ``obs``.
    """
    valid_sim, valid_obs = _align_and_drop_nulls(sim, obs)
    obs_mean = float(np.mean(valid_obs))
    ssr = float(np.sum((valid_sim - valid_obs) ** 2))
    sst = float(np.sum((valid_obs - obs_mean) ** 2))
    if sst == 0.0:
        raise ValueError("NSE undefined: observation variance is zero.")
    return 1.0 - ssr / sst


def pbias(sim, obs) -> float:
    """Percent bias as a fraction (NOT multiplied by 100).

    Matches the notebook formulation ``sum(sim - obs) / sum(obs)``.
    Note that real-world PBIAS is conventionally ``* 100``; the notebook
    omits this and the weighted objective compensates accordingly.
    """
    valid_sim, valid_obs = _align_and_drop_nulls(sim, obs)
    denom = float(np.sum(valid_obs))
    if denom == 0.0:
        raise ValueError("PBIAS undefined: sum of observations is zero.")
    return float(np.sum(valid_sim - valid_obs)) / denom


def nse_pbias_weighted(sim, obs) -> float:
    """Composite ``2*(NSE - 1) - sqrt(PBIAS**2)``.

    Used by the legacy ``obj_fn="nse_pbias"`` calibrations. Both NSE and
    PBIAS are computed on the same (already-filtered) spring window the
    caller passes in.
    """
    nse_val = nse(sim, obs)
    pbias_val = pbias(sim, obs)
    return 2.0 * (nse_val - 1.0) - float(np.sqrt(pbias_val ** 2))


# Public registry consumed by SpotPySetup. Adding a new objective here
# automatically makes it selectable via the obj_fn config string.
OBJECTIVES = {
    "kge_adj": kge_adjusted,
    "nse": nse,
    "nse_pbias": nse_pbias_weighted,
}


def evaluate(name: str, sim, obs) -> float:
    """Dispatch to one of :data:`OBJECTIVES` by string name."""
    try:
        fn = OBJECTIVES[name]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported objective function: {name!r}. "
            f"Choose from {sorted(OBJECTIVES)}."
        ) from exc
    return fn(sim, obs)


# ---------------------------------------------------------------------------
# Event-based timing realignment (upstream commit 230493c)
# ---------------------------------------------------------------------------


def center_of_mass_date(series: pd.Series, year: int) -> pd.Timestamp:
    """Return the date that splits the year's cumulative flow at 50%.

    Used to estimate the timing of each year's spring freshet so the
    observed and simulated hydrographs can be aligned year-by-year
    before computing an objective. NaN values are ignored.

    Raises
    ------
    ValueError
        If the supplied series has no values for *year*, or the year's
        total is zero (the median-mass split is undefined).
    """
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("series must have a DatetimeIndex")
    annual = series[series.index.year == year]
    if annual.empty:
        raise ValueError(f"No data for year {year}.")
    values = annual.to_numpy(dtype=float)
    total = float(np.nansum(values))
    if total <= 0.0:
        raise ValueError(f"Year {year} total mass is non-positive; cannot split.")
    # Replace NaNs with 0 so cumsum still progresses through the year.
    safe = np.where(np.isnan(values), 0.0, values)
    cumulative = np.cumsum(safe)
    half = total / 2.0
    com_idx = int(np.searchsorted(cumulative, half))
    com_idx = min(com_idx, len(annual) - 1)
    return annual.index[com_idx]


def shift_obs_by_yearly_lag(
    obs: pd.Series,
    sim: pd.Series,
    years: Iterable[int],
) -> pd.Series:
    """Realign each year's observed series by its lag against simulation.

    Lag is ``com(obs) - com(sim)`` in days; a positive lag means obs is
    later than sim, so obs is shifted earlier (``.shift(-lag)``) to
    line up with sim. The resulting series concatenates each year's
    shifted slice in input order and inherits the obs index.

    Years for which the lag can't be computed (no data, zero total)
    are passed through unshifted.
    """
    if not isinstance(obs.index, pd.DatetimeIndex):
        raise TypeError("obs must have a DatetimeIndex")
    if not isinstance(sim.index, pd.DatetimeIndex):
        raise TypeError("sim must have a DatetimeIndex")

    pieces: list[pd.Series] = []
    for year in years:
        obs_year = obs[obs.index.year == year]
        if obs_year.empty:
            continue
        try:
            com_obs = center_of_mass_date(obs, int(year))
            com_sim = center_of_mass_date(sim, int(year))
        except ValueError:
            pieces.append(obs_year)
            continue
        lag_days = (com_obs - com_sim).days
        pieces.append(obs_year.shift(-lag_days))

    if not pieces:
        return pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    return pd.concat(pieces)
