import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def _load(name: str):
    return json.loads((REPO_ROOT / name).read_text())


@pytest.fixture(scope="session")
def city_data():
    return _load("city-user-data.json")


@pytest.fixture(scope="session")
def helper_data():
    return _load("city-user-data-foe-helper.json")


@pytest.fixture(scope="session")
def grid_data():
    return _load("metadata-grid.json")
