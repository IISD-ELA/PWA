"""Unit tests for pwa_calibration.setup.

Cover the testable surfaces:
* :func:`calculate_checksum`
* :func:`robust_copy` — including raise-on-failure (the original swallowed it)
* :func:`_find_nc_template` — including raise-on-missing-template
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
    _stage_worker_directory,
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
    """A failed copy must raise IOError; the original returned False and
    every call site discarded the return value, silently corrupting
    downstream calibration runs."""
    src = tmp_path / "missing.txt"
    dst = tmp_path / "dst.txt"
    with pytest.raises(IOError, match="Failed to copy"):
        robust_copy(src, dst, retries=2, delay=0.0)


# ---------------------------------------------------------------------------
# NC template lookup
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
    """A missing template raises FileNotFoundError. The original used a
    bare ``for`` loop and crashed with NameError on a post-loop reference
    to ``filename`` instead."""
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
# CalibrationConfig — repetitions / algorithm / algorithm_kwargs
# ---------------------------------------------------------------------------


def test_config_repetitions_algorithm_defaults(tmp_path: Path):
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path)
    assert cfg.repetitions == 10
    assert cfg.algorithm == "mc"
    assert cfg.algorithm_kwargs == {}


def test_config_rejects_repetitions_below_one(tmp_path: Path):
    with pytest.raises(ValueError, match="repetitions"):
        CalibrationConfig(model_name="m", calib_dir=tmp_path, repetitions=0)


@pytest.mark.parametrize("algo", ["mc", "rope", "demcz"])
def test_config_accepts_supported_algorithms(tmp_path: Path, algo: str):
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, algorithm=algo)
    assert cfg.algorithm == algo


def test_config_rejects_unknown_algorithm(tmp_path: Path):
    with pytest.raises(ValueError, match="algorithm"):
        CalibrationConfig(model_name="m", calib_dir=tmp_path, algorithm="sceua_typo")


def test_config_round_trips_repetitions_algorithm_kwargs(tmp_path: Path):
    cfg = CalibrationConfig(
        model_name="m",
        calib_dir=tmp_path,
        repetitions=250,
        algorithm="demcz",
        algorithm_kwargs={"nChains": 8},
    )
    rebuilt = CalibrationConfig.from_dict(cfg.to_dict())
    assert rebuilt == cfg
    assert rebuilt.repetitions == 250
    assert rebuilt.algorithm == "demcz"
    assert rebuilt.algorithm_kwargs == {"nChains": 8}


def test_config_from_dict_defaults_when_new_fields_absent(tmp_path: Path):
    """A YAML written before these fields existed must still load."""
    cfg = CalibrationConfig.from_dict({"model_name": "m", "calib_dir": str(tmp_path)})
    assert cfg.repetitions == 10
    assert cfg.algorithm == "mc"
    assert cfg.algorithm_kwargs == {}


def test_config_raven_binary_defaults_to_none(tmp_path: Path):
    """Default config has no explicit Raven binary — falls back to
    data-directory search + PATH at run time. Matches the
    stage_raven_binary workflow where the binary is copied into
    calib_dir and picked up automatically."""
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path)
    assert cfg.raven_binary is None


def test_config_raven_binary_coerces_str_to_path(tmp_path: Path):
    """YAML deserializes raven_binary as a string. Coerce so downstream
    code can rely on Path methods (relative-vs-absolute checks etc.)."""
    exe_str = str(tmp_path / "external" / "Raven.exe")
    cfg = CalibrationConfig(
        model_name="m", calib_dir=tmp_path, raven_binary=exe_str,
    )
    assert isinstance(cfg.raven_binary, Path)
    assert cfg.raven_binary == Path(exe_str)


def test_config_raven_binary_round_trips_through_dict(tmp_path: Path):
    exe = tmp_path / "external" / "Raven.exe"
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, raven_binary=exe)
    rebuilt = CalibrationConfig.from_dict(cfg.to_dict())
    assert rebuilt.raven_binary == exe


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
    # 2 subbasins → small-watershed binning path → 1:1 mapping with
    # Bin_<SubId> labels and the raw Deps_Depth as Binned_Deps.
    assert inputs.deps == {"Bin_101": 0.25, "Bin_102": 0.30}
    assert inputs.qrefs == {101: 1.1, 102: 2.2}


def test_load_calibration_inputs_includes_bin_na_for_nan_depths(tmp_path: Path):
    """Cross-seam regression: bin_depression_depths labels NaN/<=0
    depths as ``"Bin_NA"`` (with NaN Binned_Deps) and the .rvp.tpl
    contains a ``Bin_NA_dep`` placeholder per row, but the deps dict
    used by ``RavenFile.rvp_update`` must include a ``"Bin_NA"`` key
    too — otherwise the placeholder survives the substitution loop
    and Raven aborts trying to parse the literal string as DEP_MAX.

    Production trigger: any watershed with a subbasin whose
    ``Deps_Depth`` is NaN or ≤ 0 (small upland subbasins, missing
    data, lake catchments that survived the contributing filter)."""
    import numpy as np
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "watershed_test_WSC_outlet.txt").write_text("875\n")
    pd.DataFrame(
        {"SubId": [101, 102, 103], "Aspect_Ratio": [0.5, 0.7, 0.9]}
    ).to_csv(input_dir / "aspect_ratios.csv", index=False)
    pd.DataFrame(
        {"HRU": [1, 2, 3], "AREA": [10.0, 20.0, 30.0]}
    ).to_csv(input_dir / "watershed_test_HRU_areas.csv", index=False)
    pd.DataFrame(
        {"SubId": [101, 102], "tp": [1.5, 2.0], "tc": [3.0, 4.0]}
    ).to_csv(input_dir / "watershed_test_tp_tc.csv", index=False)
    # Shapefile carries a NaN depth on SubId 103 — the seam-triggering case.
    deps_gdf = gpd.GeoDataFrame(
        {
            "SubId": [101, 102, 103],
            "Deps_Depth": [0.25, 0.30, np.nan],
            "Q_Mean": [1.1, 2.2, 3.3],
            "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
        },
        crs="EPSG:4326",
    )
    deps_gdf.to_file(input_dir / "CLRH_basins_depression_depths.shp")

    cfg = CalibrationConfig(model_name="watershed_test", calib_dir=tmp_path)
    inputs = load_calibration_inputs(cfg)

    # Bin_NA must be present so rvp_update can substitute its placeholder.
    # Map to 0.0 (Raven's no-depression value) since the underlying
    # Binned_Deps is NaN.
    assert "Bin_NA" in inputs.deps
    assert inputs.deps["Bin_NA"] == 0.0
    # The two valid rows should still be keyed by Bin_<SubId> (1:1
    # fallback, since the watershed has < 50 subbasins).
    assert inputs.deps["Bin_101"] == 0.25
    assert inputs.deps["Bin_102"] == 0.30


def test_rvp_update_raises_on_unsubstituted_dep_placeholder(tmp_path: Path):
    """Defence-in-depth: even if the deps dict is incomplete (e.g.
    bin_depression_depths emitted a Bin_X label that load_calibration_
    inputs filtered out), rvp_update must NOT silently write a literal
    placeholder string into the .rvp's DEP_MAX numeric field. Raven
    would abort with a parse error far from the real cause.

    This test goes red until rvp_update gains a "no unsubstituted
    _dep tokens remain" guard."""
    from pwa_raven.raven.files import RavenFile

    # Build a minimal template that contains a placeholder for which
    # the caller deliberately doesn't supply a value.
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "model.rvp.tpl").write_text(
        ":Bedslope\t\t\t 0.001000\n"
        "seep_fact\n"
        "Bin_3_dep\n"        # provided in _deps
        "Bin_NA_dep\n"       # NOT provided — this is the bug we're guarding
    )
    rf = RavenFile("model", calib_dir=tmp_path, extension="rvp")

    with pytest.raises(ValueError, match="unsubstituted .*_dep"):
        rf.rvp_update(
            "no_split",
            _dep_scale=True,
            _param_vector={"seep_k": 0.05, "dep_fact": 1.0, "bedslope_mult": 1.0},
            _deps={"Bin_3": 10.0},   # Bin_NA omitted on purpose
            _channel_scale=True,
        )


