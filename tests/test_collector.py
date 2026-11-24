from foeopt.model import Building, Footprint, Layout, Region
from webapp.collector import LayoutCollector


def _b(eid, x, y, w, l, needs, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


REGION = Region(frozenset((x, y) for x in range(12) for y in range(12)))


def _city(n_roads: int, house_x: int = 6) -> Layout:
    """TH at (0,0); a house at (house_x, 0); a straight road from the TH to the
    house, padded with extra (legal, wasteful) cells so the count is n_roads."""
    th = _b(1, 0, 0, 2, 2, False, th=True)
    house = _b(2, house_x, 0, 2, 2, True)
    roads = {(x, 0): 1 for x in range(2, house_x)}
    y = 1
    while len(roads) < n_roads:
        roads[(2, y)] = 1          # a dead-end spur down from the lane
        y += 1
    return Layout(REGION, [th, house], th, roads)


REF = _city(4)


def _collector(cap=30):
    return LayoutCollector(REF, military="connect", off_road=frozenset(), cap=cap)


def test_illegal_layout_is_refused():
    c = _collector()
    bad = _city(4)
    bad.buildings = [bad.buildings[0]]     # inventory violation: house missing
    assert c.offer(bad, 4, 4) is None
    assert c.entries() == [] and c.count == 0


def test_same_layout_twice_is_stored_once():
    c = _collector()
    e = c.offer(_city(4), 4, 4)
    assert e is not None and e["legality"]["status"] == "valid"
    assert isinstance(e["stats"]["roads"], int)
    assert e["k"] == 4 and e["achieved"] == 4 and "roads" in e and "buildings" in e
    assert c.offer(_city(4), 4, 4) is None
    assert len(c.entries()) == 1 and c.count == 1


def test_cap_keeps_lowest_road_counts():
    c = _collector(cap=2)
    for n, hx in ((5, 7), (3, 5), (4, 6)):          # 5, 3, 4 roads
        assert c.offer(_city(n, house_x=hx), n, n) is not None
    assert [len(e["roads"]) for e in c.entries()] == [3, 4]
    assert c.offer(_city(6, house_x=8), 6, 6) is None
    assert c.offer(_city(4), 4, 4) is None          # duplicate of the kept 4
    assert c.offer(_city(4, house_x=4), 4, 4) is None   # ties the worst: refused
    assert c.count == 3


def test_entries_sorted_by_roads_then_order_found():
    c = _collector()
    c.offer(_city(6), 6, 6)
    c.offer(_city(4), 4, 4)
    c.offer(_city(6, house_x=8), 6, 6)
    es = c.entries()
    assert [len(e["roads"]) for e in es] == [4, 6, 6]
    assert es[1]["id"] < es[2]["id"]
