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


# ---------------------------------------------------------------- hint / workers (S2)

def _force_hint(monkeypatch):
    """CpSolver that may only return the hinted assignment: a solve that
    succeeds proves the hint is a COMPLETE feasible solution."""
    from ortools.sat.python import cp_model

    class Fixed(cp_model.CpSolver):
        def Solve(self, model, *a, **kw):
            self.parameters.fix_variables_to_their_hinted_value = True
            return super().Solve(model, *a, **kw)

    monkeypatch.setattr(cp_model, "CpSolver", Fixed)


_DETOUR = {(1, 1), (0, 1), (2, 1)}   # legal, connected, covers both -- but 3 > 2


def test_hint_is_a_complete_feasible_solution(monkeypatch):
    _force_hint(monkeypatch)
    res = exact_route(_layout_shared_cover(), time_limit=10, hint=_DETOUR)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert set(res.roads) == _DETOUR and res.count == 3


def test_hinted_multiworker_solve_beats_the_hint_and_stays_valid():
    lay = _layout_shared_cover()
    res = exact_route(lay, time_limit=10, hint=_DETOUR, workers=4)
    assert res.status == "OPTIMAL" and res.count == 2 <= len(_DETOUR)
    assert is_valid(Layout(lay.region, lay.buildings, lay.townhall, res.roads))


def test_hint_from_greedy_route_is_complete_on_a_larger_grid(monkeypatch):
    """A 9x9 city with several consumers: route()'s own network, hinted, is
    accepted as-is (fixed-hint solve), and the free solve never exceeds it."""
    region = Region(frozenset((x, y) for x in range(9) for y in range(9)))
    th = _b(1, 3, 0, 3, 2, th=True)
    cons = [_b(10 + i, x, y, 2, 2, road=True)
            for i, (x, y) in enumerate([(0, 3), (3, 3), (6, 3), (0, 6), (4, 6), (7, 7)])]
    lay = Layout(region, [th, *cons], th, {})
    greedy = route(lay)
    free = exact_route(lay, time_limit=10, hint=set(greedy), workers=2)
    assert free.optimal and free.count <= len(greedy)
    _force_hint(monkeypatch)
    fixed = exact_route(lay, time_limit=10, hint=set(greedy))
    assert fixed.status in ("OPTIMAL", "FEASIBLE") and set(fixed.roads) == set(greedy)


def test_stale_hint_is_ignored():
    # (1, 0) is the Townhall -- not a free cell -> the hint is dropped, not fatal
    res = exact_route(_layout_shared_cover(), time_limit=10, hint={(1, 0), (1, 1)})
    assert res.status == "OPTIMAL" and res.count == 2
