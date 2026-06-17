"""Backwards-compatibility alias for :mod:`pwa_raven.raven_inputs`.

The descriptive module name (``raven_inputs``) is the canonical home
for the Raven .rv* file generation pipeline. This module re-exports
the same names under the project's internal "Step 2" vocabulary so
existing scripts, notebooks, and docs keep working.

Prefer the descriptive names in new code::

    from pwa_raven.raven_inputs import RavenInputsConfig, run_raven_inputs

The numbered aliases below are equivalent::

    from pwa_raven.step2 import Step2Config, run_step2
"""

from __future__ import annotations

from pwa_raven.raven_inputs import (
    RavenInputsConfig as Step2Config,
    RavenInputsResult as Step2Result,
    run_raven_inputs as run_step2,
)

__all__ = ["Step2Config", "Step2Result", "run_step2"]
