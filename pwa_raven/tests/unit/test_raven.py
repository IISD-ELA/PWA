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
from pwa_raven.raven.runner import (
    RavenExecutionError,
    _find_raven_binary,
    _raven_error_lines,
    run_raven,
)


# ============ RavenFile — template substitution ============


def _setup_rvp_tpl(tmp_path: Path) -> RavenFile:
    """Create a minimal .rvp template with bin-keyed placeholders."""
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    # Placeholder convention matches generate_rvp_template's output:
    # "{bin_label}_dep" — e.g. "Bin_3_dep", "Bin_NA_dep".
    tpl_content = (
        ":Bedslope\t\t\t 0.001000\n"
        "seep_fact\n"
        "Bin_3_dep\n"
        "Bin_7_dep\n"
    )
    (tpl_dir / "model.rvp.tpl").write_text(tpl_content)
    return RavenFile("model", calib_dir=tmp_path, extension="rvp")


def test_rvp_update_substitutes_params(tmp_path: Path) -> None:
    rf = _setup_rvp_tpl(tmp_path)
    params = {"seep_k": 0.05, "dep_fact": 1.5, "bedslope_mult": 2.0}
    # Deps dict is now keyed by bin label (not sub_id) — matches the
    # template's placeholders.
    deps = {"Bin_3": 10.0, "Bin_7": 20.0}

    rf.rvp_update("no_split", _dep_scale=True, _param_vector=params, _deps=deps, _channel_scale=True)

    result = rf.filepath.read_text()
    assert "0.05" in result  # seep_k
    assert "15.0" in result  # 1.5 * 10
    assert "30.0" in result  # 1.5 * 20
    assert "0.002" in result  # bedslope scaled by 2x
    # Placeholders should be fully resolved (no Bin_*_dep tokens left).
    assert "Bin_3_dep" not in result
    assert "Bin_7_dep" not in result


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
    sim = rh.read_sim("sub100", years=[2005], spring_only=False)
    assert len(sim) > 0


def test_read_sim_hourly_resolution_preserves_length(tmp_path: Path) -> None:
    """resolution='h' keeps the raw hourly index (48 samples for 48h fixture)."""
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    sim = rh.read_sim("sub100", years=[2005], spring_only=False, resolution="h")
    assert len(sim) == 48


def test_read_sim_daily_resolution_resamples(tmp_path: Path) -> None:
    """resolution='d' (default) resamples 48 hourly rows → 2 daily means."""
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    sim = rh.read_sim("sub100", years=[2005], spring_only=False)
    assert len(sim) == 2
    # Daily mean of 0..23 is 11.5, of 24..47 is 35.5.
    assert sim.iloc[0] == pytest.approx(11.5)
    assert sim.iloc[1] == pytest.approx(35.5)


def test_read_sim_rejects_unknown_resolution(tmp_path: Path) -> None:
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    with pytest.raises(ValueError, match="Unsupported resolution"):
        rh.read_sim("sub100", years=[2005], spring_only=False, resolution="weekly")


def test_read_sim_rejects_empty_years(tmp_path: Path) -> None:
    """Empty year arrays produce empty windows — catch this at the API boundary."""
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    with pytest.raises(ValueError, match="`years` is empty"):
        rh.read_sim("sub100", years=[], spring_only=False)


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
        rh.read_sim("nonexistent_subbasin", years=[2005])


