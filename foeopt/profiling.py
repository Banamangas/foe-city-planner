"""Per-run phase accounting for RoadsFirstSearch (Phase B, 2026-11-11).

Workers time their own phases and return them with each probe result; the
parent sums them here. Phase totals are WORKER seconds: with W parallel
workers, a run of wall time T has up to W*T worker seconds, so a phase's share
of the work is `total / (wall_s * workers)`, never `total / wall_s`.
"""
from __future__ import annotations

import time
from contextlib import contextmanager


class Profile:
    def __init__(self) -> None:
        self.phases: dict[str, list[float]] = {}   # name -> [total_s, count, max_s]
        self.objective = {"n": 0, "route_above_objective": 0, "route_below_objective": 0,
                          "route_minus_objective_sum": 0, "objective_improved_route": 0}
        self.events: dict[str, float] = {}         # first occurrence, seconds from start
        self.t0 = time.monotonic()

    def add(self, name: str, secs: float, count: int = 1) -> None:
        p = self.phases.setdefault(name, [0.0, 0, 0.0])
        p[0] += secs
        p[1] += count
        p[2] = max(p[2], secs)

    def merge(self, phases: dict[str, float] | None) -> None:
        for name, secs in (phases or {}).items():
            self.add(name, secs)

    @contextmanager
    def timed(self, name: str):
        t = time.monotonic()
        try:
            yield
        finally:
            self.add(name, time.monotonic() - t)

    def event(self, name: str) -> None:
        self.events.setdefault(name, round(time.monotonic() - self.t0, 2))

    def objective_row(self, objective_value, objective_route, feasible_route) -> None:
        """One objective solve: its forest objective vs the routed count of the
        same placement, and whether it beat the feasibility placement's route.
        Sizes the 'keep the solver's own roads' idea (Codex Task 1)."""
        if objective_value is None or objective_route is None:
            return
        o = self.objective
        o["n"] += 1
        diff = objective_route - objective_value
        o["route_minus_objective_sum"] += diff
        o["route_above_objective"] += diff > 0
        o["route_below_objective"] += diff < 0
        if feasible_route is not None and objective_route < feasible_route:
            o["objective_improved_route"] += 1

    def as_dict(self, workers: int = 1) -> dict:
        wall = time.monotonic() - self.t0
        cap = max(wall * max(1, workers), 1e-9)
        phases = {name: {"total_s": round(t, 2), "count": int(n),
                         "mean_s": round(t / n, 4) if n else 0.0, "max_s": round(mx, 3),
                         "share_of_worker_time": round(t / cap, 4)}
                  for name, (t, n, mx) in sorted(self.phases.items(),
                                                 key=lambda kv: -kv[1][0])}
        return {"wall_s": round(wall, 1), "workers": workers, "phases": phases,
                "objective_vs_route": dict(self.objective), "events": dict(self.events)}
