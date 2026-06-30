"""Fixtures for pwa_raven integration tests — real binaries / real data.

These tests are **local-only**: the GitHub CI workflow runs ``pytest
tests/unit`` and never touches this directory, so a cross-repo PAT is never
needed (see the CI rationale in the repo's tests README). Every fixture here
**skips cleanly** when its input is absent, so ``pytest tests/integration`` on
a bare checkout is all-skips, not failures — the developer supplies a real
config / the Raven binary to actually exercise them.

Inputs are discovered from the environment so no machine-specific paths are
baked into the tests:

* ``PWA_RAVEN_INPUTS_CONFIG`` — path to a filled-in ``raven_inputs.yml``
  (generate one with ``pwa-init-raven-inputs``). Required to run the
  generation step against real watershed data.
* ``PWA_RAVEN_BINARY`` — explicit path to the Raven executable. Optional;
  falls back to ``Raven`` / ``Raven.exe`` on PATH.

The session-scoped ``grassmere_data_dir`` / ``liard_sample_dir`` fixtures from
``tests/conftest.py`` are inherited here unchanged.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def raven_binary() -> Path:
    """Resolve the Raven executable, or skip the test.

    Resolution order: ``PWA_RAVEN_BINARY`` env var → ``Raven`` / ``Raven.exe``
    on PATH. Skips (does not fail) when none is found, so the binary-dependent
    tests are opt-in by simply having Raven installed.
    """
    override = os.environ.get("PWA_RAVEN_BINARY")
    if override:
        path = Path(override)
        if not path.exists():
            pytest.fail(f"PWA_RAVEN_BINARY={override!r} does not exist")
        return path
    for name in ("Raven", "Raven.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    pytest.skip(
        "Raven binary not found. Install Raven (http://raven.uwaterloo.ca) and "
        "put it on PATH as 'Raven'/'Raven.exe', or set PWA_RAVEN_BINARY."
    )


@pytest.fixture
def raven_inputs_config():
    """A real ``RavenInputsConfig`` from ``$PWA_RAVEN_INPUTS_CONFIG``.

    Skips when the env var is unset (the common case — no data on this
    machine); fails loudly only if it points at a missing file, since that's a
    misconfiguration the developer asked for and would want surfaced.
    """
    from pwa_raven.raven_inputs import RavenInputsConfig

    config_path = os.environ.get("PWA_RAVEN_INPUTS_CONFIG")
    if not config_path:
        pytest.skip(
            "Set PWA_RAVEN_INPUTS_CONFIG to a filled-in raven_inputs.yml "
            "(see `pwa-init-raven-inputs`) to run the Raven-inputs e2e tests."
        )
    path = Path(config_path)
    if not path.is_file():
        pytest.fail(f"PWA_RAVEN_INPUTS_CONFIG={config_path!r} is not a file")
    return RavenInputsConfig.from_yaml(path)
