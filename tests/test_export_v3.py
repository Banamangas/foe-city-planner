"""Plan X: export a result as a v3 city file (Forge Hammer planner format)."""
import copy
import json
import os
from collections import Counter
from dataclasses import replace

import pytest

from foeopt.catalog import Catalog
from foeopt.editing import apply_edits
from foeopt.export_v3 import ExportError, can_export, plan_as_city, tile_two_lane, to_v3
from foeopt.legality import chain_links, check
from foeopt.loader import _bundled_catalog, load_layout_from_dict, read_json
from foeopt.model import Footprint

ROOT = os.path.join(os.path.dirname(__file__), "..")
OFF_GRID = {"off_grid", "outpost_ship", "friends_tavern", "hub_main", "hub_part"}


def _mirror(city: dict) -> list[dict]:
    """mapBuildings as the uploads write them: cityData order, zeros omitted."""
    out = []
    for e in city.values():
        if e["type"] in OFF_GRID:
            continue
        m = {"metaId": e["cityentity_id"]}
        if e.get("x"):
            m["x"] = e["x"]
        if e.get("y"):
            m["y"] = e["y"]
        out.append({**m, "era": e["era"], "custom": False})
    return out


def _v3():
    """20x14 region, TH (0,0) 6x7. Street row y=7: level 1 at x 0-3 and 12-15,
    two-lane 2x2 tiles at x 4-11 (y 7-8, touching the TH). A military building
    below the tiles needs the two-lane road."""
    ents = [
        {"id": 1, "cityentity_id": "H_ProgressiveEra_Townhall", "type": "main_building",
         "era": "ProgressiveEra"},
        {"id": 2, "cityentity_id": "W_MultiAge_WILD21A8b", "type": "residential",
         "x": 6, "y": 3, "era": "IronAge", "level": 3},
        {"id": 3, "cityentity_id": "W_MultiAge_GR25A2", "type": "production",
         "x": 12, "y": 4, "era": "BronzeAge"},
        {"id": 4, "cityentity_id": "M_ArcticFuture_Military2", "type": "military",
         "x": 6, "y": 9, "era": "ArcticFuture"},
        {"id": 5, "cityentity_id": "D_HighMiddleAge_Gargoyle", "type": "decoration",
         "x": 19, "y": 13, "era": "HighMiddleAge"},
        {"id": 6, "cityentity_id": "Z_Unknown_Ship", "type": "outpost_ship", "x": 500, "y": 500,
         "era": "X"},
    ]
    nid = 100
    for x in list(range(0, 4)) + list(range(12, 16)):
        ents.append({"id": nid, "cityentity_id": "S_BronzeAge_Street", "type": "street",
                     "x": x, "y": 7, "era": "BronzeAge"})
        nid += 1
    for x in (4, 6, 8, 10):
        ents.append({"id": nid, "cityentity_id": "S_ProgressiveEra_CarStreet1", "type": "street",
                     "x": x, "y": 7, "era": "ProgressiveEra"})
        nid += 1
    city = {str(e["id"]): e for e in ents}
    return {"version": 3, "player": {"id": 7, "name": "someone"}, "region": "fr",
            "cityData": city,
            "mapData": [{"width": 16, "length": 14}, {"x": 16, "width": 4, "length": 14}],
            "currentEra": "ProgressiveEra",
            "mapBuildings": _mirror(city),
            "storedBuildings": [{"metaId": "D_HighMiddleAge_Gargoyle", "x": 0, "y": 0,
                                 "era": "HighMiddleAge", "custom": True}],
            "deletedBuildings": [], "camX": -1.5, "camY": 2.5, "zoomScale": 0.4,
            "rotated": False}


def _ms(entries):
    return Counter(json.dumps(e, sort_keys=True) for e in entries)


def _moved(layout, eid, x, y):
    layout.buildings = [replace(b, footprint=Footprint(x, y, b.footprint.width,
                                                       b.footprint.length))
                        if b.entity_id == eid else b for b in layout.buildings]
    return layout


def test_fixture_is_a_legal_city():
    lay = load_layout_from_dict(_v3())
    assert check(lay, lay).status == "valid"
    assert sum(1 for lvl in lay.roads.values() if lvl == 2) == 16


