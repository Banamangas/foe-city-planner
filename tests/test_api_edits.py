"""Plan E API: /api/catalog, /api/edits/preview, /api/optimize with edits,
per-city edit persistence."""
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app  # noqa: E402


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def _ent(i, cid, x, y, t="residential"):
    return {"id": i, "type": t, "x": x, "y": y, "cityentity_id": cid}


def _payload():
    lp = [{"chainId": "farm", "linkPositions": [
        {"topLeftPoint": {"x": 2}, "bottomRightPoint": {"x": 2, "y": 1}}]}]
    lp1 = [{"chainId": "farm", "linkPositions": [
        {"topLeftPoint": {"x": 1}, "bottomRightPoint": {"x": 1, "y": 1}}]}]
    cmd = {"th": _ent(1, "TH", 0, 0, "main_building"),
           "h": _ent(2, "HOUSE", 2, 0), "d": _ent(3, "DECO", 5, 0, "decoration"),
           "f": _ent(10, "FARM", 7, 0), "p1": _ent(11, "FIELD", 9, 0, "decoration")}
    for x in range(12):
        cmd[f"r{x}"] = _ent(100 + x, "ROAD", x, 2, "street")
    return {
        "CityMapData": cmd,
        "UnlockedAreas": [{"x": 0, "y": 0, "width": 12, "length": 8}],
        "CityEntities": {
            "TH": {"name": "Town Hall", "width": 2, "length": 2, "type": "main_building"},
            "HOUSE": {"name": "House", "width": 2, "length": 2, "type": "residential",
                      "requirements": {"street_connection_level": 1}},
            "DECO": {"name": "Deco", "width": 1, "length": 1, "type": "decoration"},
            "ROAD": {"name": "Road", "width": 1, "length": 1, "type": "street"},
            "FARM": {"name": "Farmhouse", "width": 2, "length": 2, "type": "residential",
                     "requirements": {"street_connection_level": 1}, "abilities": lp},
            "FIELD": {"name": "Farm field", "width": 1, "length": 2, "type": "decoration",
                      "abilities": lp1},
        },
    }


@pytest.fixture()
def city_id(client):
    r = client.post("/api/load", json=_payload())
    assert r.status_code == 200, r.get_json()
    return r.get_json()["city_id"]


@pytest.fixture()
def spy(monkeypatch):
    import webapp.app as app_mod
    calls = []

    def fake_submit(self, layout, **kwargs):
        calls.append((layout, kwargs))
        return "fake-job"
    monkeypatch.setattr(app_mod.JobManager, "submit", fake_submit)
    return calls


def test_load_summary_has_chain_fields(client):
    body = client.post("/api/load", json=_payload()).get_json()
    by = {b["entity_id"]: b for b in body["buildings"]}
    assert by[10]["is_chain_head"] is True and by[10]["chain_id"] == "farm"
    assert by[11]["is_chain_head"] is False
    assert body["edits"] is None
    assert all("id" in b for b in body["map_view"]["buildings"])


def test_catalog_search_city_and_bundled(client, city_id):
    rows = client.get(f"/api/catalog?q=farm&city_id={city_id}").get_json()["results"]
    ids = [r["id"] for r in rows]
    assert "FARM" in ids and "FIELD" in ids
    farm = next(r for r in rows if r["id"] == "FARM")
    assert farm == {"id": "FARM", "name": "Farmhouse", "type": "residential", "width": 2,
                    "length": 2, "needs_road": True, "road_level": 1, "chain_id": "farm",
                    "is_chain_head": True}
    roads = client.get(f"/api/catalog?q=road&city_id={city_id}").get_json()["results"]
    assert "ROAD" not in [r["id"] for r in roads]                   # streets hidden
    big = client.get("/api/catalog?q=a").get_json()["results"]      # bundled catalog only
    assert 0 < len(big) <= 30
    assert all(r["type"] not in ("street", "main_building", "off_grid") for r in big)
    assert client.get("/api/catalog?q=").get_json()["results"] == []
    assert client.get("/api/catalog?q=x&city_id=nope").status_code == 404


