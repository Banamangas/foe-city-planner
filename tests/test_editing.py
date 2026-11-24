"""Plan E: city edits (remove / add buildings), incl. chain reattachment."""
import pytest

from foeopt.catalog import Catalog
from foeopt.chains import compose, linked_groups
from foeopt.editing import EditError, apply_edits, loose_chain_pieces
from foeopt.legality import chain_links, check
from foeopt.model import Building, Footprint, Layout, Region


def _lp(x0, y0, x1, y1):
    return [{"chainId": "farm", "linkPositions": [
        {"topLeftPoint": {"x": x0, "y": y0}, "bottomRightPoint": {"x": x1, "y": y1}}]}]


CAT = Catalog({
    "TH": {"name": "Town Hall", "width": 2, "length": 2, "type": "main_building"},
    "HOUSE": {"name": "House", "width": 2, "length": 2, "type": "residential",
              "requirements": {"street_connection_level": 1}},
    "DECO": {"name": "Deco", "width": 1, "length": 1, "type": "decoration"},
    "ROAD": {"name": "Road", "width": 1, "length": 1, "type": "street"},
    # chain "farm": main 2x2 (road), patches 1x2, each slot to the right
    "FARM": {"name": "Farm", "width": 2, "length": 2, "type": "residential",
             "requirements": {"street_connection_level": 1}, "abilities": _lp(2, 0, 2, 1)},
    "FIELD": {"name": "Field", "width": 1, "length": 2, "type": "decoration",
              "abilities": _lp(1, 0, 1, 1)},
    "WIDE": {"name": "Wide", "width": 1, "length": 3, "type": "decoration",
             "abilities": _lp(1, 0, 1, 1)},
    "MEADOW": {"name": "Meadow", "width": 1, "length": 2, "type": "decoration",
               "abilities": _lp(1, 0, 1, 1)},
})


def _cat_b(eid, cid, x, y, needs=None):
    w, l = CAT.size(cid)
    req = CAT.street_requirement(cid) > 0
    return Building(eid, cid, CAT.entity_type(cid), Footprint(x, y, w, l),
                    req if needs is None else needs, CAT.required_level(cid),
                    cid == "TH", None, CAT.chain_id(cid), f"{CAT.name(cid)}#{eid}",
                    link_positions=CAT.link_positions(cid))


def _city(farms=((10, 0),), patches=3):
    """20x10 region, TH at (0,0), a level-1 road along y=2 from the TH, one
    farm chain (main + `patches` fields to its right) per entry of `farms`."""
    region = Region(frozenset((x, y) for x in range(20) for y in range(10)))
    th = _cat_b(1, "TH", 0, 0)
    bs = [th, _cat_b(2, "HOUSE", 2, 0), _cat_b(3, "DECO", 5, 0)]
    eid = 10
    for fx, fy in farms:
        bs.append(_cat_b(eid, "FARM", fx, fy))
        for i in range(patches):
            bs.append(_cat_b(eid + 1 + i, "FIELD", fx + 2 + i, fy))
        eid += 10
    roads = {(x, 2): 1 for x in range(20)}
    lay = Layout(region, bs, th, roads)
    assert check(lay, lay).status == "valid"
    return lay


def _pos(lay, eid):
    b = next(b for b in lay.buildings if b.entity_id == eid)
    return b.footprint.x, b.footprint.y


def _ids(lay):
    return {b.entity_id for b in lay.buildings}


# -- plain removal / custom additions -----------------------------------------

def test_remove_keeps_roads_and_positions():
    lay = _city()
    out, rep = apply_edits(lay, [3], [], CAT)
    assert _ids(out) == _ids(lay) - {3}
    assert out.roads == lay.roads
    assert _pos(out, 2) == (2, 0)
    assert [s["entity_id"] for s in rep["to_store"]] == [3]
    assert rep["seed"]["possible"] is True
    assert rep["space"]["removed_cells"] == 1


def test_townhall_cannot_be_removed():
    with pytest.raises(EditError, match="Town Hall"):
        apply_edits(_city(), [1], [], CAT)


def test_unknown_ids_rejected():
    with pytest.raises(EditError) as e:
        apply_edits(_city(), [999], [], CAT)
    assert e.value.detail["unknown_ids"] == [999]
    with pytest.raises(EditError):
        apply_edits(_city(), [], [{"cityentity_id": "NOPE"}], CAT)
    with pytest.raises(EditError):
        apply_edits(_city(), [], [{"cityentity_id": "ROAD"}], CAT)   # streets are not buildings


