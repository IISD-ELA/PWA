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
