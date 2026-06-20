from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packing import Grid, first_fit, first_fit_adjacent
from foeopt.router import RouteError, route

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class PackConfig:
    anchor: str   # Townhall start corner: "bl" | "br" | "tl" | "tr"
    seed: int     # seeds the building-order tie-break (road growth is deterministic)


@dataclass
class PackResult:
    layout: Layout
    unplaced: list[Building]
    trials: int = 0


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
    """Bottom-left-most free region cell orthogonally adjacent to the road set.

    Deterministic on purpose: randomizing the growth direction measurably degrades
    the road tree (DarkZig best 58 unplaced vs 17 with bottom-left growth). The
    multi-start's diversity comes from the anchor and the building order instead.
    """
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

    rng = random.Random(config.seed)

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
    remaining = sorted(consumers, key=lambda b: (-area(b), rng.random()))
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
    for b in sorted(fillers, key=lambda b: (-area(b), rng.random())):
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
    # Post-route gap-fill: routing prunes the reserved corridor down to the
    # minimal roads, freeing reserved-but-unused cells. Offer them to the
    # still-unplaced fillers (road-needing buildings must stay road-adjacent and
    # are never gap-filled). Roads are unchanged, so no re-route is needed.
    occupied: set[tuple[int, int]] = set()
    for b in candidate.buildings:
        occupied |= b.footprint.cells()
    free = region - occupied - set(candidate.roads)
    # block everything outside `free`, so placements stay in-region and off roads
    gap_grid = Grid(w, h, {(x, y) for x in range(w) for y in range(h)} - free)
    still_unplaced: list[Building] = []
    for b in sorted(unplaced, key=lambda b: (-area(b), rng.random())):
        if b.needs_road:
            still_unplaced.append(b)
            continue
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit(gap_grid, bw, bl)
        if p is None:
            still_unplaced.append(b)
            continue
        gap_grid.occupy(p[0], p[1], bw, bl)
        candidate.buildings.append(
            replace(b, footprint=Footprint(p[0], p[1], bw, bl))
        )
    return PackResult(layout=candidate, unplaced=still_unplaced)


def repack(layout: Layout, *, thorough: bool = False,
           budget_seconds: float | None = None, seed: int = 0) -> PackResult:
    """Budgeted randomized multi-start: try many randomized packings, keep the
    best by (fewest unplaced, then fewest roads). Deterministic given `seed` and
    the number of trials completed. Runs until the time budget so it minimizes
    roads among fully-placed layouts (no early-exit on first full placement)."""
    if budget_seconds is None:
        budget_seconds = 120.0 if thorough else 30.0
    master = random.Random(seed)
    anchors = ("bl", "br", "tl", "tr")
    best: PackResult | None = None
    best_key: tuple[int, int] | None = None
    trials = 0
    deadline = time.monotonic() + budget_seconds
    while True:
        cfg = PackConfig(master.choice(anchors), master.randrange(2 ** 32))
        res = build_candidate(layout, cfg)
        trials += 1
        key = (len(res.unplaced), len(res.layout.roads))
        if best_key is None or key < best_key:
            best, best_key = res, key
        if time.monotonic() >= deadline:
            break
    assert best is not None             # the loop body always runs at least once
    best.trials = trials
    return best