def test_unedited_export_reproduces_the_plan_and_keeps_every_other_field():
    src = _v3()
    keep = copy.deepcopy(src)
    out = to_v3(src, load_layout_from_dict(src))
    assert src == keep                                    # input not mutated
    assert _ms(out["mapBuildings"]) == _ms(src["mapBuildings"])
    assert out["storedBuildings"] == []                   # replaced, not merged
    for k in src:
        if k not in ("mapBuildings", "storedBuildings"):
            assert out[k] == src[k], k
    assert list(out) == list(src)                         # same keys, same order


def test_entries_keep_city_era_custom_false_and_omit_zero_coords():
    src = _v3()
    lay = _moved(load_layout_from_dict(src), 5, 0, 13)
    out = to_v3(src, lay)
    garg = [e for e in out["mapBuildings"] if e["metaId"] == "D_HighMiddleAge_Gargoyle"]
    assert garg == [{"metaId": "D_HighMiddleAge_Gargoyle", "y": 13, "era": "HighMiddleAge",
                     "custom": False}]
    th = [e for e in out["mapBuildings"] if e["metaId"] == "H_ProgressiveEra_Townhall"]
    assert th == [{"metaId": "H_ProgressiveEra_Townhall", "era": "ProgressiveEra",
                   "custom": False}]
    assert all(list(e)[0] == "metaId" and list(e)[-2:] == ["era", "custom"]
               for e in out["mapBuildings"])
    assert not any(e["metaId"] == "Z_Unknown_Ship" for e in out["mapBuildings"])


def test_two_lane_cells_become_one_2x2_street_per_tile():
    src = _v3()
    out = to_v3(src, load_layout_from_dict(src))
    car = [e for e in out["mapBuildings"] if "CarStreet" in e["metaId"]]
    assert sorted((e["x"], e["y"]) for e in car) == [(4, 7), (6, 7), (8, 7), (10, 7)]
    lane1 = [e for e in out["mapBuildings"] if e["metaId"] == "S_BronzeAge_Street"]
    assert len(lane1) == 8


def test_new_roads_use_the_citys_street_of_that_level():
    src = _v3()
    # Result as a published dict: roads moved one row down, a new 2x2 tile.
    lay = load_layout_from_dict(src)
    res = {"buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                            b.footprint.width, b.footprint.length]
                         for b in lay.buildings},
           "roads": [[x, 7, 1] for x in range(4)] + [[17, 0, 1]]
           + [[x, y, 2] for x in range(4, 10) for y in (7, 8)] + [[x, y, 2] for x in (16, 17)
                                                                for y in (10, 11)]}
    out = to_v3(src, res)
    streets = {(e.get("x", 0), e.get("y", 0)): (e["metaId"], e["era"])
               for e in out["mapBuildings"] if e["metaId"].startswith("S_")}
    assert streets[(17, 0)] == ("S_BronzeAge_Street", "BronzeAge")
    assert streets[(16, 10)] == ("S_ProgressiveEra_CarStreet1", "ProgressiveEra")
    assert sorted(k for k, v in streets.items() if "Car" in v[0]) == \
        [(4, 7), (6, 7), (8, 7), (16, 10)]
    assert len(streets) == 5 + 4


def test_untileable_two_lane_cells_are_an_error():
    src = _v3()
    lay = load_layout_from_dict(src)
    lay.roads[(16, 0)] = 2                       # a lone two-lane cell
    with pytest.raises(ExportError, match="cannot be split into 2x2"):
        to_v3(src, lay)
    assert tile_two_lane({(0, 0), (1, 0), (0, 1), (1, 1), (2, 0)}) == ([(0, 0)], [(2, 0)])


def test_a_city_without_two_lane_streets_gets_the_catalog_one_of_its_age():
    src = _v3()
    for k in [k for k, e in src["cityData"].items() if "CarStreet" in e["cityentity_id"]]:
        del src["cityData"][k]
    lay = load_layout_from_dict(src)
    lay.roads.update({(x, y): 2 for x in (16, 17) for y in (0, 1)})
    out = to_v3(src, lay)
    car = [e for e in out["mapBuildings"] if "CarStreet" in e["metaId"]]
    # No S_BronzeAge_CarStreet* exists, so the currentEra one.
    assert car == [{"metaId": "S_ProgressiveEra_CarStreet1", "x": 16, "era": "ProgressiveEra",
                    "custom": False}]


