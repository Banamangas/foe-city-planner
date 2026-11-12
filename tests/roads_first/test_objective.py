"""minimize_needed: the in-skeleton placement objective (2026-11-11)."""
import random
import time

import pytest

import foeopt.roads_first as rf
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import (Pattern, minimize_needed, needed_skeleton_cells,
                                skeleton_parents)


def _b(eid, w, l, needs=True, th=False, x=0, y=0):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs, 1, th, None, None, f"b{eid}")


def _corridor():
    """12x5 region; TH 2x2 at the left; a straight road along y=2 from x=2..11.

        y=0  . . . . . . . . . . . .
        y=1  T T . . . . . . . . . .      consumers (1x1) sit on y=1 or y=3
        y=2  T T r r r r r r r r r r      against the road; the closer to the
        y=3  . . . . . . . . . . . .      TH, the fewer road cells are needed.
        y=4  . . . . . . . . . . . .
    """
    region = set((x, y) for x in range(12) for y in range(5))
    th = Footprint(0, 1, 2, 2)
    roads = frozenset((x, 2) for x in range(2, 12))
    return region, Pattern(th=th, roads=roads, params={})


def test_skeleton_parents_is_a_path_to_the_townhall():
    _, pat = _corridor()
    parent = skeleton_parents(pat)
    assert set(parent) == set(pat.roads)
    assert parent[(2, 2)] is None              # touches the TH: a root
    assert parent[(11, 2)] == (10, 2)
    # following parents from the far end reaches the root in 9 steps
    c, steps = (11, 2), 0
    while parent[c] is not None:
        c, steps = parent[c], steps + 1
    assert c == (2, 2) and steps == 9


def test_needed_cells_counts_the_minimal_closed_subtree():
    _, pat = _corridor()
    # one 1x1 at (9,1) borders only (9,2): needs the path 2..9 = 8 cells
    assert needed_skeleton_cells(pat, {1: (9, 1, 1, 1)}) == 8
    # moving it next to the TH needs a single cell
    assert needed_skeleton_cells(pat, {1: (2, 1, 1, 1)}) == 1


def test_minimize_needed_pulls_consumers_toward_the_townhall():
    pytest.importorskip("ortools")
    region, pat = _corridor()
    consumers = [_b(10 + i, 1, 1) for i in range(4)]
    # feasible but wasteful: all four at the far end of the road
    far = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1), 12: (11, 3, 1, 1), 13: (10, 3, 1, 1)}
    assert needed_skeleton_cells(pat, far) == 10
    diag = {}
    pos = minimize_needed(pat, region, consumers, far, limit=10.0, diag=diag)
    assert pos is not None and set(pos) == set(far)
    got = needed_skeleton_cells(pat, pos)
    # optimum: two cells (2,2),(3,2), two consumers each above and below
    assert got == 2
    assert diag["objective"] == 2
    # no overlap, all inside the region, none on a road or the TH
    cells = [c for (x, y, w, l) in pos.values() for c in Footprint(x, y, w, l).cells()]
    assert len(cells) == len(set(cells))
    assert set(cells) <= region
    assert not (set(cells) & (set(pat.roads) | pat.th.cells()))


def test_minimize_needed_never_worse_than_its_hint():
    """The hint is a solution of the model, so the objective can only match it."""
    pytest.importorskip("ortools")
    region, pat = _corridor()
    rng = random.Random(3)
    for trial in range(5):
        spots = [(x, y) for x in range(2, 12) for y in (1, 3)]
        rng.shuffle(spots)
        consumers = [_b(10 + i, 1, 1) for i in range(5)]
        hint = {10 + i: (x, y, 1, 1) for i, (x, y) in enumerate(spots[:5])}
        pos = minimize_needed(pat, region, consumers, hint, limit=5.0)
        assert needed_skeleton_cells(pat, pos) <= needed_skeleton_cells(pat, hint)


