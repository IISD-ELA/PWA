"""Run the Raven hydrological model.

Replaces ``run_raven()`` from ``raven_py.py`` (lines 10-38).

Fixes:
  - BUG-007: ``Raven.exe`` hardcoded → platform-aware binary detection via
    ``shutil.which``. Works on Windows (Raven.exe), macOS/Linux (Raven).
  - ``subprocess.run`` now uses ``check=True``.
  - ``os.chdir`` already had try/finally in the original — preserved.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _find_raven_binary() -> str:
    """Locate the Raven binary on PATH.

    Tries ``Raven`` first (Linux/macOS convention), then ``Raven.exe``
    (Windows). Raises ``FileNotFoundError`` with install instructions
    if neither is found.
    """
    for name in ("Raven", "Raven.exe"):
        path = shutil.which(name)
        if path is not None:
            return path
    raise FileNotFoundError(
        "Raven binary not found on PATH. Download from "
        "http://raven.uwaterloo.ca/Downloads.html and place on your PATH."
    )


def run_raven(
    raven_model: str,
    data_dir: Path | str = "data/calibration",
    output_dir: str = "output",
) -> subprocess.CompletedProcess:
    """Run the Raven model.

    Parameters
    ----------
    raven_model
        Model name as it appears in the ``.rvi`` file (without extension).
    data_dir
        Directory containing the Raven input files.
    output_dir
        Name of the output subdirectory (relative to *data_dir*).

    Returns
    -------
    subprocess.CompletedProcess

    Raises
    ------
    FileNotFoundError
        If the Raven binary is not on PATH.
    subprocess.CalledProcessError
        If Raven exits with a non-zero return code.
    """
    data_dir = Path(data_dir)
    raven_binary = _find_raven_binary()

    prev_cwd = os.getcwd()
    try:
        os.chdir(data_dir)
        cmd = [raven_binary, raven_model, "-o", f"./{output_dir}/"]
        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Raven stdout:\n%s", result.stdout)
        if result.stderr:
            logger.warning("Raven stderr:\n%s", result.stderr)
        return result
    finally:
        os.chdir(prev_cwd)