def test_custom_add_fresh_ids_and_names():
    out, rep = apply_edits(_city(), [], [
        {"width": 3, "length": 2, "needs_road": True, "name": "Wonder"},
        {"width": 1, "length": 1, "count": 2}], CAT)
    new = [b for b in out.buildings if b.entity_id not in _ids(_city())]
    assert len(new) == 3 and len({b.entity_id for b in new}) == 3
    wonder = next(b for b in new if b.name == "Wonder")
    assert (wonder.footprint.width, wonder.footprint.length) == (3, 2)
    assert wonder.needs_road and wonder.road_level == 1
    assert sum(b.name == "Custom 1x1" for b in new) == 2
    assert all(a["placed"] for a in rep["added"])
    assert rep["seed"]["possible"] is True   # greedy placed them in the upload
    assert check(out, out).status == "valid"


def test_custom_add_bad_size():
    with pytest.raises(EditError):
        apply_edits(_city(), [], [{"width": 0, "length": 3}], CAT)


def test_catalog_add_real_size_and_road_need():
    out, rep = apply_edits(_city(), [], [{"cityentity_id": "HOUSE", "count": 2}], CAT)
    new = [b for b in out.buildings if b.cityentity_id == "HOUSE" and b.entity_id != 2]
    assert len(new) == 2
    assert all(b.needs_road and (b.footprint.width, b.footprint.length) == (2, 2) for b in new)
    # placed touching the upload's road, no road change
    assert out.roads == _city().roads
    assert all(b.footprint.border_cells() & set(out.roads) for b in new)
    assert rep["seed"]["possible"] is True and check(out, out).status == "valid"


def test_addition_that_does_not_fit_skips_seed_and_space_overflow():
    out, rep = apply_edits(_city(), [], [{"width": 20, "length": 9}], CAT)
    assert rep["seed"]["possible"] is False and "not" in rep["seed"]["reason"]
    assert rep["added"][0]["placed"] is False
    assert rep["space"]["fits_without_roads"] is True     # 180 free cells
    out, rep = apply_edits(_city(), [], [{"width": 20, "length": 20, "count": 1}], CAT)
    assert rep["space"]["fits_without_roads"] is False and rep["space"]["overflow"] > 0


# -- chains ------------------------------------------------------------------

def test_head_detection_on_synthetic_catalog():
    assert CAT.is_chain_head("FARM") and not CAT.is_chain_head("FIELD")
    assert not CAT.is_chain_head("HOUSE")


def test_remove_middle_patch_reattaches_tail():
    lay = _city()                              # FARM 10 at (10,0); fields 11,12,13 at x=12,13,14
    out, rep = apply_edits(lay, [12], [], CAT)
    assert _pos(out, 13) == (13, 0)            # moved into 12's slot
    assert _pos(out, 11) == (12, 0)            # in front of the removed piece: unchanged
    (r,) = rep["reattached"]
    assert r["ok"] and r["removed"] == 12 and r["moved"] == [13] and r["to"] == 10
    groups = linked_groups(out)
    assert [sorted(b.entity_id for b in g) for g in groups] == [[10, 11, 13]]
    assert len([b for b in compose(out).buildings if b.members]) == 1
    assert rep["seed"]["possible"] is True and check(out, out).status == "valid"


def test_remove_first_patch_shifts_whole_tail():
    out, rep = apply_edits(_city(), [11], [], CAT)
    assert (_pos(out, 12), _pos(out, 13)) == ((12, 0), (13, 0))
    assert rep["reattached"][0]["moved"] == [12, 13]
    assert len(linked_groups(out)[0]) == 3


def test_remove_last_patch_needs_nothing():
    out, rep = apply_edits(_city(), [13], [], CAT)
    assert rep["reattached"] == [] and rep["cascades"] == []
    assert _pos(out, 12) == (13, 0)


