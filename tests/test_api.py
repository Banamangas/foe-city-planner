import json
import time
import io
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def _slim_payload():
    return {
        "CityMapData": {},
        "UnlockedAreas": [{"x": 0, "y": 0, "width": 4, "length": 4}],
        "CityEntities": {},
    }


def _combined_payload():
    return {
        "CityMapData": {
            "th1": {"id": 1, "type": "main_building", "x": 0, "y": 0,
                    "cityentity_id": "R_MultiAge_CityHall", "name": "Town Hall"}
        },
        "UnlockedAreas": [{"x": 0, "y": 0, "width": 6, "length": 6}],
        "CityEntities": {
            "R_MultiAge_CityHall": {"id": "R_MultiAge_CityHall", "width": 7, "length": 7,
                                    "name": "Town Hall", "requirements": {}}
        },
    }


def test_api_load_with_json_body(client):
    r = client.post("/api/load", json=_combined_payload())
    assert r.status_code == 200
    body = r.get_json()
    assert "city_id" in body
    assert isinstance(body["buildings"], list)
    assert any(b["is_townhall"] for b in body["buildings"])
    assert "region_cells" in body
    assert "road_estimate" in body
    assert "map_view" in body


def test_api_load_bad_json_returns_400(client):
    r = client.post("/api/load", data=b"not json", content_type="application/json")
    assert r.status_code == 400
    assert r.is_json
    assert "error" in r.get_json()


def test_api_load_dedup_by_hash(client):
    payload = _combined_payload()
    r1 = client.post("/api/load", json=payload)
    r2 = client.post("/api/load", json=payload)
    assert r1.get_json()["city_id"] == r2.get_json()["city_id"]


def test_api_optimize_returns_job_id(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.post("/api/optimize", json={"city_id": city_id, "time_box": 1.0})
    assert r.status_code == 200
    assert "job_id" in r.get_json()


def test_api_optimize_without_load_returns_400(client):
    r = client.post("/api/optimize", json={"city_id": "nonexistent", "time_box": 1.0})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_api_optimize_defaults_to_validated_worker_config(client, monkeypatch):
    """/api/optimize's defaults must match this session's validated config
    (tasks/lessons.md 2026-07-19/20 + 2026-07-20/21): workers=6/probe_workers=2
    (not 16 total CP-SAT threads, which reproducibly regresses the walk via
    contention) and concurrent_levels=4 (a reproducible, no-downside speed
    win) -- not silently left at the old, untested workers=4/probe_workers=4
    defaults."""
    import webapp.app as app_mod
    captured = []
    def spy_submit(self, layout, **kwargs):
        captured.append(kwargs)
        return "fake-job-id"
    monkeypatch.setattr(app_mod.JobManager, "submit", spy_submit)

    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.post("/api/optimize", json={"city_id": city_id, "time_box": 1.0})
    assert r.status_code == 200
    assert captured, "JobManager.submit was never called"
    assert captured[0]["workers"] == 6
    assert captured[0]["probe_workers"] == 2
    assert captured[0]["concurrent_levels"] == 4


def test_api_optimize_worker_config_still_overridable(client, monkeypatch):
    """Explicit request params must still override the new defaults."""
    import webapp.app as app_mod
    captured = []
    def spy_submit(self, layout, **kwargs):
        captured.append(kwargs)
        return "fake-job-id"
    monkeypatch.setattr(app_mod.JobManager, "submit", spy_submit)

    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.post("/api/optimize", json={
        "city_id": city_id, "time_box": 1.0,
        "workers": 8, "probe_workers": 1, "concurrent_levels": 1,
    })
    assert r.status_code == 200
    assert captured[0]["workers"] == 8
    assert captured[0]["probe_workers"] == 1
    assert captured[0]["concurrent_levels"] == 1


def test_api_stop_unknown_job(client):
    r = client.post("/api/stop/nonexistent")
    assert r.status_code == 404


def test_api_cities_list(client):
    client.post("/api/load", json=_combined_payload())
    r = client.get("/api/cities")
    assert r.status_code == 200
    cities = r.get_json()
    assert len(cities) >= 1
    assert "id" in cities[0]


def test_api_cities_get(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.get(f"/api/cities/{city_id}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["id"] == city_id
    assert "buildings" in body
    assert "region_cells" in body


def test_api_cities_get_not_found(client):
    r = client.get("/api/cities/nonexistent")
    assert r.status_code == 404


def test_api_cities_export(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.get(f"/api/cities/{city_id}/export")
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    data = json.loads(r.data)
    assert "CityMapData" in data or "entities" in data


def test_api_layouts_crud(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    layout_data = {"k": 92, "achieved": 79, "roads": [[0, 1]], "buildings": {"1": [0, 0, 2, 2]}}
    r_save = client.post("/api/layouts", json={
        "city_id": city_id, "k": 92, "achieved": 79,
        "layout_json": layout_data, "roads_count": 79,
    })
    assert r_save.status_code == 200
    layout_id = r_save.get_json()["id"]

    r_get = client.get(f"/api/layouts/{layout_id}")
    assert r_get.status_code == 200
    assert r_get.get_json()["k"] == 92

    r_list = client.get("/api/layouts")
    assert r_list.status_code == 200
    assert len(r_list.get_json()) >= 1

    r_del = client.delete(f"/api/layouts/{layout_id}")
    assert r_del.status_code == 200
    assert client.get(f"/api/layouts/{layout_id}").status_code == 404


def test_api_load_raw_fallback(client):
    payload = json.dumps(_combined_payload()).encode()
    r = client.post("/api/load/raw", data={"city": (io.BytesIO(payload), "city.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert "city_id" in body
    assert len(body["buildings"]) > 0


def test_old_routes_still_served(client):
    r = client.get("/")
    assert r.status_code == 200
