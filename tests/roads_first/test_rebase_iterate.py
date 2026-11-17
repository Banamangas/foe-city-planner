"""Q4: rebased polish iterated to a fixed point (`rebase_iterate`)."""
import importlib.util
import pathlib
import time
from dataclasses import replace

import pytest

import foeopt.incumbent_polish as ip
import foeopt.roads_first as rf
from foeopt.model import Building, Footprint, Layout, Region

ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bench", ROOT / "scripts" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def _b(eid, w, l, needs=True, th=False, x=0, y=0):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


def _world(filler=False):
    """12x5 region, TH 2x2 at (0,1), two 1x1 consumers on a 4-cell road."""
    region = frozenset((x, y) for x in range(12) for y in range(5))
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    blds = [th, _b(10, 1, 1, x=2, y=1), _b(11, 1, 1, x=3, y=1)]
    if filler:
        blds.append(_b(30, 2, 1, needs=False, x=8, y=0))
    roads = {(2, 2): 1, (3, 2): 1, (4, 2): 1, (5, 2): 1}
    return (Layout(Region(region), blds, th, {}),
            Layout(Region(region), blds, th, roads))


def _chain(inc, n):
    """n successively shorter networks: drop the last road cell each time."""
    out, cur = [], inc
    for _ in range(n):
        r = dict(cur.roads)
        r.pop(max(r))
        cur = replace(cur, roads=r)
        out.append(cur)
    return out


def _fake(monkeypatch, layouts, filler_fail_first=False):
    calls = []

    def fake_min(pat, region, consumers, pos, limit, workers, model, diag=None,
                 fillers=None, **kw):
        calls.append((pat.roads, fillers is not None, limit))
        return dict(pos)

    def fake_validate(layout, pat, pos, exact_repair, exact_workers, witness=None):
        if filler_fail_first and not any(c[1] for c in calls):
            return ("SAT_FILLER_FAIL", None, 0)
        nxt = next((l for l in layouts if l.roads != dict.fromkeys(pat.roads, 1)
                    and len(l.roads) < len(pat.roads)), None)
        return ("OK", nxt, len(nxt.roads)) if nxt else ("OK", None, len(pat.roads))

    monkeypatch.setattr(ip, "minimize_needed", fake_min)
    monkeypatch.setattr(ip, "validate", fake_validate)
    return calls


def test_default_stops_after_max_solves(monkeypatch):
    search, inc = _world()
    calls = _fake(monkeypatch, _chain(inc, 3))
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    rep = ip.polish_rebased(s, inc, 4, time.monotonic() + 30)
    assert len(calls) == ip.MAX_SOLVES == 2
    assert rep["after"] == 2 and rep["stop"] == "max_solves" and rep["iterate"] is False


def test_iterate_rebases_until_no_gain(monkeypatch):
    search, inc = _world()
    calls = _fake(monkeypatch, _chain(inc, 2))
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1,
                            rebase_iterate=True)
    seen = []
    rep = ip.polish_rebased(s, inc, 4, time.monotonic() + 30,
                            lambda l, k, a: seen.append(a))
    assert seen == [3, 2]
    assert [len(c[0]) for c in calls] == [4, 3, 2]         # rebased on every incumbent
    assert rep["after"] == 2 and rep["stop"] == "no_gain" and rep["iterate"] is True


def test_iterate_slices_the_fast_solve_then_retries_with_model_fillers(monkeypatch):
    search, inc = _world(filler=True)
    calls = _fake(monkeypatch, _chain(inc, 2), filler_fail_first=True)
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    rep = ip.polish_rebased(s, inc, 4, time.monotonic() + 300, iterate=True)
    # sliced consumer-only solve fails fillers (empty trail), model-filler retry
    # with the whole window; the next network goes back to the fast path
    assert [c[1] for c in calls] == [False, True, False, False]
    assert all(c[2] <= ip.ITER_SLICE_S for c in calls if not c[1])
    assert calls[1][2] > ip.ITER_SLICE_S
    assert rep["attempts"][0]["filler_retry"] and rep["after"] == 2