def test_objective_off_never_calls_minimize(monkeypatch):
    """objective_limit=0 (the default) must leave the probe path untouched."""
    pytest.importorskip("ortools")
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    consumers = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(2)]
    lay = Layout(Region(frozenset(region)), [th, *consumers], th, {})

    def boom(*a, **k):
        raise AssertionError("minimize_needed called with objective off")

    monkeypatch.setattr(rf, "minimize_needed", boom)
    res = rf._run_probe_seq((pat, 10, lay, 5.0, 1))
    assert res["status"] == "SAT"


def test_objective_on_keeps_the_better_legal_layout(monkeypatch):
    """With the objective on, the reported layout is never worse than the
    feasibility one, and is strictly better when the feasibility placement is
    deliberately bad."""
    pytest.importorskip("ortools")
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    consumers = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(4)]
    lay = Layout(Region(frozenset(region)), [th, *consumers], th, {})
    far = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1), 12: (11, 3, 1, 1), 13: (10, 3, 1, 1)}
    monkeypatch.setattr(rf, "probe", lambda *a, **k: ("SAT", dict(far)))
    off = rf._run_probe_seq((pat, 10, lay, 5.0, 1))
    on = rf._run_probe_seq((pat, 10, lay, 5.0, 1, False, None, False, None, 0.0, 5.0))
    assert off["status"] == on["status"] == "SAT"
    # route() roots at the TH border, so its counts can differ by a cell from
    # the skeleton objective; the property that matters is the ordering.
    assert off["achieved"] >= 10
    assert on["achieved"] <= 3 < off["achieved"]


def test_search_threads_objective_limit_to_params(monkeypatch):
    captured = {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        captured["objective_limit"] = getattr(params, "objective_limit", None)
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    lay = Layout(Region(frozenset(region)), [th, _b(10, 1, 1, x=2, y=1)], th, {})
    rf.RoadsFirstSearch(lay, time_box=5, workers=1, k_start=5,
                        objective_limit=7.0).run()
    assert captured["objective_limit"] == 7.0


def test_production_prefilter_receives_fillers(monkeypatch):
    """The filler-area check only works if the production loop passes fillers."""
    seen = []
    real = rf.prefilter

    def spy(pattern, region, consumers, fillers=None):
        seen.append(fillers)
        return "area"  # reject everything: no probe needed

    monkeypatch.setattr(rf, "prefilter", spy)
    region, _ = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    filler = _b(20, 1, 1, needs=False, x=5, y=4)
    lay = Layout(Region(frozenset(region)), [th, _b(10, 1, 1, x=2, y=1), filler], th, {})
    from types import SimpleNamespace
    import time
    params = SimpleNamespace(patterns=5, probe_limit=1.0, probe_workers=1,
                             deadline=time.monotonic() + 5, th_anchors="coarse",
                             pattern_family="comb")
    rf._probe_levels_batch(lay, set(region), lay.road_needing(), [3],
                           random.Random(0), params, lambda r: None)
    assert seen and all(f is not None and [b.entity_id for b in f] == [20] for f in seen)
    assert real is not spy


def test_objective_respects_the_deadline(monkeypatch):
    """A SAT that arrives with too little budget left must skip the objective
    (and so still return the feasibility layout) rather than run past the
    deadline and be thrown away with the pool."""
    pytest.importorskip("ortools")
    import time
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    consumers = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(2)]
    lay = Layout(Region(frozenset(region)), [th, *consumers], th, {})

    def boom(*a, **k):
        raise AssertionError("objective ran with no budget left")

    monkeypatch.setattr(rf, "minimize_needed", boom)
    res = rf._run_probe_seq((pat, 10, lay, 5.0, 1, False, None, False, None, 0.0,
                             5.0, time.monotonic() + 1.0))
    assert res["status"] == "SAT"


