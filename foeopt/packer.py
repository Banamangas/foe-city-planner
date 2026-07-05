from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packing import Grid, first_fit, first_fit_adjacent
from foeopt.reach import ReachChecker
from foeopt.router import RouteError, route

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class PackConfig:
    anchor: str   # Townhall start corner: "bl" | "br" | "tl" | "tr"
    seed: int     # seeds the building-order tie-break (road growth is deterministic)
    th_style: str = "corner"  # "corner" (status quo) | "stub" (offset TH + corner stubs)


@dataclass
class PackResult:
    layout: Layout
    unplaced: list[Building]
    trials: int = 0
    base_roads: int | None = None   # roads before any polish (anneal); set by polish()


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


def _stub_fit(
    grid: Grid, region, tw: int, tl: int, anchor: str
) -> tuple[tuple[int, int], tuple[tuple[int, int], tuple[int, int]]] | None:
    """Like `_corner_fit`, but only accepts a position where a "flank pair" --
    the two road cells flanking the TH along the row facing the region
    interior -- is also placeable. Scans in the exact same order as
    `_corner_fit`; returns (townhall_pos, flank_pair) for the first position
    where both fit, else None (caller falls back to `_corner_fit`).

    Flank pair for TH at (x, y, tw, tl): primary row = y + tl - 1 for "bl"/"br"
    (TH lands at small y, so the row facing the interior is the TH's top row),
    y for "tl"/"tr" (TH lands at large y, interior-facing row is the bottom).
    Pair = (x - 1, row) and (x + tw, row). If the primary row's pair is
    unavailable, the opposite row's pair is tried before moving on.

    Acceptance requires more than the flank cells themselves being free: each
    flank cell's 3 non-TH orthogonal neighbors must also be in-region and
    free, so every stub starts with all 3 of its serviceable sides open. A
    boundary-flush position would leave one stub in a 1-wide corridor whose
    single open side the greedy grow-tree then dead-ends.
    """
    xs = range(grid.width) if anchor in ("bl", "tl") else range(grid.width - 1, -1, -1)
    ys = range(grid.height) if anchor in ("bl", "br") else range(grid.height - 1, -1, -1)

    def flank_ok(cx: int, cy: int, th_dx: int) -> bool:
        # The TH abuts the flank at (cx + th_dx, cy); the flank cell itself
        # and its 3 other orthogonal neighbors must be in-region and free.
        checks = ((cx, cy), (cx - th_dx, cy), (cx, cy - 1), (cx, cy + 1))
        return all(c in region and grid.is_available(c) for c in checks)

    for y in ys:
        for x in xs:
            if not grid.fits(x, y, tw, tl):
                continue
            rows = (y + tl - 1, y) if anchor in ("bl", "br") else (y, y + tl - 1)
            for row in rows:
                if flank_ok(x - 1, row, 1) and flank_ok(x + tw, row, -1):
                    return (x, y), ((x - 1, row), (x + tw, row))
    return None


def _pinwheel_prepack(
    grid: Grid,
    region,
    stub: tuple[int, int],
    remaining: list[Building],
    bocc: set[tuple[int, int]],
    guarded: list[frozenset[tuple[int, int]]],
    placed: dict[int, tuple[int, int]],
    safe_ok,
) -> None:
    """Place road-needing consumers directly adjacent to a TH corner-stub
    cell, pinwheeling around its free orthogonal sides (one of the 4 always
    abuts the TH, so at most 3 consumers land per stub). Deterministic:
    each pass walks `remaining` in its existing (biggest-first) order; for
    each consumer, the first fitting anchor among the four sides (left,
    right, above, below the stub, in that order) is taken immediately.
    Passes repeat until the stub has no free orthogonal neighbor left, or one
    full pass places nothing. Mutates grid/remaining/bocc/guarded/placed."""
    sx, sy = stub
    while True:
        free_neighbors = any(
            n in region and grid.is_available(n)
            for n in ((sx + 1, sy), (sx - 1, sy), (sx, sy + 1), (sx, sy - 1))
        )
        if not free_neighbors:
            return
        placed_any = False
        for b in list(remaining):
            bw, bl = b.footprint.width, b.footprint.length
            anchors = (
                [(sx - bw, sy - dy) for dy in range(bl)]
                + [(sx + 1, sy - dy) for dy in range(bl)]
                + [(sx - dx, sy - bl) for dx in range(bw)]
                + [(sx - dx, sy + 1) for dx in range(bw)]
            )
            ok = safe_ok(b)
            anchor = next(
                (a for a in anchors
                 if grid.fits(a[0], a[1], bw, bl) and (ok is None or ok(a[0], a[1]))),
                None,
            )
            if anchor is None:
                continue
            ax, ay = anchor
            grid.occupy(ax, ay, bw, bl)
            placed[b.entity_id] = (ax, ay)
            bocc |= Footprint(ax, ay, bw, bl).cells()
            if b.needs_road:
                guarded.append(Footprint(ax, ay, bw, bl).border_cells())
            remaining.remove(b)
            placed_any = True
        if not placed_any:
            return


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


