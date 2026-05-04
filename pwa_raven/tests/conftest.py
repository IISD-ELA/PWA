"""Shared fixtures for pwa_raven tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def grassmere_data_dir() -> Path:
    """Discover the grassmere reference data directory."""
    import os

    env_path = os.environ.get("PWA_TEST_DATA_DIR")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data"
        if candidate.is_dir() and (candidate / "Raven").is_dir():
            return candidate

    pytest.skip("Reference dataset not found. Set PWA_TEST_DATA_DIR.")


@pytest.fixture
def liard_sample_dir() -> Path:
    """Discover the Liard RavenView sample data Thomas shared on 2026-05-04.

    Walks up the workspace tree for ``data/LiardRiverModel/`` containing
    Liard.json. Falls back to the ``PWA_LIARD_SAMPLE_DIR`` env var.
    """
    import os

    env_path = os.environ.get("PWA_LIARD_SAMPLE_DIR")
    if env_path:
        path = Path(env_path)
        if path.is_dir():
            return path

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "LiardRiverModel"
        if candidate.is_dir() and (candidate / "Liard.json").is_file():
            return candidate

    pytest.skip(
        "Liard sample not found. Set PWA_LIARD_SAMPLE_DIR or place the "
        "sample at <workspace>/data/LiardRiverModel/."
    )
