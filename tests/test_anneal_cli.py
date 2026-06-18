from foeopt.build import build_layout
from foeopt.anneal import anneal
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
