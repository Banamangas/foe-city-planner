from foeopt.model import Building, Footprint, Layout, Region
from foeopt.report import road_diff, stats


def _th(x, y):
    return Building(1, "TH", "main_building", Footprint(x, y, 1, 1),
                    True, 1, True, None, None, "Townhall")


def _house(eid, x, y):
    return Building(eid, "H", "generic_building", Footprint(x, y, 1, 1),
                    True, 1, False, None, None, "House")


def test_road_diff():
    current = {(1, 0): 1, (2, 0): 1, (5, 5): 1}
    optimized = {(1, 0): 1, (2, 0): 2, (3, 0): 1}
    diff = road_diff(current, optimized)
    assert {"x": 5, "y": 5, "level": 1} in diff["remove"]
    assert {"x": 3, "y": 0, "level": 1} in diff["add"]
    # level change at (2,0) counts as an add (re-place at new level)
    assert {"x": 2, "y": 0, "level": 2} in diff["add"]


def test_stats():
    region = Region(frozenset((x, 0) for x in range(5)))
    layout = Layout(region, [_th(0, 0), _house(2, 2, 0)], _th(0, 0),
                    roads={(1, 0): 1, (2, 0): 1, (3, 0): 1})
    opt = {(1, 0): 1, (2, 0): 1, (3, 0): 1}
    s = stats(layout, opt)
    assert s["current_roads"] == 3
    assert s["optimized_roads"] == 3
    assert s["tiles_saved"] == 0
    assert s["road_needing"] == 1
    assert s["satisfied"] == 1
    assert s["unsatisfied"] == 0
