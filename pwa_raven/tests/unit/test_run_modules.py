"""Tests for the pwa_raven.run_nc_processing / run_raven_inputs CLI wrappers.

These wrappers are intentionally thin (parse args → load config → call
the existing run_step* function → print summary). The NcProcessingConfig /
RavenInputsConfig / run_step* unit tests cover the heavy lifting; here we
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

from pwa_raven.run_nc_processing import _build_arg_parser as _nc_processing_parser
from pwa_raven.run_nc_processing import main as nc_processing_main
from pwa_raven.run_raven_inputs import _build_arg_parser as _raven_inputs_parser
from pwa_raven.run_raven_inputs import main as raven_inputs_main


# ---------------------------------------------------------------------------
# Re-export contract — notebook callers should be able to import either
# the runner module's `run_step*` or the underlying step* module's. Both
# must point at the same callable.
# ---------------------------------------------------------------------------


def test_nc_runner_reexports_callable():
    from pwa_raven import run_nc_processing as runner_mod
    from pwa_raven.nc_processing import run_nc_processing as nc_mod_callable

    assert runner_mod.run_nc_processing is nc_mod_callable


def test_raven_inputs_runner_reexports_callable():
    from pwa_raven import run_raven_inputs as runner_mod
    from pwa_raven.raven_inputs import run_raven_inputs as raven_inputs_mod_callable

    assert runner_mod.run_raven_inputs is raven_inputs_mod_callable


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------


def test_nc_processing_parser_default_config_path(tmp_path: Path):
    args = _nc_processing_parser().parse_args([])
    assert args.config == Path("nc_processing.yml")
    assert args.log_level == "INFO"


def test_raven_inputs_parser_default_config_path(tmp_path: Path):
    args = _raven_inputs_parser().parse_args([])
    assert args.config == Path("raven_inputs.yml")
    assert args.log_level == "INFO"


def test_nc_processing_parser_accepts_log_level(tmp_path: Path):
    args = _nc_processing_parser().parse_args(["--log-level", "DEBUG"])
    assert args.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Missing-config behaviour
# ---------------------------------------------------------------------------


def test_nc_processing_main_returns_1_when_config_missing(tmp_path: Path, capsys):
    rc = nc_processing_main(["--config", str(tmp_path / "doesnt_exist.yml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Config file not found" in err
    assert "init_nc_processing_config" in err   # points the user at the generator


def test_raven_inputs_main_returns_1_when_config_missing(tmp_path: Path, capsys):
    rc = raven_inputs_main(["--config", str(tmp_path / "doesnt_exist.yml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Config file not found" in err
    assert "init_raven_inputs_config" in err


# ---------------------------------------------------------------------------
# Happy-path CLI invocation (with run_step* mocked — we already have e2e
# tests for the real runners in test_nc_processing.py / test_raven_inputs.py).
# ---------------------------------------------------------------------------


def test_nc_processing_main_loads_config_and_calls_run_nc_processing(monkeypatch, tmp_path: Path, capsys):
    from pwa_raven.nc_processing import NcProcessingConfig

    # Build a real config + write it to YAML.
    cfg = NcProcessingConfig(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        phydap_nc=tmp_path / "phydap.nc",
        phydap_shapefile=tmp_path / "phydap.shp",
        subbasins_shapefile=tmp_path / "subbasins.shp",
    )
    yml = tmp_path / "nc_processing.yml"
    cfg.to_yaml(yml)

    fake_result = MagicMock(
        subset_nc=tmp_path / "subset.nc",
        adjusted_nc=tmp_path / "adj.nc",
        hybas_map=tmp_path / "hybas_map.csv",
        grid_weights=tmp_path / "GridWeights.txt",
    )
    fake_run = MagicMock(return_value=fake_result)
    monkeypatch.setattr("pwa_raven.run_nc_processing.run_nc_processing", fake_run)

    rc = nc_processing_main(["--config", str(yml)])
    assert rc == 0

    fake_run.assert_called_once()
    called_cfg = fake_run.call_args[0][0]
    assert called_cfg.watershed_name == "testwater"

    out = capsys.readouterr().out
    assert "subset.nc" in out
    assert "GridWeights.txt" in out


def test_raven_inputs_main_loads_config_and_calls_run_raven_inputs(monkeypatch, tmp_path: Path, capsys):
    from pwa_raven.raven_inputs import RavenInputsConfig

    cfg = RavenInputsConfig(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        subbasins_shapefile=tmp_path / "s.shp",
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
    )
    yml = tmp_path / "raven_inputs.yml"
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
    monkeypatch.setattr("pwa_raven.run_raven_inputs.run_raven_inputs", fake_run)

    rc = raven_inputs_main(["--config", str(yml)])
    assert rc == 0

    fake_run.assert_called_once()
    called_cfg = fake_run.call_args[0][0]
    assert called_cfg.watershed_name == "testwater"

    out = capsys.readouterr().out
    assert "x.rvi" in out
    assert "WSC.rvt" in out


def test_raven_inputs_main_prints_optional_outputs_when_present(
    monkeypatch, tmp_path: Path, capsys,
):
    """When run_raven_inputs returns templates + aspect_ratios paths, the
    summary should list them. Uses a populated MagicMock to verify the
    optional-output branch."""
    from pwa_raven.raven_inputs import RavenInputsConfig

    cfg = RavenInputsConfig(
        watershed_name="testwater",
        output_dir=tmp_path / "out",
        subbasins_shapefile=tmp_path / "s.shp",
        phydap_nc=tmp_path / "n.nc",
        wsc_metadata_csv=tmp_path / "m.csv",
        wsc_daily_csv=tmp_path / "d.csv",
    )
    yml = tmp_path / "raven_inputs.yml"
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
    monkeypatch.setattr("pwa_raven.run_raven_inputs.run_raven_inputs", fake_run)

    raven_inputs_main(["--config", str(yml)])
    out = capsys.readouterr().out
    assert "x.rvh.tpl" in out
    assert "aspect_ratios.csv" in out
    assert "HRU areas CSV" in out


# ---------------------------------------------------------------------------
# run_ravenview CLI
# ---------------------------------------------------------------------------

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from pwa_raven.run_ravenview import _build_arg_parser as _ravenview_parser
from pwa_raven.run_ravenview import main as ravenview_main


def _write_clrh_subbasins(path: Path) -> Path:
    gpd.GeoDataFrame(
        {
            "SubId": [1, 2],
            "DowSubId": [2, -1],
            "BasArea": [1_000_000.0, 2_000_000.0],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
                Polygon([(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)]),
            ],
        },
        crs="EPSG:4326",
    ).to_file(path)
    return path


def _write_rivers(path: Path) -> Path:
    gpd.GeoDataFrame(
        {"UIDENT": [1], "geometry": [LineString([(0, 0), (1, 1)])]},
        crs="EPSG:4326",
    ).to_file(path)
    return path


def test_ravenview_parser_requires_all_inputs():
    with pytest.raises(SystemExit):
        _ravenview_parser().parse_args([])  # missing required flags


def test_ravenview_main_writes_and_validates(tmp_path: Path, capsys):
    subs = _write_clrh_subbasins(tmp_path / "subbasins.shp")
    rivs = _write_rivers(tmp_path / "rivers.shp")
    out_dir = tmp_path / "RavenView"

    rc = ravenview_main([
        "--subbasins", str(subs),
        "--rivers", str(rivs),
        "--output-dir", str(out_dir),
        "--watershed-name", "testws",
    ])
    assert rc == 0
    assert (out_dir / "testws.json").is_file()
    assert (out_dir / "testwsRivers.json").is_file()
    out = capsys.readouterr().out
    assert "Validation: OK" in out


def test_ravenview_main_errors_on_missing_shapefile(tmp_path: Path, capsys):
    rivs = _write_rivers(tmp_path / "rivers.shp")
    rc = ravenview_main([
        "--subbasins", str(tmp_path / "absent.shp"),
        "--rivers", str(rivs),
        "--output-dir", str(tmp_path / "out"),
        "--watershed-name", "testws",
    ])
    assert rc == 1
    assert "not found" in capsys.readouterr().err
