"""Unit tests for pwa_calibration.prepare.

Build a fake watershed Data tree under tmp_path and verify staging
copies the right files into the right places, including the .rvt
``_adj`` injection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pwa_calibration.prepare import (
    StagingPaths,
    StagingReport,
    _inject_adj_into_rvt,
    create_calibration_folders,
    prepare_calibration_directory,
    stage_depression_depths,
    stage_grid_weights,
    stage_other_inputs,
    stage_raven_binary,
    stage_raven_configs,
    stage_template_files,
)


# ---------------------------------------------------------------------------
# Fake watershed builder
# ---------------------------------------------------------------------------


WATERSHED = "grassmere_test"
NETCDF_CATEGORY = "Runoff"


def _build_source_tree(data_root: Path) -> None:
    """Build a watershed source tree matching the refactored pipeline's
    output layout:

      <watershed>/HydroConditioning/Processed/  — Step 0 depression depths
      <watershed>/Raven/Processed/              — Step 2 .rv* files (flat)
      <watershed>/Raven/Processed/input/        — Step 2 HRU/tp_tc/WSC/aspect
      <watershed>/Raven/Processed/templates/    — Step 2 .tpl templates
      <watershed>/<category>/Processed/         — Step 1 GridWeights + .nc
    """
    ws = data_root / WATERSHED

    # Step 2 — Raven/Processed: .rv* files flat; input/ and templates/ nested.
    raven_proc = ws / "Raven" / "Processed"
    raven_proc.mkdir(parents=True)
    (raven_proc / "Raven.exe").write_bytes(b"FAKE_BINARY")
    (raven_proc / f"{WATERSHED}.rvi").write_text(":SimulationStart")
    (raven_proc / f"{WATERSHED}.rvh").write_text(":SubBasins")
    (raven_proc / f"{WATERSHED}.rvp").write_text(":Soils")
    (raven_proc / f"{WATERSHED}.rvc").write_text(":InitialConditions")
    (raven_proc / f"{WATERSHED}.rvt").write_text(
        ":Gauge\n  :RedirectToFile rdrs_runoff.nc\n:EndGauge\n"
    )
    (raven_proc / "channel_properties.rvp").write_text(":Channels")

    raven_templates = raven_proc / "templates"
    raven_templates.mkdir()
    (raven_templates / "model.rvp.tpl").write_text(":Soils tpl")
    (raven_templates / "model.rvh.tpl").write_text(":SubBasins tpl")

    raven_input = raven_proc / "input"
    raven_input.mkdir()
    (raven_input / f"{WATERSHED}_HRU_areas.csv").write_text("HRU,AREA\n1,10\n")
    (raven_input / f"{WATERSHED}_tp_tc.csv").write_text("SubId,tp,tc\n101,1,2\n")
    (raven_input / f"{WATERSHED}_WSC_outlet.txt").write_text("875\n")
    (raven_input / "aspect_ratios.csv").write_text("SubId,Aspect_Ratio\n101,0.5\n")

    # Step 0 — HydroConditioning/Processed: depression-depths shapefile.
    hydrocon_proc = ws / "HydroConditioning" / "Processed"
    hydrocon_proc.mkdir(parents=True)
    for ext in (".cpg", ".dbf", ".prj", ".shp", ".shx"):
        (hydrocon_proc / f"CLRH_basins_depression_depths{ext}").write_bytes(b"x")
    (hydrocon_proc / "ignored.txt").write_text("nope")  # wrong suffix

    # Step 1 — <category>/Processed: GridWeights + forcing NetCDF.
    nc_proc = ws / NETCDF_CATEGORY / "Processed"
    nc_proc.mkdir(parents=True)
    (nc_proc / "GridWeights.txt").write_text(":GridWeights")
    (nc_proc / "rdrs_runoff.nc").write_bytes(b"FAKE_NETCDF")


@pytest.fixture
def paths(tmp_path: Path) -> StagingPaths:
    data_root = tmp_path / "Data"
    data_root.mkdir()
    _build_source_tree(data_root)
    return StagingPaths(
        watershed_name=WATERSHED,
        data_root=data_root,
        netcdf_category=NETCDF_CATEGORY,
    )


# ---------------------------------------------------------------------------
# Folder creation + path math
# ---------------------------------------------------------------------------


def test_paths_construction_uses_pathlib(tmp_path: Path):
    p = StagingPaths(
        watershed_name="w", data_root=str(tmp_path), netcdf_category="Runoff"
    )
    assert isinstance(p.data_root, Path)
    assert p.calibration_root == tmp_path / "Calibration" / "w"
    assert p.calibration_input_dir == tmp_path / "Calibration" / "w" / "input"
    assert p.calibration_template_dir == tmp_path / "Calibration" / "w" / "templates"


def test_source_paths_match_refactored_pipeline_layout(paths: StagingPaths):
    """The staging source paths must point at where the refactored
    Steps 0/1/2 actually write — not the legacy notebook layout."""
    ws = paths.data_root / WATERSHED
    assert paths.raven_processed_dir == ws / "Raven" / "Processed"
    assert paths.raven_input_dir == ws / "Raven" / "Processed" / "input"
    assert paths.raven_templates_dir == ws / "Raven" / "Processed" / "templates"
    # Step 0 writes depression depths under HydroConditioning/, not the
    # legacy DepressionDepths/ folder.
    assert paths.hydrocon_processed_dir == ws / "HydroConditioning" / "Processed"
    # aspect_ratios.csv is a Step 2 output nested in Raven/Processed/input/.
    assert paths.aspect_ratios_source == paths.raven_input_dir / "aspect_ratios.csv"


def test_create_calibration_folders_idempotent(paths: StagingPaths):
    create_calibration_folders(paths)
    create_calibration_folders(paths)  # second call must not raise
    assert paths.calibration_root.is_dir()
    assert paths.calibration_input_dir.is_dir()
    assert paths.calibration_output_dir.is_dir()
    assert paths.calibration_template_dir.is_dir()


# ---------------------------------------------------------------------------
# Per-substep tests
# ---------------------------------------------------------------------------


def test_stage_raven_binary_copies_exe(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_raven_binary(paths, report)
    assert (paths.calibration_root / "Raven.exe").exists()
    assert paths.calibration_root / "Raven.exe" in report.copied


def test_stage_raven_binary_skips_if_present(paths: StagingPaths):
    create_calibration_folders(paths)
    (paths.calibration_root / "Raven.exe").write_bytes(b"existing")
    report = StagingReport()
    stage_raven_binary(paths, report)
    assert (paths.calibration_root / "Raven.exe").read_bytes() == b"existing"
    assert paths.calibration_root / "Raven.exe" in report.skipped_existing


def test_stage_raven_binary_handles_unix_named_source(tmp_path: Path):
    """macOS/Linux: source folder has ``Raven`` (no extension); destination
    should preserve that name rather than hardcoding ``Raven.exe``."""
    data_root = tmp_path / "Data"
    data_root.mkdir()
    raven_proc = data_root / WATERSHED / "Raven" / "Processed"
    raven_proc.mkdir(parents=True)
    (raven_proc / "Raven").write_bytes(b"FAKE_UNIX_BINARY")
    paths = StagingPaths(
        watershed_name=WATERSHED,
        data_root=data_root,
        netcdf_category=NETCDF_CATEGORY,
    )
    create_calibration_folders(paths)
    report = StagingReport()
    stage_raven_binary(paths, report)
    # Source preserved, NOT renamed to Raven.exe
    assert (paths.calibration_root / "Raven").is_file()
    assert not (paths.calibration_root / "Raven.exe").exists()
    assert (paths.calibration_root / "Raven").read_bytes() == b"FAKE_UNIX_BINARY"


def test_stage_raven_binary_prefers_unix_name_when_both_present(tmp_path: Path):
    """When both ``Raven`` and ``Raven.exe`` exist, prefer the Unix name
    (deterministic — matches the lookup order in raven_exe_source)."""
    data_root = tmp_path / "Data"
    data_root.mkdir()
    raven_proc = data_root / WATERSHED / "Raven" / "Processed"
    raven_proc.mkdir(parents=True)
    (raven_proc / "Raven").write_bytes(b"UNIX")
    (raven_proc / "Raven.exe").write_bytes(b"WINDOWS")
    paths = StagingPaths(
        watershed_name=WATERSHED,
        data_root=data_root,
        netcdf_category=NETCDF_CATEGORY,
    )
    create_calibration_folders(paths)
    report = StagingReport()
    stage_raven_binary(paths, report)
    assert (paths.calibration_root / "Raven").read_bytes() == b"UNIX"
    assert not (paths.calibration_root / "Raven.exe").exists()


def test_stage_depression_depths_copies_only_recognized_extensions(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_depression_depths(paths, report)
    for ext in (".cpg", ".dbf", ".prj", ".shp", ".shx"):
        assert (paths.calibration_input_dir / f"CLRH_basins_depression_depths{ext}").exists()
    # ignored.txt has the wrong suffix
    assert not (paths.calibration_input_dir / "ignored.txt").exists()


def test_stage_grid_weights_copies(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_grid_weights(paths, report)
    assert (paths.calibration_input_dir / "GridWeights.txt").exists()


def test_stage_raven_configs_injects_adj_in_rvt(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_raven_configs(paths, report)
    rvt_text = (paths.calibration_root / f"{WATERSHED}.rvt").read_text()
    assert "rdrs_runoff_adj.nc" in rvt_text
    assert "rdrs_runoff.nc" not in rvt_text  # original reference rewritten


def test_stage_raven_configs_other_extensions_unchanged(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_raven_configs(paths, report)
    assert (paths.calibration_root / f"{WATERSHED}.rvi").read_text() == ":SimulationStart"
    assert (paths.calibration_root / "channel_properties.rvp").read_text() == ":Channels"


def test_inject_adj_returns_false_when_no_nc_references(tmp_path: Path):
    """The notebook's regex isn't idempotent — re-running on already-adjusted
    text would produce ``_adj_adj.nc``. The higher-level idempotency comes
    from ``_copy_if_absent``: the .rvt is only re-injected when a fresh
    copy was made. This test pins the no-op case (no .nc anywhere)."""
    rvt = tmp_path / "x.rvt"
    rvt.write_text(":Gauge\n")
    assert _inject_adj_into_rvt(rvt) is False
    assert rvt.read_text() == ":Gauge\n"


def test_inject_adj_handles_multiple_references(tmp_path: Path):
    rvt = tmp_path / "x.rvt"
    rvt.write_text(":G1 a.nc\n:G2 b.nc\n")
    assert _inject_adj_into_rvt(rvt) is True
    text = rvt.read_text()
    assert "a_adj.nc" in text
    assert "b_adj.nc" in text


def test_stage_template_files_copies_tpl_and_renames_nc(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_template_files(paths, report)
    assert (paths.calibration_template_dir / "model.rvp.tpl").exists()
    assert (paths.calibration_template_dir / "model.rvh.tpl").exists()
    # NetCDF gets the _tpl suffix injected
    assert (paths.calibration_input_dir / "rdrs_runoff_tpl.nc").exists()
    # The original name is NOT created in input dir
    assert not (paths.calibration_input_dir / "rdrs_runoff.nc").exists()


def test_stage_other_inputs_copies_aspect_and_other_csvs(paths: StagingPaths):
    create_calibration_folders(paths)
    report = StagingReport()
    stage_other_inputs(paths, report)
    assert (paths.calibration_input_dir / "aspect_ratios.csv").exists()
    assert (paths.calibration_input_dir / f"{WATERSHED}_HRU_areas.csv").exists()
    assert (paths.calibration_input_dir / f"{WATERSHED}_tp_tc.csv").exists()
    assert (paths.calibration_input_dir / f"{WATERSHED}_WSC_outlet.txt").exists()


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def test_prepare_calibration_directory_runs_all_substeps(paths: StagingPaths):
    report = prepare_calibration_directory(paths)
    # Should copy: 1 binary + 5 dd files + 1 grid weights + 6 raven configs
    # + 2 templates + 1 nc + 1 aspect + 3 other = 20 files
    assert report.total_copied() == 20
    assert report.missing_sources == []


def test_prepare_calibration_directory_idempotent(paths: StagingPaths):
    first = prepare_calibration_directory(paths)
    second = prepare_calibration_directory(paths)
    assert first.total_copied() == 20
    assert second.total_copied() == 0  # everything already present
    assert len(second.skipped_existing) == 20


def test_prepare_calibration_directory_records_missing_sources(tmp_path: Path):
    """When the watershed source tree is partially absent, missing
    sources are logged into the report rather than raising."""
    data_root = tmp_path / "Data"
    data_root.mkdir()
    # Only build the Raven processed dir; everything else missing.
    (data_root / "skinny" / "Raven" / "Processed").mkdir(parents=True)
    paths = StagingPaths(
        watershed_name="skinny", data_root=data_root, netcdf_category="Runoff"
    )
    report = prepare_calibration_directory(paths)
    # Raven binary, GridWeights.txt, etc. are missing → flagged in report.
    # Raven binary name is platform-dependent (Raven on macOS/Linux,
    # Raven.exe on Windows) — assert on either to make the test portable.
    missing_names = {p.name for p in report.missing_sources}
    assert "Raven" in missing_names or "Raven.exe" in missing_names
    assert "GridWeights.txt" in missing_names
    assert "aspect_ratios.csv" in missing_names
