"""Buildings the player keeps off the road: the search packs them like any
building that needs none, and legality exempts them (plan N1 task 5)."""
import pytest

import foeopt.roads_first as rf
from foeopt.legality import check
from foeopt.model import Building, Footprint, Layout, Region

pytest.importorskip("ortools")


def _b(eid, x, y, w, l, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g", Footprint(x, y, w, l),
                    needs, 1, th, None, None, f"b{eid}")


def _city():
    """8x8 region: TH 2x2, two 2x2 houses that need a road; no roads yet."""
    th = _b(1, 0, 0, 2, 2, needs=False, th=True)
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    return Layout(region, [th, _b(10, 4, 0, 2, 2), _b(11, 0, 4, 2, 2)], th, {})


def test_search_keeps_an_off_road_building_off_the_road():
    lay = _city()
    search = rf.RoadsFirstSearch(lay, time_box=10, workers=1, off_road=frozenset({11}))
    assert search.off_road == frozenset({11})
    inner = {b.entity_id: b for b in search.layout.buildings}
    assert inner[11].needs_road is False and inner[10].needs_road is True
    assert search.source_layout is lay
    published = []
    res = search.run(on_improvement=lambda vlay, k, n: published.append(vlay))
    assert res["best_achieved"] is not None and published
    best = published[-1]
    assert check(best, lay, off_road=frozenset({11})).status == "valid"


def test_search_default_leaves_every_building_on_the_road():
    search = rf.RoadsFirstSearch(_city(), time_box=10, workers=1)
    assert search.off_road == frozenset()
    assert all(b.needs_road for b in search.layout.buildings if not b.is_townhall)