def test_read_obs_returns_series(tmp_path: Path) -> None:
    rv_path = _mock_hydrograph_csv(tmp_path)
    rh = RavenHydrograph(rv_path)
    obs = rh.read_obs(years=[2005], spring_only=False)
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
        rh.read_obs(years=[2005], spring_only=False)


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
        rh.read_runoff(years=[2005], spring_only=False)


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
    """When none of the three tiers yields a binary, raise a clear
    FileNotFoundError listing all checked locations."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="Raven binary not found"):
            _find_raven_binary()


# --- explicit path ---------------------------------------------------------

def test_find_raven_binary_uses_explicit_path_when_present(tmp_path: Path) -> None:
    """An explicit path takes precedence over both data-dir and PATH."""
    binary = tmp_path / "Raven.exe"
    binary.write_text("")  # exists but empty — we only care about resolution
    with patch("shutil.which", return_value="/usr/bin/Raven"):  # would shadow if used
        result = _find_raven_binary(explicit=binary)
    assert result == str(binary.resolve())


def test_find_raven_binary_explicit_missing_raises_clear_error(tmp_path: Path) -> None:
    """Explicit path that doesn't exist must error with the path the user
    asked for — not silently fall back to PATH, which would mask a typo."""
    bogus = tmp_path / "does_not_exist" / "Raven.exe"
    with patch("shutil.which", return_value="/usr/bin/Raven"):
        with pytest.raises(FileNotFoundError, match="does_not_exist"):
            _find_raven_binary(explicit=bogus)


# --- data-directory search (Thomas's PATH-restricted workflow) -------------

def test_find_raven_binary_searches_data_dir_before_path(tmp_path: Path) -> None:
    """When the binary lives in the calibration's data directory, that
    location wins over PATH — supports environments where adding to
    PATH requires IT approval and users drop Raven.exe next to the data
    instead."""
    data_dir = tmp_path / "Calibration" / "grassmere"
    data_dir.mkdir(parents=True)
    binary = data_dir / "Raven.exe"
    binary.write_text("")
    with patch(
        "shutil.which",
        side_effect=lambda name: "/usr/bin/Raven" if name == "Raven" else None,
    ):
        result = _find_raven_binary(search_dirs=[data_dir])
    assert result == str(binary.resolve())  # data_dir wins, not /usr/bin/Raven


def test_find_raven_binary_falls_back_to_path_when_data_dir_empty(
    tmp_path: Path,
) -> None:
    """Data-dir search misses → PATH gets consulted. Keeps the
    PATH-based install option live for users who do have it."""
    data_dir = tmp_path / "empty_calib"
    data_dir.mkdir()
    with patch("shutil.which", return_value="/usr/bin/Raven"):
        result = _find_raven_binary(search_dirs=[data_dir])
    assert result == "/usr/bin/Raven"


def test_find_raven_binary_error_lists_searched_directories(tmp_path: Path) -> None:
    """Failure mode should name every place we looked so the user knows
    exactly where to drop the binary."""
    data_dir = tmp_path / "calib"
    data_dir.mkdir()
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match=str(data_dir)):
            _find_raven_binary(search_dirs=[data_dir])


def test_find_raven_binary_prefers_no_extension_over_exe_in_data_dir(
    tmp_path: Path,
) -> None:
    """When both ``Raven`` and ``Raven.exe`` sit in the data dir (cross-
    platform calibration tree), prefer the no-extension Linux/macOS
    convention to match _BINARY_NAMES ordering."""
    data_dir = tmp_path / "calib"
    data_dir.mkdir()
    (data_dir / "Raven").write_text("")
    (data_dir / "Raven.exe").write_text("")
    with patch("shutil.which", return_value=None):
        result = _find_raven_binary(search_dirs=[data_dir])
    assert result.endswith("Raven")
    assert not result.endswith(".exe")


# --- run_raven integration with the resolution tiers ----------------------

def test_run_raven_passes_explicit_binary_to_subprocess(tmp_path: Path) -> None:
    """The explicit ``raven_binary`` argument propagates straight into
    the subprocess command — load-bearing for the CalibrationConfig
    wiring."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    explicit = tmp_path / "custom" / "Raven.bin"
    explicit.parent.mkdir()
    explicit.write_text("")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        run_raven("model", data_dir=data_dir, raven_binary=explicit)

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == str(explicit.resolve())


def test_run_raven_auto_discovers_binary_in_data_dir(tmp_path: Path) -> None:
    """When no explicit path is given, run_raven finds the binary
    sitting next to the data files. This is Thomas's workflow — and
    the workflow stage_raven_binary already produces."""
    data_dir = tmp_path / "Calibration" / "grassmere"
    data_dir.mkdir(parents=True)
    binary = data_dir / "Raven.exe"
    binary.write_text("")

    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value=None):
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        run_raven("model", data_dir=data_dir)

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == str(binary.resolve())


# --- Raven_errors.txt detection (silent exit-0 failures) ------------------