def build_candidate(layout: Layout, config: PackConfig, *,
                    safe_placements: bool = False) -> PackResult:
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

    # 1. Townhall at the chosen corner. th_style="stub" scans for the first
    #    position that also admits a flank-pair of corner-stub road cells;
    #    falling back to plain _corner_fit (like th_style="corner") when none
    #    exists anywhere in the region.
    tw, tl = townhall.footprint.width, townhall.footprint.length
    stub_pair: tuple[tuple[int, int], tuple[int, int]] | None = None
    pos = None
    if config.th_style == "stub":
        found = _stub_fit(grid, region, tw, tl, config.anchor)
        if found is not None:
            pos, stub_pair = found
    if pos is None:
        pos = _corner_fit(grid, tw, tl, config.anchor)
    if pos is None:
        empty = Layout(layout.region, [], None, {})
        return PackResult(layout=empty, unplaced=list(layout.buildings))
    grid.occupy(pos[0], pos[1], tw, tl)
    placed[townhall.entity_id] = pos
    th_border = Footprint(pos[0], pos[1], tw, tl).border_cells()
    th_cells = set(Footprint(pos[0], pos[1], tw, tl).cells())
    bocc: set[tuple[int, int]] = set(th_cells)
    guarded: list[frozenset[tuple[int, int]]] = [th_border]

    # The road set is created here (rather than at step 2, as in plain
    # "corner" packing) so the stub cells can be reserved into it immediately.
    road: set[tuple[int, int]] = set()
    if stub_pair is not None:
        for c in stub_pair:
            grid.reserve([c])
            road.add(c)

    def _safe_ok(b: Building):
        if not safe_placements:
            return None
        checker = ReachChecker(region - bocc, road | th_cells, guarded=guarded)
        bw, bl = b.footprint.width, b.footprint.length

        def ok(x: int, y: int) -> bool:
            fp = Footprint(x, y, bw, bl)
            extra = (fp.border_cells(),) if b.needs_road else ()
            return checker.is_safe(fp.cells(), extra_guarded=extra)
        return ok

    remaining = sorted(consumers, key=lambda b: (-area(b), rng.random()))

    # 1b. Pinwheel pre-pack: before the border seed / grow-tree, try to ring
    #     each corner stub with up to 3 road-needing consumers (load-3 cells).
    if stub_pair is not None:
        for stub in stub_pair:
            _pinwheel_prepack(grid, region, stub, remaining, bocc, guarded, placed, _safe_ok)

    # 2. Seed the road network with a free Townhall-border cell.
    seed = min((c for c in th_border if c in region and grid.is_available(c)),
               default=None)
    if seed is not None:
        road.add(seed)
        grid.reserve([seed])

    # 3. Grow the road and attach road-needing buildings.
    #    road_target ensures the road extends past each placed building so the
    #    next building has room to attach without boxing in the road.
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
        p = first_fit_adjacent(grid, bw, bl, road, ok=_safe_ok(b))
        if p is not None:
            grid.occupy(p[0], p[1], bw, bl)
            placed[b.entity_id] = p
            bocc |= Footprint(p[0], p[1], bw, bl).cells()
            if b.needs_road:
                guarded.append(Footprint(p[0], p[1], bw, bl).border_cells())
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
        p = first_fit(grid, bw, bl, ok=_safe_ok(b))
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p
        bocc |= Footprint(p[0], p[1], bw, bl).cells()

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
           budget_seconds: float | None = None, seed: int = 0,
           safe_placements: bool = False,
           th_stub_template: bool = False) -> PackResult:
    """Budgeted randomized multi-start: try many randomized packings, keep the
    best by (fewest unplaced, then fewest roads). Deterministic given `seed` and
    the number of trials completed. Runs until the time budget so it minimizes
    roads among fully-placed layouts (no early-exit on first full placement).

    `th_stub_template`: when True, each trial's `PackConfig` also explores
    `th_style="stub"` (default-off; flag-gated per tasks/lessons.md -- proxy
    tweaks bolted onto the greedy have historically hurt the measured
    0-unplaced road count, so this is judged by A/B only). When False the
    portfolio is byte-identical to today's."""
    if budget_seconds is None:
        budget_seconds = 120.0 if thorough else 30.0
    master = random.Random(seed)
    anchors = ("bl", "br", "tl", "tr")
    best: PackResult | None = None
    best_key: tuple[int, int] | None = None
    trials = 0
    deadline = time.monotonic() + budget_seconds
    while True:
        if th_stub_template:
            cfg = PackConfig(master.choice(anchors), master.randrange(2 ** 32),
                             th_style=master.choice(("corner", "stub")))
        else:
            cfg = PackConfig(master.choice(anchors), master.randrange(2 ** 32))
        res = build_candidate(layout, cfg, safe_placements=safe_placements)
        trials += 1
        key = (len(res.unplaced), len(res.layout.roads))
        if best_key is None or key < best_key:
            best, best_key = res, key
        if time.monotonic() >= deadline:
            break
    assert best is not None             # the loop body always runs at least once
    best.trials = trials
    return best
