# PWA pipeline — test drive via the CLI

Walks through Steps 0, 1, and 2 from the shell using the unified `pwa-*` console scripts. Assumes you've finished [installation.md](installation.md). Step 3 (calibration) requires a Raven binary you may not have on macOS — see Q-006.

Approximate time: 15–30 minutes once your input data is staged. The actual computation is a few minutes per step on a small watershed.

## The mental model

Each step has the same shape:

```bash
pwa-init-<step> <output>.yml          # interactive: build the config YAML
pwa-<step> --config <output>.yml      # run the step
```

The `pwa-init-*` script writes a YAML file you can re-edit with a text editor. The `pwa-<step>` script reads that YAML and executes.

## Step 0 — hydro-conditioning

Takes a LiDAR DEM, the CLRH subbasins shapefile, and an NHN streams shapefile and produces a hydro-conditioned DEM + per-subbasin depression-depth shapefile.

### Stage your input data

The Step 0 runner expects this directory layout:
```
<base_data_dir>/<watershed_name>/HydroConditioning/Raw/
  ├── <clrh_filename>.shp + .dbf + .shx + .prj + .cpg
  ├── <lidar_filename>.tif
  └── <nhn_filename>.shp + .dbf + .shx + .prj
```

For Grassmere specifically, the inputs you need (and where to source them):

| Input | Source |
|---|---|
| LiDAR DEM (`Netley_Grassmere_LiDAR_DEM.tif`) | https://mli.gov.mb.ca/dems/index_external_lidar.html |
| CLRH subbasins (`finalcat_info_v1-0.shp` + sidecars) | from the CLRH hydrofabric — should already be on internal IISD-ELA storage |
| NHN streams (`NHN_05OJ001_4_0_HD_SLWATER_1.shp` + sidecars) | https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/05/nhn_rhn_05oj001_shp_en.zip |

### Build the config

```bash
pwa-init-hydrocondition pwa_config.yml
```

Five prompts:

| Prompt | What to enter |
|---|---|
| Watershed name | `grassmere_test_run` (any letters / digits / underscores) |
| Output root directory | `<absolute path to where you want outputs>` — e.g. `/Users/me/data` |
| CLRH shapefile filename | `finalcat_info_v1-0` (no extension) |
| LiDAR DEM filename | `Netley_Grassmere_LiDAR_DEM_clip` (no extension) |
| NHN streams filename | `NHN_05OJ001_4_0_HD_SLWATER_1` (no extension) |
| Culvert shapefile (optional) | press Enter to skip |
| CRS | press Enter for `EPSG:3158` (NAD83 / MTM 14, southern Manitoba) |

> **Gotcha — watershed name normalization**: the script silently lowercases your input and replaces spaces/hyphens with underscores. If you type `Grassmere-test-run`, it gets normalized to `grassmere_test_run` and the runner will look for files under that name. This used to silently fail; now there's a warning + the runner's error message lists sibling directories so the mismatch is obvious.

> **Gotcha — `output_dir` defaults to `./Data`**: relative to your shell's current directory at run time. For a test run, type the absolute path you want instead of accepting the default.

After the prompts, the script writes `pwa_config.yml` and prints a summary of any optional fields that fell back to defaults.

### Run

```bash
pwa-hydrocondition --config pwa_config.yml
```

Takes a few minutes for a typical watershed (most of the time is spent in WhiteboxTools depression analysis).

Outputs land at `<output_dir>/<watershed_name>/HydroConditioning/Processed/`:
- `CLRH_basins_depression_depths.shp` ← the per-subbasin depression-depth shapefile (used by Step 2)
- `merged_average_dem_filled_clip_resample_5m_FillBurn_Deps_Corr.tif` ← the hydro-conditioned DEM

## Step 1 — NetCDF processing

Subsets a raw PHyDAP NetCDF to the watershed's HYBAS basins, computes Raven GridWeights, and applies a 10-hour time offset so the time axis matches Raven's expectations.

### Stage your input data

