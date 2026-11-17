"""N6: skeleton-mutation climb as an end-of-run phase (foeopt/mutation_polish.py)."""
import time
from types import SimpleNamespace

import pytest

import foeopt.roads_first as rf
from foeopt.legality import check
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.mutation_polish import plan_starts, polish_mutation
from foeopt.roads_first import Pattern

pytest.importorskip("ortools")


def _b(eid, w, l, needs=True, th=False, x=0, y=0):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


# A 7x3 strip, TH at (0,1), one 1x1 consumer. The incumbent serves it at the
# end of a 4-cell road; one road cell next to the TH is enough.
LONG = {(1, 1), (2, 1), (3, 1), (4, 1)}


def _city(roads=LONG, at=(5, 1)):
    region = frozenset((x, y) for x in range(7) for y in range(3))
    th = _b(1, 1, 1, needs=False, th=True, x=0, y=1)
    src = Layout(Region(region), [th, _b(10, 1, 1, x=5, y=1)], th, {})
    inc = Layout(src.region, [th, _b(10, 1, 1, x=at[0], y=at[1])], th,
                 {c: 1 for c in roads})
    return src, inc


def _search(src, probe_limit=1000.0):
    # probe_limit 1000: a cold batch never fits, so only the warm half runs
    return SimpleNamespace(layout=src, source_layout=src, exact_repair=0.0,
                           road_witness=True, military="connect", closure="bfs",
                           fillers_in_model=False, workers=2, probe_workers=1,
                           probe_limit=probe_limit, objective_limit=5.0)


def _no_pool():
    raise AssertionError("cold half must not start")


def test_fixture_incumbent_is_legal():
    src, inc = _city()
    assert check(inc, src).status == "valid" and len(inc.roads) == 4


def test_climb_improves_the_incumbent_and_publishes_only_legal_strict_gains():
    src, inc = _city()
    seen = []
    rep = polish_mutation(_search(src), inc, 4, time.monotonic() + 20,
                          on_improvement=lambda lay, k, n: seen.append((lay, n)),
                          pool_factory=_no_pool)
    assert rep["after"] < 4 and rep["cold_batches"] == 0
    assert seen and [n for _, n in seen] == sorted({n for _, n in seen}, reverse=True)
    assert seen[-1][1] == rep["after"]
    for lay, n in seen:
        assert check(lay, src).status == "valid" and len(lay.roads) == n
        dims = {b.entity_id: (b.footprint.width, b.footprint.length) for b in lay.buildings}
        assert dims == {b.entity_id: (b.footprint.width, b.footprint.length)
                        for b in src.buildings}   # nothing rotated


def test_never_publishes_when_the_incumbent_is_already_optimal():
    src, inc = _city(roads={(1, 1)}, at=(2, 1))
    seen = []
    rep = polish_mutation(_search(src), inc, 1, time.monotonic() + 8,
                          on_improvement=lambda *x: seen.append(x), pool_factory=_no_pool)
    assert rep["after"] == 1 and seen == []


def test_no_time_no_generation():
    src, inc = _city()
    rep = polish_mutation(_search(src), inc, 4, time.monotonic() + 1.0, pool_factory=_no_pool)
    assert rep["after"] == 4 and rep["starts"][0]["generations"] == 0 and rep["evals"] == 0


def test_stop_flag_ends_the_phase():
    src, inc = _city()
    rep = polish_mutation(_search(src), inc, 4, time.monotonic() + 30,
                          should_stop=lambda: True, pool_factory=_no_pool)
    assert rep["starts"] == [] and rep["after"] == 4


class _InlinePool:
    """multiprocessing.Pool stand-in: runs the production worker in-process."""

    def __init__(self, search):
        rf._worker_init(search.layout, search.probe_limit, 1, False, None, False, None,
                        0.0, search.objective_limit, "position", True, False)
        self.calls = 0

    def map(self, fn, xs):
        self.calls += 1
        return [fn(x) for x in xs]

    def terminate(self):
        pass

    def join(self):
        pass


