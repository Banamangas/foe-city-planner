import time
import pytest
from types import SimpleNamespace
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.bounds import pick_k_start
from foeopt import roads_first as mod


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


def test_search_on_improvement_fires_on_sat(monkeypatch):
    """When _probe_level finds a SAT layout, on_improvement must be called
    with (layout, k, achieved) — the actual validated Layout object."""
    lay = _tiny_layout()
    improvements = []

    fake_layout_result = SimpleNamespace(roads={(0, 2)}, buildings=[])

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        if on_improvement is not None:
            on_improvement(fake_layout_result, k, k)
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)

    def on_improvement(best_layout, k, achieved):
        improvements.append((best_layout, k, achieved))

    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    result = search.run(on_improvement=on_improvement)
    assert len(improvements) >= 1
    assert improvements[0][1] == 1  # k
    assert improvements[0][2] == 1  # achieved
    assert improvements[0][0] is fake_layout_result  # the actual layout


def test_search_should_stop_interrupts(monkeypatch):
    """If should_stop returns True, the search must wrap up and return best-so-far
    rather than continuing the k-walk."""
    lay = _tiny_layout()
    stop_flag = {"calls": 0}

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)

    def should_stop():
        stop_flag["calls"] += 1
        return stop_flag["calls"] > 1

    search = mod.RoadsFirstSearch(lay, time_box=600.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    result = search.run(should_stop=should_stop)
    assert result["verdict"] == "DONE"
    assert stop_flag["calls"] >= 1


def test_search_on_status_fires_after_level(monkeypatch):
    """on_status must fire after each k-level completes with (k, level_status, probes_done, probes_total)."""
    lay = _tiny_layout()
    statuses = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)

    def on_status(k, level_status, probes_done, probes_total):
        statuses.append({"k": k, "status": level_status,
                         "done": probes_done, "total": probes_total})

    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    result = search.run(on_status=on_status)
    assert len(statuses) >= 1
    assert statuses[0]["status"] == "FEASIBLE"


def test_search_k_start_auto_resolves(monkeypatch):
    """k_start='auto' must resolve to pick_k_start(layout) before first probe."""
    lay = _tiny_layout()
    captured_k = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        captured_k.append(k)
        return ("FEASIBLE", 200)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    expected = pick_k_start(lay)
    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start="auto")
    search.run()
    assert captured_k, "run() did not probe any level"
    assert captured_k[0] == expected


def test_search_pattern_family_propagates_to_params(monkeypatch):
    """RoadsFirstSearch(pattern_family='lane') must reach _probe_level via
    params.pattern_family -- the actual dispatch lives in _probe_level, this
    just confirms the constructor kwarg makes it all the way through run()."""
    lay = _tiny_layout()
    captured = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        captured.append(getattr(params, "pattern_family", "MISSING"))
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1,
                                  pattern_family="lane")
    search.run()
    assert captured, "no _probe_level calls captured"
    assert all(c == "lane" for c in captured)


def test_search_pattern_family_defaults_to_comb(monkeypatch):
    lay = _tiny_layout()
    captured = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        captured.append(getattr(params, "pattern_family", "MISSING"))
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    search.run()
    assert captured, "no _probe_level calls captured"
    assert all(c == "comb" for c in captured)


def test_search_family_too_weak(monkeypatch):
    """When all levels are INFEASIBLE and fallback exhausts, verdict=FAMILY_TOO_WEAK."""
    lay = _tiny_layout()

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return ("INFEASIBLE", None)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    search = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=100)
    result = search.run()
    assert result["verdict"] == "FAMILY_TOO_WEAK"


def test_search_concurrent_levels_default_is_1_never_calls_batch(monkeypatch):
    """concurrent_levels defaults to 1 -- run() must never touch
    _probe_levels_batch, only the original per-level _probe_level path."""
    lay = _tiny_layout()
    batch_calls = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return ("FEASIBLE", k) if k <= 5 else ("INFEASIBLE", None)

    def fake_probe_levels_batch(*a, **kw):
        batch_calls.append(a)
        raise AssertionError("should not be called when concurrent_levels=1")

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    monkeypatch.setattr(mod, "_probe_levels_batch", fake_probe_levels_batch)
    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    search.run()
    assert not batch_calls


