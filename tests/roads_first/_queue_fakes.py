"""Task functions for the work-queue tests.

They run inside worker processes (forkserver), so they live in an importable
module rather than in the test file. Behaviour is carried by the pattern's
`params` (generated in the parent, pickled with the task): `dur` seconds of
cooperative "solving", then `status` (and `achieved` for SAT).
"""
from __future__ import annotations

import time

from foeopt import roads_first as rf


def _result(pat, k, idx, t0, status, achieved=None):
    sat = status == "SAT"
    return {"k": k, "params": pat.params, "status": status,
            "achieved": achieved if sat else None,
            "secs": round(time.monotonic() - t0, 2),
            "layout": {"fake_layout_for_k": k, "achieved": achieved} if sat else None,
            "pat_index": idx, "pos": {} if sat else None,
            "phases": {"task_total": time.monotonic() - t0}}


def fake_task(payload):
    """Mirrors _run_probe's queue contract: clamp to the task deadline, honour
    the stop flag, report CANCELLED when cut short."""
    pat, k, idx = payload[:3]
    p = pat.params
    t0 = time.monotonic()
    ctx = rf._TASK_CTX
    limit, clamped = p["dur"], False
    if ctx is not None:
        left = ctx["deadline"] - t0
        if left < rf.PROBE_MIN_S or ctx["stopped"]():
            return rf._cancelled_result(pat, k, idx, t0, {})
        if left < limit:
            limit, clamped = left, True
    while time.monotonic() - t0 < limit:
        if ctx is not None and ctx["stopped"]():
            return rf._cancelled_result(pat, k, idx, t0, {})
        time.sleep(0.005)
    if clamped:
        return rf._cancelled_result(pat, k, idx, t0, {})
    if p.get("early") is not None and ctx is not None and ctx.get("early") is not None:
        # a "probe" layout first, then the "objective" one (option early_publish)
        ctx["early"](p["early"], {"fake_layout_for_k": k, "achieved": p["early"]}, {})
        time.sleep(p.get("objective_dur", 0.0))
    return _result(pat, k, idx, t0, p["status"], p.get("achieved"))


def failing_task(payload):
    raise ValueError("boom from a worker")


def _golomb(n):
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    ub = n * n
    x = [m.NewIntVar(0, ub, f"x{i}") for i in range(n)]
    m.Add(x[0] == 0)
    for i in range(n - 1):
        m.Add(x[i] < x[i + 1])
    diffs = []
    for i in range(n):
        for j in range(i + 1, n):
            d = m.NewIntVar(1, ub, f"d{i}_{j}")
            m.Add(d == x[j] - x[i])
            diffs.append(d)
    m.AddAllDifferent(diffs)
    m.Minimize(x[-1])
    return m


def golomb(n: int = 12):
    """A model CP-SAT cannot close in minutes on one thread (Golomb ruler)."""
    return _golomb(n)


def solver_task(payload):
    """A REAL CP-SAT solve registered for cooperative cancel, with a limit far
    beyond the test's patience: only stop_search() can end it early."""
    from ortools.sat.python import cp_model
    pat, k, idx = payload[:3]
    t0 = time.monotonic()
    ctx = rf._TASK_CTX
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = min(120.0, ctx["deadline"] - t0)
    with rf._cancellable(solver):
        solver.Solve(golomb(12))
    if ctx["stopped"]():
        return rf._cancelled_result(pat, k, idx, t0, {})
    return _result(pat, k, idx, t0, "UNKNOWN")
