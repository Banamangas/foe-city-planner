"""Sparse synthetic city that exercises the 'finds real savings' path.

The bundled city is dense and already hand-tuned, so `roads`/`improve`/`anneal`
correctly report 0 savings on it (see OPTIMIZER_REVIEW.md §4). This fixture is a
handful of road-needing buildings in a region with ample free space, where every
optimizer path produces a *non-zero* road reduction — a regression anchor for the
savings path, complementing the dense city's "correctly reports no improvement".
"""
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route
from foeopt.localsearch import optimize
from foeopt.anneal import anneal
from foeopt.packer import repack
from foeopt.validate import is_valid


def _b(eid, x, y, w=1, l=1, *, needs=True, th=False, filler=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(x, y, w, l), needs_road=(needs and not filler),
                    road_level=1, is_townhall=th, set_id=None, chain_id=None,
                    name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def sparse_city() -> Layout:
    """10x5 region, 2x2 townhall in the corner, three 1x1 road-needing houses
    placed at the far edge (forcing a long road spur), plus two non-road fillers.
    Roads are the from-scratch minimal for that far placement (10 tiles)."""
    th = _b(1, 0, 0, 2, 2, needs=False, th=True)
    houses = [_b(10, 8, 0), _b(11, 8, 2), _b(12, 8, 4)]
    fillers = [_b(20, 5, 4, filler=True), _b(21, 6, 4, filler=True)]
    reg = _region(10, 5)
    placed = Layout(reg, [th, *houses, *fillers], th, {})
    return Layout(reg, placed.buildings, th, route(placed))


def test_sparse_from_scratch_route_is_minimal():
    city = sparse_city()
    # geometry-only: the far placement needs a 10-tile corridor; deterministic.
    assert len(city.roads) == 10
    assert is_valid(city)


def test_sparse_phase1_prunes_inflated_input():
    city = sparse_city()
    inflated = dict(city.roads)
    for c in [(0, 4), (1, 4), (2, 4)]:   # redundant tiles not needed by any house
        inflated[c] = 1
    bloated = Layout(city.region, city.buildings, city.townhall, inflated)
    pruned = route(bloated)
    assert len(inflated) == 13
    assert len(pruned) == 10            # Phase-1 prunes the 3 redundant tiles
    assert is_valid(Layout(city.region, city.buildings, city.townhall, pruned))


def test_sparse_optimize_finds_savings():
    city = sparse_city()
    res = optimize(city, budget_seconds=5.0)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(city.roads)        # never worse
    assert len(res.layout.roads) == 3                       # 10 -> 3 (deterministic hill-climb)
    assert res.moves_applied > 0 and res.moves_evaluated > 0


def test_sparse_anneal_finds_savings():
    city = sparse_city()
    res = anneal(city, seed=0, budget_seconds=30.0, max_iters=1000)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(city.roads)        # never worse
    assert len(res.layout.roads) == 1                       # 10 -> 1 (seed=0, deterministic)
    assert res.moves_applied > 0 and res.moves_evaluated > 0


def test_sparse_repack_places_all_with_fewer_roads():
    city = sparse_city()
    res = repack(city, budget_seconds=3.0, seed=0)
    assert len(res.unplaced) == 0                           # ample space: nothing stranded
    assert is_valid(res.layout)
    assert 0 < len(res.layout.roads) < len(city.roads)      # denser packing => fewer roads
