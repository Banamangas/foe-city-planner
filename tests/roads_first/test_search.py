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
                         on_improvement=None, corpus=None):
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
                         on_improvement=None, corpus=None):
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
                         on_improvement=None, corpus=None):
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
                         on_improvement=None, corpus=None):
        captured_k.append(k)
        return ("FEASIBLE", 200)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    expected = pick_k_start(lay)
    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start="auto")
    search.run()
    assert captured_k, "run() did not probe any level"
    assert captured_k[0] == expected


def test_search_family_too_weak(monkeypatch):
    """When all levels are INFEASIBLE and fallback exhausts, verdict=FAMILY_TOO_WEAK."""
    lay = _tiny_layout()

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None, corpus=None):
        return ("INFEASIBLE", None)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    search = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=100)
    result = search.run()
    assert result["verdict"] == "FAMILY_TOO_WEAK"
