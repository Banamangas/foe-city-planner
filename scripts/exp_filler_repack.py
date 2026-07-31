"""Ground-truth filler-packing test on the user's own city.

The expert layout is a PROOF that all 231 fillers fit around its roads and
road-needing buildings. So: strip the fillers, hand each packing strategy the
exact same free space, and count how many it can put back. Any shortfall is
purely packer weakness -- no CP-SAT, no search, no luck involved.

Strategies test the user's stated method: group by size, and avoid creating
gaps too small for anything remaining (their smallest filler is 1x2, so every
1x1 hole is dead space).
"""
import sys, pathlib, collections, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout
from foeopt.packing import Grid

ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def free_after(grid, W, H):
    return {(x, y) for y in range(H) for x in range(W) if grid.fits(x, y, 1, 1)}


def dead_cells(grid, W, H, min_w, min_l):
    """Free cells that cannot host the smallest remaining footprint in either
    orientation -- i.e. permanently wasted."""
    dead = 0
    for (x, y) in free_after(grid, W, H):
        if not (grid.fits(x, y, min_w, min_l) or grid.fits(x, y, min_l, min_w)
                or grid.fits(x - min_w + 1, y, min_w, min_l)
                or grid.fits(x, y - min_l + 1, min_w, min_l)):
            dead += 1
    return dead


def run(strategy, fillers, blocked, W, H):
    grid = Grid(W, H, set(blocked))
    order = strategy['order'](fillers)
    placed = 0
    placed_by_size = collections.defaultdict(list)
    for b in order:
        bw, bl = b.footprint.width, b.footprint.length
        spot = strategy['pick'](grid, bw, bl, W, H, placed_by_size)
        if spot is None:
            continue
        grid.occupy(spot[0], spot[1], bw, bl)
        placed_by_size[(bw, bl)].append(spot)
        placed += 1
    return placed, grid


def first_fit_pick(grid, bw, bl, W, H, _by_size):
    for y in range(H - bl + 1):
        for x in range(W - bw + 1):
            if grid.fits(x, y, bw, bl):
                return (x, y)
    return None


def tightness_pick(grid, bw, bl, W, H, _by_size):
    best, bs = None, -1
    for y in range(H - bl + 1):
        for x in range(W - bw + 1):
            if not grid.fits(x, y, bw, bl):
                continue
            s = 0
            for dx in range(bw):
                for yy in (y - 1, y + bl):
                    if not grid.fits(x + dx, yy, 1, 1):
                        s += 1
            for dy in range(bl):
                for xx in (x - 1, x + bw):
                    if not grid.fits(xx, y + dy, 1, 1):
                        s += 1
            if s > bs:
                best, bs = (x, y), s
    return best


def adjacent_same_size_pick(grid, bw, bl, W, H, by_size):
    """The user's method: keep same-size buildings together so they tile, and
    only fall back to tightness when no same-size neighbour exists."""
    same = by_size.get((bw, bl), [])
    if same:
        best, bs = None, -1
        for (px, py) in same:
            for cand in ((px + bw, py), (px - bw, py), (px, py + bl), (px, py - bl)):
                x, y = cand
                if 0 <= x <= W - bw and 0 <= y <= H - bl and grid.fits(x, y, bw, bl):
                    s = 0
                    for dx in range(bw):
                        for yy in (y - 1, y + bl):
                            if not grid.fits(x + dx, yy, 1, 1):
                                s += 1
                    if s > bs:
                        best, bs = (x, y), s
        if best:
            return best
    return tightness_pick(grid, bw, bl, W, H, by_size)


