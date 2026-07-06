import random

from foeopt.lns import find_corridor
from foeopt.model import Building, Footprint, Layout, Region


def _b(eid, x, y, w, l, *, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def _comb_layout():
    """Deliberately wasteful: four 2x2 consumers in one column at x=4..5,
    served single-loaded by the road column x=3 (y=0..7). TH 2x2 at (0,0),
    roads: (2,0) links TH border to the column."""
    th = _b(1, 0, 0, 2, 2, needs=False, th=True)
    cons = [_b(10 + i, 4, 2 * i, 2, 2) for i in range(4)]
    roads = {(3, y): 1 for y in range(8)} | {(2, 0): 1}
    return Layout(_region(10, 11), [th, *cons], th, roads)


def test_find_corridor_locates_single_loaded_run():
    lay = _comb_layout()
    run, victims = find_corridor(lay, random.Random(0))
    assert set(run) <= set(lay.roads)
    assert len(run) >= 4                       # a real stretch, not one cell
    assert {b.entity_id for b in victims} <= {10, 11, 12, 13}
    assert victims                             # at least one adjacent consumer


def test_find_corridor_none_when_all_double_loaded():
    # road row y=1 double-loaded: consumers above and below every cell
    th = _b(1, 0, 0, 1, 1, needs=False, th=True)
    top = [_b(10 + i, 1 + i, 0, 1, 1) for i in range(4)]
    bot = [_b(20 + i, 1 + i, 2, 1, 1) for i in range(4)]
    roads = {(x, 1): 1 for x in range(5)}      # (0,1) borders the TH
    lay = Layout(_region(6, 3), [th, *top, *bot], th, roads)
    # every road cell has load 2 except (0,1) which is a TH-adjacent connector
    res = find_corridor(lay, random.Random(0), max_buildings=12)
    if res is not None:                        # only the load<=1 connector may qualify
        run, _ = res
        assert set(run) <= {(0, 1)}


def test_find_corridor_caps_victims():
    lay = _comb_layout()
    run, victims = find_corridor(lay, random.Random(0), max_buildings=2)
    assert len(victims) <= 2
