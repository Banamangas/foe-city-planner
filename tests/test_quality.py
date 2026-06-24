from foeopt.model import Building, Footprint, Layout, Region
from foeopt.quality import (
    filler_road_adjacencies,
    underused_roads,
    quality_report,
    format_quality,
)


def _b(eid, x, y, w=1, l=1, *, needs=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(x, y, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


# --- Rule 1: a building that does not need a road must not touch one --------

def test_rule1_flags_filler_touching_road():
    th = _b(1, 0, 0, th=True)
    filler = _b(2, 2, 0, needs=False)            # at (2,0), borders road (1,0)
    layout = Layout(_region(4, 2), [th, filler], th, {(1, 0): 1})
    assert [b.entity_id for b in filler_road_adjacencies(layout)] == [2]


def test_rule1_ignores_filler_not_touching_road():
    th = _b(1, 0, 0, th=True)
    filler = _b(2, 3, 0, needs=False)            # at (3,0), not adjacent to road (1,0)
    layout = Layout(_region(5, 2), [th, filler], th, {(1, 0): 1})
    assert filler_road_adjacencies(layout) == []


def test_rule1_exempts_townhall_and_consumers():
    th = _b(1, 0, 0, th=True)                     # townhall borders road (1,0)
    consumer = _b(2, 2, 0, needs=True)            # consumer borders road (1,0); allowed
    layout = Layout(_region(3, 2), [th, consumer], th, {(1, 0): 1})
    assert filler_road_adjacencies(layout) == []


# --- Rule 2: every road tile should serve >=2 buildings ---------------------

def test_rule2_two_buildings_ok():
    th = _b(1, 0, 0, th=True)
    house = _b(2, 2, 0, needs=True)
    layout = Layout(_region(3, 1), [th, house], th, {(1, 0): 1})  # (1,0) touches TH + house
    assert underused_roads(layout) == []


def test_rule2_one_building_non_junction_flagged():
    th = _b(1, 0, 0, th=True)
    house = _b(2, 3, 0, needs=True)
    layout = Layout(_region(4, 1), [th, house], th, {(1, 0): 1, (2, 0): 1})
    # (1,0) touches only TH, (2,0) touches only house; each has 1 road-neighbour
    assert underused_roads(layout) == [(1, 0), (2, 0)]


def test_rule2_junction_one_building_three_roads_ok():
    th = _b(1, 0, 0, th=True)
    house = _b(2, 1, 2, needs=True)               # at (1,2)
    roads = {(1, 1): 1, (0, 1): 1, (2, 1): 1, (1, 0): 1}
    layout = Layout(_region(3, 3), [th, house], th, roads)
    # (1,1) has 3 road-neighbours + 1 building (house) -> junction, allowed
    assert (1, 1) not in underused_roads(layout)


def test_rule2_zero_buildings_flagged():
    th = _b(1, 0, 0, th=True)
    layout = Layout(_region(8, 8), [th], th, {(5, 5): 1})  # isolated road, no buildings
    assert underused_roads(layout) == [(5, 5)]


# --- report / format -------------------------------------------------------

def test_quality_report_and_format():
    th = _b(1, 0, 0, th=True)
    filler = _b(2, 2, 0, needs=False)
    layout = Layout(_region(4, 2), [th, filler], th, {(1, 0): 1})
    q = quality_report(layout)
    assert q == {"filler_road_adjacent": 1, "fillers_total": 1,
                 "underused_roads": 0, "roads_total": 1}
    s = format_quality(layout)
    assert "rule 1" in s and "rule 2" in s


def test_quality_handtuned_city_is_clean(city_data, helper_data):
    # The bundled city is an expert layout; it should satisfy both placement
    # rules. This both validates the rules against real play and anchors them.
    from foeopt.build import build_layout
    from foeopt.router import route
    layout = build_layout(city_data, helper_data)
    routed = Layout(layout.region, layout.buildings, layout.townhall, route(layout))
    q = quality_report(routed)
    assert q["filler_road_adjacent"] == 0     # rule 1: no filler touches a road
    assert q["underused_roads"] == 0          # rule 2: every road serves >=2 buildings
