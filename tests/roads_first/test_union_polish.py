"""Q2 step 2: union polish -- re-solve on the union of networks sharing the TH."""
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

import foeopt.roads_first as rf
from foeopt.legality import check
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern
from foeopt.union_polish import plan_unions, polish_union, union_pattern

pytest.importorskip("ortools")


def _b(eid, w, l, needs=True, th=False, x=0, y=0):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


# TH at (2,2). Two consumer slots: S1 (5,1) and S2 (1,5).
# Network A serves S1 in 3 cells and S2 by a 4-cell detour (7 roads);
# network B serves S2 in 3 cells and S1 by a 5-cell detour (8 roads).
# Their union serves both with A's short arm + B's short arm (<= 6).
A = {(3, 2), (4, 2), (5, 2), (3, 3), (3, 4), (3, 5), (2, 5)}
B = {(2, 3), (2, 4), (1, 4), (2, 1), (2, 0), (3, 0), (4, 0), (5, 0)}
S1, S2 = (5, 1), (1, 5)


def _city():
    region = frozenset({(2, 2)} | A | B | {S1, S2})
    th = _b(1, 1, 1, needs=False, th=True, x=2, y=2)
    cons = [_b(10, 1, 1, x=S1[0], y=S1[1]), _b(11, 1, 1, x=S2[0], y=S2[1])]
    src = Layout(Region(region), [th, *cons], th, {})
    a = Layout(src.region, list(src.buildings), th, {c: 1 for c in A})
    b = Layout(src.region, list(src.buildings), th, {c: 1 for c in B})
    return src, a, b


def _search(src):
    return SimpleNamespace(layout=src, source_layout=src, exact_repair=0.0,
                           road_witness=True, military="connect",
                           fillers_in_model=False, workers=1, probe_workers=2,
                           union_m=3)


def test_members_are_legal_and_union_has_both_networks():
    src, a, b = _city()
    assert check(a, src).status == "valid" and check(b, src).status == "valid"
    pat = union_pattern([a, b])
    assert set(pat.roads) == A | B and pat.th == a.townhall.footprint


def test_union_rejects_different_townhalls():
    src, a, b = _city()
    th2 = replace(b.townhall, footprint=Footprint(0, 0, 1, 1))
    moved = Layout(b.region, b.buildings, th2, dict(b.roads))
    with pytest.raises(ValueError):
        union_pattern([a, moved])


def test_union_beats_both_members_and_is_legal():
    src, a, b = _city()
    seen = []
    rep = polish_union(_search(src), a, 7, time.monotonic() + 30, [(8, b, None)],
                       on_improvement=lambda lay, k, n: seen.append((lay, n)))
    assert rep["planned"] == 1 and len(rep["tried"]) == 1
    row = rep["tried"][0]
    assert row["union_cells"] == len(A | B) and row["new_cells"] == len(B)
    assert row["legality"] == "valid"
    assert rep["after"] < 7 and seen and seen[-1][1] == rep["after"]
    assert check(seen[-1][0], src).status == "valid"


def test_never_publishes_a_worse_or_equal_layout():
    src, a, b = _city()
    seen = []
    rep = polish_union(_search(src), a, 2, time.monotonic() + 30, [(8, b, None)],
                       on_improvement=lambda *x: seen.append(x))
    assert rep["after"] == 2 and seen == []


def test_no_time_no_solve():
    src, a, b = _city()
    rep = polish_union(_search(src), a, 7, time.monotonic() + 1.0, [(8, b, None)])
    assert rep["tried"] == [] and rep["after"] == 7


def test_plan_unions_groups_by_th_dedupes_and_keeps_a_known_skeleton():
    src, a, b = _city()
    skel = Pattern(th=a.townhall.footprint, roads=frozenset(A | {(4, 0)}), params={})
    # the incumbent appears twice (once without, once with its skeleton)
    plans = plan_unions([(7, a, None), (7, a, skel), (8, b, None)], a, m=3)
    kinds = [p["kind"] for p in plans]
    assert kinds == ["top2", "inc+skeleton"]      # inc+1 == top2: deduped
    assert plans[1]["extra"] == skel.roads
    th2 = replace(b.townhall, footprint=Footprint(0, 0, 1, 1))
    other = Layout(b.region, b.buildings, th2, dict(b.roads))
    assert plan_unions([(7, a, None), (8, other, None)], a) == []   # no shared TH


def test_search_runs_union_between_objective_and_rebased_polish(monkeypatch):
    import foeopt.incumbent_polish as ip
    import foeopt.union_polish as up
    src, a, _ = _city()
    pat = Pattern(th=a.townhall.footprint, roads=frozenset(A), params={})
    order, ends = [], {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        if k == 7:
            if getattr(params, "sat_recorder", None):
                params.sat_recorder(k, 7, pat, {})
            kw["on_improvement"](a, k, 7)
            return ("FEASIBLE", 7)
        return ("INFEASIBLE", None)

    def fake_obj(self, cands, best, on_imp, end, should_stop=None):
        order.append("objective")
        ends["objective"] = end
        return {"before": best, "after": best}

    def fake_union(search, inc, ach, end, members, *a, **k):
        order.append("union")
        ends["union"] = end
        return {"before": ach, "after": ach}

    def fake_rebase(search, inc, ach, end, *a, **k):
        order.append("rebase")
        ends["rebase"] = end
        return {"before": ach, "after": ach}

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    monkeypatch.setattr(rf.RoadsFirstSearch, "_apply_objective_polish", fake_obj)
    monkeypatch.setattr(up, "polish_union", fake_union)
    monkeypatch.setattr(ip, "polish_rebased", fake_rebase)
    res = rf.RoadsFirstSearch(src, time_box=100, workers=1, k_start=7,
                              objective_polish=0.4, rebase_s=10, union_polish=15).run()
    assert order == ["objective", "union", "rebase"]
    assert ends["union"] - ends["objective"] == pytest.approx(15, abs=0.5)
    assert ends["rebase"] - ends["union"] == pytest.approx(10, abs=0.5)
    assert res["union_polish"] == {"before": 7, "after": 7}

    order.clear()
    res = rf.RoadsFirstSearch(src, time_box=100, workers=1, k_start=7,
                              objective_polish=0.4, rebase_s=10).run()
    assert order == ["objective", "rebase"] and res["union_polish"] is None


def test_objective_polish_records_solved_networks():
    region = set((x, y) for x in range(12) for y in range(5))
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    cons = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(2)]
    lay = Layout(Region(frozenset(region)), [th, *cons], th, {})
    pat = Pattern(th=th.footprint, roads=frozenset((x, 2) for x in range(2, 12)), params={})
    far = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1)}
    s = rf.RoadsFirstSearch(lay, time_box=30, workers=1, probe_workers=1,
                            objective_polish=0.5, closure="flow")
    info = s._apply_objective_polish([(11, 10, pat, far)], 11, None, time.monotonic() + 15)
    assert info["after"] is not None
    assert [(n, p) for n, _, p in s.solved_networks] == [(info["after"], pat)]


def test_bad_closure_is_rejected():
    src, _, _ = _city()
    with pytest.raises(ValueError):
        rf.RoadsFirstSearch(src, time_box=5, closure="dag")
