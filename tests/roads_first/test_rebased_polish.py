"""Codex T4: rebased polish on the incumbent's accepted road network."""
import time
from dataclasses import replace

import pytest

import foeopt.incumbent_polish as ip
import foeopt.roads_first as rf
from foeopt.model import Building, Footprint, Layout, Region


def _b(eid, w, l, needs=True, th=False, x=0, y=0, level=1):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, level, th, None, None, f"b{eid}")


def _world(n=2):
    """12x5 region, TH 2x2 at (0,1). The original skeleton is the row y=2 from
    x=2..11; the incumbent kept only (2,2) and (3,2)."""
    region = frozenset((x, y) for x in range(12) for y in range(5))
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    consumers = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(n)]
    search = Layout(Region(region), [th, *consumers], th, {})
    incumbent = Layout(Region(region), [th, *consumers], th, {(2, 2): 1, (3, 2): 1})
    return search, incumbent


def test_rebased_pattern_is_the_incumbent_network():
    _, inc = _world()
    pat = ip.rebase_pattern(inc)
    assert pat.roads == frozenset({(2, 2), (3, 2)}) and pat.th == inc.townhall.footprint


def test_vacated_skeleton_cells_become_legal_anchors():
    search, inc = _world()
    pat = ip.rebase_pattern(inc)
    pos = ip.incumbent_positions(search, inc)
    assert pos == {10: (2, 1, 1, 1), 11: (3, 1, 1, 1)}
    # (4,2) was an ORIGINAL skeleton cell; on the rebased network it touches (3,2)
    moved = {**pos, 11: (4, 2, 1, 1)}
    assert ip.hint_is_feasible(search, pat, moved)
    assert not ip.hint_is_feasible(search, pat, {**pos, 11: (3, 2, 1, 1)})   # on a road
    assert not ip.hint_is_feasible(search, pat, {**pos, 11: (9, 4, 1, 1)})   # no contact


def test_composite_and_two_lane_positions():
    search, inc = _world(1)
    m1, m2 = _b(20, 1, 1, x=5, y=3), _b(21, 1, 1, x=6, y=3)
    comp = replace(m1, entity_id=-20, footprint=Footprint(0, 0, 2, 1),
                   members=((m1, 0, 0), (m2, 1, 0)))
    search = replace(search, buildings=[*search.buildings, comp])
    inc = replace(inc, buildings=[*inc.buildings, m1, m2],
                  roads={**inc.roads, (2, 3): 2, (3, 3): 2, (2, 4): 2, (3, 4): 2})
    pos = ip.incumbent_positions(search, inc)
    assert pos[-20] == (5, 3, 2, 1)
    assert pos["lane2:0"] == (2, 3, 2, 2)


def test_never_publishes_worse_and_skips_without_time():
    pytest.importorskip("ortools")
    search, inc = _world()
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    seen = []
    rep = ip.polish_rebased(s, inc, 2, time.monotonic() + 15, lambda l, k, a: seen.append(a))
    assert rep["after"] <= 2 and all(a < 2 for a in seen)
    rep = ip.polish_rebased(s, inc, 2, time.monotonic() + 1.0)
    assert rep["attempts"] == [] and rep["after"] == 2


def test_accepts_strict_improvement_then_rebases_once_more(monkeypatch):
    search, inc = _world()
    th, c10, c11 = inc.buildings
    better = replace(inc, buildings=[th, c10, replace(c11, footprint=Footprint(2, 3, 1, 1))],
                     roads={(2, 2): 1})
    calls = []

    def fake_min(pat, region, consumers, pos, limit, workers, model, diag=None, fillers=None):
        calls.append(pat.roads)
        return dict(pos)

    def fake_validate(layout, pat, pos, exact_repair, exact_workers, witness=None):
        return ("OK", better, 1)

    monkeypatch.setattr(ip, "minimize_needed", fake_min)
    monkeypatch.setattr(ip, "validate", fake_validate)
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    seen = []
    rep = ip.polish_rebased(s, inc, 2, time.monotonic() + 30,
                            lambda l, k, a: seen.append(a), k=7)
    assert seen == [1] and rep["after"] == 1
    assert calls == [frozenset({(2, 2), (3, 2)}), frozenset({(2, 2)})]  # rebased twice
    assert rep["attempts"][1]["after"] == 1                              # no gain: stop


def test_run_gives_rebase_the_end_of_the_polish_window(monkeypatch):
    search, inc = _world(1)
    ends = {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        kw["on_improvement"](inc, k, 2)
        params.sat_recorder(k, 2, rf.Pattern(th=inc.townhall.footprint,
                                             roads=frozenset(inc.roads), params={}), {})
        return ("FEASIBLE", 2)

    def fake_obj(self, cands, best, cb, end, should_stop=None):
        ends["objective"] = end
        return {"before": best, "after": best, "tried": 0}

    def fake_rebase(s, lay, ach, end, cb, should_stop, k=None):
        ends["rebase"] = end
        cb(lay, k, 1)
        return {"before": ach, "after": 1, "attempts": []}

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    monkeypatch.setattr(rf.RoadsFirstSearch, "_apply_objective_polish", fake_obj)
    monkeypatch.setattr(ip, "polish_rebased", fake_rebase)
    res = rf.RoadsFirstSearch(search, time_box=30, workers=1, k_start=3,
                              objective_polish=0.5, rebase_s=5).run()
    assert abs((ends["rebase"] - ends["objective"]) - 5) < 0.01
    assert res["best_achieved"] == 1 and res["rebased_polish"]["after"] == 1
    off = rf.RoadsFirstSearch(search, time_box=30, workers=1, k_start=3,
                              objective_polish=0.5).run()
    assert off["rebased_polish"] is None