def hole_avoiding_pick(grid, bw, bl, W, H, _by_size):
    """Minimise DEAD SPACE created, not local tightness.

    The user's stated failure mode: place rashly and you are left with 1x1 and
    2x1 gaps nothing can occupy. Their smallest filler is 1x2, so any free cell
    that cannot host a 1x2 in either orientation is permanently wasted. With 3
    cells of slack on this instance, dead space IS the constraint -- the shipped
    tightness packer leaves 11 and therefore cannot finish.

    Scores each candidate by how many newly-dead cells it would create in its
    immediate neighbourhood, tie-broken by tightness.
    """
    best, best_key = None, None
    for y in range(H - bl + 1):
        for x in range(W - bw + 1):
            if not grid.fits(x, y, bw, bl):
                continue
            grid.occupy(x, y, bw, bl)
            newly_dead = 0
            tight = 0
            for cx in range(max(0, x - 2), min(W, x + bw + 2)):
                for cy in range(max(0, y - 2), min(H, y + bl + 2)):
                    if not grid.fits(cx, cy, 1, 1):
                        continue
                    if not (grid.fits(cx, cy, 1, 2) or grid.fits(cx, cy, 2, 1)
                            or grid.fits(cx, cy - 1, 1, 2) or grid.fits(cx - 1, cy, 2, 1)):
                        newly_dead += 1
            for dx in range(bw):
                for yy in (y - 1, y + bl):
                    if not grid.fits(x + dx, yy, 1, 1):
                        tight += 1
            for dy in range(bl):
                for xx in (x - 1, x + bw):
                    if not grid.fits(xx, y + dy, 1, 1):
                        tight += 1
            grid._unavail -= {(x + dx, y + dy) for dx in range(bw) for dy in range(bl)}
            key = (newly_dead, -tight)
            if best_key is None or key < best_key:
                best, best_key = (x, y), key
    return best


def main():
    lay = load_layout('city-user-data.json', 'city-user-data-foe-helper.json')
    region = set(lay.region.cells)
    xs = [c[0] for c in region]; ys = [c[1] for c in region]
    W, H = max(xs) + 1, max(ys) + 1
    fillers = [b for b in lay.buildings if not b.needs_road and not b.is_townhall]
    keep = [b for b in lay.buildings if b.needs_road or b.is_townhall]
    occupied = set(lay.roads or [])
    for b in keep:
        occupied |= b.footprint.cells()
    blocked = {(x, y) for x in range(W) for y in range(H)} - (region - occupied)
    freecells = len(region - occupied)
    fa = sum(b.footprint.width * b.footprint.length for b in fillers)
    print(f"user city: {len(fillers)} fillers, area {fa}, free cells {freecells} "
          f"(slack {freecells - fa})")
    print(f"GROUND TRUTH: the expert fits all {len(fillers)}\n")
    area = lambda b: b.footprint.width * b.footprint.length
    strategies = {
        "first-fit, area-desc (the ORIGINAL packer)":
            {'order': lambda f: sorted(f, key=lambda b: -area(b)), 'pick': first_fit_pick},
        "best-fit tightness, area-desc (what I SHIPPED)":
            {'order': lambda f: sorted(f, key=lambda b: -area(b)), 'pick': tightness_pick},
        "size-grouped + adjacent-same-size (the user's method)":
            {'order': lambda f: sorted(f, key=lambda b: (-area(b), b.footprint.width, b.footprint.length)),
             'pick': adjacent_same_size_pick},
        "hole-avoiding (minimise dead space), area-desc":
            {'order': lambda f: sorted(f, key=lambda b: -area(b)), 'pick': hole_avoiding_pick},
        "hole-avoiding + size-grouped order":
            {'order': lambda f: sorted(f, key=lambda b: (-area(b), b.footprint.width, b.footprint.length)),
             'pick': hole_avoiding_pick},
    }
    for name, st in strategies.items():
        t = time.perf_counter()
        placed, grid = run(st, fillers, blocked, W, H)
        dead = dead_cells(grid, W, H, 1, 2)
        print(f"  {name:52s} {placed:3d}/{len(fillers)}  "
              f"dead cells left {dead:4d}  ({time.perf_counter()-t:.1f}s)")


if __name__ == "__main__":
    main()
