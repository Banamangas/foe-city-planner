import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def test_old_index_still_served(client):
    """Old static index.html must still be served until Phase 3 replaces it."""
    r = client.get("/")
    assert r.status_code == 200


def test_old_static_assets_still_served(client):
    """Old static assets (app.js, style.css) must still be served."""
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
