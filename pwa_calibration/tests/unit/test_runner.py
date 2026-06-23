"""Unit tests for pwa_calibration.runner.

The full ``run_calibration`` path requires Raven + MPI and is reserved
for integration tests. This module covers the testable surfaces:
* :func:`safe_get_best_runs` against numpy-array params (the bug it fixes)
* :func:`patch_rope_get_best_runs` is idempotent and version-resilient
* :func:`_build_dbname` formatting
* CLI parsing builds a valid CalibrationConfig
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pwa_calibration import runner
from pwa_calibration.runner import (
    _build_arg_parser,
    _build_dbname,
    patch_rope_get_best_runs,
    safe_get_best_runs,
)
from pwa_calibration.setup import CalibrationConfig


def _fake_setup(rank: int = 1) -> SimpleNamespace:
    """Stand-in for SpotPySetup used by the flow-shape tests.

    Defaults to rank=1 so run_calibration skips the tqdm bar entirely —
    most of these tests are about *which sampler runs with what args*
    and don't want a real progress bar polluting stdout. The rank-0
    progress-bar path has its own dedicated tests below.
    """
    return SimpleNamespace(rank=rank, progress_bar=None)


# ---------------------------------------------------------------------------
# safe_get_best_runs
# ---------------------------------------------------------------------------


class _FakeSelf:
    """Stand-in for the ROPE algorithm's `self` (only used as receiver)."""


def test_safe_get_best_runs_with_scalar_params():
    likes = [0.1, 0.5, 0.9, 0.3]
    pars = [10.0, 50.0, 90.0, 30.0]
    # Top 50% → sorted likes [0.1, 0.3, 0.5, 0.9]; we want the upper half
    out = safe_get_best_runs(_FakeSelf(), likes, pars, runs=4, percentage=0.5)
    assert out == [50.0, 90.0]


def test_safe_get_best_runs_with_numpy_array_params():
    """The original bug: ndarray params can't be sorted as tuples."""
    likes = [0.2, 0.8, 0.5]
    pars = [np.array([1, 2]), np.array([3, 4]), np.array([5, 6])]
    out = safe_get_best_runs(_FakeSelf(), likes, pars, runs=3, percentage=0.5)
    # Top 50% of 3 → upper int(3*0.5)=1 → 2 entries (slice [1:])
    # Sorted by likes: 0.2→[1,2], 0.5→[5,6], 0.8→[3,4] → top = [[5,6], [3,4]]
    assert out == [[5, 6], [3, 4]]


def test_safe_get_best_runs_propagates_unexpected_errors():
    # Likes/pars length mismatch isn't checked but indexing pars[0] on
    # an empty list raises IndexError — verify it propagates.
    with pytest.raises(IndexError):
        safe_get_best_runs(_FakeSelf(), [0.1], [], runs=1, percentage=1.0)


# ---------------------------------------------------------------------------
# patch_rope_get_best_runs
# ---------------------------------------------------------------------------


def test_patch_rope_get_best_runs_applies_when_target_exists():
    from spotpy.algorithms import rope

    original = rope.get_best_runs  # may be the original or already patched
    try:
        result = patch_rope_get_best_runs()
        assert result is True
        assert rope.get_best_runs is safe_get_best_runs
    finally:
        rope.get_best_runs = original  # restore


def test_patch_rope_get_best_runs_returns_false_when_target_missing(monkeypatch):
    """If spotpy refactors the API and the method goes away, patch no-ops."""
    from spotpy.algorithms import rope

    monkeypatch.delattr(rope, "get_best_runs", raising=False)
    assert patch_rope_get_best_runs() is False


# ---------------------------------------------------------------------------
# dbname
# ---------------------------------------------------------------------------


def test_build_dbname_starts_with_timestamp(monkeypatch):
    import pwa_calibration.runner as runner_mod

    class _FixedDatetime:
        @classmethod
        def now(cls):
            from datetime import datetime as _dt
            return _dt(2026, 5, 3, 14, 30, 0)

    monkeypatch.setattr(runner_mod, "datetime", _FixedDatetime)
    assert _build_dbname("results") == "20260503_14results"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_builds_minimal_config(tmp_path: Path):
    """With only the required flags, optional fields fall back to
    CalibrationConfig dataclass defaults via _build_config_from_args."""
    from pwa_calibration.runner import _build_config_from_args
    parser = _build_arg_parser()
    args = parser.parse_args(
        ["results", "--model-name", "grassmere", "--calib-dir", str(tmp_path)],
    )
    cfg = _build_config_from_args(args)
    assert cfg.model_name == "grassmere"
    assert cfg.calib_dir == tmp_path
    assert cfg.obj_fn == "kge_adj"  # legacy class default
    assert cfg.spring_eval is True
    assert cfg.phydap_adj is False  # legacy class default
    assert cfg.is_mpi is False  # mpi_cores defaults to 0


