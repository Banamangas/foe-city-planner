"""PREMISE TEST A -- does region partitioning have regions to work with?

Region partitioning only makes sense if the free space left after roads and
road-needing buildings contains RECTANGLES BIG ENOUGH TO DEDICATE TO A SIZE
CLASS. If it shatters into slivers, "assign the 4x4s to this zone" has no zone
to assign to and the whole approach is dead before it is built.

Measured on the user's own city (ground truth: all 231 fillers provably fit).
Greedy maximal-rectangle carve: repeatedly extract the largest inscribed
axis-aligned rectangle from the free space until nothing is left.
"""
import sys, pathlib, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout


def largest_rect(free, W, H):
    """Largest all-free axis-aligned rectangle. Classic histogram sweep."""
    heights = [0] * W
    best = (0, 0, 0, 0, 0)  # area, x, y, w, h
    for y in range(H):
        for x in range(W):
            heights[x] = heights[x] + 1 if (x, y) in free else 0
        stack = []  # (start_x, height)
        for x in range(W + 1):
            h = heights[x] if x < W else 0
            start = x
            while stack and stack[-1][1] >= h:
                sx, sh = stack.pop()
                area = sh * (x - sx)
                if area > best[0]:
                    best = (area, sx, y - sh + 1, x - sx, sh)
                start = sx
            if h:
                stack.append((start, h))
    return best


def carve(free, W, H):
    free = set(free)
    rects = []
    while free:
        area, x, y, w, h = largest_rect(free, W, H)
        if area == 0:
            break
        rects.append((w, h))
        free -= {(x + dx, y + dy) for dx in range(w) for dy in range(h)}
    return rects


def tiles(rw, rh, bw, bl):
    """How many bw x bl blocks fit in an rw x rh rectangle, best orientation."""
    a = (rw // bw) * (rh // bl)
    b = (rw // bl) * (rh // bw)
    return max(a, b)


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
    print(f"free cells {len(free)}   fillers {len(fillers)}  "
          f"area {sum(w * l * n for (w, l), n in sizes.items())}")
    print("\nfiller size classes (what a zone would be dedicated to):")
    for (w, l), n in sizes.most_common():
        print(f"  {w}x{l:<3d} x{n:<4d}  area {w*l*n}")

    rects = carve(free, W, H)
    print(f"\ngreedy maximal-rectangle carve -> {len(rects)} rectangles")
    tot = sum(w * h for w, h in rects)
    for thresh, label in ((16, ">=4x4-capable"), (8, ">=2x4-capable"), (4, "tiny"), (1, "sliver")):
        sel = [(w, h) for w, h in rects if w * h >= thresh]
        print(f"  area in rects of >={thresh:2d} cells ({label:14s}): "
              f"{sum(w*h for w, h in sel):5d} / {tot}  ({100*sum(w*h for w,h in sel)/tot:.0f}%)  "
              f"[{len(sel)} rects]")

    print("\n  largest 20 rectangles (w x h -> how many 4x4 tile in it):")
    for w, h in sorted(rects, key=lambda r: -r[0] * r[1])[:20]:
        n44 = tiles(w, h, 4, 4)
        waste = w * h - n44 * 16
        print(f"    {w:2d}x{h:<3d} area {w*h:4d}   4x4 tiles: {n44:2d}   "
              f"leftover {waste:3d}")

    # THE decisive number: could dedicated zones absorb the 4x4s?
    n44_needed = sizes.get((4, 4), 0)
    cap, used = 0, []
    for w, h in sorted(rects, key=lambda r: -r[0] * r[1]):
        t = tiles(w, h, 4, 4)
        if t:
            cap += t
            used.append((w, h, t))
        if cap >= n44_needed:
            break
    print(f"\nDECISIVE: {n44_needed} 4x4 fillers need zones. Greedy rectangles "
          f"supply {cap} 4x4 slots using {len(used)} of them.")
    print(f"          rects consumed: {used[:12]}")

    dist = collections.Counter(rects)
    print(f"\nrectangle shape histogram (top 15): "
          f"{dist.most_common(15)}")
    print(f"single-cell rects: {dist.get((1,1),0)}")


if __name__ == "__main__":
    main()
