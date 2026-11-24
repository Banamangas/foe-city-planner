"""foeopt.profiling: phase accounting is in WORKER seconds, never naively wall."""
import time

import foeopt.roads_first as rf
from foeopt.profiling import Profile
from tests.roads_first.test_objective import _corridor_layout


def test_share_is_relative_to_wall_times_workers():
    p = Profile()
    p.t0 = time.monotonic() - 10.0          # 10 s of wall
    p.add("probe_solve", 30.0)              # 30 worker-seconds over 6 workers
    d = p.as_dict(workers=6)
    assert 0.49 < d["phases"]["probe_solve"]["share_of_worker_time"] < 0.51


def test_objective_rows_count_route_gaps():
    p = Profile()
    p.objective_row(10, 12, 15)   # routed 2 above objective; beat feasibility route
    p.objective_row(10, 9, 9)     # routed below objective (route searches wider)
    p.objective_row(None, 9, 9)   # no objective value -> ignored
    o = p.as_dict()["objective_vs_route"]
    assert o["n"] == 2 and o["route_above_objective"] == 1
    assert o["route_below_objective"] == 1 and o["objective_improved_route"] == 1


def test_run_returns_a_profile_with_first_valid(monkeypatch):
    lay, pat = _corridor_layout(1)

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        params.profile.add("probe_solve", 0.5)
        if k == 5:
            kw["on_improvement"](lay, k, 9)
            return ("FEASIBLE", 9)
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    res = rf.RoadsFirstSearch(lay, time_box=30, workers=1, k_start=5).run()
    prof = res["profile"]
    assert "first_valid" in prof["events"] and "walk_end" in prof["events"]
    assert prof["phases"]["probe_solve"]["count"] >= 1


def test_run_reports_each_phase_once_in_order(monkeypatch):
    lay, pat = _corridor_layout(1)

    def fake_level(layout, region, consumers, k, rng, params, log, pool=None, **kw):
        if k == 5:
            kw["on_improvement"](lay, k, 9)
            return ("FEASIBLE", 9)
        return ("INFEASIBLE", None)

    monkeypatch.setattr(rf, "_probe_level", fake_level)
    seen: list[str] = []
    rf.RoadsFirstSearch(lay, time_box=30, workers=1, k_start=5).run(on_phase=seen.append)
    assert seen and seen[0] in ("seed", "walk")
    assert all(n in rf.PHASES for n in seen)
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_timed_calls_on_enter_and_a_raising_phase_callback_never_breaks_run(monkeypatch):
    p = Profile()
    names: list[str] = []
    p.on_enter = names.append
    with p.timed("finish_exact"):
        pass
    assert names == ["finish_exact"]

    lay, pat = _corridor_layout(1)
    monkeypatch.setattr(rf, "_probe_level",
                        lambda *a, **kw: ("INFEASIBLE", None))

    def boom(name):
        raise RuntimeError(name)
    res = rf.RoadsFirstSearch(lay, time_box=5, workers=1, k_start=5).run(on_phase=boom)
    assert "verdict" in res
