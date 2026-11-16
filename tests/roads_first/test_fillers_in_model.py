"""Phase D: the position model places the no-road buildings too, and a run
can start from the uploaded city (seed_input)."""
import time

import pytest

import foeopt.incumbent_polish as ip
import foeopt.roads_first as rf
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern, minimize_needed, probe, validate


def _b(eid, w, l, needs=True, th=False, x=0, y=0):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


def _world(filler_w=10):
    """12x5 region, TH 2x2 at (0,1), skeleton y=2 from x=2..11. Two 1x1
    consumers; one filler of filler_w x 2 that only fits in rows 0-1 or 3-4."""
    region = frozenset((x, y) for x in range(12) for y in range(5))
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    cons = [_b(10, 1, 1), _b(11, 1, 1)]
    filler = _b(20, filler_w, 2, needs=False)
    lay = Layout(Region(region), [th, *cons, filler], th, {})
    pat = Pattern(th=th.footprint, roads=frozenset((x, 2) for x in range(2, 12)), params={})
    return lay, pat, [filler]


def _cells(pos):
    return [c for k, (x, y, w, l) in pos.items() if not isinstance(k, str)
            for c in Footprint(x, y, w, l).cells()]


def test_probe_places_fillers_without_overlap():
    pytest.importorskip("ortools")
    lay, pat, fillers = _world()
    st, pos = probe(pat, set(lay.region.cells), lay.road_needing(), probe_limit=10,
                    model="position", fillers=fillers)
    assert st == "SAT" and set(pos) == {10, 11, 20}
    cells = _cells(pos)
    assert len(cells) == len(set(cells))
    assert not set(cells) & (set(pat.roads) | pat.th.cells())


def test_a_filler_that_cannot_fit_makes_the_skeleton_unsat():
    pytest.importorskip("ortools")
    lay, pat, _ = _world()
    big = [_b(20, 12, 3, needs=False)]          # no 12x3 hole beside the road
    st, _ = probe(pat, set(lay.region.cells), lay.road_needing(), probe_limit=10,
                  model="position", fillers=big)
    assert st == "UNSAT"
    st, _ = probe(pat, set(lay.region.cells), lay.road_needing(), probe_limit=10,
                  model="position")
    assert st == "SAT"                          # without fillers it looks feasible


def test_validate_keeps_model_placed_fillers():
    pytest.importorskip("ortools")
    lay, pat, fillers = _world()
    st, pos = probe(pat, set(lay.region.cells), lay.road_needing(), probe_limit=10,
                    model="position", fillers=fillers)
    vst, out, n = validate(lay, pat, pos)
    assert vst == "OK"
    where = {b.entity_id: b.footprint for b in out.buildings}
    assert tuple(where[20].__dict__.values())[:2] == pos[20][:2]
    assert not where[20].cells() & set(out.roads)


def test_minimize_needed_with_fillers_returns_them():
    pytest.importorskip("ortools")
    lay, pat, fillers = _world()
    far = {10: (11, 1, 1, 1), 11: (11, 3, 1, 1), 20: (0, 3, 10, 2)}
    diag = {}
    pos = minimize_needed(pat, set(lay.region.cells), lay.road_needing(), far,
                          limit=10.0, model="position", fillers=fillers, diag=diag)
    # Without the filler the optimum is 1 (both consumers on (2,2)). Any 10x2 spot
    # covers x=2 in row 1 or row 3, so with it the true optimum is 2.
    assert set(pos) == {10, 11, 20} and diag["objective"] == 2
    assert minimize_needed(pat, set(lay.region.cells), lay.road_needing(), far, limit=10.0,
                           model="position", diag=diag) is not None and diag["objective"] == 1
    cells = _cells(pos)
    assert len(cells) == len(set(cells))


def test_incumbent_positions_include_fillers():
    lay, _, fillers = _world()
    inc = Layout(lay.region, [lay.townhall, _b(10, 1, 1, x=2, y=1), _b(11, 1, 1, x=2, y=3),
                              _b(20, 10, 2, needs=False, x=2, y=3)], lay.townhall, {(2, 2): 1})
    assert ip.incumbent_positions(lay, inc)[11] == (2, 3, 1, 1)
    assert 20 not in ip.incumbent_positions(lay, inc)
    assert ip.incumbent_positions(lay, inc, fillers)[20] == (2, 3, 10, 2)


def test_model_fillers_only_for_the_position_model():
    lay, _, fillers = _world()
    assert rf.model_fillers(lay, True, "position") == fillers
    assert rf.model_fillers(lay, True, "item") is None
    assert rf.model_fillers(lay, False, "position") is None


def _seeded_city():
    """The uploaded city: legal, 3 roads along y=2."""
    region = frozenset((x, y) for x in range(12) for y in range(5))
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    cons = [_b(10, 1, 1, x=4, y=1), _b(11, 1, 1, x=4, y=3)]
    return Layout(Region(region), [th, *cons], th, {(2, 2): 1, (3, 2): 1, (4, 2): 1})


def test_seed_input_publishes_the_uploaded_city_and_polishes_it(monkeypatch):
    monkeypatch.setattr(rf, "_probe_level",
                        lambda *a, **k: ("INFEASIBLE", None))
    calls = {}

    def fake_rebase(s, lay, ach, end, cb, should_stop, k=None):
        calls["rebase"] = (ach, k)
        cb(lay, k, ach - 1)
        return {"before": ach, "after": ach - 1, "attempts": []}

    monkeypatch.setattr(ip, "polish_rebased", fake_rebase)
    seen = []
    res = rf.RoadsFirstSearch(_seeded_city(), time_box=10, workers=1, k_start=3,
                              objective_polish=0.3, rebase_s=5, seed_input=True
                              ).run(on_improvement=lambda l, k, a: seen.append(a))
    assert res["verdict"] == "FAMILY_TOO_WEAK" and res["seed_input"] == {"used": True, "roads": 3}
    assert seen == [3, 2] and calls["rebase"] == (3, 3) and res["best_achieved"] == 2


def test_seed_input_off_or_illegal_publishes_nothing(monkeypatch):
    monkeypatch.setattr(rf, "_probe_level", lambda *a, **k: ("INFEASIBLE", None))
    seen = []
    res = rf.RoadsFirstSearch(_seeded_city(), time_box=5, workers=1, k_start=3
                              ).run(on_improvement=lambda l, k, a: seen.append(a))
    assert seen == [] and res.get("best_achieved") is None
    broken = _seeded_city()
    broken.roads = {(4, 2): 1}                  # not connected to the TH
    res = rf.RoadsFirstSearch(broken, time_box=5, workers=1, k_start=3, seed_input=True
                              ).run(on_improvement=lambda l, k, a: seen.append(a))
    assert seen == [] and res["seed_input"]["used"] is False


def test_worker_passes_fillers_only_when_enabled(monkeypatch):
    lay, pat, fillers = _world()
    for g in [n for n in vars(rf) if n.startswith("_WORKER_")]:
        monkeypatch.setattr(rf, g, getattr(rf, g))
    got = []

    def fake_probe(*a, fillers=None, **k):
        got.append(fillers)
        return ("UNSAT", None)

    monkeypatch.setattr(rf, "probe", fake_probe)
    for flag in (False, True):
        got.clear()
        rf._run_probe_seq((pat, 3, lay, 30.0, 1, False, None, False, None, 0.0, 0.0,
                           None, "position", False, flag))
        assert got == [fillers if flag else None]
