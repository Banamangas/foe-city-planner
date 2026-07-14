import os
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app

_DIST = os.path.join(os.path.dirname(__file__), "..", "webapp", "dist")


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_serves_built_spa_or_503(client):
    """/ serves the built SPA when webapp/dist exists, else a 503 JSON hint.
    Either is correct — the build is not a pytest prerequisite."""
    r = client.get("/")
    if os.path.exists(os.path.join(_DIST, "index.html")):
        assert r.status_code == 200
    else:
        assert r.status_code == 503
        assert r.is_json and "error" in r.get_json()


def test_unknown_api_route_is_404_json(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
