"""Backwards-compatibility alias for :mod:`pwa_raven.run_nc_processing`.

The descriptive module name (``run_nc_processing``) is the canonical
CLI entry point for the NetCDF subsetting + GridWeights pipeline. This
module re-exports the same names under the project's internal "Step 1"
vocabulary so existing scripts and ``python -m`` invocations keep
working.

Prefer the descriptive name in new code::

    python -m pwa_raven.run_nc_processing --config nc_processing.yml

The numbered alias is equivalent::

    python -m pwa_raven.run_step1 --config step1.yml
"""

from __future__ import annotations

import sys

from pwa_raven.run_nc_processing import (
    NcProcessingConfig as Step1Config,
    main,
    run_nc_processing as run_step1,
)

__all__ = ["Step1Config", "run_step1", "main"]


if __name__ == "__main__":
    sys.exit(main())
