"""Tests for pwa_raven.raven — files, runner, and hydrograph modules.

Covers the 4 bug fixes (BUG-002, BUG-003, BUG-004, BUG-007) and core
template substitution logic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pwa_raven.raven.files import RavenFile
from pwa_raven.raven.hydrograph import RavenHydrograph, index_to_date
from pwa_raven.raven.runner import _find_raven_binary


# ============ RavenFile — template substitution ============


def _setup_rvp_tpl(tmp_path: Path) -> RavenFile:
    """Create a minimal .rvp template and return a RavenFile pointing at it."""
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    tpl_content = (
        ":Bedslope\t\t\t 0.001000\n"
        "seep_fact\n"
        "s100_dep\n"
        "s200_dep\n"
    )
    (tpl_dir / "model.rvp.tpl").write_text(tpl_content)
    return RavenFile("model", calib_dir=tmp_path, extension="rvp")


def test_rvp_update_substitutes_params(tmp_path: Path) -> None:
    rf = _setup_rvp_tpl(tmp_path)
    params = {"seep_k": 0.05, "dep_fact": 1.5, "bedslope_mult": 2.0}
    deps = {100: 10.0, 200: 20.0}

    rf.rvp_update("no_split", _dep_scale=True, _param_vector=params, _deps=deps, _channel_scale=True)

    result = rf.filepath.read_text()
    assert "0.05" in result  # seep_k
    assert "15.0" in result  # 1.5 * 10
    assert "30.0" in result  # 1.5 * 20
    assert "0.002" in result  # bedslope scaled by 2x


def test_rvp_update_without_channel_scale(tmp_path: Path) -> None:
    """BUG-002 fix: no crash when _channel_scale=False and bedslope_mult missing."""
    rf = _setup_rvp_tpl(tmp_path)
    params = {"seep_k": 0.05, "dep_fact": 1.0}  # NO bedslope_mult key

    # This crashed with KeyError in the original
    rf.rvp_update("no_split", _dep_scale=True, _param_vector=params, _channel_scale=False)

    result = rf.filepath.read_text()
    assert "0.05" in result
    # Bedslope should be unchanged (original value from template)
    assert "0.001000" in result


def test_rvp_update_rejects_bad_param_set(tmp_path: Path) -> None:
    rf = _setup_rvp_tpl(tmp_path)
    with pytest.raises(ValueError, match="Unrecognized"):
        rf.rvp_update("clrh_split", _dep_scale=False, _param_vector={"seep_k": 0.01})


# ============ index_to_date — BUG-003 fix ============


def test_index_to_date_hourly() -> None:
    result = index_to_date(24, start_date="2003-01-01 00:00:00", freq="H")
    assert result == pd.Timestamp("2003-01-02 00:00:00")


def test_index_to_date_3hourly() -> None:
    """BUG-003: original had freq.to_lower() which crashes. Fixed to .lower()."""
    result = index_to_date(8, start_date="2003-01-01 00:00:00", freq="3H")
    assert result == pd.Timestamp("2003-01-02 00:00:00")


def test_index_to_date_bad_freq() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        index_to_date(1, freq="D")


# ============ RavenHydrograph — BUG-004 fixes ============


def _mock_hydrograph_csv(tmp_path: Path, run_id: str = "") -> Path:
    """Create a minimal hydrograph CSV for testing."""
    output_dir = tmp_path / f"output{('_' + run_id) if run_id else ''}"
    output_dir.mkdir(parents=True)

    dates = pd.date_range("2005-01-01", periods=48, freq="h")
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "hour": dates.strftime("%H:%M:%S"),
        "sub100 [m3/s]": range(48),
        "sub100 [observed] [m3/s]": [float(i) * 1.1 for i in range(48)],
        "precip [mm/day]": [0.5] * 48,
    })
    df.to_csv(output_dir / "Hydrographs.csv", index=False)
    return tmp_path


def test_read_sim_returns_series(tmp_path: Path) -> None:
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    sim = rh.read_sim("sub100", start_yr=2005, end_yr=2005, spring_only=False)
    assert len(sim) > 0


def test_read_sim_raises_on_missing_column(tmp_path: Path) -> None:
    """BUG-004 fix: ValueError instead of UnboundLocalError."""
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    with pytest.raises(ValueError, match="No simulated column"):
        rh.read_sim("nonexistent_subbasin", start_yr=2005, end_yr=2005)


def test_read_obs_returns_series(tmp_path: Path) -> None:
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    obs = rh.read_obs(start_yr=2005, end_yr=2005, spring_only=False)
    assert len(obs) > 0


def test_read_obs_raises_on_missing_column(tmp_path: Path) -> None:
    """BUG-004 fix for observed column."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    # Need 48+ hours so there are 2 noon timestamps (noon check passes before column check)
    dates = pd.date_range("2005-01-01", periods=48, freq="h")
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "hour": dates.strftime("%H:%M:%S"),
        "sub100 [m3/s]": range(48),
        # NO observed column
    })
    df.to_csv(output_dir / "Hydrographs.csv", index=False)

    rh = RavenHydrograph(tmp_path)
    with pytest.raises(ValueError, match="No 'observed' column"):
        rh.read_obs(start_yr=2005, end_yr=2005, spring_only=False)


def test_read_runoff_raises_on_missing_column(tmp_path: Path) -> None:
    """BUG-004 fix for runoff/precip column."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)
    dates = pd.date_range("2005-01-01", periods=24, freq="h")
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "hour": dates.strftime("%H:%M:%S"),
        "sub100 [m3/s]": range(24),
        # NO precip column
    })
    df.to_csv(output_dir / "Hydrographs.csv", index=False)

    rh = RavenHydrograph(tmp_path)
    with pytest.raises(ValueError, match="No 'precip' column"):
        rh.read_runoff(start_yr=2005, end_yr=2005, spring_only=False)


# ============ run_raven — BUG-007 fix ============


def test_find_raven_binary_with_mock() -> None:
    """When Raven is on PATH, _find_raven_binary returns it."""
    with patch("shutil.which", side_effect=lambda name: "/usr/bin/Raven" if name == "Raven" else None):
        assert _find_raven_binary() == "/usr/bin/Raven"


def test_find_raven_binary_windows_fallback() -> None:
    """Falls back to Raven.exe on Windows."""
    with patch("shutil.which", side_effect=lambda name: "C:\\Raven.exe" if name == "Raven.exe" else None):
        assert _find_raven_binary() == "C:\\Raven.exe"


def test_find_raven_binary_missing() -> None:
    """BUG-007 fix: clear error message when neither name is found."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="Raven binary not found"):
            _find_raven_binary()
