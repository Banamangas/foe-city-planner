"""Two-lane buildings: a 2x2 tile touching the TH, chosen by the position model."""
import pytest

import foeopt.roads_first as rf
from foeopt.legality import check
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern, lane_tiles_of, minimize_needed, probe, validate
from foeopt.router import RouteError, route

pytest.importorskip("ortools")


def _b(eid, x, y, w, l, needs=True, level=1, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g", Footprint(x, y, w, l),
                    needs, level, th, None, None, f"b{eid}")


def _city():
    """14x10 region, TH 4x4 at (0,3), a skeleton row along y=7 from the TH,
    one level-2 3x3 building and two ordinary 2x2 consumers."""
    region = frozenset((x, y) for x in range(14) for y in range(10))
    th = _b(1, 0, 3, 4, 4, needs=False, th=True)
    mil = _b(2, 0, 0, 3, 3, level=2)
    c1, c2 = _b(3, 0, 0, 2, 2), _b(4, 0, 0, 2, 2)
    lay = Layout(Region(region), [th, mil, c1, c2], th, {})
    roads = frozenset((x, 7) for x in range(0, 12))
    return lay, Pattern(th=th.footprint, roads=roads, params={})


def test_position_probe_places_a_tile_and_validate_keeps_it_two_lane():
    lay, pat = _city()
    region = set(lay.region.cells)
    st, pos = probe(pat, region, lay.road_needing(), probe_limit=10, model="position")
    assert st == "SAT"
    tiles = lane_tiles_of(pos)
    assert len(tiles) == 1
    vst, out, n = validate(lay, pat, pos)
    assert vst == "OK", vst
    rep = check(out, lay)
    assert rep.status == "valid", rep.violations
    tx, ty = tiles[0]
    assert all(out.roads[(tx + dx, ty + dy)] == 2 for dx in (0, 1) for dy in (0, 1))


def test_objective_model_also_keeps_the_tile():
    lay, pat = _city()
    region = set(lay.region.cells)
    st, pos = probe(pat, region, lay.road_needing(), probe_limit=10, model="position")
    opos = minimize_needed(pat, region, lay.road_needing(), pos, limit=10, model="position")
    assert opos is not None and len(lane_tiles_of(opos)) == 1
    vst, out, _ = validate(lay, pat, opos)
    assert vst == "OK" and check(out, lay).status == "valid"


def test_without_a_tile_validate_refuses_instead_of_faking_one():
    lay, pat = _city()
    pos = {2: (5, 4, 3, 3), 3: (0, 8, 2, 2), 4: (2, 8, 2, 2)}  # no lane2 entry
    vst, _, _ = validate(lay, pat, pos)
    assert vst == "ROUTE_FAIL"


def test_route_never_prunes_fixed_tiles_and_requires_one_for_level2():
    lay, _ = _city()
    th, mil = lay.buildings[0], lay.buildings[1]
    mil.footprint = Footprint(6, 3, 3, 3)
    lay2 = Layout(lay.region, [th, mil], th, {})
    tile = {(4, 4): 2, (5, 4): 2, (4, 5): 2, (5, 5): 2}
    roads = route(lay2, fixed=tile)
    assert all(roads[c] == 2 for c in tile)
    with pytest.raises(RouteError):
        route(lay2, fixed={})


def test_search_rejects_item_model_with_a_two_lane_building():
    lay, _ = _city()
    with pytest.raises(ValueError):
        rf.RoadsFirstSearch(lay, time_box=5, workers=1, probe_model="item")
    s = rf.RoadsFirstSearch(lay, time_box=5, workers=1, probe_model="item",
                            military="unconnected")
    assert not any(b.road_level >= 2 and b.needs_road for b in s.layout.buildings)


def test_exact_route_keeps_fixed_tiles():
    from foeopt.exact_router import exact_route
    lay, _ = _city()
    th, mil = lay.buildings[0], lay.buildings[1]
    mil.footprint = Footprint(6, 3, 3, 3)
    lay2 = Layout(lay.region, [th, mil], th, {})
    tile = {(4, 4): 2, (5, 4): 2, (4, 5): 2, (5, 5): 2}
    res = exact_route(lay2, time_limit=10, fixed=tile)
    assert res.optimal and res.count == 4 and all(res.roads[c] == 2 for c in tile)
    lay2.roads = res.roads
    assert check(lay2, lay2).status == "valid"
