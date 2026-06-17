"""Unit tests for pwa_calibration.objectives.

Reference values are computed analytically or by hand-coding the same
formula a second time, not by re-importing the implementation under test.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pwa_calibration import objectives as obj


# ---------------------------------------------------------------------------
# Perfect / degenerate cases
# ---------------------------------------------------------------------------


def test_perfect_match_kge_is_one():
    sim = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert obj.kge_adjusted(sim, sim) == pytest.approx(1.0, abs=1e-12)


def test_perfect_match_nse_is_one():
    sim = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert obj.nse(sim, sim) == pytest.approx(1.0, abs=1e-12)


def test_perfect_match_pbias_is_zero():
    sim = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert obj.pbias(sim, sim) == pytest.approx(0.0, abs=1e-12)


def test_perfect_match_nse_pbias_weighted_is_zero():
    sim = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert obj.nse_pbias_weighted(sim, sim) == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Known-value cases (computed by hand / second implementation)
# ---------------------------------------------------------------------------


def test_pbias_known_value():
    sim = np.array([1.0, 2.0, 3.0])
    obs = np.array([2.0, 2.0, 2.0])
    # sum(sim-obs) = -1+0+1 = 0, sum(obs) = 6, pbias = 0
    assert obj.pbias(sim, obs) == pytest.approx(0.0, abs=1e-12)

    sim2 = np.array([3.0, 4.0, 5.0])
    obs2 = np.array([2.0, 2.0, 2.0])
    # sum(sim-obs) = 1+2+3 = 6, sum(obs) = 6, pbias = 1.0
    assert obj.pbias(sim2, obs2) == pytest.approx(1.0, abs=1e-12)


def test_nse_known_value():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sim = np.array([1.5, 2.0, 2.5, 4.5, 4.0])
    # SSR = 0.25 + 0 + 0.25 + 0.25 + 1 = 1.75
    # mean(obs) = 3, SST = 4 + 1 + 0 + 1 + 4 = 10
    # NSE = 1 - 1.75/10 = 0.825
    assert obj.nse(sim, obs) == pytest.approx(0.825, abs=1e-12)


def test_kge_adjusted_known_value():
    sim = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    obs = np.array([2.0, 3.0, 4.0, 5.0, 6.0])  # sim + 1, perfect r, biased mean
    r = float(np.corrcoef(sim, obs)[0, 1])  # 1.0
    mean_ratio = float(np.mean(sim) / np.mean(obs))  # 3/4 = 0.75
    std_ratio = float(np.std(sim) / np.std(obs))  # 1.0
    expected = 1.0 - math.sqrt(
        (2 * (r - 1)) ** 2
        + (1 - mean_ratio) ** 2
        + ((1 - std_ratio) / 2) ** 2
    )
    assert obj.kge_adjusted(sim, obs) == pytest.approx(expected, abs=1e-12)


def test_nse_pbias_weighted_matches_components():
    obs = np.array([2.0, 4.0, 6.0, 8.0])
    sim = np.array([1.0, 5.0, 5.0, 9.0])
    expected = 2 * (obj.nse(sim, obs) - 1) - math.sqrt(obj.pbias(sim, obs) ** 2)
    assert obj.nse_pbias_weighted(sim, obs) == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------


def test_nan_observations_dropped_pairwise():
    sim = np.array([1.0, 2.0, 3.0, 4.0])
    obs = np.array([1.0, np.nan, 3.0, 4.0])
    # After mask: sim=[1,3,4] obs=[1,3,4] → perfect.
    assert obj.nse(sim, obs) == pytest.approx(1.0, abs=1e-12)


def test_all_observations_nan_raises():
    sim = np.array([1.0, 2.0, 3.0])
    obs = np.array([np.nan, np.nan, np.nan])
    with pytest.raises(ValueError, match="non-null"):
        obj.nse(sim, obs)


def test_pandas_series_input_works():
    """Original code path passed pd.Series; ensure the API still accepts."""
    sim = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    obs = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert obj.nse(sim, obs) == pytest.approx(1.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Length-mismatch and degenerate-input errors
# ---------------------------------------------------------------------------


def test_length_mismatch_raises():
    sim = np.array([1.0, 2.0, 3.0])
    obs = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="differs"):
        obj.nse(sim, obs)


def test_zero_obs_variance_raises_for_nse():
    sim = np.array([1.0, 2.0, 3.0])
    obs = np.array([2.0, 2.0, 2.0])
    with pytest.raises(ValueError, match="variance is zero"):
        obj.nse(sim, obs)


def test_zero_obs_sum_raises_for_pbias():
    sim = np.array([1.0, 0.0, -1.0])
    obs = np.array([1.0, -1.0, 0.0])  # sum = 0
    with pytest.raises(ValueError, match="sum of observations is zero"):
        obj.pbias(sim, obs)


# ---------------------------------------------------------------------------
# Dispatch registry
# ---------------------------------------------------------------------------


def test_evaluate_dispatches_known_objective():
    sim = np.array([1.0, 2.0, 3.0])
    assert obj.evaluate("nse", sim, sim) == pytest.approx(1.0, abs=1e-12)


def test_evaluate_unknown_objective_raises_with_known_list():
    with pytest.raises(ValueError, match="Unsupported objective"):
        obj.evaluate("does_not_exist", [1.0], [1.0])


def test_objectives_registry_contains_expected_keys():
    assert set(obj.OBJECTIVES) == {"kge_adj", "nse", "nse_pbias"}


# ---------------------------------------------------------------------------
# Event-based timing realignment (upstream commit 230493c)
# ---------------------------------------------------------------------------


def test_center_of_mass_uniform_year_is_mid_year():
    """A flat year of 1's has its 50%-mass date at the midpoint."""
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    series = pd.Series(np.ones(len(idx)), index=idx)
    com = obj.center_of_mass_date(series, 2005)
    # Midpoint of a 365-day year is day 183 (1-indexed), i.e. 2005-07-02
    assert com == pd.Timestamp("2005-07-02")


