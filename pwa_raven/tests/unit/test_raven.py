"""Tests for pwa_raven.raven — files, runner, and hydrograph modules.

Covers core template-substitution logic plus the four behavioural fixes
in this submodule:
  * rvp_update no longer crashes when channel scaling is off
  * index_to_date handles 3-hour frequency strings
  * RavenHydrograph readers raise ValueError on missing columns
  * run_raven finds the binary via PATH on every platform
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
    """When channel_scale=False, the bedslope_mult key may legitimately be
    absent from the parameter vector. The original raised KeyError; the
    refactor short-circuits the access. This pins the no-crash behaviour."""
    rf = _setup_rvp_tpl(tmp_path)
    params = {"seep_k": 0.05, "dep_fact": 1.0}  # NO bedslope_mult key

    # This crashed with KeyError in the original
    rf.rvp_update("no_split", _dep_scale=True, _param_vector=params, _channel_scale=False)

    result = rf.filepath.read_text()
    assert "0.05" in result
    # Bedslope should be unchanged (original value from template)
    assert "0.001000" in result


def _setup_rvh_tpl(tmp_path: Path) -> RavenFile:
    """Create a minimal .rvh template and return a RavenFile pointing at it."""
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "model.rvh.tpl").write_text(
        "seep_fact\nH101_area\ntc_101\ntp_101\nqref_101\n"
    )
    return RavenFile("model", calib_dir=tmp_path, extension="rvh")


def test_rvh_update_substitutes_qref_with_routing_off(tmp_path: Path) -> None:
    """qref_<subid> placeholders must be substituted even when routing is
    off. The placeholder is written into every .rvh.tpl regardless of
    routing; if it survives, Raven reads the literal 'qref_<id>' token as
    the reference flow and aborts ('Reference flow must be non-zero')."""
    rf = _setup_rvh_tpl(tmp_path)
    rf.rvh_update(
        "no_split",
        _routing=False,
        _channel_scale=False,
        _param_vector={"seep_k": 0.05, "basin_fact": 1.0},
        _aspect_ratios={},
        _HRU_areas={101: 5.0},
        _tps={101: 2.0},
        _tcs={101: 3.0},
        _qrefs={101: 0.5},
    )
    result = rf.filepath.read_text()
    assert "qref_101" not in result, "qref placeholder left unsubstituted"
    assert "0.5" in result


def test_rvh_update_substitutes_qref_with_routing_on(tmp_path: Path) -> None:
    """Routing on: qref is still substituted, scaled by qref_scale when
    channel scaling is enabled."""
    rf = _setup_rvh_tpl(tmp_path)
    rf.rvh_update(
        "no_split",
        _routing=True,
        _channel_scale=True,
        _param_vector={
            "seep_k": 0.05,
            "basin_fact": 1.0,
            "t_peak_fact": 1.0,
            "tc_tp_fact": 1.0,
            "qref_scale": 2.0,
        },
        _aspect_ratios={101: 1.0},
        _HRU_areas={101: 5.0},
        _tps={101: 2.0},
        _tcs={101: 3.0},
        _qrefs={101: 0.5},
    )
    result = rf.filepath.read_text()
    assert "qref_101" not in result
    assert "1.0" in result  # qref_scale 2.0 * qref 0.5


def test_rvp_update_rejects_bad_param_set(tmp_path: Path) -> None:
    rf = _setup_rvp_tpl(tmp_path)
    with pytest.raises(ValueError, match="Unrecognized"):
        rf.rvp_update("clrh_split", _dep_scale=False, _param_vector={"seep_k": 0.01})


# ============ index_to_date ============


def test_index_to_date_hourly() -> None:
    result = index_to_date(24, start_date="2003-01-01 00:00:00", freq="H")
    assert result == pd.Timestamp("2003-01-02 00:00:00")


def test_index_to_date_3hourly() -> None:
    """The 3-hourly branch must not crash. The original called the
    nonexistent ``freq.to_lower()`` method and threw ``AttributeError``
    the moment the 3H path was taken."""
    result = index_to_date(8, start_date="2003-01-01 00:00:00", freq="3H")
    assert result == pd.Timestamp("2003-01-02 00:00:00")


def test_index_to_date_bad_freq() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        index_to_date(1, freq="D")


# ============ RavenHydrograph ============


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


def test_hydrograph_raises_clearly_when_no_csv(tmp_path: Path) -> None:
    """A failed Raven run leaves an empty output dir. RavenHydrograph must
    raise a clear 'produced no output' error — not return an empty frame
    that detonates later as a cryptic KeyError: 'date_time'."""
    (tmp_path / "output").mkdir()
    with pytest.raises(FileNotFoundError, match="produced no output"):
        RavenHydrograph(tmp_path)


def test_hydrograph_raises_clearly_when_output_dir_absent(tmp_path: Path) -> None:
    """No output directory at all → the same clear error, not a bare
    FileNotFoundError from iterdir()."""
    with pytest.raises(FileNotFoundError, match="No Raven hydrograph CSV"):
        RavenHydrograph(tmp_path)


def test_hydrograph_raises_on_truncated_csv(tmp_path: Path) -> None:
    """A hydrograph CSV missing the date/hour columns (truncated / partial
    Raven failure) → a clear error naming the missing columns."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pd.DataFrame({"junk": [1, 2]}).to_csv(output_dir / "Hydrographs.csv", index=False)
    with pytest.raises(ValueError, match="missing expected column"):
        RavenHydrograph(tmp_path)


def test_read_sim_raises_on_missing_column(tmp_path: Path) -> None:
    """Missing column → clear ValueError. The original left ``simulated``
    unassigned and crashed with ``UnboundLocalError``."""
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
    """Same missing-column → ValueError contract for the observed series."""
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
    """Same missing-column → ValueError contract for the precip series."""
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


# ============ run_raven — binary detection ============


def test_find_raven_binary_with_mock() -> None:
    """When Raven is on PATH, _find_raven_binary returns it."""
    with patch("shutil.which", side_effect=lambda name: "/usr/bin/Raven" if name == "Raven" else None):
        assert _find_raven_binary() == "/usr/bin/Raven"


def test_find_raven_binary_windows_fallback() -> None:
    """Falls back to Raven.exe on Windows."""
    with patch("shutil.which", side_effect=lambda name: "C:\\Raven.exe" if name == "Raven.exe" else None):
        assert _find_raven_binary() == "C:\\Raven.exe"


def test_find_raven_binary_missing() -> None:
    """When neither ``Raven`` nor ``Raven.exe`` is on PATH, raise a clear
    FileNotFoundError pointing at the install instructions instead of
    silently invoking a nonexistent binary."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="Raven binary not found"):
            _find_raven_binary()
