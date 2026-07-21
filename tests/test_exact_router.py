from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.exact_router import exact_route


def _b(eid, x, y, w, l, *, road=False, th=False, level=1):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), road, level, th, None, None, f"b{eid}")


def _layout_single():
    # 1x3 strip: TH at (0,0), one consumer at (0,2); only free cell (0,1)
    # is both the Townhall root AND the consumer's only cover -> exact min = 1.
    region = Region(frozenset({(0, 0), (0, 1), (0, 2)}))
    th = _b(1, 0, 0, 1, 1, th=True)
    c = _b(2, 0, 2, 1, 1, road=True)
    return Layout(region, [th, c], th, {})


def _layout_shared_cover():
    # 3x3: TH at (1,0); consumers at (0,2) and (2,2). Cell (1,2) borders BOTH
    # consumers; it reaches the TH via (1,1). Exact min = 2 ({(1,1),(1,2)}).
    region = Region(frozenset((x, y) for x in range(3) for y in range(3)))
    th = _b(1, 1, 0, 1, 1, th=True)
    c1 = _b(2, 0, 2, 1, 1, road=True)
    c2 = _b(3, 2, 2, 1, 1, road=True)
    return Layout(region, [th, c1, c2], th, {})


def test_exact_single_cover_root_cell():
    res = exact_route(_layout_single(), time_limit=10)
    assert res.status == "OPTIMAL"
    assert res.count == 1
    assert res.roads == {(0, 1): 1}


def test_exact_finds_shared_cover_optimum():
    res = exact_route(_layout_shared_cover(), time_limit=10)
    assert res.status == "OPTIMAL"
    assert res.count == 2                      # the shared-cover optimum, not 4


def test_exact_result_is_valid_and_not_worse_than_route():
    lay = _layout_shared_cover()
    res = exact_route(lay, time_limit=10)
    chk = Layout(lay.region, lay.buildings, lay.townhall, res.roads)
    assert is_valid(chk)                       # covers + connects every consumer
    assert res.count <= len(route(lay))        # exact is never worse than greedy


def test_exact_uncoverable_consumer():
    # consumer at (1,0) has no free border cell (TH occupies (0,0), rest off-grid),
    # but the TH still has a free root (0,1) -> status UNCOVERABLE, not NO_ROOT.
    region = Region(frozenset({(0, 0), (1, 0), (0, 1)}))
    th = _b(1, 0, 0, 1, 1, th=True)
    c = _b(2, 1, 0, 1, 1, road=True)
    res = exact_route(Layout(region, [th, c], th, {}), time_limit=10)
    assert res.status == "UNCOVERABLE"
    assert res.roads is None


def test_exact_post_assigns_max_road_level_to_shared_cell():
    # two consumers of different road_level share the unique cover cell (1,2);
    # its assigned level must be the MAX (2), not last-write or the default 1.
    region = Region(frozenset((x, y) for x in range(3) for y in range(3)))
    th = _b(1, 1, 0, 1, 1, th=True)
    c1 = _b(2, 0, 2, 1, 1, road=True, level=1)
    c2 = _b(3, 2, 2, 1, 1, road=True, level=2)
    res = exact_route(Layout(region, [th, c1, c2], th, {}), time_limit=10)
    assert res.status == "OPTIMAL"
    assert res.roads[(1, 2)] == 2              # shared cover cell -> max(1, 2)
    assert res.roads[(1, 1)] == 1              # connector, adjacent to no consumer
