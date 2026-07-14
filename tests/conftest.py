import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def require_data(name: str) -> Path:
    """Return the repo-root path to a data file, skipping the test if it is
    absent. The large personal game dumps (darkzig.json, the FR cities, the
    foe-helper file) are gitignored and not shipped in the repo, so tests that
    need them skip cleanly on a fresh clone."""
    p = REPO_ROOT / name
    if not p.exists():
        pytest.skip(f"{name} not present (large data file, gitignored)")
    return p


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def _load(name: str):
    return json.loads(require_data(name).read_text())


@pytest.fixture(scope="session")
def city_data():
    return _load("city-user-data.json")


@pytest.fixture(scope="session")
def helper_data():
    return _load("city-user-data-foe-helper.json")


@pytest.fixture(scope="session")
def grid_data():
    return _load("metadata-grid.json")