def test_load_calibration_inputs_uses_pathlib_not_backslashes(tmp_path: Path):
    """The loader must work on macOS/Linux. The original built paths
    with literal backslashes (``calib_dir + "\\input\\..."``) which
    became filenames with backslashes on POSIX systems."""
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


# ---------------------------------------------------------------------------
# to_dict / to_yaml / from_yaml round-trip
# ---------------------------------------------------------------------------


def test_to_dict_round_trip(tmp_path: Path):
    original = CalibrationConfig(
        model_name="grassmere",
        calib_dir=tmp_path,
        obj_fn="nse_pbias",
        eval_start_yr=2003,
        eval_end_yr=2021,
        spring_eval=False,
        low_seep=True,
        routing=True,
        dep_scaling=True,
        runoff_scaling=True,
        channel_scaling=True,
        phydap_adj=False,
        mpi_cores=14,
    )
    rebuilt = CalibrationConfig.from_dict(original.to_dict())
    assert rebuilt == original


def test_from_dict_minimal_uses_defaults(tmp_path: Path):
    cfg = CalibrationConfig.from_dict({
        "model_name": "grassmere",
        "calib_dir": str(tmp_path),
    })
    assert cfg.model_name == "grassmere"
    assert cfg.obj_fn == "kge_adj"      # default
    assert cfg.eval_start_yr == 1995    # default
    assert cfg.spring_eval is True      # default
    assert cfg.routing is False         # default