def _write_raven_errors(data_dir: Path, output_dir: str, body: str) -> Path:
    """Create <data_dir>/<output_dir>/Raven_errors.txt with *body*."""
    out = data_dir / output_dir
    out.mkdir(parents=True, exist_ok=True)
    errors_file = out / "Raven_errors.txt"
    errors_file.write_text(body)
    return errors_file


def test_raven_error_lines_returns_only_error_prefixed(tmp_path: Path) -> None:
    """Advisories are ignored; only ERROR lines come back, stripped."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "Raven_errors.txt").write_text(
        " Raven v4.1\n"
        "ADVISORY : shortwave radiation is SW_RAD_NONE\n"
        "ERROR    : CForcingGrid::Initialize: gridded forcing data not available\n"
    )
    lines = _raven_error_lines(out)
    assert lines == [
        "ERROR    : CForcingGrid::Initialize: gridded forcing data not available"
    ]


def test_raven_error_lines_empty_when_file_absent(tmp_path: Path) -> None:
    assert _raven_error_lines(tmp_path / "output") == []


def test_run_raven_raises_on_error_in_errors_file(tmp_path: Path) -> None:
    """Raven exits 0 but writes an ERROR → run_raven must raise
    RavenExecutionError quoting that error, NOT return silently and let
    the empty hydrograph cascade into a confusing downstream crash."""
    data_dir = tmp_path / "calib"
    binary = data_dir / "Raven"
    data_dir.mkdir()
    binary.write_text("")
    _write_raven_errors(
        data_dir, "output",
        "ADVISORY : something benign\n"
        "ERROR    : CForcingGrid::Initialize: gridded forcing data not available "
        "at end of model simulation\n",
    )

    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value=None):
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        with pytest.raises(RavenExecutionError, match="gridded forcing data not available"):
            run_raven("model", data_dir=data_dir)


def test_run_raven_error_includes_forcing_hint_for_forcing_errors(
    tmp_path: Path,
) -> None:
    """A forcing-window error gets the actionable forcing_margin_hours
    hint pointing at the Step 2 fix."""
    data_dir = tmp_path / "calib"
    (data_dir).mkdir()
    (data_dir / "Raven").write_text("")
    _write_raven_errors(
        data_dir, "output",
        "ERROR    : CForcingGrid::Initialize: gridded forcing data not available\n",
    )
    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value=None):
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        with pytest.raises(RavenExecutionError, match="forcing_margin_hours"):
            run_raven("model", data_dir=data_dir)


def test_run_raven_no_forcing_hint_for_unrelated_errors(tmp_path: Path) -> None:
    """A non-forcing error still raises, but without the misleading
    forcing_margin_hours hint."""
    data_dir = tmp_path / "calib"
    data_dir.mkdir()
    (data_dir / "Raven").write_text("")
    _write_raven_errors(
        data_dir, "output",
        "ERROR    : CModel::Initialize: soil class AQUIFER has no porosity\n",
    )
    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value=None):
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        with pytest.raises(RavenExecutionError) as excinfo:
            run_raven("model", data_dir=data_dir)
    assert "porosity" in str(excinfo.value)
    assert "forcing_margin_hours" not in str(excinfo.value)


def test_run_raven_succeeds_with_advisory_only_errors_file(tmp_path: Path) -> None:
    """Advisory-only Raven_errors.txt is a normal successful run — must
    NOT raise. This is the common case (Raven emits advisories on every
    run); a false positive here would block every calibration."""
    data_dir = tmp_path / "calib"
    data_dir.mkdir()
    (data_dir / "Raven").write_text("")
    _write_raven_errors(
        data_dir, "output",
        " Raven v4.1\n"
        "ADVISORY : shortwave radiation method is SW_RAD_NONE\n"
        "ADVISORY : RAINSNOW_TEMP autogenerated with value 0.15\n",
    )
    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value=None):
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        # Should not raise.
        run_raven("model", data_dir=data_dir)


def test_run_raven_succeeds_when_no_errors_file(tmp_path: Path) -> None:
    """No Raven_errors.txt at all → treat as success (don't raise)."""
    data_dir = tmp_path / "calib"
    data_dir.mkdir()
    (data_dir / "Raven").write_text("")
    (data_dir / "output").mkdir()
    with patch("subprocess.run") as mock_run, patch("shutil.which", return_value=None):
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        run_raven("model", data_dir=data_dir)
