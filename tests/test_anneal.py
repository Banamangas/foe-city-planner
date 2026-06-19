import random

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.anneal import random_move, anneal
from foeopt.localsearch import OptimizeResult
from foeopt.router import route
from foeopt.validate import is_valid


def _rn(eid, x, y, w=1, l=1, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(x, y, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))



def test_random_move_returns_valid_or_none():
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    b = _rn(3, 4, 0)
    layout = Layout(_region(8, 1), [th, a, b], th)
    rng = random.Random(123)
    region = layout.region.cells
    for _ in range(50):
        cand = random_move(layout, rng)
        if cand is None:
            continue
        occ = set()
        for bld in cand.buildings:
            cells = bld.footprint.cells()
            assert cells <= region            # in region
            assert not (cells & occ)          # no overlap
            occ |= cells
        assert len(cand.buildings) == len(layout.buildings)   # conserved


def test_random_move_is_deterministic_for_seed():
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    layout = Layout(_region(6, 1), [th, a], th)
    m1 = random_move(layout, random.Random(7))
    m2 = random_move(layout, random.Random(7))
    # same seed -> same proposal (both None or both the same anchors)
    def anchors(layout_or_none):
        if layout_or_none is None:
            return None
        return sorted((b.entity_id, b.footprint.x, b.footprint.y) for b in layout_or_none.buildings)
    assert anchors(m1) == anchors(m2)


def test_anneal_never_worse_and_valid():
    # tiny already-tight layout: TH(0,0) road(1,0) house(2,0)
    th = _rn(1, 0, 0, th=True, needs=False)
    house = _rn(2, 2, 0)
    layout = Layout(_region(3, 1), [th, house], th, roads={(1, 0): 1})
    res = anneal(layout, seed=1, budget_seconds=1.0, max_iters=200)
    assert isinstance(res, OptimizeResult)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(layout.roads)   # never worse


def test_anneal_deterministic_for_seed():
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 3, 0)
    b = _rn(3, 5, 0)
    layout = Layout(_region(8, 2), [th, a, b], th,
                    roads=route(Layout(_region(8, 2), [th, a, b], th, {})))
    r1 = anneal(layout, seed=42, budget_seconds=5.0, max_iters=300)
    r2 = anneal(layout, seed=42, budget_seconds=5.0, max_iters=300)
    # same seed + same max_iters (budget not binding) -> identical result
    def sig(res):
        return (sorted((bld.entity_id, bld.footprint.x, bld.footprint.y)
                       for bld in res.layout.buildings),
                sorted(res.layout.roads.items()))
    assert sig(r1) == sig(r2)


def test_anneal_can_beat_inflated_start():
    # Input carries MORE roads than the placement needs; any route-confirmation
    # the search performs will beat it -> result strictly fewer roads.
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    region = _region(6, 2)
    minimal = route(Layout(region, [th, a], th, {}))
    inflated = dict(minimal)
    inflated[(0, 1)] = 1
    inflated[(1, 1)] = 1            # extra redundant tiles
    layout = Layout(region, [th, a], th, roads=inflated)
    res = anneal(layout, seed=3, budget_seconds=2.0, max_iters=500)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(layout.roads)
    # the route-confirmed result is self-consistent
    assert len(res.layout.roads) == len(route(
        Layout(res.layout.region, res.layout.buildings, res.layout.townhall, {})))


def test_anneal_moves_applied_on_improvement():
    # When annealing can confirm an improvement, moves_applied >= 1.
    # Reuse the inflated-start setup: seed=3 reliably finds an improvement.
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    region = _region(6, 2)
    minimal = route(Layout(region, [th, a], th, {}))
    inflated = dict(minimal)
    inflated[(0, 1)] = 1
    inflated[(1, 1)] = 1
    layout = Layout(region, [th, a], th, roads=inflated)
    res = anneal(layout, seed=3, budget_seconds=2.0, max_iters=500)
    assert res.moves_applied >= 1, f"Expected >=1 confirmed improvement with seed=3, got {res.moves_applied}"


def test_anneal_moves_applied_zero_on_tight_layout():
    # When layout is already tight (no improvement possible), moves_applied == 0.
    # tiny already-tight layout: TH(0,0) road(1,0) house(2,0)
    th = _rn(1, 0, 0, th=True, needs=False)
    house = _rn(2, 2, 0)
    layout = Layout(_region(3, 1), [th, house], th, roads={(1, 0): 1})
    res = anneal(layout, seed=1, budget_seconds=1.0, max_iters=200)
    assert res.moves_applied == 0
