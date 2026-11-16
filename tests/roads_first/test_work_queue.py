"""scheduler="queue" (backlog S1): persistent workers, one queue across levels,
cooperative cancel instead of pool.terminate(), same walk decisions."""
import multiprocessing
import threading
import time
from types import SimpleNamespace

import pytest

import foeopt.roads_first as mod
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.profiling import Profile
from foeopt.work_queue import LevelQueue

from tests.roads_first import _queue_fakes as fakes


def _city():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False,
                  None, None, "a")
    region = Region(frozenset((x, y) for x in range(12) for y in range(12)))
    return Layout(region, [th, c1], th, {})


def _pattern(k, i, **params):
    return mod.Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, i), (k, 0)}),
                       params={"k": k, "i": i, **params})


def _truth(k, i, n):
    """Feasible from k=40 up (two SATs per level, lower count for the slower
    one), refuted below."""
    if k >= 40 and i in (0, n - 1):
        return {"status": "SAT", "achieved": k - 1 - (i > 0), "dur": 0.05 + 0.15 * (i > 0)}
    return {"status": "UNSAT", "dur": 0.03 + 0.01 * (i % 3)}


def _fake_generation(monkeypatch, behaviour, n=6):
    monkeypatch.setattr(mod, "prefilter", lambda *a, **k: None)
    monkeypatch.setattr(mod, "generate_patterns",
                        lambda region, w, l, k, rng, count, **kw:
                        [_pattern(k, i, **behaviour(k, i, n)) for i in range(n)])


@pytest.fixture
def fake_tasks(monkeypatch):
    # Both schedulers look _run_probe up at dispatch time and pickle it by
    # reference, so the fake reaches the worker processes too.
    monkeypatch.setattr(mod, "_run_probe", fakes.fake_task)


def _search(scheduler, **kw):
    opts = dict(time_box=60, workers=3, probe_workers=1, k_start=48,
                th_anchors="coarse", probe_model="item", keep_chains=False,
                scheduler=scheduler)
    opts.update(kw)
    return mod.RoadsFirstSearch(_city(), **opts)


@pytest.mark.parametrize("concurrent", [1, 3])
def test_queue_reaches_the_same_walk_as_batch(monkeypatch, fake_tasks, concurrent):
    _fake_generation(monkeypatch, _truth)
    out = {}
    for sched in ("batch", "queue"):
        seen = []
        res = _search(sched, concurrent_levels=concurrent).run(
            on_improvement=lambda lay, k, a: seen.append(a))
        out[sched] = res
        assert seen == sorted(seen, reverse=True) and len(set(seen)) == len(seen)
    b, q = out["batch"], out["queue"]
    assert {k: v[0] for k, v in q["results"].items()} == \
        {k: v[0] for k, v in b["results"].items()}
    assert q["best_achieved"] == b["best_achieved"] == 38
    assert q["verdict"] == b["verdict"] == "DONE"
    assert q["lowest_feasible_k_probed"] == b["lowest_feasible_k_probed"] == 40
    # the rest of each FEASIBLE level is still booked: same final counts
    assert {k: v for k, v in q["results"].items()} == {k: v for k, v in b["results"].items()}
    info = q["profile"]["info"]["queue"]
    assert info["dispatched"] == info["tasks"] and info["cancelled"] == 0
    assert 0.0 <= q["profile"]["walk"]["idle_share"] <= 1.0


