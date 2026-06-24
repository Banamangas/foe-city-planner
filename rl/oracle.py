"""Pure-stdlib branch-and-bound oracle for TINY placement instances (<=4 non-TH
buildings). Gives the optimal 0-unplaced road count for the M2/M3 principled
baseline (spec ss7) without adding ortools as a dependency. Only tractable on
tiny instances; use the random/greedy baselines + the Sigma/2 target for larger
ones. Time-budgeted."""
from __future__ import annotations

import time

from foeopt.model import Building, Footprint, Layout
from foeopt.router import RouteError, route
from foeopt.validate import is_valid

_MAX_NON_TH = 4


def optimal_roads(layout: Layout, *, budget_s: float = 30.0) -> int | None:
    non_th = [b for b in layout.buildings if not b.is_townhall]
    if len(non_th) > _MAX_NON_TH:
        raise ValueError(f"oracle limited to <= {_MAX_NON_TH} non-TH buildings, got {len(non_th)}")
    th = layout.townhall
    order = sorted(non_th, key=lambda b: (-(b.footprint.width * b.footprint.length), b.entity_id))
    deadline = time.time() + budget_s
    best: list[int | None] = [None]
    _dfs(layout.region.cells, set(th.footprint.cells()), [th], layout, order, 0,
         best, deadline)
    return best[0]


def _dfs(region_cells, occ, placed, layout, order, ptr, best, deadline):
    if best[0] == 0:                 # can't beat 0 roads
        return
    if time.time() > deadline:
        return
    if ptr == len(order):
        trial = Layout(layout.region, placed, layout.townhall, {})
        try:
            roads = route(trial)
        except RouteError:
            return
        trial.roads = roads
        if not is_valid(trial):
            return
        n = len(roads)
        if best[0] is None or n < best[0]:
            best[0] = n
        return
    b = order[ptr]
    w, l = b.footprint.width, b.footprint.length
    free = region_cells - occ
    # branch on anchors adjacent to occupancy first (the prior) to find good layouts fast,
    # which makes the bound prune aggressively; fall back to all free if none adjacent.
    frontier = [(x, y) for (x, y) in free
                if any((x + dx, y + dy) in occ for dx in (0, w - 1) for dy in (0, l - 1))]
    candidates = frontier or list(free)
    for (x, y) in sorted(candidates):
        cells = Footprint(x, y, w, l).cells()
        if not cells <= free:
            continue
        from foeopt.model import Building as _B
        placed2 = placed + [_B(b.entity_id, b.cityentity_id, b.type,
                               Footprint(x, y, w, l), b.needs_road, b.road_level,
                               b.is_townhall, b.set_id, b.chain_id, b.name)]
        _dfs(region_cells, occ | cells, placed2, layout, order, ptr + 1, best, deadline)