def test_stored_and_added_buildings():
    src = _v3()
    lay, report = apply_edits(load_layout_from_dict(src), [3],
                              [{"cityentity_id": "D_HighMiddleAge_Gargoyle", "count": 1},
                               {"width": 2, "length": 2, "name": "Placeholder"}],
                              catalog=Catalog(_bundled_catalog()))
    warnings = []
    out = to_v3(src, lay, report["to_store"], report["added"], warnings=warnings)
    assert out["storedBuildings"] == [{"metaId": "W_MultiAge_GR25A2", "x": 12, "y": 4,
                                       "era": "BronzeAge", "custom": False}]
    assert not any(e["metaId"] == "W_MultiAge_GR25A2" for e in out["mapBuildings"])
    new = [e for e in out["mapBuildings"] if e["custom"]]
    assert len(new) == 1 and new[0]["metaId"] == "D_HighMiddleAge_Gargoyle"
    assert new[0]["era"] == "ProgressiveEra"             # currentEra
    assert len(warnings) == 1 and "Placeholder" in warnings[0]


def test_slim_cache_and_foreign_layouts_are_refused():
    src = _v3()
    slim = {"version": 3, "cityData": src["cityData"], "mapData": src["mapData"]}
    assert not can_export(slim)
    with pytest.raises(ExportError, match="re-upload"):
        to_v3(slim, load_layout_from_dict(src))
    lay = load_layout_from_dict(src)
    lay.buildings = [b for b in lay.buildings if b.entity_id != 2]
    with pytest.raises(ExportError, match="neither in the layout"):
        to_v3(src, lay)
    res = {"roads": [], "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y, 1, 1]
                                      for b in load_layout_from_dict(src).buildings}}
    res["buildings"]["999"] = [0, 0, 1, 1]
    with pytest.raises(ExportError, match="not in the city"):
        to_v3(src, res)


def _round_trip(src, layout, to_store=(), added=()):
    """Export, then load the export's plan as a city: same buildings at the
    same places, same road cells and levels, legal, same chain-link count."""
    out = to_v3(src, layout, to_store, added)
    back = load_layout_from_dict(plan_as_city(out))
    added_ids = {a["entity_id"] for a in added}
    pos = Counter((b.cityentity_id, b.footprint.x, b.footprint.y) for b in layout.buildings)
    assert Counter((b.cityentity_id, b.footprint.x, b.footprint.y)
                   for b in back.buildings) == pos
    assert back.roads == layout.roads
    assert check(back, back).status == "valid"
    assert len(chain_links(back)) == len(chain_links(layout))
    assert sum(e["custom"] for e in out["mapBuildings"]) == len(added_ids)
    return out


def test_round_trip_fixture():
    src = _v3()
    _round_trip(src, load_layout_from_dict(src))


REAL = ["essay", "vini", "sinj"]


def _real(name):
    path = os.path.join(ROOT, "cities", f"{name}.json")
    if not os.path.exists(path):
        pytest.skip(f"cities/{name}.json not present (player export, gitignored)")
    return read_json(path)


@pytest.mark.parametrize("name", REAL)
def test_real_city_unedited_export_equals_its_plan(name):
    src = _real(name)
    lay = load_layout_from_dict(src)
    out = _round_trip(src, lay)
    assert _ms(out["mapBuildings"]) == _ms(src["mapBuildings"])


@pytest.mark.parametrize("name", REAL)
def test_real_city_edited_round_trip(name):
    """Remove two buildings, add one: stored = exactly the removed ones."""
    src = _real(name)
    cat = Catalog(_bundled_catalog())
    lay0 = load_layout_from_dict(src)
    plain = [b for b in lay0.buildings if not b.is_townhall and not b.chain_id][:2]
    lay, report = apply_edits(lay0, [b.entity_id for b in plain],
                              [{"cityentity_id": "D_HighMiddleAge_Gargoyle", "count": 1}],
                              catalog=cat)
    out = _round_trip(src, lay, report["to_store"], report["added"])
    assert Counter(e["metaId"] for e in out["storedBuildings"]) == \
        Counter(b.cityentity_id for b in plain)
    assert all(e["custom"] is False for e in out["storedBuildings"])