def test_from_dict_rejects_missing_model_name(tmp_path: Path):
    with pytest.raises(ValueError, match="model_name"):
        CalibrationConfig.from_dict({"calib_dir": str(tmp_path)})


def test_from_dict_rejects_missing_calib_dir():
    with pytest.raises(ValueError, match="calib_dir"):
        CalibrationConfig.from_dict({"model_name": "grassmere"})


# ---------------------------------------------------------------------------
# Train/test year splitting (upstream commit 1e72e50)
# ---------------------------------------------------------------------------


def test_train_years_default_is_full_window(tmp_path: Path):
    """tt_split_freq=0 (default) → every year in [start, end) is training."""
    cfg = CalibrationConfig(
        model_name="m", calib_dir=tmp_path, eval_start_yr=2000, eval_end_yr=2005,
    )
    assert list(cfg.train_years) == [2000, 2001, 2002, 2003, 2004]
    assert list(cfg.test_years) == []


def test_train_years_split_freq_one_drops_first_five(tmp_path: Path):
    """tt_split_freq=1 mirrors upstream's `<=1` branch: hold out first 5 years."""
    cfg = CalibrationConfig(
        model_name="m", calib_dir=tmp_path,
        eval_start_yr=1983, eval_end_yr=2018, tt_split_freq=1,
    )
    assert list(cfg.train_years) == list(range(1988, 2018))
    assert list(cfg.test_years) == list(range(1983, 1988))


def test_train_years_split_freq_four_alternates(tmp_path: Path):
    """tt_split_freq=4 → every 4th year is test, the rest is training."""
    cfg = CalibrationConfig(
        model_name="m", calib_dir=tmp_path,
        eval_start_yr=2000, eval_end_yr=2010, tt_split_freq=4,
    )
    # All years 2000..2009. Test = [2000, 2004, 2008]. Train = the rest.
    assert list(cfg.test_years) == [2000, 2004, 2008]
    assert list(cfg.train_years) == [2001, 2002, 2003, 2005, 2006, 2007, 2009]


def test_rejects_negative_tt_split_freq(tmp_path: Path):
    with pytest.raises(ValueError, match="tt_split_freq"):
        CalibrationConfig(model_name="m", calib_dir=tmp_path, tt_split_freq=-1)


def test_rejects_inverted_eval_window(tmp_path: Path):
    with pytest.raises(ValueError, match="eval_end_yr"):
        CalibrationConfig(
            model_name="m", calib_dir=tmp_path,
            eval_start_yr=2010, eval_end_yr=2005,
        )


def test_round_trip_includes_new_fields(tmp_path: Path):
    """to_dict / from_dict preserves tt_split_freq and event_based."""
    original = CalibrationConfig(
        model_name="m", calib_dir=tmp_path,
        tt_split_freq=4, event_based=True,
    )
    rebuilt = CalibrationConfig.from_dict(original.to_dict())
    assert rebuilt.tt_split_freq == 4
    assert rebuilt.event_based is True


# ---------------------------------------------------------------------------
# Updated parameter priors (upstream commit 230493c)
# ---------------------------------------------------------------------------


def _find_dist(dists, name):
    return next(d for d in dists if d.name == name)


def test_dep_fact_prior_uses_widened_range(tmp_path: Path):
    """Upstream widened dep_fact from [0.10, 1.00] to [0.4, 1.2]."""
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, dep_scaling=True)
    dists, _ = build_param_distributions(cfg)
    dep = _find_dist(dists, "dep_fact")
    # SpotPY stores the configured low/high in rndargs; minbound is a
    # post-construction sample so isn't a reliable bound check.
    low, high = dep.rndargs
    assert low == pytest.approx(0.4)
    assert high == pytest.approx(1.2)
    assert dep.optguess == pytest.approx(0.8)


