"""Run the Raven hydrological model.

Replaces ``run_raven()`` from ``raven_py.py`` (lines 10-38).

Behavioural improvements over the original:
  - Three-way binary resolution (explicit path → data-directory search →
    system PATH) so users in environments where adding to PATH requires
    IT approval can drop the binary next to their calibration files and
    have it just work.
  - ``subprocess.run`` uses ``check=True`` so a non-zero exit surfaces
    immediately rather than letting downstream steps process a missing
    output file.
  - ``Raven_errors.txt`` is inspected after every run: Raven can exit 0
    while reporting an ERROR and writing only a header-only hydrograph,
    so a zero return code alone isn't proof of success.
  - ``os.chdir`` already had try/finally in the original — preserved.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


_BINARY_NAMES = ("Raven", "Raven.exe")

_RAVEN_ERRORS_FILENAME = "Raven_errors.txt"


class RavenExecutionError(RuntimeError):
    """Raised when Raven reports an error in ``Raven_errors.txt``.

    Raven can exit with code 0 while still writing an ``ERROR`` line to
    ``Raven_errors.txt`` and producing an empty (header-only)
    ``Hydrographs.csv``. Without this check that failure stays silent
    and surfaces much later as a confusing downstream error (e.g.
    "Simulation and observation arrays contain no overlapping non-null
    values" in the objective function), far from the real cause. This
    exception puts Raven's own error message in front of the user.
    """


def _raven_error_lines(output_dir: Path) -> list[str]:
    """Return the ``ERROR``-prefixed lines from ``Raven_errors.txt``.

    Returns an empty list if the file is absent or contains only
    advisories. Raven writes one line per message, prefixed with
    ``ERROR`` or ``ADVISORY``; we surface only the former.
    """
    errors_file = output_dir / _RAVEN_ERRORS_FILENAME
    if not errors_file.is_file():
        return []
    lines = errors_file.read_text(errors="replace").splitlines()
    return [ln.strip() for ln in lines if ln.lstrip().startswith("ERROR")]


def _find_raven_binary(
    *,
    explicit: Path | str | None = None,
    search_dirs: Iterable[Path | str] = (),
) -> str:
    """Locate the Raven binary, in three preference tiers.

    Resolution order:

      1. ``explicit`` — if given, must exist; raises FileNotFoundError
         with the exact path if not.
      2. ``search_dirs`` — for each directory in order, look for
         ``Raven`` then ``Raven.exe``. Intended for sites where the
         binary lives next to the calibration data because adding to
         PATH requires IT approval (Thomas's IISD constraint).
      3. ``shutil.which`` — system PATH, looking for ``Raven`` then
         ``Raven.exe``.

    Returns the absolute binary path as a string. Raises
    ``FileNotFoundError`` listing every checked location so the user
    knows what's been tried and where to drop the file.
    """
    if explicit is not None:
        explicit_path = Path(explicit)
        if explicit_path.is_file():
            resolved = str(explicit_path.resolve())
            logger.debug("Using explicit Raven binary: %s", resolved)
            return resolved
        raise FileNotFoundError(
            f"Raven binary not found at the explicit path: {explicit_path}\n"
            "Check the path or unset 'raven_binary' to fall back to "
            "the data-directory search + PATH."
        )

    search_dirs_list = [Path(d) for d in search_dirs]
    for d in search_dirs_list:
        for name in _BINARY_NAMES:
            candidate = d / name
            if candidate.is_file():
                resolved = str(candidate.resolve())
                logger.debug("Found Raven binary in %s: %s", d, resolved)
                return resolved

    for name in _BINARY_NAMES:
        path = shutil.which(name)
        if path is not None:
            logger.debug("Found Raven binary on PATH: %s", path)
            return path

    dir_list = (
        "\n".join(f"    {d}" for d in search_dirs_list)
        if search_dirs_list
        else "    (none provided)"
    )
    raise FileNotFoundError(
        "Raven binary not found. Tried:\n"
        "  1. explicit raven_binary path: not set\n"
        f"  2. data directories ({', '.join(_BINARY_NAMES)} in each):\n"
        f"{dir_list}\n"
        f"  3. system PATH ({', '.join(_BINARY_NAMES)})\n\n"
        "To fix this, do ONE of:\n"
        "  - Drop Raven (or Raven.exe) into the calibration data folder "
        "(e.g. Data/Calibration/<watershed>/) — picked up automatically.\n"
        "  - Add the binary to your system PATH.\n"
        "  - Set 'raven_binary' in calibration.yml to an absolute path.\n"
        "Download Raven from http://raven.uwaterloo.ca/Downloads.html."
    )


def run_raven(
    raven_model: str,
    data_dir: Path | str = "data/calibration",
    output_dir: str = "output",
    raven_binary: Path | str | None = None,
) -> subprocess.CompletedProcess:
    """Run the Raven model.

    Parameters
    ----------
    raven_model
        Model name as it appears in the ``.rvi`` file (without extension).
    data_dir
        Directory containing the Raven input files. Also searched for
        the Raven binary itself when ``raven_binary`` is not given —
        callers don't need to wire two separate paths for the typical
        "binary lives next to the inputs" layout.
    output_dir
        Name of the output subdirectory (relative to *data_dir*).
    raven_binary
        Optional explicit path to the Raven executable. When omitted,
        the function falls back to searching ``data_dir`` for ``Raven``
        / ``Raven.exe`` first, then the system PATH. Lets users in
        PATH-restricted environments (e.g. enterprise security
        controls) keep the binary alongside their data and have it
        picked up automatically.

    Returns
    -------
    subprocess.CompletedProcess

    Raises
    ------
    FileNotFoundError
        If none of the three resolution tiers (explicit, data-dir
        search, PATH) yields the binary.
    subprocess.CalledProcessError
        If Raven exits with a non-zero return code.
    RavenExecutionError
        If Raven exits 0 but writes an ``ERROR`` line to
        ``Raven_errors.txt`` (a silent failure that would otherwise
        cascade into a confusing downstream error).
    """
    data_dir = Path(data_dir)
    resolved_binary = _find_raven_binary(
        explicit=raven_binary,
        search_dirs=[data_dir],
    )

    prev_cwd = os.getcwd()
    try:
        os.chdir(data_dir)
        cmd = [resolved_binary, raven_model, "-o", f"./{output_dir}/"]
        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Raven stdout:\n%s", result.stdout)
        if result.stderr:
            logger.warning("Raven stderr:\n%s", result.stderr)

        # Raven can exit 0 while reporting an ERROR (and writing only a
        # header-only hydrograph). check=True above misses that case;
        # inspect Raven's own error log and fail loudly with its message.
        error_lines = _raven_error_lines(Path(output_dir))
        if error_lines:
            errors_path = data_dir / output_dir / _RAVEN_ERRORS_FILENAME
            quoted = "\n  ".join(error_lines)
            msg = (
                f"Raven exited 0 but reported {len(error_lines)} error(s) in "
                f"{errors_path}:\n  {quoted}"
            )
            if any("forcing" in ln.lower() for ln in error_lines):
                msg += (
                    "\n\nA 'gridded forcing data not available' error means "
                    "the model simulation window runs past the forcing data. "
                    "This happens when calibration time-shifts the forcing "
                    "via runoff_offset and the shifted forcing ends before "
                    "the model does. Re-run Step 2 so the model end date "
                    "picks up forcing_margin_hours (default 30 days of "
                    "headroom) — see RavenInputsConfig."
                )
            raise RavenExecutionError(msg)

        return result
    finally:
        os.chdir(prev_cwd)
