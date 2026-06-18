from foeopt.model import Building, Footprint, Layout, Region
from foeopt.localsearch import move_building, swap_buildings


def _b(eid, x, y, w, l, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(x, y, w, l), needs_road=False, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_move_building_to_free_spot():
    a = _b(1, 0, 0, 1, 1)
    layout = Layout(_region(4, 1), [a], None)
    moved = move_building(layout, 1, 3, 0)
    assert moved is not None
    assert moved.buildings[0].footprint == Footprint(3, 0, 1, 1)
    assert moved.roads == {}


def test_move_building_onto_other_is_none():
    a = _b(1, 0, 0, 1, 1)
    b = _b(2, 2, 0, 1, 1)
    layout = Layout(_region(4, 1), [a, b], None)
    assert move_building(layout, 1, 2, 0) is None      # would overlap b


def test_move_building_out_of_region_is_none():
    a = _b(1, 0, 0, 1, 1)
    layout = Layout(_region(2, 1), [a], None)
    assert move_building(layout, 1, 5, 0) is None      # leaves region


def test_swap_same_size_exchanges_anchors():
    a = _b(1, 0, 0, 1, 1)
    b = _b(2, 3, 0, 1, 1)
    layout = Layout(_region(4, 1), [a, b], None)
    swapped = swap_buildings(layout, 1, 2)
    assert swapped is not None
    pos = {bld.entity_id: (bld.footprint.x, bld.footprint.y) for bld in swapped.buildings}
    assert pos == {1: (3, 0), 2: (0, 0)}


def test_swap_updates_townhall_reference():
    th = _b(1, 0, 0, 1, 1, th=True)
    b = _b(2, 3, 0, 1, 1)
    layout = Layout(_region(4, 1), [th, b], th)
    swapped = swap_buildings(layout, 1, 2)
    assert swapped.townhall is not None
    assert (swapped.townhall.footprint.x, swapped.townhall.footprint.y) == (3, 0)
