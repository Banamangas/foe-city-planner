"""Throwaway R&D prototype for next-things-to-try #6: a single CP-SAT model
that jointly selects road cells (minimizing their count) and places
buildings, instead of the roads-first two-stage skeleton-then-place
approach in roads_first.py. Connectivity to the Townhall is enforced as a
BFS-tree constraint (distance-labeling + parent-link reification) since
road cells are now a decision variable, not a precomputed fixed set.

Expected to be intractable at real-city scale (see tasks/lessons.md
2026-07-17 entry for the gate result) -- kept as a documented, gated
negative/inconclusive result, not productionized. Not imported by any
production code path.
"""
from __future__ import annotations

from foeopt.model import Building, Footprint, Layout

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


def _bbox(region: set[Cell]) -> tuple[int, int, int, int]:
    xs = [c[0] for c in region]
    ys = [c[1] for c in region]
    return min(xs), min(ys), max(xs), max(ys)


def _building_positions(b: Building, region: set[Cell], blocked: set[Cell]) -> list[Cell]:
    w, l = b.footprint.width, b.footprint.length
    x0, y0, x1, y1 = _bbox(region)
    out = []
    for y in range(y0, y1 - l + 2):
        for x in range(x0, x1 - w + 2):
            cells = Footprint(x, y, w, l).cells()
            if cells <= region and not (cells & blocked):
                out.append((x, y))
    return out


def solve_min_roads(layout: Layout, region: set[Cell], *, time_limit: float
                    ) -> tuple[str, frozenset | None, dict | None]:
    """Returns (status, roads, positions). status is one of
    OPTIMAL/FEASIBLE/UNSAT/UNKNOWN (matching foeopt.roads_first.probe's
    vocabulary where applicable). roads/positions are None unless a
    solution was found."""
    from ortools.sat.python import cp_model

    th = layout.townhall
    th_cells = set(th.footprint.cells())
    consumers = [b for b in layout.buildings if not b.is_townhall]
    road_candidates = sorted(region - th_cells)
    sel_domain = set(road_candidates)
    th_adjacent = {c for c in road_candidates
                  if any((c[0] + dx, c[1] + dy) in th_cells for dx, dy in _ORTHO)}
    if not th_adjacent:
        return ("UNSAT", None, None)

    m = cp_model.CpModel()

    sel = {c: m.NewBoolVar(f"sel_{c}") for c in road_candidates}
    max_dist = len(road_candidates) + 1
    dist = {c: m.NewIntVar(1, max_dist, f"dist_{c}") for c in road_candidates}
    is_root = {c: m.NewBoolVar(f"root_{c}") for c in th_adjacent}
    for c in th_adjacent:
        m.Add(is_root[c] <= sel[c])
        m.Add(dist[c] == 1).OnlyEnforceIf(is_root[c])

    for c in road_candidates:
        neighbors = [n for dx, dy in _ORTHO
                    if (n := (c[0] + dx, c[1] + dy)) in sel_domain]
        link_bools = [is_root[c]] if c in is_root else []
        for n in neighbors:
            pv = m.NewBoolVar(f"parent_{c}_{n}")
            m.Add(pv <= sel[c])
            m.Add(pv <= sel[n])
            m.Add(dist[c] == dist[n] + 1).OnlyEnforceIf(pv)
            link_bools.append(pv)
        m.Add(sum(link_bools) >= 1).OnlyEnforceIf(sel[c])
        m.Add(sum(link_bools) == 0).OnlyEnforceIf(sel[c].Not())

    intervals_x, intervals_y = [], []
    at_vars: dict[int, dict[Cell, object]] = {}
    for b in consumers:
        opts = _building_positions(b, region, th_cells)
        if not opts:
            return ("UNSAT", None, None)
        w, l = b.footprint.width, b.footprint.length
        at = {}
        for (x, y) in opts:
            v = m.NewBoolVar(f"at_{b.entity_id}_{x}_{y}")
            at[(x, y)] = v
            xiv = m.NewOptionalFixedSizeIntervalVar(x, w, v, f"xi_{b.entity_id}_{x}_{y}")
            yiv = m.NewOptionalFixedSizeIntervalVar(y, l, v, f"yi_{b.entity_id}_{x}_{y}")
            intervals_x.append(xiv)
            intervals_y.append(yiv)
            border = Footprint(x, y, w, l).border_cells()
            road_touch = [sel[c] for c in border if c in sel]
            if road_touch:
                m.AddBoolOr(road_touch).OnlyEnforceIf(v)
            else:
                m.Add(v == 0)
        m.AddExactlyOne(list(at.values()))
        at_vars[b.entity_id] = at
    m.AddNoOverlap2D(intervals_x, intervals_y)

    m.Minimize(sum(sel.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    st = solver.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        roads = frozenset(c for c in road_candidates if solver.Value(sel[c]))
        positions = {}
        for b in consumers:
            for (x, y), v in at_vars[b.entity_id].items():
                if solver.Value(v):
                    positions[b.entity_id] = (x, y, b.footprint.width, b.footprint.length)
                    break
        status = "OPTIMAL" if st == cp_model.OPTIMAL else "FEASIBLE"
        return (status, roads, positions)
    if st == cp_model.INFEASIBLE:
        return ("UNSAT", None, None)
    return ("UNKNOWN", None, None)
