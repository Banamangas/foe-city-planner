from foeopt.build import build_layout
from foeopt.localsearch import optimize
from foeopt.validate import is_valid


def test_optimize_real_city_valid_and_not_worse(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    res = optimize(current, budget_seconds=2.0)   # small budget keeps the test fast
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(current.roads)   # never worse
    # buildings are conserved and non-overlapping / in-region
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    assert len(res.layout.buildings) == len(current.buildings)


def test_resolve_budget_precedence():
    from foeopt.cli import _resolve_budget
    assert _resolve_budget(None, False) == 30.0      # default
    assert _resolve_budget(None, True) == 120.0      # --thorough
    assert _resolve_budget(600.0, False) == 600.0    # explicit --budget overrides default
    assert _resolve_budget(600.0, True) == 600.0     # explicit --budget overrides --thorough
