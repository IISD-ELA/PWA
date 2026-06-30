# pwa-calibration integration tests

Runs a short, real **SPOTPY ⇄ Raven** calibration loop to prove the harness
turns over end-to-end (and to catch cross-platform path bugs that only surface
on a real non-Windows run). **Local-only** — GitHub CI runs `pytest tests/unit`
and never enters this directory.

Skips cleanly when its inputs are absent.

## Inputs (environment)

| Variable | Purpose |
|---|---|
| `PWA_CALIBRATION_CONFIG` | Path to a filled-in `calibration.yml` whose `calib_dir` is already populated (Raven binary, `.rv*`, GridWeights, depression-depths shapefile, forcing CSVs) |
| `PWA_RAVEN_BINARY` | Optional explicit Raven path (else resolved from `calib_dir`/PATH) |

To populate `calib_dir`, run the calibration runner once with `--stage-from`,
then point this config at the staged directory. Use a **serial** config
(`mpi_cores` 0/1) — the test runs one iteration without `mpirun`; an MPI config
is skipped.

## Run

```bash
# From the PWA repo root:
make integration-calibration

# Or directly:
cd pwa_calibration
PWA_CALIBRATION_CONFIG=/path/to/calibration.yml \
  pytest tests/integration -v
```

## What it proves

`integration` + `slow`: one serial SPOTPY iteration builds the parameter space,
writes `.rv*` updates, invokes Raven, reads the hydrograph back, scores it, and
returns a results dbname — i.e. the whole loop runs cleanly.
