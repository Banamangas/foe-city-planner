import json
from foeopt.loader import read_json, _build_combined


def test_read_json_plain(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text(json.dumps({"a": 1, "b": [2, 3]}), encoding="utf-8")
    assert read_json(str(p)) == {"a": 1, "b": [2, 3]}


def test_read_json_with_bom(tmp_path):
    p = tmp_path / "bom.json"
    # write a UTF-8 BOM followed by JSON
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"x": 5}).encode("utf-8"))
    assert read_json(str(p)) == {"x": 5}


def _area(x, y, w, l):
    return {"x": x, "y": y, "width": w, "length": l}


def test_build_combined_new_schema():
    # 8x8 region; new-style entities with coords/size/needsStreet
    data = {
        "UnlockedAreas": [_area(0, 0, 8, 8)],
        "CityEntities": {},
        "CityMapData": {
            "1": {"id": 1, "entityId": "TH", "type": "main_building",
                  "coords": {"x": 0, "y": 0}, "size": {"width": 2, "length": 2},
                  "needsStreet": 1, "isInInventory": False, "name": "Townhall"},
            "2": {"id": 2, "entityId": "H", "type": "residential",
                  "coords": {"x": 3, "y": 0}, "size": {"width": 2, "length": 2},
                  "needsStreet": 1, "isInInventory": False, "name": "House"},
            "3": {"id": 3, "entityId": "D", "type": "decoration",
                  "coords": {"x": 0, "y": 3}, "size": {"width": 1, "length": 1},
                  "needsStreet": 0, "isInInventory": False, "name": "Deco"},
            "4": {"id": 4, "entityId": "S", "type": "street",
                  "coords": {"x": 2, "y": 0}, "size": {"width": 1, "length": 1},
                  "needsStreet": 1, "isInInventory": False, "name": "Road"},
            "5": {"id": 5, "entityId": "INV", "type": "residential",
                  "coords": {"x": 6, "y": 6}, "size": {"width": 1, "length": 1},
                  "needsStreet": 1, "isInInventory": True, "name": "Stored"},
        },
    }
    layout = _build_combined(data)
    ids = {b.entity_id for b in layout.buildings}
    assert ids == {1, 2, 3}                       # street + inventory excluded
    assert layout.roads == {(2, 0): 1}            # street cell in road set
    assert layout.townhall is not None and layout.townhall.entity_id == 1
    by_id = {b.entity_id: b for b in layout.buildings}
    assert by_id[2].needs_road and by_id[2].road_level == 1   # needsStreet=1
    assert not by_id[3].needs_road                            # needsStreet=0


def test_build_combined_excludes_out_of_region():
    data = {
        "UnlockedAreas": [_area(0, 0, 4, 4)],
        "CityEntities": {},
        "CityMapData": {
            "1": {"id": 1, "entityId": "A", "type": "residential",
                  "coords": {"x": -2, "y": 0}, "size": {"width": 1, "length": 1},
                  "needsStreet": 0, "isInInventory": False, "name": "Off"},
        },
    }
    assert _build_combined(data).buildings == []


def test_build_combined_old_schema_in_combined_file():
    # old-style entities inside a CityMapData (like city.txt): cityentity_id + x/y + connected,
    # size resolved from CityEntities. Road-need = connected AND road-adjacent.
    data = {
        "UnlockedAreas": [_area(0, 0, 5, 1)],
        "CityEntities": {
            "TH": {"id": "TH", "name": "TownHall", "type": "main_building",
                   "width": 1, "length": 1,
                   "requirements": {"street_connection_level": 1}},
            "H": {"id": "H", "name": "House", "type": "residential",
                  "width": 1, "length": 1,
                  "requirements": {"street_connection_level": 1}},
            "S": {"id": "S", "name": "Street", "type": "street",
                  "width": 1, "length": 1,
                  "requirements": {"street_connection_level": 1}},
        },
        "CityMapData": {
            "1": {"id": 1, "cityentity_id": "TH", "type": "main_building",
                  "x": 0, "y": 0, "connected": 1},
            "2": {"id": 2, "cityentity_id": "H", "type": "residential",
                  "x": 2, "y": 0, "connected": 1},
            "3": {"id": 3, "cityentity_id": "S", "type": "street", "x": 1, "y": 0},
        },
    }
    layout = _build_combined(data)
    assert layout.roads == {(1, 0): 1}
    by_id = {b.entity_id: b for b in layout.buildings}
    # house at (2,0) is connected AND borders the road (1,0) -> needs_road True
    assert by_id[2].needs_road
