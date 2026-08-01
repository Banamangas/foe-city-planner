"""Design A/B for the exact filler-packing repair pass, on the user's own city.

Ground truth: all 231 fillers provably fit (slack 3 cells). The shipped greedy
packer reaches 222. Two open design choices:

  1. objective -- maximise COUNT (what actually decides survival) or AREA?
  2. does hinting the greedy solution stop the solver ever returning worse?

Both are measured at the budgets a repair pass could plausibly afford.
"""
import sys, pathlib, time
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout
from foeopt.packing import Grid
from foeopt.roads_first import _place_fillers
from foeopt.exact_packing import exact_pack


def instance():
    lay = load_layout('city-user-data.json', 'city-user-data-foe-helper.json')
    region = set(lay.region.cells)
    W = max(c[0] for c in region) + 1
    H = max(c[1] for c in region) + 1
    fillers = [b for b in lay.buildings if not b.needs_road and not b.is_townhall]
    keep = [b for b in lay.buildings if b.needs_road or b.is_townhall]
    occupied = set(lay.roads or [])
    for b in keep:
        occupied |= b.footprint.cells()
    return region - occupied, W, H, fillers


def greedy(free, W, H, fillers):
    blocked = {(x, y) for x in range(W) for y in range(H)} - free
    grid = Grid(W, H, blocked)
    cand = SimpleNamespace(buildings=[])
    t = time.perf_counter()
    unplaced = _place_fillers(grid, fillers, cand)
    el = time.perf_counter() - t
    hint = [(b, b.footprint.x, b.footprint.y) for b in cand.buildings]
    return hint, len(unplaced), el


def main():
    free, W, H, fillers = instance()
    n = len(fillers)
    print(f"user city: {n} fillers, {len(free)} free cells, "
          f"slack {len(free) - sum(b.footprint.width*b.footprint.length for b in fillers)}")

    hint, n_unplaced, el = greedy(free, W, H, fillers)
    print(f"GREEDY (shipped): {n - n_unplaced}/{n} in {el:.2f}s  <- the bar to beat\n")

    for workers in (1, 8):
        print(f"--- num_search_workers = {workers} ---")
        for tl in (5.0, 10.0, 30.0, 60.0):
            row = []
            for obj in ("count", "area"):
                for use_hint in (False, True):
                    t = time.perf_counter()
                    placed, un = exact_pack(free, W, H, fillers, tl,
                                            workers=workers,
                                            hint=hint if use_hint else None,
                                            objective=obj)
                    dt = time.perf_counter() - t
                    tag = f"{obj}{'+hint' if use_hint else '     '}"
                    row.append(f"{tag}: {len(placed):3d} ({dt:4.1f}s)")
            print(f"  {tl:5.1f}s budget | " + " | ".join(row))
        print()


if __name__ == "__main__":
    main()
