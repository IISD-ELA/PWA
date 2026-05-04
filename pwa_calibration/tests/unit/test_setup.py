"""Unit tests for pwa_calibration.setup.

Cover the testable surfaces:
* :func:`calculate_checksum`
* :func:`robust_copy` — including the BUG-015 raise-on-failure behavior
* :func:`_find_nc_template` — including BUG-006 raise-on-missing
* :func:`_adj_path_from_template`
* :func:`_round_sig`
* :class:`CalibrationConfig` validation
* :func:`load_calibration_inputs` against fixture files
* :func:`build_param_distributions` (requires spotpy)

The full ``SpotPySetup.simulation`` end-to-end path is not unit-tested —
it requires Raven on PATH and is reserved for integration/regression.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from pwa_calibration.setup import (
    CalibrationConfig,
    _adj_path_from_template,
    _find_nc_template,
    _round_sig,
    build_param_distributions,
    calculate_checksum,
    load_calibration_inputs,
    robust_copy,
)


# ---------------------------------------------------------------------------
# checksum + robust_copy
# ---------------------------------------------------------------------------


def test_calculate_checksum_matches_known_md5(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello world\n")
    # md5 of "hello world\n"
    assert calculate_checksum(p) == "6f5902ac237024bdd0c176cb93063dc4"


def test_robust_copy_succeeds(tmp_path: Path):
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("payload")
    robust_copy(src, dst)
    assert dst.read_text() == "payload"


def test_robust_copy_raises_when_source_missing(tmp_path: Path):
    """BUG-015 regression: failed copy must raise, not silently return."""
    src = tmp_path / "missing.txt"
    dst = tmp_path / "dst.txt"
    with pytest.raises(IOError, match="Failed to copy"):
        robust_copy(src, dst, retries=2, delay=0.0)


# ---------------------------------------------------------------------------
# NC template lookup (BUG-006 regression)
# ---------------------------------------------------------------------------


def test_find_nc_template_picks_tpl_suffix(tmp_path: Path):
    (tmp_path / "irrelevant.nc").touch()
    target = tmp_path / "rdrs_runoff_tpl.nc"
    target.touch()
    assert _find_nc_template(tmp_path) == target


def test_find_nc_template_picks_template_suffix(tmp_path: Path):
    target = tmp_path / "phydap_template.nc"
    target.touch()
    (tmp_path / "other.csv").touch()
    assert _find_nc_template(tmp_path) == target


def test_find_nc_template_raises_when_missing(tmp_path: Path):
    """BUG-006 regression: missing template → FileNotFoundError, not NameError."""
    (tmp_path / "no_match.nc").touch()
    with pytest.raises(FileNotFoundError, match="No NetCDF template"):
        _find_nc_template(tmp_path)


def test_adj_path_from_template_strips_tpl_suffix(tmp_path: Path):
    template = tmp_path / "rdrs_runoff_tpl.nc"
    assert _adj_path_from_template(template) == tmp_path / "rdrs_runoff_adj.nc"


def test_adj_path_from_template_strips_template_suffix(tmp_path: Path):
    template = tmp_path / "phydap_template.nc"
    assert _adj_path_from_template(template) == tmp_path / "phydap_adj.nc"


def test_adj_path_from_template_unrecognized_suffix_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="recognized template suffix"):
        _adj_path_from_template(tmp_path / "weird.nc")


# ---------------------------------------------------------------------------
# _round_sig
# ---------------------------------------------------------------------------


def test_round_sig_zero_passes_through():
    assert _round_sig([0, 0.0, 1.234567890]) == [0.0, 0.0, 1.2345679]


def test_round_sig_handles_negative():
    out = _round_sig([-1.234567890123, 1234.56789012345])
    assert out[0] == pytest.approx(-1.2345679, rel=1e-7)
    assert out[1] == pytest.approx(1234.5679, rel=1e-7)


# ---------------------------------------------------------------------------
# CalibrationConfig validation
# ---------------------------------------------------------------------------


def test_config_normalizes_calib_dir_to_path(tmp_path: Path):
    cfg = CalibrationConfig(model_name="m", calib_dir=str(tmp_path) + "/")
    assert isinstance(cfg.calib_dir, Path)
    assert str(cfg.calib_dir) == str(tmp_path).rstrip("/")


def test_config_rejects_unknown_objective(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported obj_fn"):
        CalibrationConfig(model_name="m", calib_dir=tmp_path, obj_fn="foo")


@pytest.mark.parametrize("split", ["clrh", "phydap", "CLRH", "PhyDAP"])
def test_config_rejects_deprecated_splits(tmp_path: Path, split: str):
    with pytest.raises(ValueError, match="deprecated"):
        CalibrationConfig(model_name="m", calib_dir=tmp_path, split_areas=split)


def test_config_rejects_unknown_split(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported split_areas"):
        CalibrationConfig(model_name="m", calib_dir=tmp_path, split_areas="weird")


def test_config_accepts_no_split_aliases(tmp_path: Path):
    for split in ("none", "no_split", "NONE", "No_Split"):
        cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, split_areas=split)
        assert cfg.split_areas == split


def test_config_is_mpi_threshold(tmp_path: Path):
    assert CalibrationConfig(model_name="m", calib_dir=tmp_path, mpi_cores=0).is_mpi is False
    assert CalibrationConfig(model_name="m", calib_dir=tmp_path, mpi_cores=1).is_mpi is False
    assert CalibrationConfig(model_name="m", calib_dir=tmp_path, mpi_cores=2).is_mpi is True


def test_config_is_frozen(tmp_path: Path):
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path)
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.model_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_calibration_inputs
# ---------------------------------------------------------------------------


def _write_calibration_fixture(root: Path, model_name: str = "watershed_test") -> None:
    """Build a minimal calibration input directory."""
    input_dir = root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    (input_dir / f"{model_name}_WSC_outlet.txt").write_text("875\n")

    pd.DataFrame(
        {"SubId": [101, 102, 103], "Aspect_Ratio": [0.5, 0.7, 0.9]}
    ).to_csv(input_dir / "aspect_ratios.csv", index=False)

    pd.DataFrame(
        {"HRU": [1, 2, 3], "AREA": [10.0, 20.0, 30.0]}
    ).to_csv(input_dir / f"{model_name}_HRU_areas.csv", index=False)

    pd.DataFrame(
        {"SubId": [101, 102], "tp": [1.5, 2.0], "tc": [3.0, 4.0]}
    ).to_csv(input_dir / f"{model_name}_tp_tc.csv", index=False)

    deps_gdf = gpd.GeoDataFrame(
        {
            "SubId": [101, 102],
            "Deps_Depth": [0.25, 0.30],
            "Q_Mean": [1.1, 2.2],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )
    deps_gdf.to_file(input_dir / "CLRH_basins_depression_depths.shp")


def test_load_calibration_inputs_round_trip(tmp_path: Path):
    _write_calibration_fixture(tmp_path)
    cfg = CalibrationConfig(model_name="watershed_test", calib_dir=tmp_path)
    inputs = load_calibration_inputs(cfg)

    assert inputs.outlet == 875
    assert inputs.aspect_ratios == {101: 0.5, 102: 0.7, 103: 0.9}
    assert inputs.HRU_areas == {1: 10.0, 2: 20.0, 3: 30.0}
    assert inputs.tps == {101: 1.5, 102: 2.0}
    assert inputs.tcs == {101: 3.0, 102: 4.0}
    assert inputs.deps == {101: 0.25, 102: 0.30}
    assert inputs.qrefs == {101: 1.1, 102: 2.2}


def test_load_calibration_inputs_uses_pathlib_not_backslashes(tmp_path: Path):
    """BUG-013 regression: macOS/Linux must accept the input dir."""
    _write_calibration_fixture(tmp_path, model_name="cross_platform")
    cfg = CalibrationConfig(model_name="cross_platform", calib_dir=tmp_path)
    inputs = load_calibration_inputs(cfg)
    assert inputs.outlet == 875


# ---------------------------------------------------------------------------
# build_param_distributions
# ---------------------------------------------------------------------------


def test_build_param_distributions_no_runoff_scaling_uses_no_runoff_scale_marker(tmp_path: Path):
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, runoff_scaling=False)
    dists, marker = build_param_distributions(cfg)
    assert marker == "no_runoff_scale"
    # Always seep_k present
    names = [d.name for d in dists]
    assert "seep_k" in names
    assert "basin_fact" not in names


def test_build_param_distributions_runoff_scaling_uses_no_split_marker(tmp_path: Path):
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, runoff_scaling=True)
    dists, marker = build_param_distributions(cfg)
    assert marker == "no_split"
    names = [d.name for d in dists]
    assert "basin_fact" in names


def test_build_param_distributions_low_seep_narrows_prior(tmp_path: Path):
    """Low-seep mode caps the seep_k upper bound to ~0.03 (vs ~0.5 default).

    Spotpy applies a small epsilon to the stored ``maxbound`` for
    half-open interval semantics, so we assert the bound is well below
    the default ceiling rather than equal to the target value.
    """
    default_cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, low_seep=False)
    low_cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, low_seep=True)
    default_seep = next(d for d in build_param_distributions(default_cfg)[0] if d.name == "seep_k")
    low_seep = next(d for d in build_param_distributions(low_cfg)[0] if d.name == "seep_k")
    assert low_seep.maxbound < default_seep.maxbound
    assert low_seep.maxbound < 0.05  # well below 0.5 default


# ---------------------------------------------------------------------------
# Input-file validation
# ---------------------------------------------------------------------------


def test_expected_input_files_lists_all(tmp_path: Path):
    cfg = CalibrationConfig(model_name="grass", calib_dir=tmp_path)
    files = cfg.expected_input_files()
    expected_names = {
        "grass_WSC_outlet.txt",
        "aspect_ratios.csv",
        "grass_HRU_areas.csv",
        "grass_tp_tc.csv",
        "CLRH_basins_depression_depths.shp",
    }
    assert {p.name for p in files} == expected_names
    assert all(p.parent == tmp_path / "input" for p in files)


def test_validate_inputs_exist_passes_when_all_present(tmp_path: Path):
    cfg = CalibrationConfig(model_name="grass", calib_dir=tmp_path)
    cfg.input_dir.mkdir(parents=True)
    for path in cfg.expected_input_files():
        path.touch()
    cfg.validate_inputs_exist()  # should not raise


def test_validate_inputs_exist_raises_listing_all_missing(tmp_path: Path):
    cfg = CalibrationConfig(model_name="grass", calib_dir=tmp_path)
    cfg.input_dir.mkdir(parents=True)
    # Create only the WSC outlet; everything else missing.
    (cfg.input_dir / "grass_WSC_outlet.txt").touch()
    with pytest.raises(FileNotFoundError) as exc_info:
        cfg.validate_inputs_exist()
    msg = str(exc_info.value)
    assert "aspect_ratios.csv" in msg
    assert "grass_HRU_areas.csv" in msg
    assert "grass_tp_tc.csv" in msg
    assert "CLRH_basins_depression_depths.shp" in msg
    # Already-staged file is NOT in the missing list.
    assert "WSC_outlet.txt" not in msg


def test_validate_inputs_exist_raises_when_input_dir_absent(tmp_path: Path):
    cfg = CalibrationConfig(model_name="grass", calib_dir=tmp_path)
    # No make_dirs; the entire input directory is absent.
    with pytest.raises(FileNotFoundError, match="missing"):
        cfg.validate_inputs_exist()


def test_build_param_distributions_full_set(tmp_path: Path):
    cfg = CalibrationConfig(
        model_name="m",
        calib_dir=tmp_path,
        dep_scaling=True,
        runoff_scaling=True,
        routing=True,
        channel_scaling=True,
        phydap_adj=True,
    )
    dists, _ = build_param_distributions(cfg)
    names = [d.name for d in dists]
    assert names == [
        "dep_fact",
        "seep_k",
        "basin_fact",
        "tc_tp_fact",
        "t_peak_fact",
        "qref_scale",
        "bedslope_mult",
        "runoff_offset",
    ]
