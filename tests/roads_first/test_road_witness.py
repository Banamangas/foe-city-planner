"""Codex T1: keep the objective's selected road forest as a candidate network."""
import pytest

import foeopt.roads_first as rf
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern, minimize_needed, validate, witness_network
from foeopt.validate import is_valid


def _b(eid, w, l, needs=True, th=False, x=0, y=0):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


def _world(fillers=()):
    """12x5 region, TH 2x2 at (0,1), skeleton y=2 from x=2..11; two 1x1
    consumers above and below (2,2), so the witness is the single cell (2,2)."""
    region = frozenset((x, y) for x in range(12) for y in range(5))
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    cons = [_b(10, 1, 1), _b(11, 1, 1)]
    lay = Layout(Region(region), [th, *cons, *fillers], th, {})
    pat = Pattern(th=th.footprint, roads=frozenset((x, 2) for x in range(2, 12)), params={})
    pos = {10: (2, 1, 1, 1), 11: (2, 3, 1, 1)}
    return lay, pat, pos


def _worse_greedy(monkeypatch):
    """A valid but wasteful greedy route: (2,2) plus a dangling (3,2)."""
    monkeypatch.setattr(rf, "route", lambda cand, fixed=None: {(2, 2): 1, (3, 2): 1})


@pytest.mark.parametrize("model", ["item", "position"])
def test_objective_witness_is_connected_and_serves_every_consumer(model):
    pytest.importorskip("ortools")
    lay, pat, _ = _world()
    far = {10: (11, 1, 1, 1), 11: (11, 3, 1, 1)}
    diag = {}
    pos = minimize_needed(pat, set(lay.region.cells), lay.road_needing(), far,
                          limit=10.0, diag=diag, model=model)
    w = diag["witness"]
    assert len(w) == diag["objective"] == 1 and w <= pat.roads
    placed = [b for b in lay.buildings if not b.needs_road] + [
        Building(**{**b.__dict__, "footprint": Footprint(*pos[b.entity_id])})
        for b in lay.road_needing()]
    assert is_valid(Layout(lay.region, placed, lay.townhall, {c: 1 for c in w}))


def test_witness_survives_a_worse_greedy_reroute(monkeypatch):
    _worse_greedy(monkeypatch)
    lay, pat, pos = _world()
    assert validate(lay, pat, pos)[2] == 2                     # greedy alone
    diag = {}
    st, out, n = validate(lay, pat, pos, witness=frozenset({(2, 2)}), diag=diag)
    assert (st, n, out.roads) == ("OK", 1, {(2, 2): 1})
    assert diag["witness_used"] and diag["greedy_roads"] == 2 and diag["witness_roads"] == 1


def test_witness_is_pruned_and_illegal_witnesses_are_ignored(monkeypatch):
    _worse_greedy(monkeypatch)
    lay, pat, pos = _world()
    # extra skeleton cells the forest selected but nothing needs are pruned
    assert validate(lay, pat, pos, witness=frozenset({(2, 2), (3, 2), (4, 2)}))[2] == 1
    for bad in ({(5, 2)},            # serves nobody from the TH
                {(2, 2), (2, 1)}):   # covers a consumer
        diag = {}
        st, _, n = validate(lay, pat, pos, witness=frozenset(bad), diag=diag)
        assert (st, n, diag["witness_roads"]) == ("OK", 2, None)


def test_equal_witness_keeps_the_greedy_route():
    lay, pat, pos = _world()
    diag = {}
    validate(lay, pat, pos, witness=frozenset({(2, 2)}), diag=diag)
    assert diag["greedy_roads"] == 1 and diag["witness_used"] is False


def test_smaller_witness_does_not_displace_complete_layout_when_fillers_fail(monkeypatch):
    _worse_greedy(monkeypatch)
    real = rf._finish_layout

    def fillers_fail_on_witness(layout_src, cand, th, placed, fillers, roads, *a):
        if len(roads) == 1:
            return ("SAT_FILLER_FAIL", None, 1)
        return real(layout_src, cand, th, placed, fillers, roads, *a)

    monkeypatch.setattr(rf, "_finish_layout", fillers_fail_on_witness)
    lay, pat, pos = _world()
    diag = {}
    st, out, n = validate(lay, pat, pos, witness=frozenset({(2, 2)}), diag=diag)
    assert (st, n) == ("OK", 2) and diag["witness_used"] is False


def test_witness_network_keeps_the_two_lane_tile():
    lay, pat, pos = _world()
    th = lay.townhall
    cand = Layout(lay.region, [th, *(Building(**{**b.__dict__,
                  "footprint": Footprint(*pos[b.entity_id])}) for b in lay.road_needing())],
                  th, {})
    tile = {(2, 3): 2, (3, 3): 2, (2, 4): 2, (3, 4): 2}
    cand.buildings[2] = Building(**{**cand.buildings[2].__dict__,
                                    "footprint": Footprint(4, 3, 1, 1)})
    net = witness_network(cand, frozenset({(2, 2)}), tile)
    assert net is not None and all(net[c] == 2 for c in tile)


def test_worker_passes_the_witness_only_when_enabled(monkeypatch):
    lay, pat, pos = _world()
    seen = []
    for g in [n for n in vars(rf) if n.startswith("_WORKER_")]:
        monkeypatch.setattr(rf, g, getattr(rf, g))   # the seq path sets these globals
    monkeypatch.setattr(rf, "probe", lambda *a, **k: ("SAT", pos))

    def fake_min(*a, diag=None, **k):
        diag.update(witness=frozenset({(2, 2)}), objective=1)
        return pos

    def fake_validate(layout, p, ps, exact_repair=0, exact_workers=1, diag=None, witness=None):
        seen.append(witness)
        return ("OK", layout, 1)

    monkeypatch.setattr(rf, "minimize_needed", fake_min)
    monkeypatch.setattr(rf, "validate", fake_validate)
    for flag in (False, True):
        seen.clear()
        rf._run_probe_seq((pat, 3, lay, 30.0, 1, False, None, False, None, 0.0, 10.0,
                           None, "position", flag))
        assert seen == [None, frozenset({(2, 2)}) if flag else None]


def test_search_threads_road_witness_to_params(monkeypatch):
    captured = {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        captured["w"] = getattr(params, "road_witness", None)
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    lay, _, _ = _world()
    rf.RoadsFirstSearch(lay, time_box=5, workers=1, k_start=5, road_witness=True).run()
    assert captured["w"] is True