def test_cli_full_flag_set(tmp_path: Path):
    from pwa_calibration.runner import _build_config_from_args
    parser = _build_arg_parser()
    args = parser.parse_args(
        [
            "calib_run",
            "--model-name", "manning",
            "--calib-dir", str(tmp_path),
            "--obj-fn", "nse_pbias",
            "--eval-start-yr", "2003",
            "--eval-end-yr", "2021",
            "--mpi-cores", "14",
            "--repetitions", "100",
            "--no-spring-eval",
            "--low-seep",
            "--routing",
            "--dep-scaling",
            "--runoff-scaling",
            "--channel-scaling",
            "--no-phydap-adj",
        ]
    )
    cfg = _build_config_from_args(args)
    assert cfg.obj_fn == "nse_pbias"
    assert cfg.eval_start_yr == 2003
    assert cfg.eval_end_yr == 2021
    assert cfg.is_mpi is True
    assert cfg.spring_eval is False
    assert cfg.low_seep is True
    assert cfg.routing is True
    assert cfg.phydap_adj is False
    assert args.repetitions == 100


def test_cli_rejects_unknown_obj_fn(tmp_path: Path):
    parser = _build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["x", "--model-name", "m", "--calib-dir", str(tmp_path), "--obj-fn", "bogus"]
        )


# ---------------------------------------------------------------------------
# Staging integration (--stage-from / --netcdf-category + run_calibration's
# `staging` keyword)
# ---------------------------------------------------------------------------


from pwa_calibration.prepare import StagingPaths
from pwa_calibration.runner import main as runner_main
from pwa_calibration.runner import run_calibration


def test_cli_stage_from_flags_default_to_none(tmp_path: Path):
    parser = _build_arg_parser()
    args = parser.parse_args(
        ["x", "--model-name", "m", "--calib-dir", str(tmp_path)]
    )
    assert args.stage_from is None
    assert args.netcdf_category is None


def test_cli_stage_from_requires_netcdf_category(tmp_path: Path, capsys):
    """argparse --stage-from without --netcdf-category should error out."""
    rc = None
    try:
        runner_main([
            "results",
            "--model-name", "grassmere",
            "--calib-dir", str(tmp_path),
            "--stage-from", str(tmp_path / "Data"),
        ])
    except SystemExit as exc:
        rc = exc.code
    assert rc == 2  # argparse error exit
    err = capsys.readouterr().err
    assert "--stage-from" in err and "--netcdf-category" in err


def test_cli_netcdf_category_requires_stage_from(tmp_path: Path, capsys):
    """The mutual-requirement check is symmetric."""
    rc = None
    try:
        runner_main([
            "results",
            "--model-name", "grassmere",
            "--calib-dir", str(tmp_path),
            "--netcdf-category", "Runoff",
        ])
    except SystemExit as exc:
        rc = exc.code
    assert rc == 2
    err = capsys.readouterr().err
    assert "--stage-from" in err and "--netcdf-category" in err


def test_run_calibration_calls_prepare_when_staging_set(monkeypatch, tmp_path: Path):
    """When ``staging`` is provided, run_calibration calls
    prepare_calibration_directory before validate_inputs_exist."""
    call_log: list[str] = []

    def fake_prepare(paths: StagingPaths):
        call_log.append("prepare")
        # Mimic the real return shape — has .copied / .skipped_existing
        # / .missing_sources lists.
        from pwa_calibration.prepare import StagingReport
        return StagingReport()

    def fake_validate(self):
        call_log.append("validate")

    def fake_setup(_config):
        call_log.append("setup")
        return _fake_setup()

    def fake_alg_mc(*_a, **_kw):
        class _S:
            def sample(self, *_a, **_kw):
                call_log.append("sample")
        return _S()

    import pwa_calibration.runner as runner_mod
    monkeypatch.setattr(runner_mod, "prepare_calibration_directory", fake_prepare)
    monkeypatch.setattr(
        "pwa_calibration.setup.CalibrationConfig.validate_inputs_exist",
        fake_validate,
    )
    monkeypatch.setattr(runner_mod, "SpotPySetup", fake_setup)
    monkeypatch.setattr(runner_mod, "patch_rope_get_best_runs", lambda: True)
    monkeypatch.setattr("spotpy.algorithms.mc", fake_alg_mc)

    cfg = CalibrationConfig(model_name="grassmere", calib_dir=tmp_path)
    staging = StagingPaths(
        watershed_name="grassmere",
        data_root=tmp_path / "Data",
        netcdf_category="Runoff",
    )
    run_calibration(cfg, repetitions=1, db_suffix="x", staging=staging)

    # prepare must run BEFORE validate (otherwise we'd validate before the
    # files are in place and fail spuriously)
    assert call_log[:2] == ["prepare", "validate"]
    assert "sample" in call_log


