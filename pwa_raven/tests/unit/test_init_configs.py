"""Tests for the two pwa_raven init-config CLIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from pwa_raven.init_nc_processing_config import (
    _build_arg_parser as _nc_processing_parser,
)
from pwa_raven.init_nc_processing_config import main as nc_processing_main
from pwa_raven.init_raven_inputs_config import (
    _build_arg_parser as _raven_inputs_parser,
)
from pwa_raven.init_raven_inputs_config import main as raven_inputs_main
from pwa_raven.nc_processing import NcProcessingConfig
from pwa_raven.raven_inputs import RavenInputsConfig


def _stub_inputs(monkeypatch, answers: list[str]) -> None:
    """Replace input() with a queue of canned answers."""
    iterator = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(iterator))


# ---------------------------------------------------------------------------
# init_nc_processing_config CLI
# ---------------------------------------------------------------------------


def test_nc_processing_parser_requires_output_path():
    with pytest.raises(SystemExit):
        _nc_processing_parser().parse_args([])


def test_nc_processing_main_writes_yaml_and_round_trips(monkeypatch, tmp_path: Path, capsys):
    out = tmp_path / "nc_processing.yml"
    _stub_inputs(monkeypatch, [
        "grassmere",                                         # watershed_name
        str(tmp_path / "Data"),                              # output_dir
        str(tmp_path / "raw" / "phydap.nc"),                 # phydap_nc
        str(tmp_path / "raw" / "phydap.shp"),                # phydap_shapefile
        str(tmp_path / "subbasins" / "deps.shp"),            # subbasins_shapefile
    ])

    rc = nc_processing_main([str(out)])
    assert rc == 0
    assert f"Wrote {out}" in capsys.readouterr().out

    cfg = NcProcessingConfig.from_yaml(out)
    assert cfg.watershed_name == "grassmere"
    assert cfg.output_dir == tmp_path / "Data"
    assert cfg.data_category == "Runoff"  # default
    assert cfg.time_offset_hours == 10    # default


def test_nc_processing_main_uses_default_output_dir_on_blank(monkeypatch, tmp_path: Path):
    out = tmp_path / "nc_processing.yml"
    _stub_inputs(monkeypatch, [
        "manning",
        "",                                # output_dir → default ./Data
        str(tmp_path / "p.nc"),
        str(tmp_path / "p.shp"),
        str(tmp_path / "s.shp"),
    ])
    rc = nc_processing_main([str(out)])
    assert rc == 0
    cfg = NcProcessingConfig.from_yaml(out)
    assert cfg.output_dir == Path("./Data")


def test_nc_processing_main_refuses_overwrite_without_force(monkeypatch, tmp_path: Path, capsys):
    out = tmp_path / "existing.yml"
    out.write_text("watershed_name: keep\noutput_dir: ./\nphydap_nc: ./p.nc\n"
                   "phydap_shapefile: ./p.shp\nsubbasins_shapefile: ./s.shp\n")
    monkeypatch.setattr(
        "builtins.input",
        lambda *_a, **_kw: pytest.fail("input() called despite refuse-overwrite"),
    )
    rc = nc_processing_main([str(out)])
    assert rc == 1
    assert "Refusing to overwrite" in capsys.readouterr().err


def test_nc_processing_main_overwrites_with_force(monkeypatch, tmp_path: Path):
    out = tmp_path / "existing.yml"
    out.write_text("watershed_name: stale\n")
    _stub_inputs(monkeypatch, [
        "fresh", str(tmp_path), str(tmp_path / "p.nc"),
        str(tmp_path / "p.shp"), str(tmp_path / "s.shp"),
    ])
    rc = nc_processing_main([str(out), "--force"])
    assert rc == 0
    assert "watershed_name: fresh" in out.read_text()


# ---------------------------------------------------------------------------
# init_raven_inputs_config CLI
# ---------------------------------------------------------------------------


def test_raven_inputs_parser_requires_output_path():
    with pytest.raises(SystemExit):
        _raven_inputs_parser().parse_args([])


def test_raven_inputs_main_writes_yaml_and_round_trips(monkeypatch, tmp_path: Path, capsys):
    out = tmp_path / "raven_inputs.yml"
    _stub_inputs(monkeypatch, [
        "grassmere",                                         # watershed_name
        str(tmp_path / "Data"),                              # output_dir
        str(tmp_path / "subbasins" / "deps.shp"),            # subbasins_shapefile
        str(tmp_path / "Runoff" / "adj.nc"),                 # phydap_nc
        str(tmp_path / "wsc" / "metadata_05NF002.csv"),      # wsc_metadata_csv
        str(tmp_path / "wsc" / "daily_05NF002.csv"),         # wsc_daily_csv
    ])

    rc = raven_inputs_main([str(out)])
    assert rc == 0
    assert f"Wrote {out}" in capsys.readouterr().out

    cfg = RavenInputsConfig.from_yaml(out)
    assert cfg.watershed_name == "grassmere"
    assert cfg.curve_number == 63.0   # default
    assert cfg.write_calibration_templates is True   # default
    assert cfg.write_aspect_ratios is True   # default


def test_raven_inputs_main_refuses_overwrite_without_force(monkeypatch, tmp_path: Path, capsys):
    out = tmp_path / "existing.yml"
    out.write_text("watershed_name: keep\n")
    monkeypatch.setattr(
        "builtins.input",
        lambda *_a, **_kw: pytest.fail("input() called despite refuse-overwrite"),
    )
    rc = raven_inputs_main([str(out)])
    assert rc == 1
    assert "Refusing to overwrite" in capsys.readouterr().err


def test_raven_inputs_main_overwrites_with_force(monkeypatch, tmp_path: Path):
    out = tmp_path / "existing.yml"
    out.write_text("watershed_name: stale\n")
    _stub_inputs(monkeypatch, [
        "fresh", str(tmp_path), str(tmp_path / "s.shp"),
        str(tmp_path / "n.nc"), str(tmp_path / "m.csv"), str(tmp_path / "d.csv"),
    ])
    rc = raven_inputs_main([str(out), "--force"])
    assert rc == 0
    assert "watershed_name: fresh" in out.read_text()
