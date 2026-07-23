"""seed_polish wiring: RoadsFirstSearch._apply_seed_polish (the opt-in hook)
and the webapp/app passthroughs. The solver is never run here -- seed_minimize_roads
is monkeypatched -- so these are fast and deterministic."""
import pytest

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern, RoadsFirstSearch
from foeopt.seed_search import SeedMinResult
import foeopt.seed_search as seed_search


def _search(seed_polish):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th], th, {})
    return RoadsFirstSearch(layout, time_box=1.0, seed_polish=seed_polish)


def test_off_by_default_never_calls_seed_minimize(monkeypatch):
    called = []
    monkeypatch.setattr(seed_search, "seed_minimize_roads",
                        lambda *a, **k: called.append(1))
    s = _search(seed_polish=0)
    assert s._apply_seed_polish({"achieved": 102, "pattern": object(), "k": 105,
                                 "layout": None}, None) is None
    assert called == []


def test_emits_and_reports_strict_improvement(monkeypatch):
    """A lower legal road count is streamed via on_improvement and reported."""
    pat, better = object(), Layout(Region(frozenset({(0, 0)})), [], None, {})
    monkeypatch.setattr(
        seed_search, "seed_minimize_roads",
        lambda *a, **k: SeedMinResult(achieved=99, layout=better, seed=7,
                                      n_legal=3, n_tried=4))
    emitted = []
    s = _search(seed_polish=4)
    info = s._apply_seed_polish({"achieved": 102, "pattern": pat, "k": 105,
                                 "layout": None},
                                lambda lay, k, ach: emitted.append((lay, k, ach)))
    assert info == {"before": 102, "after": 99, "improved": True, "seed": 7,
                    "seeds_tried": 4, "n_legal": 3}
    assert emitted == [(better, 105, 99)]


def test_no_emit_when_polish_ties_or_worsens(monkeypatch):
    """A tie (or worse) must not be streamed and must not lower best_achieved."""
    monkeypatch.setattr(
        seed_search, "seed_minimize_roads",
        lambda *a, **k: SeedMinResult(achieved=102, layout=object(), seed=1,
                                      n_legal=4, n_tried=4))
    emitted = []
    s = _search(seed_polish=4)
    info = s._apply_seed_polish({"achieved": 102, "pattern": object(), "k": 105,
                                 "layout": None},
                                lambda *a: emitted.append(a))
    assert info["improved"] is False
    assert info["after"] == 102 and info["seed"] is None
    assert emitted == []


def test_no_pattern_recorded_is_a_noop(monkeypatch):
    called = []
    monkeypatch.setattr(seed_search, "seed_minimize_roads",
                        lambda *a, **k: called.append(1))
    s = _search(seed_polish=4)
    assert s._apply_seed_polish({"achieved": None, "pattern": None, "k": None,
                                 "layout": None}, None) is None
    assert called == []


def test_roadsfirstsearch_defaults_seed_polish_off():
    assert _search(seed_polish=0).seed_polish == 0
    assert RoadsFirstSearch(_search(0).layout, time_box=1.0).seed_polish == 0


def test_jobmanager_submit_forwards_seed_polish(monkeypatch):
    """webapp JobManager.submit must thread seed_polish into RoadsFirstSearch."""
    import webapp.runner as runner
    captured = {}

    class FakeSearch:
        def __init__(self, layout, **kw):
            captured.update(kw)

        def run(self, **kw):
            return {"verdict": "DONE"}

    monkeypatch.setattr(runner, "RoadsFirstSearch", FakeSearch)
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    region = Region(frozenset((x, y) for x in range(4) for y in range(4)))
    layout = Layout(region, [th], th, {})
    jm = runner.JobManager()
    jid = jm.submit(layout, time_box=0.1, seed_polish=5)
    # let the worker thread construct the search
    import time
    for _ in range(50):
        if "seed_polish" in captured:
            break
        time.sleep(0.02)
    assert captured.get("seed_polish") == 5
    assert jm.exists(jid)
