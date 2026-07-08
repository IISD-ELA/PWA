"""R vs Python LP3 comparison test.

Generates a synthetic annual peak-flow series, fits LP3 using both Python
(lmoments3) and R (lmomco), and asserts close agreement on:
  - fitted PE3 parameters (≤ 1 % relative error)
  - design-flow quantiles at standard return periods (≤ 2 % relative error)
  - per-event return periods (≤ 5 % relative error)

Marked @pytest.mark.regression and skipped when R 4.3.0 is unavailable so
it does not block CI that lacks R.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import pearson3

import pwa_raven.freq_analysis as fa

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

RSCRIPT = Path("C:/Program Files/R/R-4.3.0/bin/Rscript.exe")
R_COMPARISON_SCRIPT = (
    Path(__file__).parent.parent / "r" / "freq_analysis_comparison.R"
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _synthetic_wy_summary(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """Return a wy_summary DataFrame with realistic LP3-distributed peak flows."""
    rng = np.random.default_rng(seed)
    # PE3 params in log10 space chosen to produce a realistic series
    log_flows = pearson3.rvs(
        skew=-0.25, loc=1.6, scale=0.28, size=n, random_state=rng
    )
    flows = np.clip(10 ** log_flows, 1.0, None)
    return pd.DataFrame(
        {
            "WaterYear": np.arange(1961, 1961 + n),
            "PeakFlow": flows,
            "TotalVolume": flows * 86400 * 30,
            "Type": "Spring",
        }
    )


def _run_r(tmp_path: Path) -> dict:
    """Run the R comparison script on tmp_path and return parsed JSON."""
    result = subprocess.run(
        [str(RSCRIPT), str(R_COMPARISON_SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"R script failed:\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}")
    out_path = tmp_path / "r_comparison_results.json"
    with out_path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.skipif(
    not RSCRIPT.exists(),
    reason="R 4.3.0 not found at expected path — skipping R comparison",
)
def test_lp3_params_match_r(tmp_path):
    """LP3 fitted parameters (loc, scale, skew) agree within 1 % of R."""
    wy = _synthetic_wy_summary()
    wy.to_csv(tmp_path / "wy_summary.csv", index=False)

    # Python
    py_params = fa._fit_lp3(wy["PeakFlow"].values)

    # R
    r_data = _run_r(tmp_path)
    r_params = r_data["lp3_params"]

    for key in ("loc", "scale", "skew"):
        py_val = py_params[key]
        r_val = r_params[key]
        np.testing.assert_allclose(
            py_val, r_val, rtol=0.01,
            err_msg=f"LP3 param '{key}': Python={py_val:.6f}, R={r_val:.6f}",
        )


@pytest.mark.regression
@pytest.mark.skipif(
    not RSCRIPT.exists(),
    reason="R 4.3.0 not found at expected path — skipping R comparison",
)
def test_design_flow_quantiles_match_r(tmp_path):
    """Design-flow quantiles at standard return periods agree within 2 % of R."""
    wy = _synthetic_wy_summary()
    wy.to_csv(tmp_path / "wy_summary.csv", index=False)

    std_neps = np.array([0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.998])

    # Python
    py_params = fa._fit_lp3(wy["PeakFlow"].values)
    py_quantiles = fa._lp3_quantiles(py_params, std_neps)

    # R — jsonlite serialises data.frames row-major: [{"nep":..., "q":...}, ...]
    r_data = _run_r(tmp_path)
    r_quantiles = np.array([row["q"] for row in r_data["standard_quantiles"]])

    np.testing.assert_allclose(
        py_quantiles, r_quantiles, rtol=0.02,
        err_msg="Design-flow quantiles differ by more than 2% from R output",
    )


@pytest.mark.regression
@pytest.mark.skipif(
    not RSCRIPT.exists(),
    reason="R 4.3.0 not found at expected path — skipping R comparison",
)
def test_event_return_periods_match_r(tmp_path):
    """Per-event LP3 return period estimates agree within 5 % of R."""
    wy = _synthetic_wy_summary()
    wy.to_csv(tmp_path / "wy_summary.csv", index=False)

    # Python
    py_params = fa._fit_lp3(wy["PeakFlow"].values)
    py_rps = fa._lp3_return_period(wy["PeakFlow"].values, py_params)

    # R (ordered by WaterYear, same as wy)
    r_data = _run_r(tmp_path)
    r_rp_df = pd.DataFrame(r_data["annual_return_periods"])
    r_rp_df = r_rp_df.sort_values("WaterYear").reset_index(drop=True)
    wy_sorted = wy.sort_values("WaterYear").reset_index(drop=True)

    np.testing.assert_allclose(
        py_rps[np.argsort(wy["WaterYear"].values)],
        r_rp_df["ReturnPeriod"].values,
        rtol=0.05,
        err_msg="Per-event return periods differ by more than 5% from R output",
    )
