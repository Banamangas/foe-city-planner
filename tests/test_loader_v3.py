"""FoE Helper v3 city exports: `cityData` + `mapData`, no catalog, no `connected`."""
import json
import os

import pytest

from foeopt.catalog import Catalog
from foeopt.legality import check
from foeopt.loader import (_bundled_catalog, is_v3, load_layout,
                           load_layout_from_dict, read_json)

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _city():
    """A 20x14 region (two areas, one with x omitted as FoE does for 0).
    TH at (0,0) 6x7; a street run along y=7; buildings above/below it."""
    ents = [
        {"id": 1, "cityentity_id": "H_ProgressiveEra_Townhall", "type": "main_building"},
        # needs a road (components-style requirement), touches the street
        {"id": 2, "cityentity_id": "W_MultiAge_WILD21A8b", "type": "generic_building", "x": 6, "y": 3},
        # catalog: no road requirement, although it touches the street
        {"id": 3, "cityentity_id": "W_MultiAge_GR25A2", "type": "generic_building", "x": 12, "y": 4},
        # needs a road (old-style requirement) but the player left it unconnected
        {"id": 4, "cityentity_id": "X_EarlyMiddleAge_Landmark2", "type": "greatbuilding", "x": 14, "y": 0},
        # decoration, no requirement
        {"id": 5, "cityentity_id": "D_HighMiddleAge_Gargoyle", "type": "decoration", "x": 19, "y": 13},
        # off-grid entity with an id no catalog knows: ignored, never an error
        {"id": 6, "cityentity_id": "Z_Unknown_Ship", "type": "outpost_ship", "x": 500, "y": 500},
    ]
    ents += [{"id": 100 + x, "cityentity_id": "S_BronzeAge_Street", "type": "street",
              "x": x, "y": 7} for x in range(0, 16)]
    return {"version": 3, "region": "fr",
            "cityData": {str(e["id"]): e for e in ents},
            "mapData": [{"width": 16, "length": 14},            # x and y omitted = 0
                        {"x": 16, "width": 4, "length": 14}]}


def test_detects_v3():
    assert is_v3(_city())
    assert not is_v3({"CityMapData": {}, "UnlockedAreas": []})


def test_region_streets_and_buildings():
    lay = load_layout_from_dict(_city())
    assert len(lay.region.cells) == 20 * 14
    assert lay.townhall.footprint.cells() == {(x, y) for x in range(6) for y in range(7)}
    assert set(lay.roads) == {(x, 7) for x in range(16)}
    assert {b.entity_id for b in lay.buildings} == {1, 2, 3, 4, 5}   # ship dropped


def test_needs_road_from_catalog_and_upload():
    by_id = {b.entity_id: b for b in load_layout_from_dict(_city()).buildings}
    assert by_id[2].needs_road and by_id[2].road_level == 1
    assert not by_id[3].needs_road     # catalog: no requirement
    assert not by_id[4].needs_road     # requirement, but unconnected in the upload
    assert not by_id[5].needs_road


def test_upload_is_legal():
    lay = load_layout_from_dict(_city())
    assert check(lay, lay, military="connect").status == "valid"


def test_two_lane_requirement_in_components_block():
    cat = Catalog({"A": {"components": {"AllAge": {"streetConnectionRequirement":
                                                    {"requiredLevel": 2}}}},
                   "B": {"requirements": {"street_connection_level": 2}},
                   "C": {}})
    assert (cat.street_requirement("A"), cat.required_level("A")) == (2, 2)
    assert (cat.street_requirement("B"), cat.required_level("B")) == (2, 2)
    assert (cat.street_requirement("C"), cat.required_level("C")) == (0, 1)


def test_unknown_building_type_is_a_clear_error():
    data = _city()
    data["cityData"]["7"] = {"id": 7, "cityentity_id": "W_NotInCatalog", "type": "generic_building",
                             "x": 8, "y": 9}
    with pytest.raises(ValueError, match="W_NotInCatalog"):
        load_layout_from_dict(data)


def test_helper_export_extends_the_catalog(tmp_path):
    data = _city()
    data["cityData"]["7"] = {"id": 7, "cityentity_id": "W_NotInCatalog", "type": "generic_building",
                             "x": 8, "y": 8}
    helper = {"CityEntities": {"W_NotInCatalog": {"width": 2, "length": 2,
                                                  "requirements": {"street_connection_level": 1}}}}
    city_p, helper_p = tmp_path / "c.json", tmp_path / "h.json"
    city_p.write_text(json.dumps(data))
    helper_p.write_text(json.dumps(helper))
    b = {b.entity_id: b for b in load_layout(str(city_p), str(helper_p)).buildings}[7]
    assert b.needs_road and (b.footprint.width, b.footprint.length) == (2, 2)


def test_bundled_catalog_has_the_fields_the_loader_reads():
    cat = Catalog(_bundled_catalog())
    assert cat.size("H_ProgressiveEra_Townhall") == (6, 7)
    assert cat.provided_level("S_ArcticFuture_CarStreet1") == 2
    assert cat.street_requirement("M_FutureEra_Military4") == 2
    assert any(cat.chain_id(cid) for cid in _bundled_catalog())


@pytest.mark.parametrize("name", ["darkzig.json", "CityMap-Born-FR16-2026-07-07.json"])
def test_v3_matches_combined_loader(name):
    """The same city as a CityMap export and as v3 gives the same layout."""
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} not present")
    d = read_json(path)
    v3 = {"version": 3,
          "cityData": {k: {kk: vv for kk, vv in e.items() if kk not in ("connected", "state")}
                       for k, e in d["CityMapData"].items()},
          "mapData": d["UnlockedAreas"]}
    a, b = load_layout(path), load_layout_from_dict(v3)
    assert a.region == b.region and a.roads == b.roads

    def sig(lay):
        return {x.entity_id: (x.footprint, x.needs_road, x.road_level, x.chain_id,
                              x.link_positions) for x in lay.buildings}
    assert sig(a) == sig(b)


def test_webapp_loads_a_v3_upload(tmp_path):
    from webapp.app import create_app
    client = create_app(db_path=str(tmp_path / "c.db")).test_client()
    r = client.post("/api/load", json=_city())
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    r2 = client.get(f"/api/cities/{body['city_id']}")
    assert r2.status_code == 200


def test_chain_declared_in_components_block():
    """Newer definitions put the chain in components.<age>.chain (e.g. the
    Gentiana windmill, Breezemill); the ability-only reader missed them."""
    cat = Catalog({"W": {"components": {"AllAge": {"chain": {
        "chainId": "gentiana_windmill",
        "linkPositions": [{"topLeftPoint": {"x": 5}, "bottomRightPoint": {"x": 6, "y": 5}}]}}}}})
    assert cat.chain_id("W") == "gentiana_windmill"
    assert cat.link_positions("W") == ((5, 0, 6, 5),)
    bundled = Catalog(_bundled_catalog())
    assert bundled.chain_id("W_MultiAge_FALL25A11") == "fall25a_chain"
    assert bundled.chain_id("W_MultiAge_CUP22D1") == "gentiana_windmill"
