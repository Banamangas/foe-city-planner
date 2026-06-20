import pytest

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route, free_cells, RouteError, _articulation_points
from foeopt.validate import is_valid, unsatisfied


def _th(x, y, w=1, h=1):
    return Building(1, "TH", "main_building", Footprint(x, y, w, h),
                    needs_road=True, road_level=1, is_townhall=True,
                    set_id=None, chain_id=None, name="Townhall")


def _house(eid, x, y, level=1):
    return Building(eid, "H", "generic_building", Footprint(x, y, 1, 1),
                    needs_road=True, road_level=level, is_townhall=False,
                    set_id=None, chain_id=None, name="House")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_free_cells_excludes_buildings():
    layout = Layout(_region(3, 1), [_th(0, 0), _house(2, 2, 0)], _th(0, 0))
    assert free_cells(layout) == {(1, 0)}


def test_straight_line_minimal():
    # TH at (0,0), house at (4,0). One road at (1,0),(2,0),(3,0) connects:
    # house border includes (3,0); that road must be connected back to TH.
    layout = Layout(_region(5, 1), [_th(0, 0), _house(2, 4, 0)], _th(0, 0))
    roads = route(layout)
    layout.roads = roads
    assert is_valid(layout)
    # optimal: cells (1,0),(2,0),(3,0) -> 3 tiles
    assert len(roads) == 3


def test_shared_corridor_reused():
    # Two houses at (4,0) and (4,1); TH at (0,0) on a 5x2 grid.
    # A single corridor along row 0 plus one tap should serve both cheaply.
    layout = Layout(_region(5, 2),
                    [_th(0, 0), _house(2, 4, 0), _house(3, 4, 1)],
                    _th(0, 0))
    roads = route(layout)
    layout.roads = roads
    assert is_valid(layout)
    # both houses adjacent to (3,0)/(3,1); corridor (1,0),(2,0),(3,0),(3,1) = 4
    assert len(roads) <= 4


def test_level_two_requirement():
    layout = Layout(_region(4, 1), [_th(0, 0), _house(2, 3, 0, level=2)], _th(0, 0))
    roads = route(layout)
    layout.roads = roads
    assert is_valid(layout)
    # the connector adjacent to the house must be level >= 2
    assert any(lvl >= 2 for lvl in roads.values())


def test_unreachable_raises():
    # House walled off: region only has the two footprints, no free cells
    layout = Layout(_region(2, 1), [_th(0, 0), _house(2, 1, 0)], _th(0, 0))
    with pytest.raises(RouteError):
        route(layout)


def test_articulation_midchain_is_cut_vertex():
    # townhall root borders (0,0); chain (0,0)-(1,0)-(2,0). Removing (1,0)
    # disconnects (2,0) from the root -> (1,0) is an articulation point.
    roads = {(0, 0): 1, (1, 0): 1, (2, 0): 1}
    th_border = {(0, 0)}      # a road at (0,0) is the rooted entry
    art = _articulation_points(roads, th_border)
    assert (1, 0) in art
    assert (2, 0) not in art   # leaf, not a cut vertex
    assert (0, 0) in art       # removing it disconnects (1,0),(2,0)


def test_articulation_leaf_not_cut():
    # star-ish: (0,0) root, (1,0) hub, (2,0) and (1,1) leaves off the hub
    roads = {(0, 0): 1, (1, 0): 1, (2, 0): 1, (1, 1): 1}
    art = _articulation_points(roads, {(0, 0)})
    assert (2, 0) not in art and (1, 1) not in art   # leaves
    assert (1, 0) in art                              # hub is a cut vertex


def test_articulation_cycle_no_cut():
    # a 2x2 loop of roads, all rooted via (0,0) and (1,0).
    # With two TH-border entries, the virtual root has 2 children, and
    # the cycle means no single road removal disconnects any road from the TH.
    roads = {(0, 0): 1, (1, 0): 1, (0, 1): 1, (1, 1): 1}
    art = _articulation_points(roads, {(0, 0), (1, 0)})
    assert art == set()


def test_articulation_empty():
    assert _articulation_points({}, set()) == set()
    assert _articulation_points({(0, 0): 1}, {(0, 0)}) == set()


def test_prune_real_city_output_is_valid(city_data, helper_data):
    from foeopt.build import build_layout
    from foeopt.validate import unsatisfied
    from foeopt.model import Layout
    layout = build_layout(city_data, helper_data)
    roads = route(layout)
    probe = Layout(layout.region, layout.buildings, layout.townhall, roads)
    assert unsatisfied(probe) == []        # every consumer connected & covered
    assert len(roads) == 142               # golden count preserved