def test_t_peak_fact_prior_uses_widened_range(tmp_path: Path):
    """Upstream widened t_peak_fact from [0.4, 1.2] to [0.2, 5.0]."""
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, routing=True)
    dists, _ = build_param_distributions(cfg)
    tpeak = _find_dist(dists, "t_peak_fact")
    low, high = tpeak.rndargs
    assert low == pytest.approx(0.2)
    assert high == pytest.approx(5.0)


def test_to_yaml_writes_human_readable_file(tmp_path: Path):
    cfg = CalibrationConfig(model_name="grassmere", calib_dir=tmp_path)
    out = tmp_path / "out" / "calibration.yml"
    written = cfg.to_yaml(out)
    assert written == out
    text = out.read_text()
    assert text.startswith("model_name: grassmere")
    assert "!!python" not in text
    assert "obj_fn: kge_adj" in text


def test_to_yaml_round_trip(tmp_path: Path):
    cfg = CalibrationConfig(
        model_name="manning",
        calib_dir=tmp_path,
        obj_fn="nse",
        mpi_cores=8,
    )
    out = tmp_path / "calibration.yml"
    cfg.to_yaml(out)
    rebuilt = CalibrationConfig.from_yaml(out)
    assert rebuilt == cfg


def test_to_yaml_creates_parent_dir(tmp_path: Path):
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path)
    out = tmp_path / "deeply" / "nested" / "calibration.yml"
    cfg.to_yaml(out)
    assert out.is_file()


# ---------------------------------------------------------------------------
# _stage_worker_directory
# ---------------------------------------------------------------------------


def _populate_calib_dir(root: Path) -> None:
    """Build a realistic calib_dir layout: input/, templates/, output/,
    a few top-level .rv* files and a Raven binary."""
    (root / "input").mkdir(parents=True)
    (root / "input" / "HRU_areas.csv").write_text("HRU,AREA\n101,1.0\n")
    (root / "templates").mkdir()
    (root / "templates" / "model.rvh.tpl").write_text(":SubBasins\n")
    (root / "output").mkdir()
    (root / "output" / "Hydrographs.csv").write_text("date,sim\n2010-01-01,1.5\n")
    (root / "output" / "Diagnostics.csv").write_text("name,value\nNSE,0.5\n")
    (root / "model.rvi").write_text(":StartDate 2010-01-01\n")
    (root / "model.rvc").write_text(":InitialConditions\n")
    (root / "Raven.exe").write_text("binary")


def test_stage_worker_directory_skips_output_dir(tmp_path: Path):
    """Output/ is Raven's per-iteration scratch directory. Staging it
    is the root cause of the IISD MPI failure: a Hydrographs.csv from a
    prior killed Raven run is in an inconsistent state and trips
    robust_copy's checksum verification. Excluding it is the fix."""
    source = tmp_path / "calib"
    dest = tmp_path / "core0"
    _populate_calib_dir(source)

    _stage_worker_directory(source, dest)

    # output/ exists in dest — but EMPTY. The pre-existing stale files
    # from source/output/ were not carried over.
    assert (dest / "output").is_dir()
    assert list((dest / "output").iterdir()) == []
    # The non-scratch content was staged normally.
    assert (dest / "input" / "HRU_areas.csv").is_file()
    assert (dest / "templates" / "model.rvh.tpl").is_file()
    assert (dest / "model.rvi").is_file()
    assert (dest / "Raven.exe").is_file()


def test_stage_worker_directory_creates_output_when_source_has_none(
    tmp_path: Path,
):
    """A freshly-prepared calib_dir might not have output/ yet — the
    worker still needs an empty one to exist so Raven's -o ./output/
    invocation doesn't fail on a missing directory."""
    source = tmp_path / "calib"
    dest = tmp_path / "core0"
    source.mkdir()
    (source / "model.rvi").write_text("")  # at least one file so the loop runs

    _stage_worker_directory(source, dest)

    assert (dest / "output").is_dir()
    assert list((dest / "output").iterdir()) == []


def test_stage_worker_directory_doesnt_inherit_stale_outputs(tmp_path: Path):
    """Regression: a half-written Hydrographs.csv left over from a
    killed Raven process in the source must not propagate into a fresh
    worker directory — otherwise robust_copy would race against a
    Windows file lock or partial write and fail with the exact
    'Checksum mismatch ... after 3 attempts' error Thomas hit."""
    source = tmp_path / "calib"
    dest = tmp_path / "core0"
    _populate_calib_dir(source)

    _stage_worker_directory(source, dest)

    assert not (dest / "output" / "Hydrographs.csv").exists()
    assert not (dest / "output" / "Diagnostics.csv").exists()