def test_remove_main_stores_patches_with_candidates():
    lay = _city(farms=((10, 0), (10, 3)))      # second farm 20 just below the road
    lay.buildings = [b for b in lay.buildings if b.entity_id not in (21, 22, 23)]
    out, rep = apply_edits(lay, [10], [], CAT)
    assert {s["entity_id"] for s in rep["to_store"]} == {10, 11, 12, 13}
    (c,) = rep["cascades"]
    assert c["stored"] == [11, 12, 13]
    assert [x["entity_id"] for x in c["relink_candidates"]] == [20]


def test_remove_main_relinks_patches_to_other_main():
    lay = _city(farms=((10, 0), (10, 3)))
    lay.buildings = [b for b in lay.buildings if b.entity_id not in (21, 22, 23)]
    out, rep = apply_edits(lay, [10], [], CAT, relink={10: 20})
    assert {s["entity_id"] for s in rep["to_store"]} == {10}
    assert rep["reattached"][0]["relinked"] is True
    groups = linked_groups(out)
    assert [sorted(b.entity_id for b in g) for g in groups] == [[11, 12, 13, 20]]
    assert check(out, out).status == "valid"


def test_relink_must_be_same_chain_and_kept():
    with pytest.raises(EditError):
        apply_edits(_city(), [10], [], CAT, relink={10: 2})


def test_add_patch_auto_links_to_single_main_at_chain_end():
    out, rep = apply_edits(_city(), [], [{"cityentity_id": "MEADOW", "count": 2}], CAT)
    new = sorted(b.entity_id for b in out.buildings if b.cityentity_id == "MEADOW")
    assert [a["link_to"] for a in rep["added"]] == [10, 10]
    assert [_pos(out, e) for e in new] == [(15, 0), (16, 0)]
    (g,) = linked_groups(out)
    assert {b.entity_id for b in g} == {10, 11, 12, 13, *new}
    assert rep["seed"]["possible"] is True and check(out, out).status == "valid"


def test_add_patch_needs_link_to_when_several_mains():
    lay = _city(farms=((10, 0), (10, 3)))
    with pytest.raises(EditError) as e:
        apply_edits(lay, [], [{"cityentity_id": "FIELD"}], CAT)
    assert e.value.detail["link_to_required"] is True
    assert {c["entity_id"] for c in e.value.detail["candidates"]} == {10, 20}
    out, rep = apply_edits(lay, [], [{"cityentity_id": "FIELD", "link_to": 20}], CAT)
    assert rep["added"][0]["link_to"] == 20
    with pytest.raises(EditError):
        apply_edits(lay, [], [{"cityentity_id": "FIELD", "link_to": 11}], CAT)  # a patch


def test_add_patch_without_main_is_rejected():
    lay = _city(farms=())
    with pytest.raises(EditError, match="no main building"):
        apply_edits(lay, [], [{"cityentity_id": "FIELD"}], CAT)


def test_add_main_and_patch_together():
    lay = _city(farms=())
    out, rep = apply_edits(lay, [], [{"cityentity_id": "FIELD"}, {"cityentity_id": "FARM"}], CAT)
    farm = next(a for a in rep["added"] if a["cityentity_id"] == "FARM")
    field = next(a for a in rep["added"] if a["cityentity_id"] == "FIELD")
    assert field["link_to"] == farm["entity_id"]
    assert len(linked_groups(out)) == 1
    assert rep["seed"]["possible"] is True and check(out, out).status == "valid"


# -- real data ---------------------------------------------------------------

def test_bundled_catalog_head_patch_split():
    from collections import defaultdict
    from foeopt.loader import _bundled_catalog
    cat = Catalog(_bundled_catalog())
    by = defaultdict(lambda: [0, 0])
    for cid in cat.ids():
        ch = cat.chain_id(cid)
        if ch:
            by[ch][0 if cat.is_chain_head(cid) else 1] += 1
    assert len(by) >= 11
    assert all(h > 0 and p > 0 for h, p in by.values()), dict(by)
    assert cat.is_chain_head("W_MultiAge_CUP22A10")       # road-less upgraded main
    assert not cat.is_chain_head("W_MultiAge_CUP22D1")
    assert cat.is_chain_head("W_MultiAge_FALL25A11") and not cat.is_chain_head("W_MultiAge_FALL25D1")


