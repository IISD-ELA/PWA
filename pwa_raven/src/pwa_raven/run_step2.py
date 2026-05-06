"""Backwards-compatibility alias for :mod:`pwa_raven.run_raven_inputs`.

The descriptive module name (``run_raven_inputs``) is the canonical
CLI entry point for the Raven .rv* file generation pipeline. This
module re-exports the same names under the project's internal "Step 2"
vocabulary so existing scripts and ``python -m`` invocations keep
working.

Prefer the descriptive name in new code::

    python -m pwa_raven.run_raven_inputs --config raven_inputs.yml

The numbered alias is equivalent::

    python -m pwa_raven.run_step2 --config step2.yml
"""

from __future__ import annotations

import sys

from pwa_raven.run_raven_inputs import (
    RavenInputsConfig as Step2Config,
    main,
    run_raven_inputs as run_step2,
)

__all__ = ["Step2Config", "run_step2", "main"]


if __name__ == "__main__":
    sys.exit(main())