def test_objective_limit_is_clamped_to_remaining_budget(monkeypatch):
    pytest.importorskip("ortools")
    import time
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    consumers = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(2)]
    lay = Layout(Region(frozenset(region)), [th, *consumers], th, {})
    seen = {}

    def spy(pattern, region, consumers, positions, *, limit, **kw):
        seen["limit"] = limit
        return None

    monkeypatch.setattr(rf, "minimize_needed", spy)
    rf._run_probe_seq((pat, 10, lay, 30.0, 1, False, None, False, None, 0.0,
                       30.0, time.monotonic() + 10.0))
    assert 0 < seen["limit"] <= 10.0 - rf.OBJECTIVE_MARGIN_S


def _corridor_layout(n=4):
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    consumers = [_b(10 + i, 1, 1, x=2 + i, y=1) for i in range(n)]
    return Layout(Region(frozenset(region)), [th, *consumers], th, {}), pat


def test_objective_polish_improves_a_bad_sat_and_reports_it():
    pytest.importorskip("ortools")
    import time
    lay, pat = _corridor_layout()
    far = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1), 12: (11, 3, 1, 1), 13: (10, 3, 1, 1)}
    search = rf.RoadsFirstSearch(lay, time_box=30, workers=1, probe_workers=1,
                                 objective_polish=0.5, objective_polish_top=2)
    seen = []
    info = search._apply_objective_polish([(11, 10, pat, far)], 11,
                                          lambda l, k, a: seen.append(a),
                                          time.monotonic() + 15)
    assert info["tried"] == 1
    assert info["after"] is not None and info["after"] <= 3
    assert seen == [info["after"]]


def test_objective_polish_never_reports_worse():
    """A candidate that cannot beat the incumbent changes nothing."""
    pytest.importorskip("ortools")
    import time
    lay, pat = _corridor_layout()
    far = {10: (11, 1, 1, 1), 11: (10, 1, 1, 1), 12: (11, 3, 1, 1), 13: (10, 3, 1, 1)}
    search = rf.RoadsFirstSearch(lay, time_box=30, workers=1, probe_workers=1,
                                 objective_polish=0.5)
    seen = []
    info = search._apply_objective_polish([(11, 10, pat, far)], 1,
                                          lambda l, k, a: seen.append(a),
                                          time.monotonic() + 15)
    assert info["after"] == 1 and seen == []


def test_objective_polish_skips_when_no_time_left():
    lay, pat = _corridor_layout()
    import time
    search = rf.RoadsFirstSearch(lay, time_box=30, workers=1, objective_polish=0.5)
    info = search._apply_objective_polish([(11, 10, pat, {})], 11, None,
                                          time.monotonic() + 1.0)
    assert info["tried"] == 0 and info["after"] == 11


def test_objective_polish_reserve_shortens_the_walk(monkeypatch):
    """Once a layout exists, the walk must stop early enough to leave the
    reserve: its deadline is box x (1 - objective_polish)."""
    import time
    captured = {}
    lay, _ = _corridor_layout(1)

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        if "first" not in captured:
            captured["first"] = params.deadline - time.monotonic()
            captured["recorder"] = getattr(params, "sat_recorder", None)
            kw["on_improvement"](lay, k, 9)
            return ("FEASIBLE", 9)
        captured.setdefault("walk_left", params.deadline - time.monotonic())
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    rf.RoadsFirstSearch(lay, time_box=100, workers=1, k_start=5,
                        objective_polish=0.3).run()
    assert captured["first"] > 95          # nothing to polish yet: reserve usable
    assert 65 < captured["walk_left"] <= 70
    assert captured["recorder"] is not None


