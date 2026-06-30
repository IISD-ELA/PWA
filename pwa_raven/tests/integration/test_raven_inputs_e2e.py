"""End-to-end: generate Raven input files from a real config, and prove the
real Raven binary accepts them.

Why this exists
---------------
The ``.rv*`` writers are thoroughly unit-tested with synthetic inputs and
mocks (``tests/unit/test_rv_writers.py``, ``test_raven.py``). What no unit test
can prove is that the *actual Raven executable* parses the generated set
without error. The files are built by string substitution into templates, so a
placeholder typo silently produces a well-formed-but-wrong file that only Raven
rejects — the exact failure mode flagged in the project review.

Two layers, so the cheaper one still runs without Raven installed:

1. ``regression`` (data, no binary) — the full generation step runs over real
   watershed data and emits non-empty, directive-bearing files.
2. ``integration`` + ``slow`` (data + Raven binary) — Raven actually runs the
   generated model and exits cleanly (``run_raven`` also checks
   ``Raven_errors.txt`` for the silent-error case).

Both skip cleanly without their inputs — see ``conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pwa_raven.raven.runner import run_raven
from pwa_raven.raven_inputs import run_raven_inputs


@pytest.fixture
def generated_inputs(raven_inputs_config):
    """Run the real Raven-input generation step once and hand back the result."""
    return run_raven_inputs(raven_inputs_config)


@pytest.mark.regression
def test_run_raven_inputs_emits_nonempty_rv_files(generated_inputs):
    """The five core .rv* files are written, non-empty, and contain Raven
    directives (lines beginning with ``:``). Catches an empty/garbage write
    long before Raven is involved."""
    core_files = {
        "rvi": generated_inputs.rvi,
        "rvp": generated_inputs.rvp,
        "rvh": generated_inputs.rvh,
        "rvc": generated_inputs.rvc,
        "model_rvt": generated_inputs.model_rvt,
    }
    for label, path in core_files.items():
        path = Path(path)
        assert path.is_file(), f"{label} was not written: {path}"
        text = path.read_text()
        assert text.strip(), f"{label} is empty: {path}"
        assert any(line.lstrip().startswith(":") for line in text.splitlines()), (
            f"{label} contains no Raven ':' directives — likely a broken "
            f"template substitution: {path}"
        )


@pytest.mark.integration
@pytest.mark.slow
def test_raven_accepts_generated_inputs(generated_inputs, raven_binary):
    """The generated model runs under the real Raven binary without error.

    ``run_raven`` raises CalledProcessError on a non-zero exit and
    RavenExecutionError when Raven exits 0 but logs an ERROR, so reaching the
    assertion already means a clean run; we assert the return code for clarity.
    """
    rvi_path = Path(generated_inputs.rvi)
    completed = run_raven(
        rvi_path.stem,
        data_dir=rvi_path.parent,
        output_dir="output",
        raven_binary=raven_binary,
    )
    assert completed.returncode == 0