def test_queue_mode_never_builds_a_pool_nor_terminates(monkeypatch, fake_tasks):
    """Long tasks and a short box: every level runs out of slice/deadline. The
    batch path would terminate (and rebuild) its pool; the queue must not."""
    _fake_generation(monkeypatch, lambda k, i, n: {"status": "UNKNOWN", "dur": 2.5}, n=8)

    def no_pool(*a, **k):
        raise AssertionError("queue mode must not create a multiprocessing.Pool")

    monkeypatch.setattr(mod.multiprocessing, "Pool", no_pool)
    terminated = []
    real_terminate = multiprocessing.Process.terminate
    monkeypatch.setattr(multiprocessing.Process, "terminate",
                        lambda self: (terminated.append(self.pid), real_terminate(self)))
    box = 6.0
    t0 = time.monotonic()
    res = _search("queue", time_box=box, probe_limit=2.5, concurrent_levels=2).run()
    wall = time.monotonic() - t0
    assert wall <= box + 1.5, f"box overrun: {wall:.2f}s for a {box}s box"
    assert terminated == [], "a worker was terminated instead of stopping cooperatively"
    assert res["deadline_hit"] and not res["walk_complete"]
    assert any(st == "UNDERSAMPLED" for st, _ in res["results"].values())
    assert res["profile"]["info"]["queue"]["cancelled"] > 0


def _queue(layout, params, workers=2, task_fn=None, **kw):
    region = set(layout.region.cells)
    return LevelQueue(layout, region, layout.road_needing(), __import__("random").Random(0),
                      params, workers=workers, init_args=(layout, 1.0, 1),
                      task_fn=task_fn, **kw)


def _params(deadline_in, slice_in=None):
    now = time.monotonic()
    return SimpleNamespace(patterns=8, probe_limit=5.0, probe_workers=1,
                           deadline=now + deadline_in, th_anchors="coarse",
                           pattern_family="comb",
                           slice_deadline=None if slice_in is None else now + slice_in,
                           profile=Profile())


def test_slice_expiry_drops_queued_tasks_and_cuts_running_ones(monkeypatch):
    _fake_generation(monkeypatch, lambda k, i, n: {"status": "UNSAT", "dur": 3.0}, n=8)
    lay = _city()
    params = _params(60, slice_in=0.6)
    cov = {}
    q = _queue(lay, params, task_fn=fakes.fake_task, coverage=cov)
    try:
        t0 = time.monotonic()
        ans = q.levels([40])
        took = time.monotonic() - t0
    finally:
        q.close()
    assert ans[40] == ("UNDERSAMPLED", None), "cut work is not evidence"
    assert took < 0.6 + 1.5, f"level held the controller {took:.2f}s past its slice"
    assert cov[40]["probed"] == 0 and cov[40]["surviving"] == 8
    # the two running tasks are cut, the buffered one is cancelled on start,
    # the rest never leave the parent
    assert q.stats["cancelled"] >= 2 and q.stats["cancelled"] + q.stats["dropped"] == 8


def test_a_feasible_level_answers_at_once_and_books_the_rest_later(monkeypatch):
    def beh(k, i, n):
        if i == 0:
            return {"status": "SAT", "achieved": 10, "dur": 0.05}
        return {"status": "SAT", "achieved": 8, "dur": 0.8}
    _fake_generation(monkeypatch, beh, n=4)
    lay = _city()
    params = _params(60)
    updates, published = [], []
    q = _queue(lay, params, task_fn=fakes.fake_task,
               on_level_update=lambda k, a: updates.append((k, a)),
               on_improvement=lambda lay_, k, a: published.append(a))
    try:
        t0 = time.monotonic()
        ans = q.levels([40])
        took = time.monotonic() - t0
        q.drain(until=time.monotonic() + 10)
    finally:
        q.close()
    assert ans[40] == ("FEASIBLE", 10)
    assert took < 0.6, "a FEASIBLE level must not wait for its stragglers"
    assert updates == [(40, ("FEASIBLE", 8))]
    assert published == [10, 8]
    assert q.stats["late_results"] == 3


def test_stop_ends_real_solver_runs_cooperatively(monkeypatch):
    """End to end with real CP-SAT solves that would run for 120 s: a user stop
    must end them through stop_search(), well inside the close() grace, with no
    worker terminated."""
    pytest.importorskip("ortools")
    _fake_generation(monkeypatch, lambda k, i, n: {"dur": 0}, n=4)
    lay = _city()
    params = _params(300)
    t_stop = time.monotonic() + 1.5
    terminated = []
    real_terminate = multiprocessing.Process.terminate
    monkeypatch.setattr(multiprocessing.Process, "terminate",
                        lambda self: (terminated.append(self.pid), real_terminate(self)))
    q = _queue(lay, params, task_fn=fakes.solver_task,
               should_stop=lambda: time.monotonic() >= t_stop)
    try:
        t0 = time.monotonic()
        ans = q.levels([40])
        took = time.monotonic() - t0
    finally:
        q.close()
    closed = time.monotonic() - t0
    assert ans[40][0] == "UNDERSAMPLED"
    assert took < 4.0, f"stop took {took:.2f}s to reach the controller"
    assert closed < 6.0
    assert terminated == []
    assert q.stats["cancelled"] >= 2 and q.stats["cancelled"] + q.stats["dropped"] == 4


