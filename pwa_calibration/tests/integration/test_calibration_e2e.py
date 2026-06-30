"""End-to-end: run a short, real SPOTPY ⇄ Raven calibration loop.

Why this exists
---------------
``tests/unit/`` covers the objectives, dbname building, ROPE patching, and
staging with mocks — but a real calibration has never been exercised by the
suite. A single short serial run proves the whole harness turns over: SPOTPY
builds the parameter space, writes .rv* updates, invokes Raven, reads the
hydrograph back, scores it, and persists a results database. It's also the only
test that catches the cross-platform path handling on a real non-Windows run.

Kept deliberately tiny (``repetitions=1``) — this is a smoke test of the loop,
not a calibration. Run with::

    PWA_CALIBRATION_CONFIG=/path/to/calibration.yml pytest tests/integration

Marked ``integration`` + ``slow``; skips without the config and Raven.
"""

from __future__ import annotations

import pytest

from pwa_calibration.runner import run_calibration


@pytest.mark.integration
@pytest.mark.slow
def test_short_serial_calibration_runs(calibration_config, raven_on_path):
    """One serial SPOTPY iteration completes and returns its dbname.

    ``run_calibration`` validates inputs up front and raises on a missing
    Raven binary / non-zero Raven exit / Raven error log, so simply returning a
    dbname already means the full loop ran cleanly. We assert the return shape
    for clarity.
    """
    dbname = run_calibration(
        config=calibration_config,
        db_suffix="itest",
        repetitions=1,
        save_sim=False,
    )
    assert isinstance(dbname, str) and dbname
    assert dbname.endswith("itest")
