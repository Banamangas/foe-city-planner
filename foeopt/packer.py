from __future__ import annotations

from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packing import Grid, first_fit, first_fit_adjacent
from foeopt.router import RouteError, route


@dataclass
class PackConfig:
    orientation: str   # "h" (horizontal road rows) — only mode in Phase 2
    spacing: int       # rows between corridor lines
    trunk_x: int       # column for the vertical connecting trunk


@dataclass
class PackResult:
    layout: Layout
    unplaced: list[Building]


def classify(layout: Layout) -> tuple[Building, list[Building], list[Building]]:
    if layout.townhall is None:
        raise ValueError("layout has no townhall")
    consumers = [b for b in layout.buildings if b.needs_road and not b.is_townhall]
    fillers = [b for b in layout.buildings if not b.needs_road and not b.is_townhall]
    return layout.townhall, consumers, fillers


def bbox(region: Region) -> tuple[int, int]:
    xs = [c[0] for c in region.cells]
    ys = [c[1] for c in region.cells]
    return (max(xs) + 1, max(ys) + 1)


def _corridor_cells(region: frozenset[tuple[int, int]], w: int, h: int, cfg: PackConfig) -> set:
    cells = set()
    for y in range(0, h, cfg.spacing):          # horizontal road rows
        for x in range(w):
            if (x, y) in region:
                cells.add((x, y))
    for y in range(h):                           # vertical trunk joins the rows
        if (cfg.trunk_x, y) in region:
            cells.add((cfg.trunk_x, y))
    return cells


def build_candidate(layout: Layout, config: PackConfig) -> PackResult:
    region = layout.region.cells
    w, h = bbox(layout.region)
    blocked = {(x, y) for x in range(w) for y in range(h)} - region
    corridor = _corridor_cells(region, w, h, config)

    grid = Grid(w, h, blocked)
    grid.reserve(corridor)

    townhall, consumers, fillers = classify(layout)
    placed: dict[int, tuple[int, int]] = {}
    unplaced: list[Building] = []

    def area(b: Building) -> int:
        return b.footprint.width * b.footprint.length

    # Townhall first — prefer corridor-adjacent so the trunk can root on it.
    tw, tl = townhall.footprint.width, townhall.footprint.length
    pos = first_fit_adjacent(grid, tw, tl, corridor) or first_fit(grid, tw, tl)
    if pos is None:
        unplaced.append(townhall)
    else:
        grid.occupy(pos[0], pos[1], tw, tl)
        placed[townhall.entity_id] = pos

    # Consumers: corridor-adjacent, largest first.
    for b in sorted(consumers, key=area, reverse=True):
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit_adjacent(grid, bw, bl, corridor)
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p

    # Fillers: anywhere, largest first.
    for b in sorted(fillers, key=area, reverse=True):
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit(grid, bw, bl)
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p

    new_buildings: list[Building] = []
    new_townhall: Building | None = None
    for b in layout.buildings:
        if b.entity_id not in placed:
            continue
        x, y = placed[b.entity_id]
        moved = replace(b, footprint=Footprint(x, y, b.footprint.width, b.footprint.length))
        new_buildings.append(moved)
        if moved.is_townhall:
            new_townhall = moved

    candidate = Layout(region=layout.region, buildings=new_buildings,
                       townhall=new_townhall, roads={})
    try:
        candidate.roads = route(candidate)
    except RouteError:
        # No feasible road network for this placement — every consumer is
        # unsatisfiable. Add the spatially-placed consumers to the ones that
        # already failed placement, without double-counting.
        placed_consumers = [b for b in consumers if b.entity_id in placed]
        return PackResult(layout=candidate, unplaced=unplaced + placed_consumers)
    return PackResult(layout=candidate, unplaced=unplaced)
