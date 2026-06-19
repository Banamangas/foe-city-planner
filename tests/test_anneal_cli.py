import pathlib

from foeopt.anneal import anneal
from foeopt.build import build_layout
from foeopt.loader import load_layout
from foeopt.validate import is_valid


def test_anneal_real_city_valid_and_not_worse(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    res = anneal(current, seed=0, budget_seconds=2.0, max_iters=500)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(current.roads)     # never worse
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    assert len(res.layout.buildings) == len(current.buildings)


def test_anneal_darkzig_valid_and_not_worse():
    repo = pathlib.Path(__file__).resolve().parent.parent
    current = load_layout(str(repo / "darkzig.json"))
    res = anneal(current, seed=0, budget_seconds=3.0, max_iters=10_000)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(current.roads)   # never worse than the player's 250
    # buildings conserved, non-overlapping, in-region
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    assert len(res.layout.buildings) == len(current.buildings)
