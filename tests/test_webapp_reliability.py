"""Phase A (2026-11-11 reviews): job admission, coherent terminal snapshots,
stream errors, split uploads keeping helper data, input-shape validation."""
import io
import json
import threading

import pytest

flask = pytest.importorskip("flask")
import webapp.runner as runner_mod
from webapp.app import create_app
from webapp.runner import JobBusy, JobManager
from tests.test_runner import _tiny_layout


class _GateSearch:
    """Fake RoadsFirstSearch: blocks until released, then returns or raises."""
    gate = threading.Event()
    fail = False

    def __init__(self, layout, **kw):
        pass

    def run(self, on_improvement=None, on_status=None, should_stop=None, **_kw):
        while not _GateSearch.gate.wait(0.01):
            if should_stop and should_stop():
                break
        if _GateSearch.fail:
            raise RuntimeError("solver exploded")
        return {"verdict": "DONE", "best_achieved": None}


@pytest.fixture()
def fake_search(monkeypatch):
    _GateSearch.gate = threading.Event()
    _GateSearch.fail = False
    monkeypatch.setattr(runner_mod, "RoadsFirstSearch", _GateSearch)
    return _GateSearch


def _wait_done(jobs, jid):
    for _ in range(500):
        if jobs.is_done(jid):
            return
        threading.Event().wait(0.01)
    raise AssertionError("job did not finish")


def test_second_job_is_refused_while_one_runs(fake_search):
    jobs = JobManager()
    first = jobs.submit(_tiny_layout(), time_box=60.0)
    with pytest.raises(JobBusy) as exc:
        jobs.submit(_tiny_layout(), time_box=60.0)
    assert exc.value.job_id == first
    fake_search.gate.set()
    _wait_done(jobs, first)
    jobs.submit(_tiny_layout(), time_box=60.0)  # admitted once the first ended


def test_terminal_snapshot_carries_the_error(fake_search):
    jobs = JobManager()
    fake_search.fail = True
    jid = jobs.submit(_tiny_layout(), time_box=60.0)
    fake_search.gate.set()
    _wait_done(jobs, jid)
    snap = jobs.snapshot(jid)
    assert snap["state"] == "error" and "solver exploded" in snap["error"]
    assert snap["result"] is None and snap["elapsed"] >= 0
    assert jobs.snapshot("nope") is None


def test_snapshot_never_shows_done_without_result(fake_search):
    jobs = JobManager()
    jid = jobs.submit(_tiny_layout(), time_box=60.0)
    fake_search.gate.set()
    _wait_done(jobs, jid)
    snap = jobs.snapshot(jid)
    assert snap["state"] == "done" and snap["result"]["verdict"] == "DONE"


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def _combined():
    return {
        "CityMapData": {"th1": {"id": 1, "type": "main_building", "x": 0, "y": 0,
                                "cityentity_id": "R_MultiAge_CityHall", "name": "TH"}},
        "UnlockedAreas": [{"x": 0, "y": 0, "width": 10, "length": 10}],
        "CityEntities": {"R_MultiAge_CityHall": {"id": "R_MultiAge_CityHall", "width": 3,
                                                 "length": 3, "name": "TH",
                                                 "requirements": {}}},
    }


def test_stream_of_unknown_job_is_404(client):
    assert client.get("/api/stream/nope").status_code == 404


def test_stream_done_event_is_a_full_envelope(client, fake_search):
    cid = client.post("/api/load", json=_combined()).get_json()["city_id"]
    fake_search.fail = True
    jid = client.post("/api/optimize", json={"city_id": cid}).get_json()["job_id"]
    fake_search.gate.set()
    body = client.get(f"/api/stream/{jid}").get_data(as_text=True)
    done = body.split("event: done\ndata: ", 1)[1].split("\n", 1)[0]
    env = json.loads(done)
    assert env["state"] == "error" and "solver exploded" in env["error"]