def test_unedited_optimize_unchanged(client, city_id, spy):
    r1 = client.post("/api/optimize", json={"city_id": city_id, "time_box": 5})
    r2 = client.post("/api/optimize", json={"city_id": city_id, "time_box": 5,
                                            "edits": {"remove": [], "add": []}})
    assert r1.status_code == r2.status_code == 200
    (l1, k1), (l2, k2) = spy
    assert k1 == k2 and "edit_info" not in k1
    assert set(r1.get_json()) == {"job_id", "options"}
    assert [b.entity_id for b in l1.buildings] == [b.entity_id for b in l2.buildings]


def test_optimize_with_edits(client, city_id, spy):
    edits = {"remove": [3], "add": [{"cityentity_id": "HOUSE", "count": 1},
                                    {"width": 1, "length": 1, "name": "Statue"}]}
    r = client.post("/api/optimize", json={"city_id": city_id, "time_box": 5, "edits": edits})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["edits"] == edits
    rep = body["report"]
    assert [s["entity_id"] for s in rep["to_store"]] == [3]
    assert rep["seed"]["possible"] is True
    (layout, kw), = spy
    ids = {b.entity_id for b in layout.buildings}
    assert 3 not in ids and len(ids) == 5 + 2 - 1
    assert kw["edit_info"]["to_store"][0]["entity_id"] == 3
    assert {a["name"] for a in kw["edit_info"]["added"]} == {"House", "Statue"}
    # the same options as an unedited request
    client.post("/api/optimize", json={"city_id": city_id, "time_box": 5})
    assert {k: v for k, v in kw.items() if k != "edit_info"} == spy[1][1]


def test_optimize_edit_errors(client, city_id, spy):
    def post(edits):
        return client.post("/api/optimize", json={"city_id": city_id, "edits": edits})
    r = post({"remove": [12345]})
    assert r.status_code == 400 and r.get_json()["unknown_ids"] == [12345]
    assert post({"remove": [1]}).status_code == 400                     # Town Hall
    r = post({"add": [{"cityentity_id": "NOPE"}]})
    assert r.status_code == 400 and r.get_json()["unknown_entity"] == "NOPE"
    r = post({"add": [{"width": 20, "length": 20}]})
    assert r.status_code == 400 and "do not fit" in r.get_json()["error"]
    assert r.get_json()["space"]["overflow"] > 0
    assert post("remove everything").status_code == 400
    assert spy == []


def test_add_patch_link_to(client, city_id, spy):
    # one farm: automatic link
    r = client.post("/api/edits/preview", json={
        "city_id": city_id, "edits": {"add": [{"cityentity_id": "FIELD"}]}})
    assert r.status_code == 200
    assert r.get_json()["report"]["added"][0]["link_to"] == 10
    # two farms: link_to required, candidates listed
    r = client.post("/api/edits/preview", json={
        "city_id": city_id, "edits": {"add": [{"cityentity_id": "FARM"},
                                              {"cityentity_id": "FIELD"}]}})
    assert r.status_code == 400
    body = r.get_json()
    assert body["link_to_required"] is True
    assert 10 in {c["entity_id"] for c in body["candidates"]}


def test_preview_reports_chain_reattach(client, city_id):
    # farm 10 + field 11: removing the main stores the field
    r = client.post("/api/edits/preview", json={"city_id": city_id,
                                                "edits": {"remove": [10]}})
    rep = r.get_json()["report"]
    assert {s["entity_id"] for s in rep["to_store"]} == {10, 11}
    assert rep["cascades"][0]["relink_candidates"] == []


def test_edits_persist_with_city(client, city_id):
    edits = {"remove": [3], "add": []}
    assert client.put(f"/api/cities/{city_id}/edits", json=edits).status_code == 200
    assert client.get(f"/api/cities/{city_id}").get_json()["edits"] == edits
    again = client.post("/api/load", json=_payload()).get_json()   # re-upload keeps them
    assert again["edits"] == edits
    assert client.put("/api/cities/nope/edits", json=edits).status_code == 404
