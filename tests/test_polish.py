from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import repack
from foeopt.polish import polish
from foeopt.validate import is_valid


def _sparse_city():
    th = Building(1, "c1", "t", Footprint(0, 0, 2, 2), False, 0, True, None, None, "TH")
    cons = [Building(10 + i, f"r{i}", "t", Footprint(0, 0, 2, 2), True, 1, False, None, None, f"r{i}")
            for i in range(4)]
    fill = [Building(20 + i, f"f{i}", "t", Footprint(0, 0, 1, 1), False, 0, False, None, None, f"f{i}")
            for i in range(4)]
    region = Region(frozenset({(x, y) for x in range(20) for y in range(20)}))
    return Layout(region, [th, *cons, *fill], th)


def test_polish_valid_and_places_all():
    L = _sparse_city()
    res = polish(L, repack_budget=0.3, anneal_budget=0.5, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(L.buildings)   # conservation


def test_polish_never_worse_than_repack():
    L = _sparse_city()
    base = repack(L, budget_seconds=0.3, seed=0)
    res = polish(L, repack_budget=0.3, anneal_budget=0.5, seed=0)
    # sparse city -> repack reaches the minimal tree; anneal can only match it
    assert len(res.layout.roads) <= len(base.layout.roads)


def test_polish_preserves_unplaced():
    L = _sparse_city()
    base = repack(L, budget_seconds=0.3, seed=0)
    res = polish(L, repack_budget=0.3, anneal_budget=0.3, seed=0)
    assert len(res.unplaced) == len(base.unplaced)
