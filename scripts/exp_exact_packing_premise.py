"""PREMISE TEST B -- is exact (CP-SAT) filler packing tractable at real scale?

Filler placement is pure rectangle packing: no road adjacency, no connectivity.
So CP-SAT can in principle solve it optimally. The only question is whether it
does so in usable time on the biggest realistic instance.

Stress test: the user's own city, 231 fillers into 2486 free cells with 3 cells
of slack -- and a PROVEN feasible answer, so a correct solver must find 231.
The shipped greedy packer plateaus at 222.

Model note: buildings cannot rotate (hard domain constraint), so (4,3) and
(3,4) are different classes. Identical buildings are interchangeable, so the
model is over SIZE CLASSES ("place n_s rectangles of size s"), not over
individual buildings -- that removes 231! worth of symmetry.
"""
import sys, pathlib, collections, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout
from ortools.sat.python import cp_model


def build_and_solve(free, W, H, sizes, time_limit, workers=8, maximize=True):
    cover = collections.defaultdict(list)   # cell -> [vars]
    model = cp_model.CpModel()
    per_class = {}
    nvars = 0
    for (w, l), n in sizes.items():
        vs = []
        for y in range(H - l + 1):
            for x in range(W - w + 1):
                cells = [(x + dx, y + dy) for dx in range(w) for dy in range(l)]
                if any(c not in free for c in cells):
                    continue
                v = model.NewBoolVar(f"p{w}x{l}_{x}_{y}")
                vs.append(v)
                for c in cells:
                    cover[c].append(v)
        nvars += len(vs)
        per_class[(w, l)] = (vs, n)
        if maximize:
            model.Add(sum(vs) <= n)
        else:
            model.Add(sum(vs) == n)
    for c, vs in cover.items():
        if len(vs) > 1:
            model.AddAtMostOne(vs)
    if maximize:
        model.Maximize(sum(w * l * v for (w, l), (vs, _) in per_class.items() for v in vs))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    t = time.perf_counter()
    st = solver.Solve(model)
    el = time.perf_counter() - t
    placed = 0
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        placed = sum(int(solver.Value(v)) for (vs, _) in per_class.values() for v in vs)
    return solver.StatusName(st), placed, el, nvars, len(cover)


def main():
    lay = load_layout('city-user-data.json', 'city-user-data-foe-helper.json')
    region = set(lay.region.cells)
    W = max(c[0] for c in region) + 1
    H = max(c[1] for c in region) + 1
    fillers = [b for b in lay.buildings if not b.needs_road and not b.is_townhall]
    keep = [b for b in lay.buildings if b.needs_road or b.is_townhall]
    occupied = set(lay.roads or [])
    for b in keep:
        occupied |= b.footprint.cells()
    free = region - occupied
    sizes = collections.Counter(
        (b.footprint.width, b.footprint.length) for b in fillers)
    total = sum(sizes.values())
    print(f"user city: {total} fillers, {len(free)} free cells, "
          f"slack {len(free) - sum(w*l*n for (w,l),n in sizes.items())}")
    print(f"GROUND TRUTH: 231 is achievable. Shipped greedy gets 222.\n")

    for tl in (10.0, 60.0, 300.0):
        st, placed, el, nv, nc = build_and_solve(free, W, H, sizes, tl)
        print(f"  MAXIMIZE-area, limit {tl:5.0f}s -> {st:12s} placed {placed:3d}/{total} "
              f"in {el:6.1f}s   [{nv} bools, {nc} cell constraints]")
        if placed == total:
            print("  -> reached ground truth; stopping.")
            break

    print()
    st, placed, el, nv, nc = build_and_solve(
        free, W, H, sizes, 60.0, maximize=False)
    print(f"  FEASIBILITY (place all {total}), limit 60s -> {st:12s} in {el:6.1f}s")


if __name__ == "__main__":
    main()
