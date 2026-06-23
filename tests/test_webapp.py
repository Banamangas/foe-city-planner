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


def test_index_has_polish_control(client):
    assert b'id="polish"' in client.get("/").data


def test_run_with_polish(client, repo_root):
    import time
    with open(repo_root / CITY, "rb") as cf, open(repo_root / HELPER, "rb") as hf:
        client.post("/load", data={"city": (cf, CITY), "helper": (hf, HELPER)},
                    content_type="multipart/form-data")
    r = client.post("/run", json={"remove_ids": [], "add_specs": [], "mode": "repack",
                                  "budget": 0.3, "seed": 0, "polish": True, "anneal_budget": 0.3})
    jid = r.get_json()["job_id"]
    for _ in range(200):
        st = client.get(f"/status/{jid}").get_json()
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["state"] == "done", st
    assert st["result"]["roads"] <= st["result"]["base_roads"]


def _load(client, repo_root):
    with open(repo_root / CITY, "rb") as cf, open(repo_root / HELPER, "rb") as hf:
        client.post("/load", data={"city": (cf, CITY), "helper": (hf, HELPER)},
                    content_type="multipart/form-data")


@pytest.mark.parametrize("payload", [
    {"mode": "repack", "budget": 0.3, "add_specs": [{"name": "x"}]},        # missing width/length
    {"mode": "repack", "budget": 0.3, "add_specs": [{"width": 2}]},          # missing length
    {"mode": "repack", "budget": 0.3, "add_specs": "notalist"},              # add_specs not a list
    {"mode": "repack", "budget": "abc"},                                      # non-numeric budget
    {"mode": "sweep", "budget": 0.3, "seeds": "lots"},                       # non-numeric seeds
])
def test_run_bad_input_returns_400_json(client, repo_root, payload):
    """Malformed run input must return a structured 400 JSON error, never a 500
    HTML page (which makes the browser's r.json() throw and freezes the UI)."""
    _load(client, repo_root)
    r = client.post("/run", json=payload)
    assert r.status_code == 400, r.data
    assert r.is_json, r.content_type
    assert "error" in r.get_json()


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