def test_run_calibration_skips_prepare_when_staging_none(monkeypatch, tmp_path: Path):
    """When staging is None (default), prepare_calibration_directory is
    never called — the calibration directory must already be populated."""
    called = {"prepare": 0}

    def fake_prepare(_paths):
        called["prepare"] += 1
        from pwa_calibration.prepare import StagingReport
        return StagingReport()

    monkeypatch.setattr(
        "pwa_calibration.runner.prepare_calibration_directory", fake_prepare
    )
    monkeypatch.setattr(
        "pwa_calibration.setup.CalibrationConfig.validate_inputs_exist",
        lambda self: None,
    )
    monkeypatch.setattr(
        "pwa_calibration.runner.SpotPySetup", lambda _c: _fake_setup()
    )
    monkeypatch.setattr("pwa_calibration.runner.patch_rope_get_best_runs", lambda: True)

    class _Sampler:
        def sample(self, *_a, **_kw):
            pass

    monkeypatch.setattr("spotpy.algorithms.mc", lambda *_a, **_kw: _Sampler())

    cfg = CalibrationConfig(model_name="grassmere", calib_dir=tmp_path)
    run_calibration(cfg, repetitions=1, db_suffix="x")  # no staging arg

    assert called["prepare"] == 0


# ---------------------------------------------------------------------------
# CLI --config flag (YAML-driven config + per-field overrides)
# ---------------------------------------------------------------------------


from pwa_calibration.runner import _build_config_from_args


def _write_yaml_config(path: Path, **overrides) -> Path:
    cfg = CalibrationConfig(
        model_name=overrides.pop("model_name", "yamlbase"),
        calib_dir=overrides.pop("calib_dir", path.parent / "yamlbase"),
        **overrides,
    )
    return cfg.to_yaml(path)


def test_cli_accepts_config_yaml_with_no_per_field_flags(tmp_path: Path):
    yml = _write_yaml_config(
        tmp_path / "calibration.yml",
        obj_fn="nse_pbias",
        eval_start_yr=2003,
    )
    parser = _build_arg_parser()
    args = parser.parse_args(["x", "--config", str(yml)])
    cfg = _build_config_from_args(args)
    assert cfg.model_name == "yamlbase"
    assert cfg.obj_fn == "nse_pbias"
    assert cfg.eval_start_yr == 2003


def test_cli_per_field_flag_overrides_yaml(tmp_path: Path):
    """Explicit CLI flag wins over the YAML value."""
    yml = _write_yaml_config(tmp_path / "calibration.yml", obj_fn="nse_pbias")
    parser = _build_arg_parser()
    args = parser.parse_args([
        "x",
        "--config", str(yml),
        "--obj-fn", "nse",  # override
    ])
    cfg = _build_config_from_args(args)
    assert cfg.obj_fn == "nse"


def test_cli_boolean_flag_overrides_yaml(tmp_path: Path):
    """A store_true flag flips the YAML False to True. (No --no-X — to
    flip True → False, edit the YAML.)"""
    yml = _write_yaml_config(tmp_path / "calibration.yml")  # routing default False
    parser = _build_arg_parser()
    args = parser.parse_args(["x", "--config", str(yml), "--routing"])
    cfg = _build_config_from_args(args)
    assert cfg.routing is True


def test_cli_without_config_or_required_fields_exits(tmp_path: Path):
    parser = _build_arg_parser()
    args = parser.parse_args(["x"])  # no --config, no --model-name, no --calib-dir
    with pytest.raises(SystemExit):
        _build_config_from_args(args)


# ---------------------------------------------------------------------------
# parallel= selection, algorithm dispatch, repetitions fallback
# ---------------------------------------------------------------------------