def test_center_of_mass_concentrated_peak():
    """A single non-zero day defines the COM directly."""
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    series = pd.Series(np.zeros(len(idx)), index=idx)
    series.loc["2005-04-15"] = 10.0
    com = obj.center_of_mass_date(series, 2005)
    assert com == pd.Timestamp("2005-04-15")


def test_center_of_mass_raises_on_missing_year():
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    series = pd.Series(np.ones(len(idx)), index=idx)
    with pytest.raises(ValueError, match="No data for year"):
        obj.center_of_mass_date(series, 2099)


def test_center_of_mass_raises_on_zero_year():
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    series = pd.Series(np.zeros(len(idx)), index=idx)
    with pytest.raises(ValueError, match="non-positive"):
        obj.center_of_mass_date(series, 2005)


def test_center_of_mass_handles_nan_values():
    """NaNs in the series are ignored — they don't perturb the COM."""
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    series = pd.Series(np.ones(len(idx)), index=idx)
    series.iloc[10:30] = np.nan
    com = obj.center_of_mass_date(series, 2005)
    # Still near mid-year — fewer days contribute but they're symmetric.
    assert pd.Timestamp("2005-06-15") < com < pd.Timestamp("2005-08-15")


def test_center_of_mass_requires_datetime_index():
    series = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(TypeError, match="DatetimeIndex"):
        obj.center_of_mass_date(series, 2005)


def test_shift_obs_by_yearly_lag_no_lag_when_aligned():
    """Obs and sim with the same COM → no shift, output equals input."""
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    obs_vals = np.zeros(len(idx))
    obs_vals[100:110] = 5.0  # peak around day 100
    obs = pd.Series(obs_vals, index=idx)
    sim = obs.copy()
    shifted = obj.shift_obs_by_yearly_lag(obs, sim, [2005])
    pd.testing.assert_series_equal(shifted, obs)


def test_shift_obs_by_yearly_lag_shifts_late_obs_earlier():
    """Obs peaks 10 days after sim → obs gets shifted earlier by 10 days."""
    idx = pd.date_range("2005-01-01", "2005-12-31", freq="D")
    sim_vals = np.zeros(len(idx))
    sim_vals[100] = 100.0  # sim peaks on day 100
    sim = pd.Series(sim_vals, index=idx)
    obs_vals = np.zeros(len(idx))
    obs_vals[110] = 100.0  # obs peaks on day 110
    obs = pd.Series(obs_vals, index=idx)
    shifted = obj.shift_obs_by_yearly_lag(obs, sim, [2005])
    # shift(-10): the value at position 110 moves to position 100. The
    # last 10 positions get filled with NaN (values shifted off the end).
    assert shifted.iloc[100] == 100.0
    assert shifted.iloc[110] == 0.0  # came from original position 120
    assert pd.isna(shifted.iloc[-1])  # tail filled with NaN


def test_shift_obs_by_yearly_lag_passes_through_unshiftable_years():
    """Years with zero total mass can't compute a lag — passed through."""
    idx = pd.date_range("2005-01-01", "2006-12-31", freq="D")
    obs = pd.Series(np.zeros(len(idx)), index=idx, dtype=float)
    sim = pd.Series(np.zeros(len(idx)), index=idx, dtype=float)
    # Only 2006 has data — 2005 should pass through unshifted.
    obs.loc["2006-04-15"] = 1.0
    sim.loc["2006-04-15"] = 1.0
    shifted = obj.shift_obs_by_yearly_lag(obs, sim, [2005, 2006])
    # 2005 slice equals original (zeros).
    assert (shifted[shifted.index.year == 2005] == 0).all()
    # 2006 slice has the peak — lag was 0 so no shift.
    assert shifted.loc["2006-04-15"] == 1.0
