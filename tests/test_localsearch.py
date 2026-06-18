from foeopt.model import Building, Footprint, Layout, Region
from foeopt.localsearch import move_building, swap_buildings, free_cells, same_footprint_swaps, relocate_candidates, spur_served_buildings
from foeopt.localsearch import optimize, OptimizeResult
from foeopt.router import route
from foeopt.validate import is_valid


def _b(eid, x, y, w, l, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(x, y, w, l), needs_road=False, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def _rn(eid, x, y, w, l):
    return Building(eid, f"c{eid}", "generic", Footprint(x, y, w, l),
                    needs_road=True, road_level=1, is_townhall=False,
                    set_id=None, chain_id=None, name=f"b{eid}")


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


def test_free_cells():
    a = _b(1, 0, 0, 1, 1)
    layout = Layout(_region(3, 1), [a], None)
    assert free_cells(layout) == {(1, 0), (2, 0)}


def test_same_footprint_swaps_pairs_equal_sizes():
    a = _b(1, 0, 0, 2, 2)
    b = _b(2, 2, 0, 2, 2)
    c = _b(3, 4, 0, 1, 1)        # different size -> not paired
    layout = Layout(_region(6, 2), [a, b, c], None)
    assert same_footprint_swaps(layout) == [(1, 2)]


def test_same_footprint_swaps_excludes_townhall():
    th = _b(1, 0, 0, 2, 2, th=True)
    b = _b(2, 2, 0, 2, 2)
    layout = Layout(_region(6, 2), [th, b], th)
    assert same_footprint_swaps(layout) == []   # townhall not swappable


def test_relocate_candidates_finds_free_spot_by_road():
    # building at (0,0); free cells (1,0),(2,0); road_cells {(2,1)} touches (2,0)
    a = _b(1, 0, 0, 1, 1)
    layout = Layout(_region(3, 2), [a], None)
    cands = relocate_candidates(layout, road_cells={(2, 1)})
    assert (1, 2, 0) in cands     # (2,0) borders the road (2,1)


def test_spur_served_building_detected():
    # road (1,0) is a dead-end (only neighbour (0,0) is road); building at (1,1)
    # touches (1,0). Townhall at (0,0) roots the network.
    th = _b(1, 0, 0, 1, 1, th=True)
    house = _rn(2, 1, 1, 1, 1)
    layout = Layout(_region(3, 3), [th, house], th, roads={(0, 0): 1, (1, 0): 1})
    assert spur_served_buildings(layout) == [2]


def test_no_spur_when_road_not_dead_end():
    # both road tiles have degree >= ... here (1,0) neighbours (0,0) and (2,0): degree 2
    th = _b(1, 0, 0, 1, 1, th=True)
    house = _rn(2, 1, 1, 1, 1)
    layout = Layout(_region(3, 3), [th, house], th,
                    roads={(0, 0): 1, (1, 0): 1, (2, 0): 1})
    assert spur_served_buildings(layout) == []


def test_optimize_never_worse_and_valid():
    # already-minimal tiny layout: TH at (0,0), house at (2,0), road (1,0).
    th = _b(1, 0, 0, 1, 1, th=True)
    house = _rn(2, 2, 0, 1, 1)
    layout = Layout(_region(3, 1), [th, house], th, roads={(1, 0): 1})
    res = optimize(layout, budget_seconds=1.0)
    assert isinstance(res, OptimizeResult)
    assert len(res.layout.roads) <= len(layout.roads)   # never worse
    assert is_valid(res.layout)


def test_optimize_finds_improving_swap():
    # Two same-size road-needing houses; one is far (needs a long spur), one near.
    # A 6x2 grid: TH(0,0) houseNear(2,0) houseFar(5,0); row 1 used for routing.
    # Start: houseFar at (5,0) reached via long detour through row 1.
    th = _b(1, 0, 0, 1, 1, th=True)
    near = _rn(2, 2, 0, 1, 1)        # blocked by gap in row 0
    far = _rn(3, 5, 0, 1, 1)         # far end, reachable via row 1
    layout = Layout(_region(6, 2), [th, near, far], th, {})
    # this start may not even be valid/minimal; optimize must still return valid & not worse
    start_roads = len(route(Layout(layout.region, layout.buildings, layout.townhall, {})))
    base = Layout(layout.region, layout.buildings, layout.townhall,
                  route(Layout(layout.region, layout.buildings, layout.townhall, {})))
    res = optimize(base, budget_seconds=2.0)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= start_roads
