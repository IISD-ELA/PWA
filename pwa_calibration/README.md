# pwa-calibration

SPOTPY-driven calibration of Raven hydrological models, extracted from the PWA dev repo's `src/py/setup_spotpy.py`, `3_calibrate.py`, and `_notebooks/4_calibrate.ipynb` (sections 1.1–1.3).

## Layout

```
pwa_calibration/
  objectives.py    # KGE / NSE / NSE+PBIAS — pure functions, no Raven dependency
  setup.py         # SpotPySetup class (refactored spot_setup_rvn)
  prepare.py       # Stages files into the calibration directory
  runner.py        # Parallel calibration entrypoint (refactored 3_calibrate.py)
```

## Installation

```bash
pip install -e .                 # core
pip install -e .[mpi]            # plus mpi4py (requires system MPI)
pip install -e .[dev]            # plus pytest
```

`pwa-raven` must be installable; install it from `../pwa_raven` first.

## Running calibration

See `pwa_calibration.runner` for the programmatic entry point and the CLI.
The legacy `mpirun -c 14 python 3_calibrate.py results` invocation is preserved
behaviorally by `runner.run_calibration(config)`.