def _install_calibration_stubs(monkeypatch, algo_name: str) -> dict:
    """Monkeypatch the run_calibration collaborators so it executes without
    Raven/MPI, and record what the sampler constructor + .sample() received.

    Returns a dict populated with `ctor_kwargs`, `sample_reps`,
    `sample_kwargs` once run_calibration has been called.
    """
    rec: dict = {}

    def fake_cls(_setup, **kwargs):
        rec["ctor_kwargs"] = kwargs

        class _Sampler:
            def sample(self, reps, **skwargs):
                rec["sample_reps"] = reps
                rec["sample_kwargs"] = skwargs

        return _Sampler()

    monkeypatch.setattr(f"spotpy.algorithms.{algo_name}", fake_cls)
    monkeypatch.setattr(
        "pwa_calibration.setup.CalibrationConfig.validate_inputs_exist",
        lambda self: None,
    )
    monkeypatch.setattr("pwa_calibration.runner.SpotPySetup", lambda _c: _fake_setup())
    monkeypatch.setattr(
        "pwa_calibration.runner.patch_rope_get_best_runs", lambda: True
    )
    return rec


def test_run_calibration_uses_seq_parallel_when_serial(monkeypatch, tmp_path: Path):
    rec = _install_calibration_stubs(monkeypatch, "mc")
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, mpi_cores=0)
    run_calibration(cfg, db_suffix="x")
    assert rec["ctor_kwargs"]["parallel"] == "seq"


def test_run_calibration_uses_mpi_parallel_when_mpi(monkeypatch, tmp_path: Path):
    rec = _install_calibration_stubs(monkeypatch, "mc")
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, mpi_cores=4)
    run_calibration(cfg, db_suffix="x")
    assert rec["ctor_kwargs"]["parallel"] == "mpi"


def test_run_calibration_dispatches_to_configured_algorithm(monkeypatch, tmp_path: Path):
    rec = _install_calibration_stubs(monkeypatch, "rope")
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, algorithm="rope")
    run_calibration(cfg, db_suffix="x")
    # If dispatch picked the wrong class, the rope recorder would be empty.
    assert "ctor_kwargs" in rec


def test_run_calibration_passes_algorithm_kwargs_to_sample(monkeypatch, tmp_path: Path):
    rec = _install_calibration_stubs(monkeypatch, "demcz")
    cfg = CalibrationConfig(
        model_name="m",
        calib_dir=tmp_path,
        algorithm="demcz",
        algorithm_kwargs={"nChains": 6},
    )
    run_calibration(cfg, db_suffix="x")
    assert rec["sample_kwargs"] == {"nChains": 6}


def test_run_calibration_repetitions_falls_back_to_config(monkeypatch, tmp_path: Path):
    rec = _install_calibration_stubs(monkeypatch, "mc")
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, repetitions=7)
    run_calibration(cfg, db_suffix="x")  # no repetitions arg
    assert rec["sample_reps"] == 7


def test_run_calibration_explicit_repetitions_overrides_config(monkeypatch, tmp_path: Path):
    rec = _install_calibration_stubs(monkeypatch, "mc")
    cfg = CalibrationConfig(model_name="m", calib_dir=tmp_path, repetitions=99)
    run_calibration(cfg, db_suffix="x", repetitions=3)
    assert rec["sample_reps"] == 3


# ---------------------------------------------------------------------------
# CLI: --repetitions / --algorithm flow into the config
# ---------------------------------------------------------------------------


def test_cli_repetitions_default_is_none(tmp_path: Path):
    """--repetitions must default to None so explicit use is distinguishable
    from the default (otherwise it would always override the YAML)."""
    parser = _build_arg_parser()
    args = parser.parse_args(["x", "--model-name", "m", "--calib-dir", str(tmp_path)])
    assert args.repetitions is None


def test_cli_repetitions_flows_into_config(tmp_path: Path):
    parser = _build_arg_parser()
    args = parser.parse_args(
        ["x", "--model-name", "m", "--calib-dir", str(tmp_path), "--repetitions", "500"]
    )
    cfg = _build_config_from_args(args)
    assert cfg.repetitions == 500


def test_cli_algorithm_flows_into_config(tmp_path: Path):
    parser = _build_arg_parser()
    args = parser.parse_args(
        ["x", "--model-name", "m", "--calib-dir", str(tmp_path), "--algorithm", "rope"]
    )
    cfg = _build_config_from_args(args)
    assert cfg.algorithm == "rope"


def test_cli_rejects_unknown_algorithm(tmp_path: Path):
    parser = _build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["x", "--model-name", "m", "--calib-dir", str(tmp_path), "--algorithm", "bogus"]
        )


# ---------------------------------------------------------------------------
# Progress bar (rank-gated)
# ---------------------------------------------------------------------------


