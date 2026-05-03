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
    parser = _build_arg_parser()
    args = parser.parse_args(
        [
            "results",
            "--model-name",
            "grassmere",
            "--calib-dir",
            str(tmp_path),
        ]
    )
    cfg = CalibrationConfig(
        model_name=args.model_name,
        calib_dir=args.calib_dir,
        obj_fn=args.obj_fn,
        eval_start_yr=args.eval_start_yr,
        eval_end_yr=args.eval_end_yr,
        spring_eval=not args.no_spring_eval,
        low_seep=args.low_seep,
        routing=args.routing,
        dep_scaling=args.dep_scaling,
        runoff_scaling=args.runoff_scaling,
        channel_scaling=args.channel_scaling,
        phydap_adj=not args.no_phydap_adj,
        mpi_cores=args.mpi_cores,
    )
    assert cfg.model_name == "grassmere"
    assert cfg.calib_dir == tmp_path
    assert cfg.obj_fn == "kge_adj"  # default
    assert cfg.spring_eval is True
    assert cfg.phydap_adj is True
    assert cfg.is_mpi is False  # mpi_cores defaults to 0


def test_cli_full_flag_set(tmp_path: Path):
    parser = _build_arg_parser()
    args = parser.parse_args(
        [
            "calib_run",
            "--model-name",
            "manning",
            "--calib-dir",
            str(tmp_path),
            "--obj-fn",
            "nse_pbias",
            "--eval-start-yr",
            "2003",
            "--eval-end-yr",
            "2021",
            "--mpi-cores",
            "14",
            "--repetitions",
            "100",
            "--no-spring-eval",
            "--low-seep",
            "--routing",
            "--dep-scaling",
            "--runoff-scaling",
            "--channel-scaling",
            "--no-phydap-adj",
        ]
    )
    cfg = CalibrationConfig(
        model_name=args.model_name,
        calib_dir=args.calib_dir,
        obj_fn=args.obj_fn,
        eval_start_yr=args.eval_start_yr,
        eval_end_yr=args.eval_end_yr,
        spring_eval=not args.no_spring_eval,
        low_seep=args.low_seep,
        routing=args.routing,
        dep_scaling=args.dep_scaling,
        runoff_scaling=args.runoff_scaling,
        channel_scaling=args.channel_scaling,
        phydap_adj=not args.no_phydap_adj,
        mpi_cores=args.mpi_cores,
    )
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
