# PWA pipeline — test drive from a notebook

Walks through Steps 0, 1, and 2 from Python / Jupyter using the umbrella `import pwa` API. Assumes you've finished [installation.md](installation.md). Step 3 (calibration) requires a Raven binary you may not have on macOS — see Q-006.

This file mirrors [testing-cli.md](testing-cli.md) — same inputs, same outputs, just driven from Python instead of the shell. Pick whichever style fits how you'll use this day-to-day.

## Setup cell

Paste this at the top of a fresh notebook to enable progress logging and verify the install:

```python
import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

import pwa
print("pwa version:", pwa.__version__)
print("public symbols:", sorted(pwa.__all__))
```

The `__all__` list shows every callable and config class available under the `pwa.*` namespace. If this cell errors with `ModuleNotFoundError`, your conda env wasn't activated or the install didn't complete — see [installation.md](installation.md).

## The mental model

Every step has the same shape:

1. **Build a config** — either load a YAML you wrote with `pwa-init-<step>` from the shell, or construct one programmatically from a dict.
2. **Run** — call `pwa.run_<step>(config)`.
3. **Inspect results** — every `run_*` returns a dataclass with `Path` attributes pointing at the produced files.

Two ways to build a config:

```python
# Style A — load a YAML written by `pwa-init-<step>`. Most ergonomic for
# iteration: generate once with the CLI, then re-run from the notebook.
config = pwa.PwaConfig.from_yaml("pwa_config.yml")

# Style B — build from a dict. Useful for parameter sweeps, no filesystem
# round-trip.
config = pwa.PwaConfig.from_dict({
    "watershed_name": "grassmere_test_run",
    "base_data_dir": "/Users/me/data",
    "inputs": {
        "clrh_filename": "finalcat_info_v1-0",
        "lidar_filenames": ["Netley_Grassmere_LiDAR_DEM_clip"],
        "nhn_filename": "NHN_05OJ001_4_0_HD_SLWATER_1",
        "culvert_filename": None,
        "crs_string": "EPSG:3158",
    },
})
```

The two are equivalent; the runner doesn't care which path was used.

## Step 0 — hydro-conditioning

Takes a LiDAR DEM, the CLRH subbasins shapefile, and an NHN streams shapefile and produces a hydro-conditioned DEM + per-subbasin depression-depth shapefile.

### Inputs

The runner expects this directory layout on disk:
```
<base_data_dir>/<watershed_name>/HydroConditioning/Raw/
  ├── <clrh_filename>.shp + .dbf + .shx + .prj + .cpg
  ├── <lidar_filename>.tif
  └── <nhn_filename>.shp + .dbf + .shx + .prj
```

For Grassmere specifically, source the data from:
- LiDAR DEM: https://mli.gov.mb.ca/dems/index_external_lidar.html
- CLRH subbasins: from internal IISD-ELA storage
- NHN streams: https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/05/nhn_rhn_05oj001_shp_en.zip

### Run

```python
config0 = pwa.PwaConfig.from_dict({
    "watershed_name": "grassmere_test_run",
    "base_data_dir": "/Users/me/data",                # ← edit for your machine
    "inputs": {
        "clrh_filename": "finalcat_info_v1-0",
        "lidar_filenames": ["Netley_Grassmere_LiDAR_DEM_clip"],
        "nhn_filename": "NHN_05OJ001_4_0_HD_SLWATER_1",
        "culvert_filename": None,
        "crs_string": "EPSG:3158",
    },
})

result0 = pwa.run_step0(config0, generate_wetlands=False)

print("Depression depths shapefile:", result0.depression_depths)
print("Hydro-conditioned DEM:", result0.depression_raster)
```

> **Gotcha — watershed_name normalization**: when using the CLI's `pwa-init-hydrocondition`, watershed names get silently lowercased and have spaces/hyphens replaced with underscores. From a notebook, what you pass in `from_dict` is what gets used verbatim — so `Grassmere-test-run` works fine if your directory is named that way. Be consistent.

> **Gotcha — `base_data_dir` is resolved as-given**: relative paths are relative to the notebook's working directory at run time. Use absolute paths to remove ambiguity.

The runner logs progress to the standard `logging` module — with the setup cell at the top, you'll see step-by-step output in the notebook cell's stdout.

### Inspect outputs

```python
import geopandas as gpd
gdf = gpd.read_file(result0.depression_depths)
gdf.head()
gdf.plot(column="Deps_Depth", legend=True)
```

## Step 1 — NetCDF processing

Subsets a raw PHyDAP NetCDF to the watershed's HYBAS basins, computes Raven GridWeights, and applies a 10-hour time offset.

### Inputs

