"""Fixtures for pwa_calibration integration tests — real Raven + SPOTPY.

Local-only: GitHub CI runs ``pytest tests/unit`` and never enters this
directory. The calibration loop, objectives, and staging are unit-tested with
mocks; nothing proves the SPOTPY ⇄ Raven loop actually turns over against a
real, populated calibration directory. This is also the test that would catch
the cross-platform path bug (backslash paths) that only surfaces on a real
non-Windows run.

Inputs discovered from the environment:

* ``PWA_CALIBRATION_CONFIG`` — path to a filled-in ``calibration.yml`` whose
  ``calib_dir`` is already populated (Raven binary, .rv* files, GridWeights,
  depression-depths shapefile, forcing CSVs). Generate the config with
  ``pwa-init-calibration``; stage the directory with the runner's
  ``--stage-from`` once, then point this at it.
* ``PWA_RAVEN_BINARY`` — optional explicit Raven path; otherwise resolved from
  ``calib_dir`` / PATH by the calibration runner itself.

Both fixtures skip cleanly when their inputs are absent.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def calibration_config():
    """A real ``CalibrationConfig`` from ``$PWA_CALIBRATION_CONFIG``, or skip.

    Also skips if the config requests MPI mode — these integration tests run a
    short *serial* sampler, since launching under ``mpirun`` is the developer's
    job, not the test runner's.
    """
    from pwa_calibration.setup import CalibrationConfig

    config_path = os.environ.get("PWA_CALIBRATION_CONFIG")
    if not config_path:
        pytest.skip(
            "Set PWA_CALIBRATION_CONFIG to a filled-in calibration.yml with a "
            "populated calib_dir (see `pwa-init-calibration`) to run."
        )
    path = Path(config_path)
    if not path.is_file():
        pytest.fail(f"PWA_CALIBRATION_CONFIG={config_path!r} is not a file")
    config = CalibrationConfig.from_yaml(path)
    if getattr(config, "is_mpi", False):
        pytest.skip(
            "Config requests MPI mode; the integration test runs a serial "
            "sampler. Set mpi_cores to 0/1 (or use a serial config) to run it."
        )
    return config


@pytest.fixture(scope="session")
def raven_on_path() -> None:
    """Skip unless a Raven binary is resolvable (PWA_RAVEN_BINARY or PATH).

    The runner resolves the binary from calib_dir/PATH itself; this is just an
    early, clear skip so the test doesn't fail deep inside SPOTPY when Raven is
    simply not installed.
    """
    if os.environ.get("PWA_RAVEN_BINARY"):
        return
    if shutil.which("Raven") or shutil.which("Raven.exe"):
        return
    pytest.skip(
        "Raven binary not found. Install Raven, put it on PATH "
        "(or in calib_dir), or set PWA_RAVEN_BINARY."
    )
