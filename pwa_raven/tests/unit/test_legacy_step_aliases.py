"""Smoke tests for the backwards-compatibility ``step1`` / ``step2`` aliases.

The descriptive ``nc_processing`` / ``raven_inputs`` modules are the
canonical homes; this test suite confirms that scripts using the
project's internal "Step N" vocabulary still work via the alias
modules.
"""

from __future__ import annotations


def test_step1_alias_module_reexports_canonical_names():
    """``from pwa_raven.step1 import Step1Config, run_step1`` returns
    the same objects as the descriptive imports."""
    from pwa_raven import nc_processing, step1
    assert step1.Step1Config is nc_processing.NcProcessingConfig
    assert step1.Step1Result is nc_processing.NcProcessingResult
    assert step1.run_step1 is nc_processing.run_nc_processing


def test_step2_alias_module_reexports_canonical_names():
    from pwa_raven import raven_inputs, step2
    assert step2.Step2Config is raven_inputs.RavenInputsConfig
    assert step2.Step2Result is raven_inputs.RavenInputsResult
    assert step2.run_step2 is raven_inputs.run_raven_inputs


def test_run_step1_alias_module_reexports_canonical_names():
    """``python -m pwa_raven.run_step1`` invokes the same main as
    ``python -m pwa_raven.run_nc_processing``."""
    from pwa_raven import run_nc_processing, run_step1
    assert run_step1.run_step1 is run_nc_processing.run_nc_processing
    assert run_step1.main is run_nc_processing.main


def test_run_step2_alias_module_reexports_canonical_names():
    from pwa_raven import run_raven_inputs, run_step2
    assert run_step2.run_step2 is run_raven_inputs.run_raven_inputs
    assert run_step2.main is run_raven_inputs.main


def test_init_step1_alias_module_reexports_canonical_main():
    from pwa_raven import init_nc_processing_config, init_step1_config
    assert init_step1_config.main is init_nc_processing_config.main


def test_init_step2_alias_module_reexports_canonical_main():
    from pwa_raven import init_raven_inputs_config, init_step2_config
    assert init_step2_config.main is init_raven_inputs_config.main