def test_darkzig_remove_middle_patch_reattaches():
    from tests.conftest import require_data
    from foeopt.loader import city_catalog_defs, load_layout, read_json
    path = require_data("darkzig.json")
    lay = load_layout(str(path))
    cat = Catalog(city_catalog_defs(read_json(str(path))))
    out, rep = apply_edits(lay, [1275], [], cat)       # pirates' hideout, middle patch
    (r,) = rep["reattached"]
    assert r["ok"] and r["to"] == 1269
    sizes = sorted(len(g) for g in linked_groups(out))
    assert sizes == [5, 7, 12]
    assert len(chain_links(out)) == len(chain_links(lay)) - 1
    assert check(out, out).status == "valid"


# -- loose chain pieces --------------------------------------------------------

def _moved(lay, eid, dx, dy):
    from dataclasses import replace
    bs = [replace(b, footprint=Footprint(b.footprint.x + dx, b.footprint.y + dy,
                                         b.footprint.width, b.footprint.length))
          if b.entity_id == eid else b for b in lay.buildings]
    return Layout(lay.region, bs, lay.townhall, lay.roads)


def test_loose_chain_pieces_reports_patch_off_its_slot():
    lay = _moved(_city(), 11, 0, 3)
    assert loose_chain_pieces(lay, CAT) == [11]


def test_loose_chain_pieces_empty_for_linked_chain():
    assert loose_chain_pieces(_city(), CAT) == []


def test_loose_chain_pieces_ignores_chain_without_main():
    lay = _city(farms=())
    bs = lay.buildings + [_cat_b(40, "FIELD", 12, 5)]
    lay = Layout(lay.region, bs, lay.townhall, lay.roads)
    assert loose_chain_pieces(lay, CAT) == []


def test_loose_chain_pieces_needs_a_catalog():
    assert loose_chain_pieces(_moved(_city(), 11, 0, 3), None) == []


# -- relinking loose chain pieces ------------------------------------------------

def test_relink_loose_attaches_piece_at_chain_end():
    lay = _moved(_city(), 13, 0, 5)
    assert loose_chain_pieces(lay, CAT) == [13]
    out, rep = apply_edits(lay, [], catalog=CAT, relink_loose=True)
    assert rep["relinked"] == [{"entity_id": 13, "name": "Field#13", "main": 10,
                              "placed": True}]
    assert rep["relink_failed"] == []
    assert _ids(out) == _ids(lay)                      # entity id kept
    assert _pos(out, 13) == (14, 0)                    # the end of the chain
    assert loose_chain_pieces(out, CAT) == []
    assert len(chain_links(out)) == len(chain_links(_city()))
    assert len(compose(out).buildings) == len(compose(_city()).buildings)
    assert check(out, out).status == "valid"


def test_relink_loose_default_leaves_city_unchanged():
    lay = _moved(_city(), 11, 0, 3)
    out, rep = apply_edits(lay, [], catalog=CAT)
    assert rep["relinked"] == [] and rep["relink_failed"] == []
    assert _pos(out, 11) == (12, 3)
    assert loose_chain_pieces(out, CAT) == [11]


def test_relink_loose_no_free_slot_for_wrong_size():
    lay = _city()
    bs = lay.buildings + [_cat_b(40, "WIDE", 12, 5)]
    lay = Layout(lay.region, bs, lay.townhall, lay.roads)
    out, rep = apply_edits(lay, [], catalog=CAT, relink_loose=True)
    assert rep["relinked"] == []
    assert rep["relink_failed"] == [
        {"entity_id": 40, "name": "Wide#40", "reason": "no_free_slot"}]
    assert _pos(out, 40) == (12, 5)


def test_relink_loose_picks_lowest_main_with_a_free_slot():
    lay = _moved(_city(farms=((10, 0), (10, 3))), 13, 0, 6)
    out, rep = apply_edits(lay, [], catalog=CAT, relink_loose=True)
    assert [r["main"] for r in rep["relinked"]] == [10]
    assert loose_chain_pieces(out, CAT) == []


def test_relink_loose_never_raises_and_reports_not_rigid(monkeypatch):
    import foeopt.editing as ed
    monkeypatch.setattr(ed, "make_composite", lambda bs: None)
    lay = _moved(_city(), 11, 0, 3)
    out, rep = apply_edits(lay, [], catalog=CAT, relink_loose=True)
    assert rep["relink_failed"][0]["reason"] == "not_rigid"
    assert rep["relinked"] == [] and _pos(out, 11) == (12, 3)
