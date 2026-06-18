from __future__ import annotations

from dataclasses import replace

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