def test_optimize_while_busy_is_409(client, fake_search):
    cid = client.post("/api/load", json=_combined()).get_json()["city_id"]
    first = client.post("/api/optimize", json={"city_id": cid})
    assert first.status_code == 200
    second = client.post("/api/optimize", json={"city_id": cid})
    assert second.status_code == 409
    assert second.get_json()["active_job_id"] == first.get_json()["job_id"]
    fake_search.gate.set()


@pytest.mark.parametrize("body", [[1, 2], "x", 3])
def test_non_object_bodies_are_400(client, body):
    for url in ("/api/load", "/api/optimize", "/api/layouts", "/api/cities/import"):
        r = client.post(url, json=body)
        assert r.status_code == 400, url


def test_oversized_integer_option_is_400(client):
    cid = client.post("/api/load", json=_combined()).get_json()["city_id"]
    raw = '{"city_id": "%s", "patterns": %s}' % (cid, "9" * 400)
    r = client.post("/api/optimize", data=raw, content_type="application/json")
    assert r.status_code == 400 and "patterns" in r.get_json()["error"]


def test_layout_save_validates_numbers_and_city(client):
    cid = client.post("/api/load", json=_combined()).get_json()["city_id"]
    assert client.post("/api/layouts", json={"city_id": "nope"}).status_code == 400
    bad = client.post("/api/layouts", json={"city_id": cid, "k": "abc"})
    assert bad.status_code == 400
    ok = client.post("/api/layouts", json={"city_id": cid, "k": 3, "achieved": 2,
                                           "roads_count": 2, "layout_json": {}})
    assert ok.status_code == 200


def test_split_upload_keeps_helper_through_cache_and_optimize(client, fake_search):
    city = {"gridId": "main", "unlocked_areas": [{"width": 10, "length": 10}],
            "entities": [{"id": 1, "cityentity_id": "TH", "type": "main_building"}]}
    helper = {"CityEntities": {"TH": {"id": "TH", "width": 3, "length": 3, "name": "TH"}}}
    r = client.post("/api/load/raw", data={
        "city": (io.BytesIO(json.dumps(city).encode()), "city.json"),
        "helper": (io.BytesIO(json.dumps(helper).encode()), "helper.json"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    cid = r.get_json()["city_id"]
    # the cached city must load again on its own (optimize, export, re-import)
    assert client.post("/api/optimize", json={"city_id": cid}).status_code == 200
    fake_search.gate.set()
    exported = client.get(f"/api/cities/{cid}/export").get_json()
    assert "helper_data" in exported
    assert client.post("/api/cities/import", json=exported).status_code == 200


def test_stream_sends_a_layout_event_per_kept_layout(client, monkeypatch):
    class OfferSearch:
        def __init__(self, layout, **kw):
            self.layout = layout

        def run(self, on_layout=None, **_kw):
            on_layout(self.layout, 3, 3)
            on_layout(self.layout, 3, 3)
            return {"verdict": "DONE", "best_achieved": 3}

    class KeepAll:
        """Stands in for LayoutCollector: keeps everything offered."""
        def __init__(self, reference, **kw):
            self.count = 0

        def offer(self, layout, k, achieved):
            self.count += 1
            return {"id": self.count - 1, "k": k, "achieved": achieved}

        def entries(self):
            return [{"id": i} for i in range(self.count)]

    monkeypatch.setattr(runner_mod, "RoadsFirstSearch", OfferSearch)
    monkeypatch.setattr(runner_mod, "LayoutCollector", KeepAll)
    cid = client.post("/api/load", json=_combined()).get_json()["city_id"]
    jid = client.post("/api/optimize", json={"city_id": cid}).get_json()["job_id"]
    body = client.get(f"/api/stream/{jid}").get_data(as_text=True)
    events = [json.loads(chunk.split("\ndata: ", 1)[1].split("\n", 1)[0])
              for chunk in body.split("event: layout")[1:]]
    assert [e["id"] for e in events] == [0, 1]
    done = json.loads(body.split("event: done\ndata: ", 1)[1].split("\n", 1)[0])
    assert done["layouts_found"] == 2 and len(done["result"]["layouts"]) == 2