def test_objective_polish_off_changes_nothing(monkeypatch):
    import time
    captured = {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        captured["walk_left"] = params.deadline - time.monotonic()
        captured["recorder"] = getattr(params, "sat_recorder", None)
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    lay, _ = _corridor_layout(1)
    rf.RoadsFirstSearch(lay, time_box=100, workers=1, k_start=5).run()
    assert captured["walk_left"] > 99 and captured["recorder"] is None


def test_exact_finish_keeps_only_a_strictly_smaller_valid_network(monkeypatch):
    pytest.importorskip("ortools")
    from foeopt.exact_router import ExactResult
    lay, _ = _corridor_layout(1)
    lay.roads = {(2, 1): 1}  # placeholder; validity is checked on the new roads
    search = rf.RoadsFirstSearch(lay, time_box=5, workers=1, exact_finish=True)
    seen = []
    latest = {"layout": lay, "k": 5, "achieved": 3}
    # a smaller but INVALID network must be rejected
    monkeypatch.setattr("foeopt.exact_router.exact_route",
                        lambda l, time_limit: ExactResult("OPTIMAL", 1, {(9, 9): 1}, 0.0, True))
    info = search._apply_exact_finish(latest, lambda l, k, a: seen.append(a))
    assert info["after"] == 3 and seen == []


def test_exact_finish_runs_the_real_router_on_a_toy():
    pytest.importorskip("ortools")
    from foeopt.router import route
    region, pat = _corridor()
    th = _b(1, 2, 2, needs=False, th=True, x=0, y=1)
    cons = [_b(10, 1, 1, x=5, y=1)]
    lay = Layout(Region(frozenset(region)), [th, *cons], th, {})
    lay.roads = route(lay)
    search = rf.RoadsFirstSearch(lay, time_box=5, workers=1, exact_finish=True)
    info = search._apply_exact_finish({"layout": lay, "k": 5, "achieved": len(lay.roads)},
                                      lambda *a: None)
    assert info["after"] <= len(lay.roads) and info["optimal"]


def test_empty_quality_band_is_topped_up_with_unbanded_patterns(monkeypatch):
    """FR24: the band yields zero skeletons, which used to end the run in seconds
    with no probe at all. A level must still get patterns to probe."""
    calls = []

    def fake_gen(region, tw, tl, k, rng, n, th_mode="coarse", quality_index_band=None, **kw):
        calls.append(quality_index_band)
        if quality_index_band is not None:
            return []
        return [rf.Pattern(th=Footprint(0, 1, 2, 2), roads=frozenset({(2, 1)}), params={"k": k})]

    monkeypatch.setattr(rf, "generate_nonuniform_patterns", fake_gen)
    seen = []
    monkeypatch.setattr(rf, "prefilter", lambda p, r, c, f=None: seen.append(p) or "area")
    from types import SimpleNamespace
    import time
    lay, _ = _corridor_layout(1)
    params = SimpleNamespace(patterns=5, probe_limit=1.0, probe_workers=1,
                             deadline=time.monotonic() + 5, th_anchors="coarse",
                             pattern_family="nonuniform", quality_index_band=(3, 4))
    rf._probe_levels_batch(lay, set(lay.region.cells), lay.road_needing(), [3],
                           random.Random(0), params, lambda r: None)
    assert calls == [(3, 4), None]
    assert len(seen) == 1


def test_finishing_phases_share_one_incumbent(monkeypatch):
    """Review 2026-11-11: walk 100 -> objective polish 90 -> seed polish 95 must
    publish 100, 90 only and return 90 (seed polish used to compare against the
    stale walk best and publish 95 after 90)."""
    import foeopt.seed_search as ss
    lay, pat = _corridor_layout(1)

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        if k == 5:
            if getattr(params, "best_recorder", None):
                params.best_recorder(k, 100, pat, lay)
            if getattr(params, "sat_recorder", None):
                params.sat_recorder(k, 100, pat, {})
            kw["on_improvement"](lay, k, 100)
            return ("FEASIBLE", 100)
        return ("INFEASIBLE", None)

    def fake_obj(self, cands, best, on_imp, end, should_stop=None):
        on_imp(lay, 5, 90)
        return {"before": best, "after": 90}

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    monkeypatch.setattr(rf.RoadsFirstSearch, "_apply_objective_polish", fake_obj)
    monkeypatch.setattr(ss, "seed_minimize_roads",
                        lambda *a, **k: ss.SeedMinResult(95, lay, 3, 1, 1))
    for exact in (False, True):
        if exact:
            monkeypatch.setattr("foeopt.exact_router.exact_route",
                                lambda *a, **k: (_ for _ in ()).throw(AssertionError))
            monkeypatch.setattr(rf.RoadsFirstSearch, "_apply_exact_finish",
                                lambda self, latest, cb, d=None, s=None:
                                {"before": latest["achieved"], "after": latest["achieved"]})
        seen = []
        res = rf.RoadsFirstSearch(lay, time_box=100, workers=1, k_start=5,
                                  objective_polish=0.3, seed_polish=1, probe_limit=1,
                                  exact_finish=exact).run(
            on_improvement=lambda l, k, a: seen.append(a))
        assert seen == [100, 90], (exact, seen)
        assert res["best_achieved"] == 90
        assert not res["seed_polish"]["improved"]


def test_exact_finish_is_not_started_when_stopped_or_out_of_time(monkeypatch):
    import time
    lay, _ = _corridor_layout(1)
    monkeypatch.setattr("foeopt.exact_router.exact_route",
                        lambda *a, **k: pytest.fail("exact_route must not start"))
    search = rf.RoadsFirstSearch(lay, time_box=5, workers=1, exact_finish=True)
    latest = {"layout": lay, "k": 5, "achieved": 3}
    assert search._apply_exact_finish(latest, None, time.monotonic() + 0.2)["status"] == "SKIPPED"
    assert search._apply_exact_finish(latest, None, time.monotonic() + 60,
                                      lambda: True)["status"] == "SKIPPED"


def test_walk_at_k_max_retries_and_searches_downward(monkeypatch):
    """Review 2026-11-11 (P1): with k_start == k_max an unfinished start level
    ended the run FAMILY_TOO_WEAK at once. Now the level is retried, then the
    walk searches downward (at the cap, fewer roads leave room to pack)."""
    lay, pat = _corridor_layout(1)
    k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                        for b in lay.buildings)
    calls = []

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        calls.append(k)
        if k == k_max - 8:
            kw["on_improvement"](lay, k, 7)
            return ("FEASIBLE", 7)
        if k == k_max and calls.count(k) == 1:
            return ("UNDERSAMPLED", None)
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    res = rf.RoadsFirstSearch(lay, time_box=30, workers=1, k_start=k_max).run()
    assert calls[:2] == [k_max, k_max]          # retried, not abandoned
    assert k_max - 8 in calls and res["verdict"] == "DONE"
    assert res["best_achieved"] == 7
    assert res["boundary_descent"][:2] == [k_max - 4, k_max - 8]


