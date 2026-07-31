"""Every phase must be bounded by the REMAINING budget, not by its own parameter.

Four phases failed this way in one day (tasks/lessons.md 2026-07-31):
  probe_limit >= time_box      -> 2.43x overrun   (fixed: preset)
  pick_k_start margin          -> whole box spent above the useful region (fixed)
  seed_polish after the walk   -> 2.34x overrun for one road (fixed here)
  warm_start before the walk   -> ran entirely outside the box (fixed here)

The class matters more than the instances, so these tests assert the *property*
-- a phase stops when told to -- rather than any particular timing.
"""
from __future__ import annotations

import pytest

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import Pattern
from foeopt.seed_search import seed_minimize_roads


def _toy():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(8) for y in range(8)))
    return Layout(region, [th, c1], th, {})


def test_seed_sweep_stops_when_told_to(monkeypatch):
    """should_stop must be polled BEFORE each solve, so a caller out of budget
    pays for zero further probes -- not one more."""
    import foeopt.seed_search as ss
    calls = {"n": 0}

    def fake_solve(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(ss, "_solve_one", fake_solve)
    lay = _toy()
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2)}), params={"k": 1})
    res = ss.seed_minimize_roads(lay, pat, seeds=range(12), probe_limit=1.0,
                                 should_stop=lambda: True)
    assert calls["n"] == 0, "stopped sweep must not run a single solve"
    assert res.n_tried == 0


def test_seed_sweep_runs_everything_when_not_stopped(monkeypatch):
    import foeopt.seed_search as ss
    calls = {"n": 0}

    def fake_solve(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(ss, "_solve_one", fake_solve)
    lay = _toy()
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2)}), params={"k": 1})
    ss.seed_minimize_roads(lay, pat, seeds=range(5), probe_limit=1.0)
    assert calls["n"] == 5


def test_seed_sweep_stops_partway_and_keeps_the_best_so_far(monkeypatch):
    """Stopping early must return the best result found, not discard it."""
    import foeopt.seed_search as ss
    state = {"n": 0}

    def fake_solve(layout, pattern, seed, **k):
        state["n"] += 1
        return (100 - seed, layout)          # improves with each seed

    monkeypatch.setattr(ss, "_solve_one", fake_solve)
    lay = _toy()
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2)}), params={"k": 1})
    res = ss.seed_minimize_roads(lay, pat, seeds=range(20), probe_limit=1.0,
                                 should_stop=lambda: state["n"] >= 3)
    assert res.n_tried == 3
    assert res.achieved == 98, "best of the seeds actually run must survive the stop"


def test_seed_sweep_signature_accepts_should_stop_by_keyword():
    """RoadsFirstSearch passes it by keyword; a positional-only change would
    break the wiring silently."""
    import inspect
    sig = inspect.signature(seed_minimize_roads)
    assert "should_stop" in sig.parameters
    assert sig.parameters["should_stop"].kind == inspect.Parameter.KEYWORD_ONLY


def test_search_passes_its_deadline_into_the_polish_phase():
    """The wiring itself: _apply_seed_polish must receive a should_stop, or the
    phase silently reverts to being bounded by seed_polish * probe_limit."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert "should_stop=_stop_polish" in src, (
        "run() must pass a deadline predicate into _apply_seed_polish")
    sig = inspect.signature(RoadsFirstSearch._apply_seed_polish)
    assert "should_stop" in sig.parameters


def test_warm_start_is_charged_against_the_time_box():
    """warm_start used to run before RoadsFirstSearch was constructed, entirely
    outside the box: a 60s request with warm_start took 90s minimum."""
    import inspect
    from webapp.runner import JobManager
    src = inspect.getsource(JobManager.submit)
    assert "search_box" in src, "the search must get a reduced box after a warm start"
    assert "time_box=search_box" in src, "RoadsFirstSearch must receive the reduced box"


def test_polish_reserve_is_zero_when_polish_is_off():
    """The reserve must not shrink the walk for users who never asked for
    polish -- that would silently shorten every default run."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert "polish_reserve = 0.0" in src
    assert "if self.seed_polish > 0:" in src


def test_polish_reserve_is_capped_so_it_cannot_starve_the_walk():
    """Polish refines the best skeleton the walk found; if the reserve ate the
    box there would be nothing to refine."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert "self.time_box * 0.25" in src, "reserve must be capped as a share of the box"


def test_walk_and_polish_use_different_stop_predicates():
    """The walk must stop at walk_deadline (leaving the reserve); polish may use
    the reserve but not exceed the real deadline. One predicate cannot do both."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert "walk_deadline" in src and "_stop_polish" in src
    assert "should_stop=_stop_polish" in src, "polish must get its own predicate"


def test_polish_refuses_a_seed_it_cannot_finish():
    """The polish loop is sequential and each seed costs up to probe_limit, so
    checking only `now >= deadline` lets the last seed overshoot by a full probe
    (measured 141.7s on a 120s box). It must require room for a whole seed."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert "time.monotonic() + self.probe_limit >= deadline" in src, (
        "polish must stop before starting a seed that cannot finish in the box")


def test_reserve_is_not_taken_when_it_cannot_fit_a_seed():
    """A reserve smaller than one probe shortens the walk and is then refused by
    _stop_polish, spending nothing: measured 92s on a 120s box (0.77x) with
    seeds_tried=0 -- strictly worse than not reserving. All-or-nothing."""
    import inspect
    from foeopt.roads_first import RoadsFirstSearch
    src = inspect.getsource(RoadsFirstSearch.run)
    assert "want if want >= self.probe_limit * 1.2 else 0.0" in src


def test_reserve_arithmetic_on_the_measured_configurations():
    """120s box at probe_limit=30 cannot fit a seed -> no reserve, walk gets the
    whole box. 600s box can -> reserve taken."""
    def reserve(time_box, probe_limit, seed_polish):
        if seed_polish <= 0:
            return 0.0
        want = min(seed_polish * probe_limit, time_box * 0.25)
        return want if want >= probe_limit * 1.2 else 0.0

    assert reserve(120.0, 30.0, 12) == 0.0, "120s box: reserve would not fit a seed"
    assert reserve(600.0, 30.0, 12) == 150.0, "600s box: reserve fits 5 seeds"
    assert reserve(120.0, 30.0, 0) == 0.0, "polish off: never reserve"
    assert reserve(600.0, 10.0, 4) == 40.0, "small probes fit inside the cap"
