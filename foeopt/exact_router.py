"""Exact minimum-roads router for a FIXED placement.

route() (foeopt/router.py) is a greedy SPH-Steiner heuristic with no optimality
guarantee. For a fixed placement the minimum connected set of road cells that
covers every consumer and reaches the Townhall is an exact optimization: pick road
cells from the free set, cover each consumer, keep the picked cells connected to the
TH via single-commodity flow, minimize the count. This is the tractable slice of
foeopt/minroads.py (placement fixed -> no rectangle-placement variables). ortools is
imported lazily, as in roads_first.probe.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from foeopt.model import Layout

Cell = tuple[int, int]
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class ExactResult:
    status: str                    # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN | NO_ROOT | UNCOVERABLE
    count: int | None              # road cells in the best solution found
    roads: dict[Cell, int] | None  # best network found, levels post-assigned
    wall_s: float
    optimal: bool                  # status == OPTIMAL (roads is the proven minimum)


def exact_route(layout: Layout, *, time_limit: float = 300.0, seed: int = 0) -> ExactResult:
    from ortools.sat.python import cp_model

    t0 = time.monotonic()
    region = set(layout.region.cells)
    th = layout.townhall
    if th is None:
        return ExactResult("NO_ROOT", None, None, 0.0, False)

    occupied: set[Cell] = set()
    for b in layout.buildings:
        occupied |= b.footprint.cells()
    free = region - occupied

    th_roots = set(th.footprint.border_cells()) & free
    if not th_roots:
        return ExactResult("NO_ROOT", None, None, round(time.monotonic() - t0, 2), False)

    consumers = layout.road_needing()
    cover: list[list[Cell]] = []
    for b in consumers:
        opts = [c for c in b.footprint.border_cells() if c in free]
        if not opts:
            return ExactResult("UNCOVERABLE", None, None, round(time.monotonic() - t0, 2), False)
        cover.append(opts)

    free_list = sorted(free)
    n = len(free_list)
    m = cp_model.CpModel()
    r = {c: m.NewBoolVar(f"r_{c[0]}_{c[1]}") for c in free_list}

    for opts in cover:
        m.AddBoolOr([r[c] for c in opts])          # each consumer covered by >=1 road

    # single-commodity flow: every selected cell must receive 1 unit routed from a
    # selected Townhall-root through selected cells -> one component reaching the TH.
    in_edges: dict[Cell, list] = {c: [] for c in free_list}
    out_edges: dict[Cell, list] = {c: [] for c in free_list}
    for c in free_list:
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in free:
                fv = m.NewIntVar(0, n, f"f_{c[0]}_{c[1]}__{nb[0]}_{nb[1]}")
                out_edges[c].append(fv)
                in_edges[nb].append(fv)
                m.Add(fv <= n * r[c])
                m.Add(fv <= n * r[nb])
    for c in th_roots:
        sv = m.NewIntVar(0, n, f"s_{c[0]}_{c[1]}")
        in_edges[c].append(sv)
        m.Add(sv <= n * r[c])
    for c in free_list:
        m.Add(sum(in_edges[c]) - sum(out_edges[c]) == r[c])

    m.Minimize(sum(r.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = time_limit
    st = solver.Solve(m)
    wall = round(time.monotonic() - t0, 2)

    name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE"}.get(st, "UNKNOWN")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ExactResult(name, None, None, wall, False)

    roads: dict[Cell, int] = {c: 1 for c in free_list if solver.Value(r[c]) == 1}
    for b, opts in zip(consumers, cover):        # post-assign levels for validity
        for c in opts:
            if c in roads:
                roads[c] = max(roads[c], b.road_level)
    return ExactResult(name, len(roads), roads, wall, st == cp_model.OPTIMAL)