def test_cold_half_runs_the_production_probe_when_a_probe_fits():
    src, inc = _city()
    s = _search(src, probe_limit=3.0)
    pools = []
    rep = polish_mutation(s, inc, 4, time.monotonic() + 15,
                          pool_factory=lambda: pools.append(_InlinePool(s)) or pools[-1])
    assert len(pools) == 1 and pools[0].calls == rep["cold_batches"] >= 1
    assert rep["after"] < 4


def test_plan_starts_incumbent_first_then_distinct_skeletons_by_roads():
    src, inc = _city()
    th = inc.townhall.footprint
    p1 = Pattern(th, frozenset(LONG | {(4, 0)}), {})
    p2 = Pattern(th, frozenset(LONG | {(4, 2)}), {})
    solved = [(6, "b", p2), (5, "a", p1), (5, "dup", p1), (4, inc, p1)]
    plan = plan_starts(inc, 4, solved, 3)
    assert [(a, lay) for a, lay, _ in plan] == [(4, inc), (5, "a"), (6, "b")]
    assert plan[0][2] == frozenset(inc.roads) and plan[1][2] == p1.roads
    assert len(plan_starts(inc, 4, solved, 1)) == 1


def _wired_run(monkeypatch, **kw):
    """RoadsFirstSearch.run with the walk and every polish faked; returns the
    phase order, each phase's end, and the result."""
    import foeopt.incumbent_polish as ip
    import foeopt.mutation_polish as mp
    src, inc = _city()
    pat = Pattern(th=inc.townhall.footprint, roads=frozenset(LONG), params={})
    order, ends = [], {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **k2):
        if k == 4:
            if getattr(params, "sat_recorder", None):
                params.sat_recorder(k, 4, pat, {})
            k2["on_improvement"](inc, k, 4)
            return ("FEASIBLE", 4)
        return ("INFEASIBLE", None)

    def fake_obj(self, cands, best, on_imp, end, should_stop=None):
        order.append("objective")
        ends["objective"] = end
        return {"before": best, "after": best}

    def fake_rebase(search, lay, ach, end, *a, **k2):
        order.append("rebase")
        ends["rebase"] = end
        return {"before": ach, "after": ach}

    def fake_mut(search, lay, ach, end, solved, *a, **k2):
        order.append("mutation")
        ends["mutation"] = end
        return {"before": ach, "after": ach, "starts_arg": k2["starts"]}

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    monkeypatch.setattr(rf.RoadsFirstSearch, "_apply_objective_polish", fake_obj)
    monkeypatch.setattr(ip, "polish_rebased", fake_rebase)
    monkeypatch.setattr(mp, "polish_mutation", fake_mut)
    t0 = time.monotonic()
    res = rf.RoadsFirstSearch(src, time_box=100, workers=1, k_start=4,
                              objective_polish=0.3, rebase_s=10, **kw).run()
    return order, {k: v - t0 for k, v in ends.items()}, res


def test_search_runs_mutation_last_until_the_deadline(monkeypatch):
    order, ends, res = _wired_run(monkeypatch, mutation_polish=True, mutation_starts=2)
    assert order == ["objective", "rebase", "mutation"]
    # leftover only: the polish window is untouched and the climb ends at the box
    assert ends["rebase"] == pytest.approx(100, abs=0.5)
    assert ends["mutation"] == pytest.approx(100, abs=0.5)
    assert res["mutation_polish"]["starts_arg"] == 2


def test_reserve_moves_the_polish_window_earlier_without_shrinking_it(monkeypatch):
    _, base, _ = _wired_run(monkeypatch, mutation_polish=True)
    _, ends, _ = _wired_run(monkeypatch, mutation_polish=True, mutation_reserve=20)
    assert ends["mutation"] == pytest.approx(100, abs=0.5)
    assert ends["mutation"] - ends["rebase"] == pytest.approx(20, abs=0.5)
    assert base["objective"] - ends["objective"] == pytest.approx(20, abs=0.5)


def test_off_by_default_and_reserve_needs_the_switch(monkeypatch):
    order, ends, res = _wired_run(monkeypatch, mutation_reserve=50)
    assert order == ["objective", "rebase"] and res["mutation_polish"] is None
    assert ends["rebase"] == pytest.approx(100, abs=0.5)   # no reserve taken
