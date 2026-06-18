from __future__ import annotations

import time
from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout


def _cells_except(layout: Layout, exclude_ids: set[int]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for b in layout.buildings:
        if b.entity_id in exclude_ids:
            continue
        cells |= b.footprint.cells()
    return cells


def _find(layout: Layout, entity_id: int) -> Building | None:
    for b in layout.buildings:
        if b.entity_id == entity_id:
            return b
    return None


def move_building(
    layout: Layout, entity_id: int, new_x: int, new_y: int
) -> Layout | None:
    target = _find(layout, entity_id)
    if target is None:
        return None
    fp = Footprint(new_x, new_y, target.footprint.width, target.footprint.length)
    cells = fp.cells()
    if not cells <= layout.region.cells:
        return None
    if cells & _cells_except(layout, {entity_id}):
        return None
    moved = replace(target, footprint=fp)
    buildings = [moved if b.entity_id == entity_id else b for b in layout.buildings]
    townhall = moved if target.is_townhall else layout.townhall
    return Layout(region=layout.region, buildings=buildings, townhall=townhall, roads={})


def swap_buildings(layout: Layout, id_a: int, id_b: int) -> Layout | None:
    if id_a == id_b:
        return None
    a, b = _find(layout, id_a), _find(layout, id_b)
    if a is None or b is None:
        return None
    fa = Footprint(b.footprint.x, b.footprint.y, a.footprint.width, a.footprint.length)
    fb = Footprint(a.footprint.x, a.footprint.y, b.footprint.width, b.footprint.length)
    ca, cb = fa.cells(), fb.cells()
    if not (ca <= layout.region.cells and cb <= layout.region.cells):
        return None
    if ca & cb:
        return None
    others = _cells_except(layout, {id_a, id_b})
    if (ca | cb) & others:
        return None
    na, nb = replace(a, footprint=fa), replace(b, footprint=fb)
    townhall = layout.townhall
    buildings: list[Building] = []
    for bld in layout.buildings:
        if bld.entity_id == id_a:
            buildings.append(na)
            townhall = na if a.is_townhall else townhall
        elif bld.entity_id == id_b:
            buildings.append(nb)
            townhall = nb if b.is_townhall else townhall
        else:
            buildings.append(bld)
    return Layout(region=layout.region, buildings=buildings, townhall=townhall, roads={})


def free_cells(layout: Layout) -> set[tuple[int, int]]:
    return set(layout.region.cells) - _cells_except(layout, set())


def same_footprint_swaps(layout: Layout) -> list[tuple[int, int]]:
    by_size: dict[tuple[int, int], list[Building]] = {}
    for b in layout.buildings:
        if b.is_townhall:
            continue
        by_size.setdefault((b.footprint.width, b.footprint.length), []).append(b)
    pairs: list[tuple[int, int]] = []
    for group in by_size.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pairs.append((group[i].entity_id, group[j].entity_id))
    return pairs


def relocate_candidates(
    layout: Layout, road_cells: set[tuple[int, int]]
) -> list[tuple[int, int, int]]:
    free = free_cells(layout)
    out: list[tuple[int, int, int]] = []
    for b in layout.buildings:
        if b.is_townhall:
            continue
        w, l = b.footprint.width, b.footprint.length
        for (x, y) in sorted(free, key=lambda p: (p[1], p[0])):
            fp = Footprint(x, y, w, l)
            if fp.cells() <= free and (fp.border_cells() & road_cells):
                out.append((b.entity_id, x, y))
                break
    return out


_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _road_degree(road_cells: set[tuple[int, int]], cell: tuple[int, int]) -> int:
    cx, cy = cell
    return sum(1 for dx, dy in _ORTHO if (cx + dx, cy + dy) in road_cells)


def spur_served_buildings(layout: Layout) -> list[int]:
    road = set(layout.roads)
    out: list[int] = []
    for b in layout.road_needing():
        adjacent = [c for c in b.footprint.border_cells() if c in road]
        if adjacent and any(_road_degree(road, c) == 1 for c in adjacent):
            out.append(b.entity_id)
    return sorted(out)


@dataclass
class OptimizeResult:
    layout: Layout
    moves_applied: int


def _candidate_moves(layout: Layout):
    """Yield ('swap', a, b) or ('move', eid, x, y) in priority order."""
    road_cells = set(layout.roads)
    spur_ids = set(spur_served_buildings(layout))

    swaps = same_footprint_swaps(layout)
    relocs = relocate_candidates(layout, road_cells)

    # 1) swaps touching a spur-served building
    for a, b in swaps:
        if a in spur_ids or b in spur_ids:
            yield ("swap", a, b)
    # 2) relocations of spur-served buildings
    for eid, x, y in relocs:
        if eid in spur_ids:
            yield ("move", eid, x, y)
    # 3) all remaining swaps
    for a, b in swaps:
        if a not in spur_ids and b not in spur_ids:
            yield ("swap", a, b)
    # 4) all remaining relocations
    for eid, x, y in relocs:
        if eid not in spur_ids:
            yield ("move", eid, x, y)


def _apply(layout: Layout, move) -> Layout | None:
    if move[0] == "swap":
        return swap_buildings(layout, move[1], move[2])
    return move_building(layout, move[1], move[2], move[3])


def optimize(
    layout: Layout, budget_seconds: float = 30.0, max_iters: int = 1_000_000
) -> OptimizeResult:
    from foeopt.router import RouteError, route
    from foeopt.validate import is_valid

    state = layout
    best = len(state.roads)
    moves_applied = 0
    deadline = time.monotonic() + budget_seconds
    iters = 0

    while time.monotonic() < deadline and iters < max_iters:
        iters += 1
        improved = False
        for move in _candidate_moves(state):
            if time.monotonic() >= deadline:
                break
            cand = _apply(state, move)
            if cand is None:
                continue
            try:
                roads = route(cand)
            except RouteError:
                continue
            if len(roads) < best:
                candidate = Layout(cand.region, cand.buildings, cand.townhall, roads)
                if is_valid(candidate):
                    state = candidate
                    best = len(roads)
                    moves_applied += 1
                    improved = True
                    break
        if not improved:
            break

    return OptimizeResult(layout=state, moves_applied=moves_applied)
