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


def exact_route(layout: Layout, *, time_limit: float = 300.0, seed: int = 0,
                fixed: dict[Cell, int] | None = None, workers: int = 1,
                hint=None) -> ExactResult:
    """`fixed` road cells (two-lane tiles) are forced into the network with
    their level; a road_level-2 building is then covered only by a fixed
    level-2 cell, never by a post-assigned 1x1 "two-lane" cell.

    `hint`: a known road network (e.g. the incumbent's cells). Its road
    booleans AND a matching flow (a BFS tree from the TH roots) are hinted, so
    for a legal connected network the hint is a complete feasible solution and
    CP-SAT starts at its count. A stale hint (a cell off the free set) is
    ignored. `workers`: CP-SAT search workers."""
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

    fixed = dict(fixed or {})
    consumers = layout.road_needing()
    if fixed:
        lane_ok = all(any(fixed.get(c, 0) >= b.road_level for c in b.footprint.border_cells())
                      for b in consumers if b.road_level >= 2)
        if not lane_ok or not set(fixed) <= free:
            return ExactResult("UNCOVERABLE", None, None, round(time.monotonic() - t0, 2), False)
        consumers = [b for b in consumers if b.road_level < 2]
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
    for c in fixed:
        m.Add(r[c] == 1)                           # two-lane tiles stay

    # single-commodity flow: every selected cell must receive 1 unit routed from a
    # selected Townhall-root through selected cells -> one component reaching the TH.
    in_edges: dict[Cell, list] = {c: [] for c in free_list}
    out_edges: dict[Cell, list] = {c: [] for c in free_list}
    flow: dict[tuple[Cell, Cell], object] = {}
    for c in free_list:
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in free:
                fv = m.NewIntVar(0, n, f"f_{c[0]}_{c[1]}__{nb[0]}_{nb[1]}")
                flow[c, nb] = fv
                out_edges[c].append(fv)
                in_edges[nb].append(fv)
                m.Add(fv <= n * r[c])
                m.Add(fv <= n * r[nb])
    source: dict[Cell, object] = {}
    for c in th_roots:
        sv = source[c] = m.NewIntVar(0, n, f"s_{c[0]}_{c[1]}")
        in_edges[c].append(sv)
        m.Add(sv <= n * r[c])
    for c in free_list:
        m.Add(sum(in_edges[c]) - sum(out_edges[c]) == r[c])

    if hint is not None and set(hint) <= free:
        _add_hint(m, r, flow, source, set(hint))

    m.Minimize(sum(r.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = max(1, workers)
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = time_limit
    st = solver.Solve(m)
    wall = round(time.monotonic() - t0, 2)

    name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE"}.get(st, "UNKNOWN")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ExactResult(name, None, None, wall, False)

    roads: dict[Cell, int] = {c: 1 for c in free_list if solver.Value(r[c]) == 1}
    roads.update(fixed)
    for b, opts in zip(consumers, cover):        # post-assign levels for validity
        for c in opts:
            if c in roads:
                roads[c] = max(roads[c], b.road_level)
    return ExactResult(name, len(roads), roads, wall, st == cp_model.OPTIMAL)


def _add_hint(m, r, flow, source, cells: set[Cell]) -> None:
    """Hint `cells` as the network plus a flow that satisfies conservation:
    a multi-source BFS tree from the hinted TH roots, each tree edge carrying
    its child's subtree size and each root's source its own subtree. Cells the
    BFS cannot reach from a root are hinted off (a network that is not
    connected to the TH is not a solution anyway)."""
    from collections import deque
    roots = sorted(c for c in source if c in cells)
    parent: dict[Cell, Cell | None] = {c: None for c in roots}
    order, q = [], deque(roots)
    while q:
        c = q.popleft()
        order.append(c)
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in cells and nb not in parent:
                parent[nb] = c
                q.append(nb)
    size = dict.fromkeys(order, 1)
    for c in reversed(order):
        if parent[c] is not None:
            size[parent[c]] += size[c]
    for c, v in r.items():
        m.AddHint(v, c in parent)
    for (a, b), fv in flow.items():
        m.AddHint(fv, size[b] if parent.get(b) == a else 0)
    for c, sv in source.items():
        m.AddHint(sv, size[c] if c in parent and parent[c] is None else 0)
