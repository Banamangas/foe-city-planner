"""Plan X API: full v3 cache, stable city ids, Forge Hammer export endpoints."""
import json

import pytest

flask = pytest.importorskip("flask")
from foeopt.catalog import Catalog  # noqa: E402
from foeopt.editing import apply_edits  # noqa: E402
from foeopt.loader import _bundled_catalog, load_layout_from_dict  # noqa: E402
from tests.test_export_v3 import _ms, _v3  # noqa: E402
from webapp.app import _v3_slim, city_id_for, create_app  # noqa: E402
from webapp.runner import layout_to_dict  # noqa: E402


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def _load(client, data, name=None):
    r = client.post(f"/api/load?name={name}" if name else "/api/load", json=data)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["city_id"]


def test_full_v3_file_is_cached(client):
    src = _v3()
    cid = _load(client, src, "essay.json")
    assert client.get(f"/api/cities/{cid}").get_json()["payload"] == src


def test_city_id_is_the_slim_id_so_old_caches_keep_their_id(client):
    src = _v3()
    slim = _v3_slim(src)
    assert set(slim) == {"version", "cityData", "mapData"}
    old_id = _load(client, slim)                    # what the pre-plan-X worker sent
    client.put(f"/api/cities/{old_id}/edits", json={"remove": [5], "add": []})
    lay = layout_to_dict(load_layout_from_dict(src))
    r = client.post("/api/export/v3", json={"city_id": old_id, "layout": lay})
    assert r.status_code == 400
    assert r.get_json()["reupload"] is True and "re-upload" in r.get_json()["error"]
    # Re-uploading the full file: same id, edits kept, export now works.
    new = client.post("/api/load?name=essay.json", json=src).get_json()
    # (Flask's test client sends keys sorted; a browser keeps the file's order.)
    assert new["city_id"] == old_id == city_id_for(json.loads(json.dumps(src, sort_keys=True)))
    assert new["edits"] == {"remove": [5], "add": []}
    assert client.post("/api/export/v3", json={"city_id": old_id, "layout": lay}).status_code == 200


def test_export_live_result(client):
    src = _v3()
    cid = _load(client, src, "my city.json")
    lay = layout_to_dict(load_layout_from_dict(src))
    r = client.post("/api/export/v3", json={"city_id": cid, "layout": lay})
    assert r.status_code == 200
    assert r.headers["Content-Disposition"] == 'attachment; filename="my city-optimized.json"'
    assert "X-Export-Warnings" not in r.headers
    doc = json.loads(r.data)
    assert _ms(doc["mapBuildings"]) == _ms(src["mapBuildings"])
    assert doc["storedBuildings"] == []
    assert doc["cityData"] == src["cityData"] and doc["player"] == src["player"]


def test_export_with_edits_and_warnings(client):
    src = _v3()
    cid = _load(client, src)
    lay, report = apply_edits(load_layout_from_dict(src), [3],
                              [{"width": 2, "length": 2, "name": "Placeholder"}],
                              catalog=Catalog(_bundled_catalog()))
    body = {**layout_to_dict(lay), "to_store": report["to_store"], "added": report["added"]}
    r = client.post("/api/export/v3", json={"city_id": cid, "layout": body})
    assert r.status_code == 200
    assert r.headers["Content-Disposition"] == f'attachment; filename="{cid}-optimized.json"'
    assert "Placeholder" in json.loads(r.headers["X-Export-Warnings"])[0]
    doc = json.loads(r.data)
    assert [e["metaId"] for e in doc["storedBuildings"]] == ["W_MultiAge_GR25A2"]


def test_export_saved_layout(client):
    src = _v3()
    cid = _load(client, src, "essay.json")
    lay = layout_to_dict(load_layout_from_dict(src))
    lid = client.post("/api/layouts", json={"city_id": cid, "k": 1, "achieved": 1,
                                            "layout_json": lay, "roads_count": 1}).get_json()["id"]
    r = client.get(f"/api/layouts/{lid}/export.v3")
    assert r.status_code == 200
    assert 'filename="essay-optimized.json"' in r.headers["Content-Disposition"]
    assert client.get("/api/layouts/nope/export.v3").status_code == 404


def test_export_errors(client):
    src = _v3()
    cid = _load(client, src)
    assert client.post("/api/export/v3", json={}).status_code == 400
    assert client.post("/api/export/v3", json={"city_id": "nope", "layout": {}}).status_code == 400
    lay = layout_to_dict(load_layout_from_dict(src))
    lay["roads"].append([17, 0, 2])                      # untileable two-lane cell
    r = client.post("/api/export/v3", json={"city_id": cid, "layout": lay})
    assert r.status_code == 400 and "2x2" in r.get_json()["error"]
    assert r.get_json()["reupload"] is False


def test_city_id_ignores_city_key_order_like_a_browser():
    """JSON.parse in a browser enumerates integer-like keys ascending, so the
    old slim caches saw cityData in that order whatever the file's order."""
    src = _v3()
    shuffled = {**src, "cityData": dict(reversed(list(src["cityData"].items())))}
    assert city_id_for(shuffled) == city_id_for(src)
    assert list(_v3_slim(shuffled)["cityData"])[:3] == ["1", "2", "3"]


def test_export_file_name_is_header_safe(client):
    src = _v3()
    cid = _load(client, src, "ma%20cit%C3%A9%22.json")        # 'ma cité".json'
    lay = layout_to_dict(load_layout_from_dict(src))
    r = client.post("/api/export/v3", json={"city_id": cid, "layout": lay})
    assert r.headers["Content-Disposition"] == 'attachment; filename="ma cit-optimized.json"'
