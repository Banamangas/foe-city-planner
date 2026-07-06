"""Corridor-granularity LNS (Track B, 2026-07-06 spec).

Destroy an under-used road corridor's neighbourhood, rebuild it as a balanced
double row around a 1-wide gap, keep only strict improvements. Roads are never
placed directly: route() recomputes the network from building positions, so a
repair shapes roads by shaping placements."""
from __future__ import annotations

import random
from dataclasses import replace

from foeopt.model import Building, Footprint, Layout
from foeopt.quality import road_cell_load
from foeopt.router import RouteError, route
from foeopt.validate import is_valid

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


def _underused(layout: Layout) -> set[Cell]:
    """Road cells with load <= 1, excluding tolerated junctions (a load-1 cell
    whose other >=3 orthogonal neighbours are roads — rule-2 semantics)."""
    load = road_cell_load(layout)
    roads = layout.roads
    out = set()
    for c, v in load.items():
        if v >= 2:
            continue
        n_road = sum(((c[0] + dx, c[1] + dy) in roads) for dx, dy in _ORTHO)
        if v == 1 and n_road >= 3:
            continue
        out.add(c)
    return out


def find_corridor(layout: Layout, rng: random.Random, *,
                  max_buildings: int = 12) -> tuple[list[Cell], list[Building]] | None:
    """One corridor pick: BFS-flood the under-used set from an rng-chosen seed
    cell; victims = non-TH buildings orthogonally adjacent to the run. Runs are
    truncated from the far end (BFS order) until the victim count fits."""
    cand = _underused(layout)
    if not cand:
        return None
    seed = rng.choice(sorted(cand))
    run: list[Cell] = [seed]
    seen = {seed}
    i = 0
    while i < len(run):                        # BFS: run stays sorted by distance
        cx, cy = run[i]
        i += 1
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in cand and n not in seen:
                seen.add(n)
                run.append(n)
    cell_owner: dict[Cell, Building] = {}
    for b in layout.buildings:
        if b.is_townhall:
            continue
        for c in b.footprint.cells():
            cell_owner[c] = b

    def victims_of(cells: list[Cell]) -> list[Building]:
        found: dict[int, Building] = {}
        for (cx, cy) in cells:
            for dx, dy in _ORTHO:
                b = cell_owner.get((cx + dx, cy + dy))
                if b is not None:
                    found[b.entity_id] = b
        return [found[k] for k in sorted(found)]

    while run:
        vs = victims_of(run)
        if len(vs) <= max_buildings:
            return (run, vs) if vs else None
        run = run[:-1]                         # drop the BFS-farthest cell
    return None


def _partition(frontages: list[int]) -> int:
    """Exact two-side split minimizing the longer side's total frontage.
    n <= 12 (destroy cap), so 2^n enumeration is trivial."""
    total = sum(frontages)
    best_mask, best_key = 0, None
    for mask in range(1 << len(frontages)):
        s = sum(f for i, f in enumerate(frontages) if mask >> i & 1)
        key = max(s, total - s)
        if best_key is None or key < best_key:
            best_mask, best_key = mask, key
    return best_mask


def _lane_candidates(area: set[Cell]) -> list[list[Cell]]:
    """Maximal straight 1-wide segments (len >= 2) inside `area`, both axes."""
    lanes: list[list[Cell]] = []
    for horiz in (True, False):
        key = (lambda c: (c[1], c[0])) if horiz else (lambda c: (c[0], c[1]))
        step = (1, 0) if horiz else (0, 1)
        cells = sorted(area, key=key)
        seg: list[Cell] = []
        for c in cells:
            if seg and (seg[-1][0] + step[0], seg[-1][1] + step[1]) == c:
                seg.append(c)
            else:
                if len(seg) >= 2:
                    lanes.append(seg)
                seg = [c]
        if len(seg) >= 2:
            lanes.append(seg)
    return lanes


