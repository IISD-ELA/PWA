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
