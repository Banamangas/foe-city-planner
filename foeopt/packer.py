from __future__ import annotations

from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packing import Grid, first_fit, first_fit_adjacent
from foeopt.router import RouteError, route
from foeopt.validate import is_valid

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class PackConfig:
    anchor: str   # Townhall start corner: "bl" | "br" | "tl" | "tr"
    order: str    # building order; "area" = largest first (reserved knob)


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


def _corner_fit(grid: Grid, w: int, l: int, anchor: str) -> tuple[int, int] | None:
    xs = range(grid.width) if anchor in ("bl", "tl") else range(grid.width - 1, -1, -1)
    ys = range(grid.height) if anchor in ("bl", "br") else range(grid.height - 1, -1, -1)
    for y in ys:
        for x in xs:
            if grid.fits(x, y, w, l):
                return (x, y)
    return None


def _road_frontier_cell(grid: Grid, road: set, region) -> tuple[int, int] | None:
    """Bottom-left-most free region cell orthogonally adjacent to the road set."""
    best = None
    for (rx, ry) in road:
        for dx, dy in _ORTHO:
            n = (rx + dx, ry + dy)
            if n in region and n not in road and grid.is_available(n):
                if best is None or n < best:
                    best = n
    return best


def build_candidate(layout: Layout, config: PackConfig) -> PackResult:
    region = layout.region.cells
    w, h = bbox(layout.region)
    blocked = {(x, y) for x in range(w) for y in range(h)} - region
    grid = Grid(w, h, blocked)
    townhall, consumers, fillers = classify(layout)
    placed: dict[int, tuple[int, int]] = {}
    unplaced: list[Building] = []

    def area(b: Building) -> int:
        return b.footprint.width * b.footprint.length

    # 1. Townhall at the chosen corner.
    tw, tl = townhall.footprint.width, townhall.footprint.length
    pos = _corner_fit(grid, tw, tl, config.anchor)
    if pos is None:
        empty = Layout(layout.region, [], None, {})
        return PackResult(layout=empty, unplaced=list(layout.buildings))
    grid.occupy(pos[0], pos[1], tw, tl)
    placed[townhall.entity_id] = pos
    th_border = Footprint(pos[0], pos[1], tw, tl).border_cells()

    # 2. Seed the road network with a free Townhall-border cell.
    road: set[tuple[int, int]] = set()
    seed = min((c for c in th_border if c in region and grid.is_available(c)),
               default=None)
    if seed is not None:
        road.add(seed)
        grid.reserve([seed])

    # 3. Grow the road and attach road-needing buildings.
    #    road_target ensures the road extends past each placed building so the
    #    next building has room to attach without boxing in the road.
    remaining = sorted(consumers, key=area, reverse=True)
    road_target = 1
    while remaining and road:
        b = remaining[0]
        bw, bl = b.footprint.width, b.footprint.length
        # Pre-grow road to target length before attempting placement.
        while len(road) < road_target:
            cell = _road_frontier_cell(grid, road, region)
            if cell is None:
                break
            road.add(cell)
            grid.reserve([cell])
        p = first_fit_adjacent(grid, bw, bl, road)
        if p is not None:
            grid.occupy(p[0], p[1], bw, bl)
            placed[b.entity_id] = p
            remaining.pop(0)
            # Advance target so road extends past the newly placed building.
            road_target = len(road) + max(bw, bl)
            continue
        cell = _road_frontier_cell(grid, road, region)
        if cell is None:
            break  # cannot grow the road any further
        road.add(cell)
        grid.reserve([cell])
    unplaced.extend(remaining)

    # 4. Fillers: densest first, anywhere free.
    for b in sorted(fillers, key=area, reverse=True):
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit(grid, bw, bl)
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p

    # 5. Build candidate + route for the minimal road set.
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
        # No feasible road network (should not happen for the grow-tree, where
        # every placed consumer borders a connected road). Move the placed
        # consumers fully to `unplaced` and drop them from the layout so a
        # building is never listed in both places.
        placed_consumers = [b for b in consumers if b.entity_id in placed]
        moved_ids = {b.entity_id for b in placed_consumers}
        kept = [b for b in new_buildings if b.entity_id not in moved_ids]
        rejected = Layout(region=layout.region, buildings=kept,
                          townhall=new_townhall, roads={})
        return PackResult(layout=rejected, unplaced=unplaced + placed_consumers)
    return PackResult(layout=candidate, unplaced=unplaced)


def _configs(layout: Layout, thorough: bool) -> list[PackConfig]:
    if not thorough:
        return [PackConfig("bl", "area")]
    return [
        PackConfig(anchor, "area")
        for anchor in ("bl", "br", "tl", "tr")
    ]


def repack(layout: Layout, thorough: bool = False) -> PackResult:
    best: PackResult | None = None
    best_key: tuple[int, int, int] | None = None
    for cfg in _configs(layout, thorough):
        res = build_candidate(layout, cfg)
        fully_valid = not res.unplaced and is_valid(res.layout)
        # sort key: valid candidates first (0), then fewer unplaced, then roads
        key = (0 if fully_valid else 1, len(res.unplaced), len(res.layout.roads))
        if best_key is None or key < best_key:
            best, best_key = res, key
    assert best is not None  # _configs always yields at least one config
    return best