def _place_row(members: list[Building], lane: list[Cell], side: int,
               free: set[Cell], horiz: bool) -> list[Building] | None:
    """Pack `members` shoulder-to-shoulder along the lane on one side.
    side=-1: before the lane row/col; side=+1: after. Returns re-footprinted
    buildings or None if any member cannot fit."""
    placed: list[Building] = []
    used: set[Cell] = set()
    cursor = 0
    lx, ly = lane[0]
    for b in members:
        w, l = b.footprint.width, b.footprint.length
        for ext, dep in ((min(w, l), max(w, l)), (max(w, l), min(w, l))):
            if horiz:
                bx = lx + cursor
                by = ly - dep if side < 0 else ly + 1
                fp = Footprint(bx, by, ext, dep)
            else:
                bx = lx - dep if side < 0 else lx + 1
                by = ly + cursor
                fp = Footprint(bx, by, dep, ext)
            cells = fp.cells()
            frontage = {(lx + i, ly) if horiz else (lx, ly + i)
                        for i in range(cursor, cursor + ext)}
            if cells <= (free - used) and frontage <= set(lane):
                placed.append(replace(b, footprint=fp))
                used |= cells
                cursor += ext
                break
        else:
            return None
    return placed


def _place_fillers(fillers: list[Building], free: set[Cell]) -> list[Building] | None:
    placed: list[Building] = []
    remaining = set(free)
    for b in sorted(fillers, key=lambda b: -(b.footprint.width * b.footprint.length)):
        w, l = b.footprint.width, b.footprint.length
        spot = None
        for (x, y) in sorted(remaining):
            for fw, fl in ((w, l), (l, w)):
                fp = Footprint(x, y, fw, fl)
                if fp.cells() <= remaining:
                    spot = fp
                    break
            if spot:
                break
        if spot is None:
            return None
        placed.append(replace(b, footprint=spot))
        remaining -= spot.cells()
    return placed


def rebuild_corridor(layout: Layout, run_cells: list[Cell], victims: list[Building],
                     rng: random.Random) -> Layout | None:
    victim_ids = {b.entity_id for b in victims}
    keep = [b for b in layout.buildings if b.entity_id not in victim_ids]
    occupied: set[Cell] = set()
    for b in keep:
        occupied |= b.footprint.cells()
    free = set(layout.region.cells) - occupied
    core: set[Cell] = set(run_cells)
    for v in victims:
        core |= v.footprint.cells()
    area = {c for c in free
            if c in core or any((c[0] + dx, c[1] + dy) in core for dx, dy in _ORTHO)}
    lanes = _lane_candidates(area)
    rng.shuffle(lanes)                      # tie-break order only, see below
    consumers = [v for v in victims if v.needs_road]
    fillers = [v for v in victims if not v.needs_road]
    best: Layout | None = None
    for lane in lanes:
        horiz = len(lane) > 1 and lane[1][1] == lane[0][1]
        if consumers:
            mask = _partition([min(b.footprint.width, b.footprint.length)
                               for b in consumers])
            side_a = [b for i, b in enumerate(consumers) if mask >> i & 1]
            side_b = [b for i, b in enumerate(consumers) if not mask >> i & 1]
        else:
            side_a, side_b = [], []
        lane_free = free - set(lane)           # buildings must not cover the lane
        rows_a = _place_row(side_a, lane, -1, lane_free, horiz)
        if rows_a is None:
            continue
        used_a: set[Cell] = set()
        for b in rows_a:
            used_a |= b.footprint.cells()
        rows_b = _place_row(side_b, lane, +1, lane_free - used_a, horiz)
        if rows_b is None:
            continue
        used: set[Cell] = set(used_a)
        for b in rows_b:
            used |= b.footprint.cells()
        filled = _place_fillers(fillers, free - used - set(lane))
        if filled is None:
            continue
        cand = Layout(layout.region, keep + rows_a + rows_b + filled,
                      layout.townhall, {})
        try:
            cand.roads = route(cand)
        except RouteError:
            continue
        if not is_valid(cand):
            continue
        # A lane that merely routes is not necessarily an improvement (a lane
        # far from the Townhall can cost more to connect than the double-load
        # saves). Evaluate every candidate lane and keep the fewest-roads one
        # instead of stopping at the first that happens to validate -- ties are
        # broken by the rng-shuffled scan order for diversity across repairs.
        if best is None or len(cand.roads) < len(best.roads):
            best = cand
    return best