Three:
1. **Raw PHyDAP NetCDF** — from [FRDR](https://www.frdr-dfdr.ca/repo/dataset/7ce4bd7a-4bcc-4f8c-8129-32a691f46c8e). Full dataset is ~180 GB; download the runoff variable (a few GB). A pre-subsetted version on internal storage works too — the subsetter is idempotent.
2. **PHyDAP grid polygons** — `prairie_hydrosheds_true_WGS84.shp` + sidecars from internal storage.
3. **Step 0 output** — the depression-depths shapefile.

### Run

```python
config1 = pwa.NcProcessingConfig.from_dict({
    "watershed_name": "grassmere_test_run",
    "output_dir": "/Users/me/data",                   # ← edit
    "phydap_nc": "/Users/me/data/PHyDAP_RDRS21_runoff.nc",   # ← edit
    "phydap_shapefile": "/Users/me/data/prairie_hydrosheds_true_WGS84.shp",   # ← edit
    "subbasins_shapefile": str(result0.depression_depths),   # reuse Step 0 output
    "data_category": "Runoff",
    "nc_variable": "cropped_runoff",   # the variable name in your raw NetCDF
    "time_offset_hours": 10,
    "lat_value": 49.43,
})

result1 = pwa.run_nc_processing(config1)

print("Subset NetCDF:", result1.subset_nc)
print("Time-shifted NetCDF (Step 2 input):", result1.adjusted_nc)
print("GridWeights:", result1.grid_weights)
print("hybas_map:", result1.hybas_map)
```

> **Gotcha — `nc_variable` must match your input file's actual variable name**. The CLI's `pwa-init-nc-processing` opens the NetCDF and auto-detects this. From a notebook, you can do the same lookup yourself:
> ```python
> import xarray as xr
> with xr.open_dataset(config1.phydap_nc) as ds:
>     print(list(ds.data_vars))
> ```
> Then set `nc_variable` to whichever name is in there.

> **Gotcha — `lat_value=49.43`** is the prairie default. Adjust if working outside southern Manitoba.

## Step 2 — Raven input generation

Generates the Raven model files (`.rvi`, `.rvp`, `.rvh`, `.rvc`, `.rvt`) plus calibration templates and the WSC observed-flow `.rvt`.

### Inputs

Two new (besides Step 0 + Step 1 outputs):
1. **WSC metadata CSV** — streamgauge metadata.
2. **WSC daily-discharge CSV** — observed daily streamflow.

For Grassmere the relevant gauge is **WSC 05OJ017**.

### Run

```python
config2 = pwa.RavenInputsConfig.from_dict({
    "watershed_name": "grassmere_test_run",
    "output_dir": "/Users/me/data",                   # ← edit
    "subbasins_shapefile": str(result0.depression_depths),
    "phydap_nc": str(result1.adjusted_nc),
    "wsc_metadata_csv": "/Users/me/data/metadata_05OJ017.csv",   # ← edit
    "wsc_daily_csv": "/Users/me/data/daily_05OJ017.csv",         # ← edit
    "curve_number": 63.0,                  # ← Manning Canal value; adjust per watershed
    "user_start": "1990-01-01 00:00:00",
    "user_end": "2019-12-30 00:00:00",
    "avg_annual_runoff_mm": 75.0,
    "initial_soil_storage_mm": 15.0,
    "write_calibration_templates": True,
    "write_aspect_ratios": True,
    "forcing_var_name": "runoff",          # ← variable name in the *_adj.nc file (usually "runoff")
})

result2 = pwa.run_raven_inputs(config2)

print("Raven model files:")
print("  rvi:", result2.rvi)
print("  rvp:", result2.rvp)
print("  rvh:", result2.rvh)
print("  rvc:", result2.rvc)
print("  rvt:", result2.model_rvt)
```

> **Gotcha — `user_start` / `user_end` must overlap with both the NetCDF time range AND the WSC daily-discharge date range**. The runner takes the intersection. If they don't overlap at all, you'll get an error about an empty simulation window.

## Step 3 — calibration (skipped for now)

`pwa.run_calibration` calls the Raven binary thousands of times to evaluate parameter samples. macOS doesn't have a pre-built NetCDF-enabled Raven binary — we'd need to compile from source. See **Q-006** in `client-questions.md`. Skip for this test drive.

If you want to dry-run the *staging* phase (which doesn't need Raven yet), you can build the config and inspect what `--stage-from` would copy:

```python
config3 = pwa.CalibrationConfig.from_yaml("calibration.yml")
print(config3)   # inspect resolved paths and parameter group toggles
```

## What to send back

If anything fails, send:
1. The full traceback (or paste the cell output)
2. The contents of the dict passed to `<Config>.from_dict` (or the YAML you loaded)
3. Output of `pip list | grep pwa` (MacOS/linux) or `pip list | findstr pwa` (Windows) so we know which versions you have

If everything runs cleanly, send a one-liner confirming so we can move on to addressing your feedback on the open questions.