def test_deepening_reprobes_unknown_levels_with_a_growing_limit(monkeypatch):
    """Phase C ("use the leftover box"): when the walk settles on unknown levels
    with time left, re-probe them nearest-first with a longer limit instead of
    stopping. Here k=17 only resolves (FEASIBLE) at a 30 s limit."""
    lay, pat = _corridor_layout(1)
    seen = []

    def fake_batch(layout, region, consumers, ks, rng, params, log, pool=None, **kw):
        time.sleep(0.01)
        out = {}
        for k in ks:
            seen.append((k, params.probe_limit))
            if k >= 20 or (k == 18 and params.probe_limit >= 30):
                kw["on_improvement"](lay, k, k)
                out[k] = ("FEASIBLE", k)
            else:
                out[k] = ("INCONCLUSIVE", None)
        return out

    monkeypatch.setattr(rf, "_probe_levels_batch", fake_batch)
    kw = dict(time_box=3, workers=1, k_start=20, probe_limit=10, objective_polish=0)
    off = rf.RoadsFirstSearch(lay, **kw).run()
    assert off["best_achieved"] == 20 and off["deepen"] is None
    seen.clear()
    res = rf.RoadsFirstSearch(lay, deepen=True, **kw).run()
    assert res["best_achieved"] == 18
    d = res["deepen"]
    assert d["start_hi"] == 20 and d["end_hi"] == 18
    # the bound (20, best roads) is re-solved first, then unknowns nearest-first
    assert d["rounds"][0]["limit"] == 30
    assert d["rounds"][0]["status"] == {20: "FEASIBLE", 19: "INCONCLUSIVE",
                                        18: "FEASIBLE", 16: "INCONCLUSIVE"}
    assert list(d["rounds"][0]["status"])[:2] == [20, 19]
    assert d["rounds"][1]["limit"] == 90 and 17 in d["rounds"][1]["status"]
    assert (18, 30) in seen and res["profile"]["wall_s"] >= 2   # used the box