Three inputs:
1. **Raw PHyDAP NetCDF** — gridded basin-aggregated forcing data. **Available on the [Federated Research Data Repository](https://www.frdr-dfdr.ca/repo/dataset/7ce4bd7a-4bcc-4f8c-8129-32a691f46c8e)** (full set is ~180 GB; download just the runoff variable — likely a few GB). If you already have a watershed-subset version on internal storage, you can also pass that — the subsetter is idempotent.
2. **PHyDAP grid polygons** (`prairie_hydrosheds_true_WGS84.shp` + sidecars) — should already be on internal IISD-ELA storage.
3. **Step 0 output** — the depression-depths shapefile produced above.

### Build the config

```bash
pwa-init-nc-processing nc_processing.yml
```

Six prompts (paths can be absolute or relative):

| Prompt | What to enter |
|---|---|
| Watershed name | `grassmere_test_run` (matches Step 0) |
| Output root directory | absolute path; outputs land at `<output_dir>/Runoff/Processed/` |
| Path to raw PHyDAP NetCDF | absolute path to your `.nc` file |
| Path to PHyDAP grid shapefile | absolute path to `prairie_hydrosheds_true_WGS84.shp` |
| Path to subbasins shapefile (Step 0 output) | absolute path to `CLRH_basins_depression_depths.shp` |
| Variable to extract from NetCDF | the script auto-detects this — press Enter to accept |

> **Gotcha — silent defaults for optional fields**: `data_category=Runoff`, `nc_var_units=mm/h`, `time_offset_hours=10`, `lat_value=49.43` are not prompted. After the YAML is written, the script prints a summary of these so you can edit `nc_processing.yml` if any are wrong for your data.

### Run

```bash
pwa-nc-processing --config nc_processing.yml
```

Outputs land at `<output_dir>/Runoff/Processed/`:
- `<watershed>_runoff.nc` ← subsetted NetCDF
- `<watershed>_runoff_adj.nc` ← time-shifted (used by Step 2)
- `hybas_map.csv`
- `GridWeights.txt`

## Step 2 — Raven input generation

Generates the Raven model files (`.rvi`, `.rvp`, `.rvh`, `.rvc`, `.rvt`) plus calibration templates (`.rvh.tpl`, `.rvp.tpl`, `channel_properties.rvp.tpl`) and the WSC observed-flow `.rvt`.

### Stage your input data

Two new inputs (besides Step 0 + Step 1 outputs):
1. **WSC metadata CSV** — streamgauge metadata for your outlet gauge.
2. **WSC daily-discharge CSV** — observed daily streamflow at the gauge.

For Grassmere the relevant gauge is **WSC 05OJ017**. CSVs from the Water Survey Canada Hydat extract.

### Build the config

```bash
pwa-init-raven-inputs raven_inputs.yml
```

Six prompts:

| Prompt | What to enter |
|---|---|
| Watershed name | `grassmere_test_run` |
| Output root directory | absolute path; outputs land at `<output_dir>/Raven/Processed/` |
| Subbasins shapefile | absolute path to Step 0's `CLRH_basins_depression_depths.shp` |
| PHyDAP NetCDF (Step 1 output) | absolute path to `<watershed>_runoff_adj.nc` |
| WSC metadata CSV | absolute path |
| WSC daily-discharge CSV | absolute path |

> **Gotcha — silent defaults**: `curve_number=63.0` (Manning Canal value — adjust per watershed), `user_start=1990-01-01`, `user_end=2019-12-30`, `forcing_var_name=runoff`. Edit `raven_inputs.yml` if any are wrong.

### Run

```bash
pwa-raven-inputs --config raven_inputs.yml
```

Outputs at `<output_dir>/Raven/Processed/`:
- `<watershed>.rvi` / `.rvp` / `.rvh` / `.rvc` / `.rvt` ← Raven model files
- `WSC<gauge>.rvt` ← observed flow
- `templates/` ← calibration templates
- `input/` ← `HRU_areas.csv`, `tp_tc.csv`, `aspect_ratios.csv`, `WSC_outlet.txt`

## Step 3 — calibration (skipped for now)

`pwa-calibrate` requires the Raven binary on PATH. macOS doesn't have a pre-built NetCDF-enabled binary; we'd need to compile from source. See **Q-006** in `client-questions.md`. Skip for this test drive.

## What to send back

If anything fails, send:
1. The full traceback / error output
2. The `<step>.yml` config file the init script produced
3. Output of `pip list | grep pwa` so we know which versions you have

If everything runs cleanly, send a one-liner confirming so we can move on to addressing your feedback on the open questions.