def _install_tqdm_recorder(monkeypatch) -> dict:
    """Replace tqdm.auto.tqdm with a recorder that captures construction
    kwargs and tracks .update / .close calls. Returns the rec dict.
    """
    rec: dict = {"ctor_kwargs": None, "updates": [], "closed": False, "instances": 0}

    class _RecorderBar:
        def __init__(self, **kwargs):
            rec["ctor_kwargs"] = kwargs
            rec["instances"] += 1

        def update(self, n=1):
            rec["updates"].append(n)

        def close(self):
            rec["closed"] = True

    monkeypatch.setattr("tqdm.auto.tqdm", _RecorderBar)
    return rec


def test_run_calibration_creates_progress_bar_on_rank_0(monkeypatch, tmp_path: Path):
    """Rank 0 owns the user-facing progress bar — verify it is
    constructed with the requested rep count, attached to the setup,
    and closed in the finally block after sampling."""
    rec = _install_tqdm_recorder(monkeypatch)

    captured_setup = {"value": None}

    def fake_setup_factory(_config):
        s = _fake_setup(rank=0)
        captured_setup["value"] = s
        return s

    monkeypatch.setattr("pwa_calibration.runner.SpotPySetup", fake_setup_factory)
    monkeypatch.setattr(
        "pwa_calibration.setup.CalibrationConfig.validate_inputs_exist",
        lambda self: None,
    )
    monkeypatch.setattr("pwa_calibration.runner.patch_rope_get_best_runs", lambda: True)

    class _Sampler:
        def sample(self, *_a, **_kw):
            pass

    monkeypatch.setattr("spotpy.algorithms.mc", lambda *_a, **_kw: _Sampler())

    cfg = CalibrationConfig(model_name="grassmere", calib_dir=tmp_path, repetitions=7)
    runner.run_calibration(cfg, db_suffix="x")

    assert rec["instances"] == 1
    assert rec["ctor_kwargs"]["total"] == 7
    assert rec["ctor_kwargs"]["desc"] == "Calibrating grassmere"
    # setup.progress_bar should have been wired so simulation() can tick it
    assert captured_setup["value"].progress_bar is not None
    # Bar must be closed even on successful completion
    assert rec["closed"] is True


def test_run_calibration_skips_progress_bar_on_non_zero_rank(
    monkeypatch, tmp_path: Path,
):
    """MPI worker ranks (rank > 0) must not construct a bar — multiple
    ranks fighting for stdout would render an unreadable mess. Per-rank
    log lines carry the progress signal for non-master ranks."""
    rec = _install_tqdm_recorder(monkeypatch)

    monkeypatch.setattr(
        "pwa_calibration.runner.SpotPySetup", lambda _c: _fake_setup(rank=1)
    )
    monkeypatch.setattr(
        "pwa_calibration.setup.CalibrationConfig.validate_inputs_exist",
        lambda self: None,
    )
    monkeypatch.setattr("pwa_calibration.runner.patch_rope_get_best_runs", lambda: True)

    class _Sampler:
        def sample(self, *_a, **_kw):
            pass

    monkeypatch.setattr("spotpy.algorithms.mc", lambda *_a, **_kw: _Sampler())

    cfg = CalibrationConfig(model_name="grassmere", calib_dir=tmp_path, repetitions=5)
    runner.run_calibration(cfg, db_suffix="x")

    # tqdm must NOT have been constructed at all on rank 1
    assert rec["instances"] == 0
    assert rec["closed"] is False


def test_run_calibration_closes_progress_bar_even_if_sample_raises(
    monkeypatch, tmp_path: Path,
):
    """A sampler exception must not leave the tqdm bar dangling — it'd
    sit half-rendered in the terminal until the process exits. The
    finally clause owns the close call."""
    rec = _install_tqdm_recorder(monkeypatch)

    monkeypatch.setattr(
        "pwa_calibration.runner.SpotPySetup", lambda _c: _fake_setup(rank=0)
    )
    monkeypatch.setattr(
        "pwa_calibration.setup.CalibrationConfig.validate_inputs_exist",
        lambda self: None,
    )
    monkeypatch.setattr("pwa_calibration.runner.patch_rope_get_best_runs", lambda: True)

    class _BadSampler:
        def sample(self, *_a, **_kw):
            raise RuntimeError("sampler exploded")

    monkeypatch.setattr("spotpy.algorithms.mc", lambda *_a, **_kw: _BadSampler())

    cfg = CalibrationConfig(model_name="grassmere", calib_dir=tmp_path, repetitions=3)
    with pytest.raises(RuntimeError, match="sampler exploded"):
        runner.run_calibration(cfg, db_suffix="x")
    assert rec["closed"] is True
