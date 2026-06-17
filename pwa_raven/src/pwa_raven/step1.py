"""Backwards-compatibility alias for :mod:`pwa_raven.nc_processing`.

The descriptive module name (``nc_processing``) is the canonical home
for the NetCDF subsetting + GridWeights pipeline. This module
re-exports the same names under the project's internal "Step 1"
vocabulary so existing scripts, notebooks, and docs keep working.

Prefer the descriptive names in new code::

    from pwa_raven.nc_processing import NcProcessingConfig, run_nc_processing

The numbered aliases below are equivalent::

    from pwa_raven.step1 import Step1Config, run_step1
"""

from __future__ import annotations

from pwa_raven.nc_processing import (
    NcProcessingConfig as Step1Config,
    NcProcessingResult as Step1Result,
    run_nc_processing as run_step1,
)

__all__ = ["Step1Config", "Step1Result", "run_step1"]
