from foeopt.editing import apply_edits
from foeopt.model import Building, Footprint, Layout, Region


def _b(eid, w, l, needs=False, th=False):
    return Building(eid, f"c{eid}", "t", Footprint(0, 0, w, l), needs, 1 if needs else 0,
                    th, None, None, f"b{eid}")


def _layout():
    th = _b(1, 2, 2, th=True)
    return Layout(Region(frozenset({(0, 0), (1, 0)})), [th, _b(2, 3, 3), _b(3, 4, 4, needs=True)], th)


def test_apply_edits_removes_building():
    out = apply_edits(_layout(), {2}, [])
    ids = {b.entity_id for b in out.buildings}
    assert ids == {1, 3}                       # building 2 removed
    assert out.region == _layout().region      # region preserved
    assert out.townhall.entity_id == 1


def test_apply_edits_never_removes_townhall():
    out = apply_edits(_layout(), {1}, [])       # try to remove townhall
    assert any(b.is_townhall for b in out.buildings)


def test_apply_edits_adds_building():
    out = apply_edits(_layout(), set(), [{"width": 5, "length": 6, "needs_road": True, "name": "Wonder"}])
    added = [b for b in out.buildings if b.name == "Wonder"]
    assert len(added) == 1
    a = added[0]
    assert a.entity_id not in {1, 2, 3}         # fresh unique id
    assert (a.footprint.width, a.footprint.length) == (5, 6)
    assert a.needs_road is True and a.road_level == 1 and a.is_townhall is False


def test_apply_edits_default_name_and_unique_ids():
    out = apply_edits(_layout(), set(),
                      [{"width": 1, "length": 1, "needs_road": False, "name": None},
                       {"width": 2, "length": 2, "needs_road": False, "name": None}])
    new = [b for b in out.buildings if b.entity_id not in {1, 2, 3}]
    assert len(new) == 2
    assert len({b.entity_id for b in new}) == 2     # unique
    assert new[0].name == "Custom 1x1"
    assert new[0].road_level == 0


def test_apply_edits_rejects_bad_size():
    import pytest
    with pytest.raises(ValueError):
        apply_edits(_layout(), set(), [{"width": 0, "length": 3, "needs_road": False, "name": None}])
