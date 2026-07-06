"""Corridor-granularity LNS (Track B, 2026-07-06 spec).

Destroy an under-used road corridor's neighbourhood, rebuild it as a balanced
double row around a 1-wide gap, keep only strict improvements. Roads are never
placed directly: route() recomputes the network from building positions, so a
repair shapes roads by shaping placements."""
from __future__ import annotations

import random

from foeopt.model import Building, Layout
from foeopt.quality import road_cell_load

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
