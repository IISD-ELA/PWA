# pwa-raven

Raven hydrological model setup and input generation for PWA (pipeline Steps 1–2), extracted from the PWA dev repo's `_notebooks/1_nc_processing.ipynb`, `_notebooks/2_raven_input_gen.ipynb`, and `src/py/phydap.py` / `raven_py.py`. Also generates the RavenView visualization GeoJSON.

## Layout

```
pwa_raven/
  nc_processing.py       # Step 1: PHyDAP/NetCDF subsetting + time offset + grid weights
  raven_inputs.py        # Step 2: orchestrates .rv* + WSC RVT + calibration templates
  run_*.py               # CLI entry points (nc_processing, raven_inputs, ravenview)
  init_*_config.py        # Interactive config builders (one per step)
  raven/
    rv_writers.py        # .rvi/.rvp/.rvh/.rvc/.rvt template writers
    runner.py            # run_raven() — invokes the Raven binary, checks errors
    ravenview.py         # subbasin/river shapefiles -> RavenView GeoJSON + validation
    wsc_rvt.py           # WSC observed-streamflow RVT generation
    basin_prep.py        # subbasin/HRU preparation
    calibration_templates.py
  grid/
    weights.py           # GridWeights.txt generation
```

## Installation

```bash
pip install -e .                 # core
pip install -e .[dev]            # plus pytest, pytest-cov, xarray (test deps)
```

The Raven binary is **not** a pip dependency — install it from
<http://raven.uwaterloo.ca/Downloads.html> and place it on `PATH` as `Raven`
(Linux/macOS) or `Raven.exe` (Windows). `pwa-raven` is itself a dependency of
`pwa-calibration`.

## Running

Programmatic entry points (notebook / script use):

```python
from pwa_raven.nc_processing import NcProcessingConfig, run_nc_processing
from pwa_raven.raven_inputs import RavenInputsConfig, run_raven_inputs
from pwa_raven.raven.ravenview import export_for_ravenview
```

Equivalent CLIs (thin wrappers around the above):

```bash
python -m pwa_raven.run_nc_processing --config nc_processing.yml
python -m pwa_raven.run_raven_inputs  --config raven_inputs.yml
python -m pwa_raven.run_ravenview --subbasins SUB.shp --rivers RIV.shp \
    --output-dir RavenView --watershed-name my_watershed
```

Generate a starter config for any step with the matching `pwa_raven.init_*_config` module.

## Running tests

This project uses `pytest`. From `pwa_raven/` with the conda env activated:

```bash
python -m pytest tests/unit -q          # fast unit suite (what CI runs)
python -m pytest tests/integration      # local-only e2e (see below)
```

From the repo root, the `Makefile` provides shortcuts: `make test-raven` (unit) and `make integration-raven` (e2e).

Test tiers, by marker:

- **unit** (default, `tests/unit/`) — fast, no external dependencies; runs in CI. Includes a real-data RavenView export test backed by the committed `tests/fixtures/05MH008/` watershed.
- **integration** — invokes the real Raven binary; **local-only**, skips unless inputs are present. See `tests/integration/README.md` for the env vars (`PWA_RAVEN_INPUTS_CONFIG`, `PWA_RAVEN_BINARY`) and how to trigger.
- **regression** — needs an external reference dataset (e.g. the Liard sample); skips when absent.
- **slow** — a real Raven run; skip with `-m "not slow"` during a fast dev loop.

Useful flags: `-q` (quiet), `-k <pattern>` (filter by name), `-x` (stop on first failure), `--tb=short` (concise tracebacks).

All unit tests should pass before opening a pull request.

## Contributing

Workflow for adding a feature or fixing a bug:

1. **Create a feature branch** off the default branch. Use `feat/<short-name>` for features and `fix/<short-name>` for bug fixes — never commit directly to the default branch.
2. **Write a failing test first** that describes the desired behavior. Run `python -m pytest -q` to confirm the new test fails. For bug fixes, the test should reproduce the bug.
3. **Write code to make the test pass.** Run the suite again and confirm green.
4. **Commit incrementally** with focused commit messages that explain *why* (the motivation, the problem, the trade-off) rather than just *what* (the diff is the *what*).
5. **Open a pull request** against the default branch. Tag the relevant reviewer. The PR description should include a short summary, a test plan, and links to any related issues.

Practical notes:

- New features should ship with corresponding tests. If a unit test is hard to write, that's often a signal the design needs refactoring.
- Avoid disabling, skipping, or commenting out tests to make builds pass — investigate the root cause and fix it properly.
- Keep commits small and atomic. If you find yourself making unrelated changes in the same commit, split them.
- Don't add features beyond what the issue/PR scope requires. YAGNI — build for the current need, refactor later when a second use case emerges.
