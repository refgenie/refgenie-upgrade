"""Shared test fixtures for refgenie-upgrade."""

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def v04_config_path():
    """Path to a v0.4 test config."""
    return DATA_DIR / "genomes_v04.yaml"


@pytest.fixture
def v03_config_path():
    """Path to a v0.3 test config."""
    return DATA_DIR / "genomes_v03.yaml"
