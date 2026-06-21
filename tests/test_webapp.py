import time
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app

CITY = "city-user-data.json"
HELPER = "city-user-data-foe-helper.json"


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"id=\"building-table\"" in r.data or b"building-table" in r.data


def test_load_returns_buildings(client, repo_root):
    with open(repo_root / CITY, "rb") as cf, open(repo_root / HELPER, "rb") as hf:
        r = client.post("/load", data={"city": (cf, CITY), "helper": (hf, HELPER)},
                        content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["buildings"]) > 0
    assert isinstance(body["road_estimate"], int)
    assert any(b["is_townhall"] for b in body["buildings"])


def test_bad_upload_returns_400(client):
    import io
    r = client.post("/load", data={"city": (io.BytesIO(b"not json"), "x.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_static_assets_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_run_and_status(client, repo_root):
    with open(repo_root / CITY, "rb") as cf, open(repo_root / HELPER, "rb") as hf:
        client.post("/load", data={"city": (cf, CITY), "helper": (hf, HELPER)},
                    content_type="multipart/form-data")
    r = client.post("/run", json={"remove_ids": [], "add_specs": [], "mode": "repack",
                                  "budget": 0.5, "seed": 0})
    jid = r.get_json()["job_id"]
    for _ in range(120):
        st = client.get(f"/status/{jid}").get_json()
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["state"] == "done", st
    assert st["result"]["placed"] > 0 and st["result"]["map_html"]
