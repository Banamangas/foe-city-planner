"""Exact (CP-SAT) rectangle packing for the non-road-needing "filler" buildings.

Fillers have no road-adjacency and no connectivity requirement, so placing them
is *pure* rectangle packing -- a much easier problem than the consumer placement
in `roads_first.probe`. That makes CP-SAT viable here where it is not viable for
the layout as a whole.

Two modelling choices carry the whole thing (measured, see
tasks/remaining-work.md section 8):

**Model over size classes, not buildings.** Two 4x4 fillers are interchangeable,
so a per-building model would carry 77! symmetric permutations of the 4x4s alone
on the user's city. Deciding instead "how many rectangles of size s go at
position p" collapses 231 buildings to 18 classes. Buildings are re-attached to
the chosen positions afterwards, arbitrarily within their class.

**No rotation.** Buildings cannot be rotated in Forge of Empires, so (4,3) and
(3,4) are *different* classes and each is enumerated only in its own orientation.

The pass is a *repair*: greedy packing runs first and is hinted into the model,
so the solver starts from the greedy answer. It is worth running only on layouts
that would otherwise be discarded outright.

Measured on the user's own city -- 231 fillers, 2486 free cells, 3 cells of
slack, and a proven-feasible answer. Greedy reaches 222:

    threads  budget  objective   placed
    1        5-30s   any           none   -- no solution found at all
    1        60s     count          222
    8        5s      count          217   -- WORSE than greedy
    8        5s      count+hint     230   -- reproduced 3/3
    8        10s     count+hint     230
    8        60s     count+hint     230

So all three of {>1 thread, the greedy hint, the count objective} are load-
bearing, and 5 seconds is enough. Two consequences for callers:

  * Never run this single-threaded.
  * The hint does NOT make the result monotonically >= greedy (CP-SAT reports
    its own incumbent), so `validate` accepts the repair only when it strictly
    beats greedy. Do not remove that guard.

Note it reaches 230, not 231: even exact packing does not fully match the
expert's own layout at this density. It is a large improvement, not an oracle.
"""
from __future__ import annotations

import collections
from dataclasses import replace

from foeopt.model import Building, Footprint

Cell = tuple[int, int]
Placement = tuple[Building, int, int]


def _positions(free: set[Cell], w: int, h: int, bw: int, bl: int) -> list[Cell]:
    """Every anchor where a bw x bl rectangle lies wholly inside `free`."""
    out = []
    for y in range(h - bl + 1):
        for x in range(w - bw + 1):
            if all((x + dx, y + dy) in free
                   for dx in range(bw) for dy in range(bl)):
                out.append((x, y))
    return out


def exact_pack(free: set[Cell], width: int, height: int,
               fillers: list[Building], time_limit: float,
               workers: int = 8,
               hint: list[Placement] | None = None,
               objective: str = "count") -> tuple[list[Placement], list[Building]]:
    """Pack as many of `fillers` into `free` as possible.

    Returns (placements, unplaced). `placements` are (building, x, y) triples;
    a building appears in exactly one of the two lists.

    `hint` is a known-good partial packing (typically the greedy result) fed to
    the solver as a starting point. It is not optional in practice -- see the
    measurements in the module docstring.

    `objective` is "count" (maximise buildings placed -- what actually decides
    whether a layout survives) or "area".

    `workers` is CP-SAT's thread count and must be > 1: single-threaded, this
    model returns no solution at all below a 60s budget.
    """
    from ortools.sat.python import cp_model

    by_size: dict[tuple[int, int], list[Building]] = collections.defaultdict(list)
    for b in fillers:
        by_size[(b.footprint.width, b.footprint.length)].append(b)

    model = cp_model.CpModel()
    cover: dict[Cell, list] = collections.defaultdict(list)
    # size class -> {position: var}
    cls_vars: dict[tuple[int, int], dict[Cell, object]] = {}
    for (bw, bl), group in by_size.items():
        vars_at: dict[Cell, object] = {}
        for (x, y) in _positions(free, width, height, bw, bl):
            v = model.NewBoolVar(f"p{bw}x{bl}_{x}_{y}")
            vars_at[(x, y)] = v
            for dx in range(bw):
                for dy in range(bl):
                    cover[(x + dx, y + dy)].append(v)
        cls_vars[(bw, bl)] = vars_at
        if vars_at:
            model.Add(sum(vars_at.values()) <= len(group))

    for vs in cover.values():
        if len(vs) > 1:
            model.AddAtMostOne(vs)

    terms = []
    for (bw, bl), vars_at in cls_vars.items():
        weight = bw * bl if objective == "area" else 1
        terms.extend(weight * v for v in vars_at.values())
    if not terms:
        return [], list(fillers)
    model.Maximize(sum(terms))

    if hint:
        seen: set[tuple[int, int, int, int]] = set()
        for b, x, y in hint:
            bw, bl = b.footprint.width, b.footprint.length
            key = (bw, bl, x, y)
            v = cls_vars.get((bw, bl), {}).get((x, y))
            if v is not None and key not in seen:
                model.AddHint(v, 1)
                seen.add(key)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    # Floored at 2, not merely defaulted: single-threaded this model returns NO
    # solution at all on a real instance (0/231 at 5s, twice), so a caller that
    # innocently passes probe_workers=1 would get a repair that silently does
    # nothing. Measured on the user's city at a 5s budget, greedy = 222:
    #   workers=1 -> 0     workers=2 -> 228
    #   workers=4 -> 224-228   workers=8 -> 230
    solver.parameters.num_search_workers = max(2, workers)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], list(fillers)

    placements: list[Placement] = []
    unplaced: list[Building] = []
    for (bw, bl), vars_at in cls_vars.items():
        chosen = [pos for pos, v in vars_at.items() if solver.Value(v)]
        group = by_size[(bw, bl)]
        for b, (x, y) in zip(group, chosen):
            placements.append((b, x, y))
        unplaced.extend(group[len(chosen):])
    return placements, unplaced


def apply_placements(placements: list[Placement]) -> list[Building]:
    """Rebuild the buildings with the footprints the solver chose."""
    return [replace(b, footprint=Footprint(x, y, b.footprint.width,
                                           b.footprint.length))
            for b, x, y in placements]