def test_filler_failure_falls_back_to_the_trail_best_first(monkeypatch):
    search, inc = _world(filler=True)
    better = _chain(inc, 1)[0]
    fits = {"loose"}
    validated = []

    def fake_min(pat, region, consumers, pos, limit, workers, model, diag=None,
                 fillers=None, **kw):
        assert fillers is None
        for obj, tag in [(3.0, "loose"), (2.5, "tight"), (2.5, "tight2"), (2.0, "final")]:
            diag["trail"].append((obj, {**pos, "_tag": tag}, frozenset()))
        return {**pos, "_tag": "final"}

    def fake_validate(layout, pat, pos, exact_repair, exact_workers, witness=None):
        validated.append(pos["_tag"])
        if pos["_tag"] in fits and len(pat.roads) == 4:
            return ("OK", better, 3)
        return ("SAT_FILLER_FAIL", None, 2) if len(pat.roads) == 4 else ("OK", None, 3)

    monkeypatch.setattr(ip, "minimize_needed", fake_min)
    monkeypatch.setattr(ip, "validate", fake_validate)
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    rep = ip.polish_rebased(s, inc, 4, time.monotonic() + 300, iterate=True)
    # final fails; then one solution per value, best first: tight2 (last 2.5), loose
    assert validated[:3] == ["final", "tight2", "loose"]
    row = rep["attempts"][0]
    assert row["trail"] == {"solutions": 4, "values": 2, "tried": 2}
    assert row["trail_ok_objective"] == 3.0 and "filler_retry" not in row
    assert rep["after"] == 3


def test_default_keeps_one_unsliced_fast_solve(monkeypatch):
    search, inc = _world(filler=True)
    calls = _fake(monkeypatch, _chain(inc, 2), filler_fail_first=True)
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    ip.polish_rebased(s, inc, 4, time.monotonic() + 300)
    assert [c[1] for c in calls[:2]] == [False, True] and calls[0][2] > ip.ITER_SLICE_S


def test_iterate_respects_the_deadline():
    search, inc = _world()
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    rep = ip.polish_rebased(s, inc, 4, time.monotonic() + 1.0, iterate=True)
    assert rep["attempts"] == [] and rep["stop"] == "deadline" and rep["after"] == 4


def test_minimize_needed_records_its_trail():
    pytest.importorskip("ortools")
    search, inc = _world()
    pat = ip.rebase_pattern(inc)
    pos = ip.incumbent_positions(search, inc)
    diag = {"trail": []}
    out = rf.minimize_needed(pat, set(search.region.cells), search.road_needing(), pos,
                             limit=10, model="position", diag=diag)
    trail = diag["trail"]
    assert trail and trail[-1][1] == out
    objs = [t[0] for t in trail]
    assert objs == sorted(objs, reverse=True) and objs[-1] == diag["objective"]
    assert all(set(t[1]) == set(pos) and t[2] <= pat.roads for t in trail)


def test_iterated_real_solves_publish_only_legal_layouts():
    """Real CP-SAT: every published layout passes bench.verify() (full legality,
    no rotation, same inventory, no overlap, inside the region, off the roads)."""
    pytest.importorskip("ortools")
    search, inc = _world(filler=True)
    s = rf.RoadsFirstSearch(search, time_box=30, workers=1, probe_workers=1)
    pubs = []
    rep = ip.polish_rebased(s, inc, len(inc.roads), time.monotonic() + 20,
                            lambda l, k, a: pubs.append((l, a)), iterate=True)
    assert pubs and rep["after"] < len(inc.roads)
    for lay, a in pubs:
        v = bench.verify(inc, lay)
        assert v["legality"] == "valid", v
        assert v["roads_delivered"] == a
        assert v["rotated"] == 0 and v["inventory_ok"]
        assert v["overlap"] == v["out_of_region"] == v["on_road"] == 0
