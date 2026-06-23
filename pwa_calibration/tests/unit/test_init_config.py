"""Tests for the pwa_calibration.init_config CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from pwa_calibration.init_config import _build_arg_parser, main
from pwa_calibration.setup import CalibrationConfig


def test_arg_parser_requires_output_path():
    parser = _build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_arg_parser_minimal(tmp_path: Path):
    parser = _build_arg_parser()
    args = parser.parse_args([str(tmp_path / "out.yml")])
    assert args.output_path == tmp_path / "out.yml"
    assert args.base_calib_dir is None
    assert args.force is False


def _stub_inputs(monkeypatch, answers: list[str]) -> None:
    """Replace input() with a queue of canned answers."""
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(iterator))


def test_main_writes_valid_yaml(monkeypatch, tmp_path: Path, capsys):
    """End-to-end: feed stdin, get a YAML file that round-trips through
    CalibrationConfig."""
    out = tmp_path / "calibration.yml"
    # Match prompt_for_calibration_config's call sequence.
    _stub_inputs(monkeypatch, [
        "grassmere",                                    # model_name
        str(tmp_path / "Calibration" / "grassmere"),    # calib_dir
        "nse_pbias",                                    # obj_fn
        "2003",                                         # eval_start_yr
        "2021",                                         # eval_end_yr
        "14",                                           # mpi_cores
        "200",                                          # repetitions
        "rope",                                         # algorithm
    ])

    rc = main([str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    assert f"Wrote {out}" in captured.out

    cfg = CalibrationConfig.from_yaml(out)
    assert cfg.model_name == "grassmere"
    assert cfg.obj_fn == "nse_pbias"
    assert cfg.eval_start_yr == 2003
    assert cfg.eval_end_yr == 2021
    assert cfg.mpi_cores == 14
    assert cfg.repetitions == 200
    assert cfg.algorithm == "rope"
    # The dataclass defaults flow through (we didn't prompt for these)
    assert cfg.spring_eval is True
    assert cfg.routing is False
    assert cfg.phydap_adj is False    # legacy class default


def test_main_uses_defaults_on_blank_input(monkeypatch, tmp_path: Path):
    """Pressing Enter on optional prompts keeps the dataclass default."""
    out = tmp_path / "calibration.yml"
    _stub_inputs(monkeypatch, [
        "manning",                                      # required: model_name
        str(tmp_path / "Calibration" / "manning"),      # required: calib_dir
        "",                                             # obj_fn (default kge_adj)
        "",                                             # eval_start_yr (1995)
        "",                                             # eval_end_yr (2010)
        "",                                             # mpi_cores (0)
        "",                                             # repetitions (10)
        "",                                             # algorithm (mc)
    ])

    rc = main([str(out)])
    assert rc == 0

    cfg = CalibrationConfig.from_yaml(out)
    assert cfg.model_name == "manning"
    assert cfg.obj_fn == "kge_adj"
    assert cfg.eval_start_yr == 1995
    assert cfg.eval_end_yr == 2010
    assert cfg.mpi_cores == 0
    assert cfg.repetitions == 10
    assert cfg.algorithm == "mc"


def test_main_refuses_overwrite_without_force(monkeypatch, tmp_path: Path, capsys):
    out = tmp_path / "existing.yml"
    out.write_text("model_name: keep_me\ncalib_dir: ./\n")

    monkeypatch.setattr(
        "builtins.input",
        lambda *_a, **_kw: pytest.fail("input() called despite refuse-overwrite"),
    )

    rc = main([str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Refusing to overwrite" in err
    assert out.read_text().startswith("model_name: keep_me")


def test_main_overwrites_with_force(monkeypatch, tmp_path: Path):
    out = tmp_path / "existing.yml"
    out.write_text("model_name: stale\ncalib_dir: ./\n")
    _stub_inputs(monkeypatch, [
        "fresh", str(tmp_path / "fresh"), "", "", "", "", "", "",
    ])
    rc = main([str(out), "--force"])
    assert rc == 0
    assert "model_name: fresh" in out.read_text()


def test_main_creates_output_parent(monkeypatch, tmp_path: Path):
    out = tmp_path / "deeply" / "nested" / "calibration.yml"
    _stub_inputs(monkeypatch, [
        "deepwater", str(tmp_path / "deepwater"), "", "", "", "", "", "",
    ])
    rc = main([str(out)])
    assert rc == 0
    assert out.is_file()