def test_stop_active_solvers_interrupts_a_solve_from_another_thread():
    pytest.importorskip("ortools")
    from ortools.sat.python import cp_model
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 120
    threading.Timer(0.5, mod._stop_active_solvers).start()
    t0 = time.monotonic()
    with mod._cancellable(solver):
        st = solver.Solve(fakes.golomb(12))
    took = time.monotonic() - t0
    if st == cp_model.OPTIMAL:
        pytest.skip("the model was closed before the stop: inconclusive")
    assert took < 5.0
    assert not mod._ACTIVE_SOLVERS, "the registry must be empty after the solve"


def test_a_worker_exception_reaches_the_caller(monkeypatch):
    _fake_generation(monkeypatch, lambda k, i, n: {"status": "UNSAT", "dur": 0}, n=2)
    lay = _city()
    q = _queue(lay, _params(60), task_fn=fakes.failing_task)
    try:
        with pytest.raises(RuntimeError, match="boom from a worker"):
            q.levels([40])
    finally:
        q.close(abort=True)


def test_scheduler_is_validated():
    with pytest.raises(ValueError, match="scheduler"):
        mod.RoadsFirstSearch(_city(), time_box=5, scheduler="nope")
    import inspect
    assert inspect.signature(mod.RoadsFirstSearch.__init__).parameters[
        "scheduler"].default == "batch"


def test_run_probe_outside_a_queue_is_unchanged(monkeypatch):
    """No task context -> the probe gets the full probe limit and an UNKNOWN is
    reported as such (the batch path's behaviour)."""
    seen = {}

    def fake_probe(pattern, region, consumers, *, probe_limit, **kw):
        seen["limit"] = probe_limit
        return ("UNKNOWN", None)

    monkeypatch.setattr(mod, "probe", fake_probe)
    monkeypatch.setattr(mod, "_WORKER_LAYOUT", _city())
    monkeypatch.setattr(mod, "_WORKER_PROBE_LIMIT", 30.0)
    assert mod._TASK_CTX is None
    res = mod._run_probe((_pattern(40, 0), 40, 0, time.monotonic() + 1.0))
    assert res["status"] == "UNKNOWN" and seen["limit"] == 30.0


def test_run_probe_in_a_queue_clamps_and_cancels(monkeypatch):
    seen = {}

    def fake_probe(pattern, region, consumers, *, probe_limit, **kw):
        seen["limit"] = probe_limit
        return ("UNKNOWN", None)

    monkeypatch.setattr(mod, "probe", fake_probe)
    monkeypatch.setattr(mod, "_WORKER_LAYOUT", _city())
    monkeypatch.setattr(mod, "_WORKER_PROBE_LIMIT", 30.0)
    deadline = time.monotonic() + 5.0
    monkeypatch.setattr(mod, "_TASK_CTX", {"deadline": deadline, "stopped": lambda: False})
    res = mod._run_probe((_pattern(40, 0), 40, 0, deadline))
    assert seen["limit"] <= 5.0, "the probe must be clamped to the level deadline"
    assert res["status"] == "CANCELLED"
    # past the deadline the task is not even started
    monkeypatch.setattr(mod, "_TASK_CTX", {"deadline": time.monotonic() - 1,
                                           "stopped": lambda: False})
    seen.clear()
    res = mod._run_probe((_pattern(40, 0), 40, 0, deadline))
    assert res["status"] == "CANCELLED" and "limit" not in seen