def test_deepen_retry_reprobes_the_skeletons_that_timed_out(monkeypatch):
    """deepen_retry: the walk's 10 s probes drop hard skeletons as UNKNOWN; the
    deepening round retries exactly those at 30 s before drawing fresh ones."""
    lay, pat = _corridor_layout(1)
    givens = []

    def fake_batch(layout, region, consumers, ks, rng, params, log, pool=None,
                   given=None, **kw):
        time.sleep(0.01)
        givens.append(given)
        out = {}
        for k in ks:
            if k >= 20:
                kw["on_improvement"](lay, k, k)
                out[k] = ("FEASIBLE", k)
            elif given and k in given and params.probe_limit >= 30:
                assert given[k] == ["hard19"]
                kw["on_improvement"](lay, k, k)
                out[k] = ("FEASIBLE", k)
            else:
                if k == 19 and params.probe_limit < 30 and not given:
                    params.unknown_recorder(k, "hard19")     # timed out at 10 s
                out[k] = ("INCONCLUSIVE", None)
        return out

    monkeypatch.setattr(rf, "_probe_levels_batch", fake_batch)
    res = rf.RoadsFirstSearch(lay, time_box=3, workers=1, k_start=20, probe_limit=10,
                              objective_polish=0, deepen=True, deepen_retry=True).run()
    assert res["best_achieved"] == 19
    first = res["deepen"]["rounds"][0]
    assert first["retried"] == {19: 1} and first["status"][19] == "FEASIBLE"
    assert {19: ["hard19"]} in givens


@pytest.mark.parametrize("fill,expect", [(False, 2), (True, 5)])
def test_objective_polish_fill_spends_leftover_on_more_candidates(monkeypatch, fill, expect):
    """FR17's 103 is made by objective polish, whose top-3 solves end early
    (proven optimal), leaving ~35% of the box. With fill, the time left goes to
    the remaining stored candidates; the top-N split itself is unchanged."""
    lay, pat = _corridor_layout(1)
    limits = []

    def fake_min(pat, region, consumers, pos, limit, workers, model):
        limits.append(limit)
        return None                      # instant "solve": nothing better

    monkeypatch.setattr(rf, "minimize_needed", fake_min)
    search = rf.RoadsFirstSearch(lay, time_box=30, workers=1, objective_polish=0.5,
                                 objective_polish_top=2, objective_polish_fill=fill)
    cands = [(10 + i, 10, pat, {}) for i in range(5)]
    info = search._apply_objective_polish(cands, 10, None, time.monotonic() + 23)
    assert info["tried"] == expect
    assert 9 < limits[0] < 10.5          # top-2 split: (23 - 3) / 2, as before
    if fill:
        assert 6 < limits[2] < 7         # then (23 - 3) / 3 over the rest


def test_objective_polish_keep_widens_the_candidate_store(monkeypatch):
    lay, pat = _corridor_layout(1)
    captured = {}

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        for i in range(30):
            params.sat_recorder(k, 10 + i, Pattern(th=pat.th, roads=frozenset({(i, 0)}),
                                                   params={}), {})
        captured["n"] = None
        kw["on_improvement"](lay, k, 10)
        return ("FEASIBLE", 10)

    def fake_polish(self, cands, best, *a, **kw):
        captured["n"] = len(cands)
        return {"before": best, "after": best, "tried": 0}

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    monkeypatch.setattr(rf.RoadsFirstSearch, "_apply_objective_polish", fake_polish)
    rf.RoadsFirstSearch(lay, time_box=20, workers=1, k_start=20, objective_polish=0.5,
                        objective_polish_keep=25).run()
    assert captured["n"] == 25