def test_search_concurrent_levels_ascent_batches_multiple_ks(monkeypatch):
    """concurrent_levels=3 during the ascent (k_start infeasible) must probe
    up to 3 candidate k's in one _probe_levels_batch call, not one at a time
    via _probe_level."""
    lay = _tiny_layout()
    seen_batches = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return ("INFEASIBLE", None)  # k_start itself always infeasible -> ascent kicks in

    def fake_probe_levels_batch(layout, region, consumers, ks, rng, params, log, pool=None,
                                on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        seen_batches.append(list(ks))
        # first batch after k_start=1: [5, 9, 13] -- make 9 the smallest feasible
        return {kk: (("FEASIBLE", kk) if kk == 9 else ("INFEASIBLE", None)) for kk in ks}

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    monkeypatch.setattr(mod, "_probe_levels_batch", fake_probe_levels_batch)
    search = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1,
                                  concurrent_levels=3)
    search.run()
    assert seen_batches, "ascent phase never batched"
    assert seen_batches[0] == [5, 9, 13], (
        f"expected the first ascent batch to be [k+4, k+8, k+12] = [5, 9, 13], got {seen_batches[0]}")


def test_search_concurrent_levels_descent_batches_multiple_ks(monkeypatch):
    """concurrent_levels=3 during fine descent must probe several k's below
    lo_feasible in one batch, stopping at the smallest still-feasible k."""
    lay = _tiny_layout()
    seen_batches = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return ("FEASIBLE", k)  # k_start=100 itself feasible -> straight to descent

    def fake_probe_levels_batch(layout, region, consumers, ks, rng, params, log, pool=None,
                                on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        seen_batches.append(list(ks))
        # descending from 100: batch [96, 92, 88] -- 92 is the deepest still feasible
        return {kk: (("FEASIBLE", kk) if kk >= 92 else ("INFEASIBLE", None)) for kk in ks}

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    monkeypatch.setattr(mod, "_probe_levels_batch", fake_probe_levels_batch)
    search = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=100,
                                  concurrent_levels=3)
    result = search.run()
    assert seen_batches, "descent phase never batched"
    assert seen_batches[0] == [96, 92, 88]
    # bisection then narrows [92-4, 92] = [88, 92] sequentially via _probe_level
    assert result["verdict"] == "DONE"


def test_search_concurrent_levels_reaches_same_verdict_as_sequential(monkeypatch):
    """The whole point of idea #7: concurrent_levels must be a pure speed
    change. Build one k->status truth table and confirm concurrent_levels=1
    (via _probe_level) and concurrent_levels=4 (via _probe_levels_batch)
    reach the identical best_achieved/verdict/lowest_feasible_k_probed."""
    lay = _tiny_layout()
    # k_start=1 infeasible; feasible for k>=13, smallest achieved count = k itself.
    # A function, not a sparse dict: bisection probes midpoints not on the +/-4 grid.
    def truth(k):
        return ("FEASIBLE", k) if k >= 13 else ("INFEASIBLE", None)

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return truth(k)

    def fake_probe_levels_batch(layout, region, consumers, ks, rng, params, log, pool=None,
                                on_improvement=None, corpus=None, scorer=None, score_threshold=None):
        return {kk: truth(kk) for kk in ks}

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    search_seq = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                      workers=1, th_anchors="coarse", k_start=1,
                                      concurrent_levels=1)
    result_seq = search_seq.run()

    monkeypatch.setattr(mod, "_probe_levels_batch", fake_probe_levels_batch)
    search_conc = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                       workers=1, th_anchors="coarse", k_start=1,
                                       concurrent_levels=4)
    result_conc = search_conc.run()

    assert result_seq["verdict"] == result_conc["verdict"] == "DONE"
    assert result_seq["best_achieved"] == result_conc["best_achieved"]
    assert result_seq["lowest_feasible_k_probed"] == result_conc["lowest_feasible_k_probed"]
