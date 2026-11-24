from dataclasses import replace
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.stats import city_stats


def _b(eid, x, y, w, l, needs, level=1, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, level, th, None, None, f"b{eid}")


def _city(roads=True, level=1):
    region = Region(frozenset((x, y) for x in range(10) for y in range(10)))
    th = _b(1, 0, 0, 2, 2, False, th=True)
    house = _b(2, 5, 0, 2, 3, True, level)
    deco = _b(3, 0, 6, 4, 4, False)
    r = {(2, 0): 2, (3, 0): 2, (4, 0): 2} if roads else {}
    return Layout(region, [th, house, deco], th, r)


def test_stats_connected_city():
    s = city_stats(_city())
    occupied = 4 + 6 + 16
    assert s["area"] == 100 and s["roads"] == 3
    assert s["road_efficiency_pct"] == round(100 * (2 * 1 / 2) / 3, 1)
    assert s["free_cells"] == 100 - occupied - 3
    assert s["with_roads"] == 1 and s["without_roads"] == 1
    assert s["unconnected"] == []
    assert s["buildings_pct"] == 26.0 and s["roads_pct"] == 3.0 and s["free_pct"] == 71.0


def test_stats_no_roads():
    s = city_stats(_city(roads=False))
    assert s["roads"] == 0 and s["road_efficiency_pct"] is None
    assert s["unconnected"] == [2]


def test_stats_two_lane_counts_double():
    s = city_stats(_city(level=2))
    assert s["unconnected"] == []
    assert s["road_efficiency_pct"] == round(100 * (2 * 2 / 2) / 3, 1)


def test_stats_reference_supplies_player_road_needs():
    """Published layouts rewrite needs_road=False for off-road buildings; with
    the player's city as reference the building still counts as needing a road
    (and, without contact, as unconnected)."""
    ref = _city(roads=False)
    lay = _city(roads=False)
    lay.buildings = [replace(b, needs_road=False) if b.entity_id == 2 else b
                     for b in lay.buildings]
    assert city_stats(lay)["unconnected"] == []
    s = city_stats(lay, reference=ref)
    assert s["unconnected"] == [2]
    assert s["without_roads"] == 1 and s["with_roads"] == 1
