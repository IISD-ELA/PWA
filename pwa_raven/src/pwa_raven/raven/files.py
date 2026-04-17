"""Raven input file operations — template reading, parameter substitution, writing.

Replaces ``RavenFile`` class from ``raven_py.py`` (lines 41-259).

Fixes:
  - BUG-002: ``rvp_update()`` unconditionally accessed ``_param_vector["bedslope_mult"]``
    even when ``channel_scaling=False``. Now guarded by a ``_channel_scale`` parameter.
  - Deprecated ``clrh_split`` and ``phydap_split`` code paths removed (~120 lines of
    dead code that only raised ValueError). ``_param_set`` now only accepts
    ``"no_split"`` and ``"no_runoff_scale"``.
  - ``.replace('\\\\', '/')`` path workarounds → ``pathlib.Path``
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class RavenFile:
    """Handle Raven configuration files — read templates, substitute parameters, write.

    Parameters
    ----------
    filename
        Base name of the Raven input file (extension added if missing).
    calib_dir
        Directory where the Raven input files are stored.
    extension
        File extension (default ``rvt``).
    """

    def __init__(
        self,
        filename: str,
        calib_dir: Path | str = "",
        extension: str = "rvt",
    ) -> None:
        if not filename.endswith(f".{extension}"):
            filename = f"{filename}.{extension}"

        self.filename = filename
        self.filepath = Path(calib_dir) / self.filename
        self.tpl_path = Path(calib_dir) / "templates" / f"{self.filename}.tpl"

    def write(self, content: str) -> None:
        """Write *content* to the file (create or overwrite)."""
        self.filepath.write_text(content)

    def read_tpl(self) -> str:
        """Read and return the template file's content."""
        return self.tpl_path.read_text()

    def rvp_update(
        self,
        _param_set: str,
        _dep_scale: bool,
        _param_vector: dict,
        _deps: dict | None = None,
        _channel_scale: bool = True,
    ) -> None:
        """Update the .rvp file with calibration parameters.

        Parameters
        ----------
        _param_set
            One of ``"no_split"`` or ``"no_runoff_scale"``.
        _dep_scale
            If True, apply ``dep_fact`` from param vector to depression depths.
        _param_vector
            Dict of calibration parameter values (keys: ``dep_fact``, ``seep_k``,
            optionally ``bedslope_mult``).
        _deps
            Mapping of subbasin_id → base depression depth. Required if
            ``_dep_scale`` is True.
        _channel_scale
            If True, scale bedslope values using ``_param_vector["bedslope_mult"]``.
            **BUG-002 fix**: was unconditionally accessed in the original.
        """
        if not self.filename.endswith(".rvp"):
            raise ValueError("Filename must end with .rvp extension.")

        if _param_set not in ("no_split", "no_runoff_scale"):
            raise ValueError(
                f"Unrecognized parameter set '{_param_set}'. "
                f"Use 'no_split' or 'no_runoff_scale'."
            )

        rvp_txt = self.read_tpl()

        dep_fact = _param_vector["dep_fact"] if _dep_scale else 1
        seep_k = _param_vector["seep_k"]

        rvp_txt = rvp_txt.replace("seep_fact", str(seep_k))

        if _deps is not None:
            for subid, base_depth in _deps.items():
                depth_value = dep_fact * base_depth
                rvp_txt = rvp_txt.replace(f"s{subid}_dep", str(depth_value))

        # BUG-002 fix: only access bedslope_mult when channel scaling is enabled
        if _channel_scale:
            bedslope_mult = _param_vector["bedslope_mult"]

            def scale_bedslope(match):
                original = float(match.group(1))
                return f":Bedslope\t\t\t {original * bedslope_mult:.7f}"

            rvp_txt = re.sub(r":Bedslope\s+([0-9.Ee+-]+)", scale_bedslope, rvp_txt)

        self.write(rvp_txt)

    def rvh_update(
        self,
        _param_set: str,
        _routing: bool,
        _channel_scale: bool,
        _param_vector: dict,
        _aspect_ratios: dict,
        _HRU_areas: dict,
        _tps: dict,
        _tcs: dict,
        _qrefs: dict,
    ) -> None:
        """Update the .rvh file with calibration parameters.

        Parameters
        ----------
        _param_set
            ``"no_split"`` or ``"no_runoff_scale"``.
        _routing
            If True, scale transport peak/concentration times.
        _channel_scale
            If True, scale Qref values.
        _param_vector
            Dict of calibration parameter values.
        _aspect_ratios, _HRU_areas, _tps, _tcs, _qrefs
            Per-subbasin lookup dicts.
        """
        if not self.filename.endswith(".rvh"):
            raise ValueError("Filename must end with .rvh extension.")

        if _param_set not in ("no_split", "no_runoff_scale"):
            raise ValueError(
                f"Unrecognized parameter set '{_param_set}'. "
                f"Use 'no_split' or 'no_runoff_scale'."
            )

        rvh_txt = self.read_tpl()

        seep_k = _param_vector["seep_k"]
        rvh_txt = rvh_txt.replace("seep_fact", str(seep_k))

        # Scale HRU areas
        if _param_set == "no_split":
            basin_fact = _param_vector["basin_fact"]
        else:  # no_runoff_scale
            basin_fact = 1.0

        for hru, area in _HRU_areas.items():
            rvh_txt = rvh_txt.replace(f"H{hru}_area", str(basin_fact * area))

        # Scale transport parameters
        if _routing:
            t_peak_fact = _param_vector["t_peak_fact"]
            t_conc_fact = _param_vector["tc_tp_fact"] * t_peak_fact

            for subid, tc in _tcs.items():
                rvh_txt = rvh_txt.replace(f"tc_{subid}", str(tc * t_conc_fact))

            for subid, tp in _tps.items():
                scaled = tp * t_peak_fact / _aspect_ratios[subid]
                rvh_txt = rvh_txt.replace(f"tp_{subid}", str(scaled))

            qref_scale = _param_vector["qref_scale"] if _channel_scale else 1
            for subid, qref in _qrefs.items():
                rvh_txt = rvh_txt.replace(f"qref_{subid}", str(qref_scale * qref))
        else:
            for subid, tc in _tcs.items():
                rvh_txt = rvh_txt.replace(f"tc_{subid}", str(tc))
            for subid, tp in _tps.items():
                rvh_txt = rvh_txt.replace(f"tp_{subid}", str(tp))

        self.write(rvh_txt)
