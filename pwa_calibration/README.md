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


## Running tests

This project uses `pytest`. From the repo root with the conda env activated:

```bash
python -m pytest -q
```

Useful flags during development:

- `-q` — quiet output (one dot per test, summary at the end)
- `-k <pattern>` — run only tests whose name matches the pattern
- `-x` — stop on the first failure (fast feedback while iterating)
- `--tb=short` — concise tracebacks
- `-p no:cacheprovider` — skip the `.pytest_cache/` write (useful in read-only checkouts)

Tests live in `tests/unit/` and (where applicable) `tests/regression/`. All tests should pass before opening a pull request.

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
