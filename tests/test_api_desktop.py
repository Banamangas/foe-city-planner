"""Desktop mode: create_app(data_dir=...) keeps one city, a last session, ping."""
import json
import os
import threading
import time

import pytest

pytest.importorskip("flask")
from tests.test_api_edits import _payload  # noqa: E402
from webapp.app import create_app  # noqa: E402
from webapp.runner import JobManager  # noqa: E402


@pytest.fixture(autouse=True)
def _no_update(monkeypatch):
    monkeypatch.setenv("FOEOPT_NO_UPDATE", "1")


def _desktop(tmp_path):
    app = create_app(data_dir=str(tmp_path))
    app.config.update(TESTING=True)
    return app, app.test_client()


def _two_payloads():
    a = _payload()
    b = _payload()
    b["CityMapData"]["extra"] = {"id": 999, "type": "decoration", "x": 10, "y": 4,
                                 "cityentity_id": "DECO"}
    return a, b


def test_desktop_keeps_only_last_city(tmp_path):
    app, c = _desktop(tmp_path)
    a, b = _two_payloads()
    ida = c.post("/api/load", json=a).get_json()["city_id"]
    idb = c.post("/api/load", json=b).get_json()["city_id"]
    assert ida != idb
    ids = [x["id"] for x in c.get("/api/cities").get_json()]
    assert ids == [idb]
    assert os.path.isfile(os.path.join(str(tmp_path), "cities.db"))


def test_session_roundtrip(tmp_path):
    app, c = _desktop(tmp_path)
    r = c.get("/api/session")
    assert r.status_code == 404 and r.get_json() == {"error": "no session"}
    assert c.put("/api/session", json={"version": 1, "step": 3}).status_code == 204
    r = c.get("/api/session")
    assert r.status_code == 200 and r.get_json() == {"version": 1, "step": 3}
    assert os.path.isfile(os.path.join(str(tmp_path), "last-session.json"))
    assert c.delete("/api/session").status_code == 204
    assert c.get("/api/session").status_code == 404
    assert c.delete("/api/session").status_code == 204


def test_session_rejects_bad_bodies(tmp_path):
    app, c = _desktop(tmp_path)
    assert c.put("/api/session", json={"v": 1}).status_code == 204
    assert c.put("/api/session", json=[1, 2]).status_code == 400
    big = json.dumps({"blob": "x" * (5 * 1024 * 1024 + 10)})
    r = c.put("/api/session", data=big, content_type="application/json")
    assert r.status_code == 400
    assert c.get("/api/session").get_json() == {"v": 1}


def test_ping_records_time(tmp_path):
    app, c = _desktop(tmp_path)
    assert c.post("/api/ping").status_code == 204
    assert isinstance(app.config["LAST_PING"], float)


def test_dev_mode_unchanged(tmp_path):
    app = create_app(db_path=str(tmp_path / "x.db"))
    c = app.test_client()
    assert c.get("/api/session").status_code == 404
    assert c.get("/api/session").get_json() != {"error": "no session"}
    assert c.put("/api/session", json={"a": 1}).status_code == 404
    assert c.delete("/api/session").status_code == 404
    assert c.post("/api/ping").status_code == 404
    a, b = _two_payloads()
    c.post("/api/load", json=a)
    c.post("/api/load", json=b)
    assert len(c.get("/api/cities").get_json()) == 2
    assert app.extensions["foeopt_jobs"] is not None


def test_stop_all():
    jm = JobManager()
    ev = threading.Event()
    jm._jobs["j"] = {"state": {"state": "running", "start": time.monotonic(), "end": None,
                               "result": None, "error": None, "phase": None,
                               "layouts_found": 0},
                     "stop_event": ev, "improvements": None, "layouts": None}
    assert jm.any_running() is True
    jm.stop_all()
    assert ev.is_set()
    jm._jobs["j"]["state"]["state"] = "done"
    assert jm.any_running() is False


def test_desktop_rejects_foreign_host(tmp_path):
    """DNS-rebinding guard: only 127.0.0.1 / localhost (with or without the port)."""
    app, c = _desktop(tmp_path)
    app.config["FOEOPT_PORT"] = 8123
    assert c.get("/api/session").status_code == 404                     # Host: localhost
    for host in ("127.0.0.1:8123", "localhost:8123", "127.0.0.1", "LOCALHOST:8123"):
        assert c.get("/api/session", headers={"Host": host}).status_code == 404, host
    for host in ("evil.example:8123", "evil.example", "127.0.0.1:9999",
                 "127.0.0.1.evil.example:8123", "[::1]:8123"):
        assert c.get("/api/session", headers={"Host": host}).status_code == 403, host
        assert c.put("/api/session", json={"a": 1},
                     headers={"Host": host}).status_code == 403, host
    assert not (tmp_path / "last-session.json").exists()


def test_desktop_host_guard_any_port_until_known(tmp_path):
    app, c = _desktop(tmp_path)
    assert c.get("/api/session", headers={"Host": "127.0.0.1:4242"}).status_code == 404
    assert c.get("/api/session", headers={"Host": "evil.example:4242"}).status_code == 403


def test_developer_mode_has_no_host_guard(tmp_path):
    app = create_app(str(tmp_path / "c.db"))
    app.config.update(TESTING=True)
    r = app.test_client().get("/api/cities", headers={"Host": "evil.example:5000"})
    assert r.status_code == 200


def test_desktop_startup_removes_leftover_tmp_files(tmp_path):
    (tmp_path / "tmpab12cd.tmp").write_text("{}")
    (tmp_path / "tmp_x.tmp").write_text("{}")
    keep = tmp_path / "notes.tmp"
    keep.write_text("x")
    (tmp_path / "last-session.json").write_text("{}")
    _desktop(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()
                  if not p.name.startswith("cities.db")) == ["last-session.json", "notes.tmp"]
