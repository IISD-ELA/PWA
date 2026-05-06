"""Tests for the pwa_raven.run_step1 / run_step2 CLI wrappers.

These wrappers are intentionally thin (parse args → load config → call
the existing run_step* function → print summary). The Step1Config /
Step2Config / run_step* unit tests cover the heavy lifting; here we
verify the wrapper behaviour:

* ``--config`` defaults to ``./step{1,2}.yml`` and errors with a
  helpful message when missing.
* The runner is also importable so notebooks can drive the same code
  path without going through argparse.
* The CLI returns 0 on success and prints a summary of every output.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pwa_raven.run_step1 import _build_arg_parser as _step1_parser
from pwa_raven.run_step1 import main as step1_main
from pwa_raven.run_step2 import _build_arg_parser as _step2_parser
from pwa_raven.run_step2 import main as step2_main


# ---------------------------------------------------------------------------
# Re-export contract — notebook callers should be able to import either
# the runner module's `run_step*` or the underlying step* module's. Both
# must point at the same callable.
# ---------------------------------------------------------------------------


def test_step1_runner_reexports_callable():
    from pwa_raven import run_step1 as runner_mod
    from pwa_raven.step1 import run_step1 as step1_mod_callable

    assert runner_mod.run_step1 is step1_mod_callable


def test_step2_runner_reexports_callable():
    from pwa_raven import run_step2 as runner_mod
    from pwa_raven.step2 import run_step2 as step2_mod_callable

    assert runner_mod.run_step2 is step2_mod_callable


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def test_step1_parser_default_config_path(tmp_path: Path):
    args = _step1_parser().parse_args([])
    assert args.config == Path("step1.yml")
    assert args.log_level == "INFO"


def test_step2_parser_default_config_path(tmp_path: Path):
    args = _step2_parser().parse_args([])
    assert args.config == Path("step2.yml")
    assert args.log_level == "INFO"


def test_step1_parser_accepts_log_level(tmp_path: Path):
    args = _step1_parser().parse_args(["--log-level", "DEBUG"])
    assert args.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Missing-config behaviour
# ---------------------------------------------------------------------------


def test_step1_main_returns_1_when_config_missing(tmp_path: Path, capsys):
    rc = step1_main(["--config", str(tmp_path / "doesnt_exist.yml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Config file not found" in err
    assert "init_step1_config" in err   # points the user at the generator


def test_step2_main_returns_1_when_config_missing(tmp_path: Path, capsys):
    rc = step2_main(["--config", str(tmp_path / "doesnt_exist.yml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Config file not found" in err
    assert "init_step2_config" in err


# ---------------------------------------------------------------------------
# Happy-path CLI invocation (with run_step* mocked — we already have e2e
# tests for the real runners in test_step1.py / test_step2.py).
# ---------------------------------------------------------------------------


def test_step1_main_loads_config_and_calls_run_step1(monkeypatch, tmp_path: Path, capsys):
    from pwa_raven.step1 import Step1Config

    # Build a real config + write it to YAML.
    cfg = Step1Config(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        phydap_nc=tmp_path / "phydap.nc",
        phydap_shapefile=tmp_path / "phydap.shp",
        subbasins_shapefile=tmp_path / "subbasins.shp",
    )
    yml = tmp_path / "step1.yml"
    cfg.to_yaml(yml)

    fake_result = MagicMock(
        subset_nc=tmp_path / "subset.nc",
        adjusted_nc=tmp_path / "adj.nc",
        hybas_map=tmp_path / "hybas_map.csv",
        grid_weights=tmp_path / "GridWeights.txt",
    )
    fake_run = MagicMock(return_value=fake_result)
    monkeypatch.setattr("pwa_raven.run_step1.run_step1", fake_run)

    rc = step1_main(["--config", str(yml)])
    assert rc == 0

    fake_run.assert_called_once()
    called_cfg = fake_run.call_args[0][0]
    assert called_cfg.watershed_name == "testwater"

    out = capsys.readouterr().out
    assert "subset.nc" in out
    assert "GridWeights.txt" in out


def test_step2_main_loads_config_and_calls_run_step2(monkeypatch, tmp_path: Path, capsys):
    from pwa_raven.step2 import Step2Config

    cfg = Step2Config(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        subbasins_shapefile=tmp_path / "s.shp",
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
    )
    yml = tmp_path / "step2.yml"
    cfg.to_yaml(yml)

    fake_result = MagicMock(
        rvi=tmp_path / "x.rvi",
        rvc=tmp_path / "x.rvc",
        rvp=tmp_path / "x.rvp",
        rvh=tmp_path / "x.rvh",
        model_rvt=tmp_path / "x.rvt",
        channel_rvp=tmp_path / "channel_properties.rvp",
        wsc_rvt=tmp_path / "WSC.rvt",
        wsc_outlet_txt=tmp_path / "outlet.txt",
        rvh_template=None,
        rvp_template=None,
        channel_rvp_template=None,
        hru_areas_csv=None,
        tp_tc_csv=None,
        aspect_ratios_csv=None,
    )
    fake_run = MagicMock(return_value=fake_result)
    monkeypatch.setattr("pwa_raven.run_step2.run_step2", fake_run)

    rc = step2_main(["--config", str(yml)])
    assert rc == 0

    fake_run.assert_called_once()
    called_cfg = fake_run.call_args[0][0]
    assert called_cfg.watershed_name == "testwater"

    out = capsys.readouterr().out
    assert "x.rvi" in out
    assert "WSC.rvt" in out


def test_step2_main_prints_optional_outputs_when_present(
    monkeypatch, tmp_path: Path, capsys,
):
    """When run_step2 returns templates + aspect_ratios paths, the
    summary should list them. Uses a populated MagicMock to verify the
    optional-output branch."""
    from pwa_raven.step2 import Step2Config

    cfg = Step2Config(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        subbasins_shapefile=tmp_path / "s.shp",
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
    )
    yml = tmp_path / "step2.yml"
    cfg.to_yaml(yml)

    fake_result = MagicMock(
        rvi=tmp_path / "x.rvi",
        rvc=tmp_path / "x.rvc",
        rvp=tmp_path / "x.rvp",
        rvh=tmp_path / "x.rvh",
        model_rvt=tmp_path / "x.rvt",
        channel_rvp=tmp_path / "channel_properties.rvp",
        wsc_rvt=tmp_path / "WSC.rvt",
        wsc_outlet_txt=tmp_path / "outlet.txt",
        rvh_template=tmp_path / "x.rvh.tpl",
        rvp_template=tmp_path / "x.rvp.tpl",
        channel_rvp_template=tmp_path / "channel_properties.rvp.tpl",
        hru_areas_csv=tmp_path / "x_HRU_areas.csv",
        tp_tc_csv=tmp_path / "x_tp_tc.csv",
        aspect_ratios_csv=tmp_path / "aspect_ratios.csv",
    )
    fake_run = MagicMock(return_value=fake_result)
    monkeypatch.setattr("pwa_raven.run_step2.run_step2", fake_run)

    step2_main(["--config", str(yml)])
    out = capsys.readouterr().out
    assert "x.rvh.tpl" in out
    assert "aspect_ratios.csv" in out
    assert "HRU areas CSV" in out
