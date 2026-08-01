"""PREMISE TEST A, re-run on SEARCH-PRODUCED layouts.

The first run of this test (scripts/exp_region_partition_premise.py) measured
the user's OWN city and found the free space carves into 23 rectangles with no
1x1s -- so "dedicate a zone to the 4x4s" had real geometry to work with. But
that free space was shaped by the expert's own road skeleton, and the search
invents its own. The stated caveat was that a search skeleton might fragment
the leftover space far worse, which would kill region partitioning outright.

This settles it, on the record artifacts in docs/records/ -- real layouts the
roads-first search actually produced, including the two current records.
"""
import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout
from scripts.exp_region_partition_premise import carve, tiles

RECORDS = [
    ("docs/records/fr16-76-roads-nonuniform-k84.json", "CityMap-Born-FR16-2026-07-07.json"),
    ("docs/records/darkzig-94-roads-nonuniform-k105.json", "darkzig.json"),
    ("docs/records/darkzig-95-roads-lane-k105.json", "darkzig.json"),
    ("docs/records/darkzig-98-roads-lane-k105.json", "darkzig.json"),
]


def free_space_of(record_path, city_path):
    rec = json.loads(pathlib.Path(record_path).read_text())
    lay = load_layout(city_path)
    region = set(lay.region.cells)
    W = max(c[0] for c in region) + 1
    H = max(c[1] for c in region) + 1

    filler_ids = {b.entity_id for b in lay.buildings
                  if not b.needs_road and not b.is_townhall}
    fillers = [b for b in lay.buildings if b.entity_id in filler_ids]

    occupied = {tuple(c) for c in rec["roads"]}
    for eid, (x, y, w, l) in rec["buildings"].items():
        if int(eid) in filler_ids:
            continue                      # fillers are what we are re-placing
        occupied |= {(x + dx, y + dy) for dx in range(w) for dy in range(l)}
    return region - occupied, W, H, fillers, rec


def report(label, free, W, H, fillers, achieved):
    sizes = collections.Counter(
        (b.footprint.width, b.footprint.length) for b in fillers)
    area = sum(w * l * n for (w, l), n in sizes.items())
    rects = carve(free, W, H)
    tot = sum(w * h for w, h in rects)
    dist = collections.Counter(rects)
    big = [(w, h) for w, h in rects if w * h >= 16]

    # The dominant class by COUNT is 1x1 on both search cities, which makes a
    # capacity test against it meaningless -- a 1x1 fits anywhere. Zoning only
    # ever mattered for the BIG classes, so test those.
    big_cls = {sz: n for sz, n in sizes.items() if sz[0] * sz[1] >= 16}
    dominant, dom_n = (max(big_cls.items(), key=lambda kv: kv[1])
                       if big_cls else sizes.most_common(1)[0])
    cap = sum(tiles(w, h, *dominant) for w, h in rects)
    tiny = sum(n for sz, n in sizes.items() if sz[0] * sz[1] <= 4)

    print(f"\n=== {label}  ({achieved} roads) ===")
    print(f"  free {len(free)} cells, {len(fillers)} fillers, area {area}, "
          f"slack {len(free) - area}")
    print(f"  carve -> {len(rects)} rectangles   1x1 slivers: {dist.get((1,1),0)}")
    print(f"  area in rects >=16 cells: {sum(w*h for w,h in big)}/{tot} "
          f"({100*sum(w*h for w,h in big)/tot:.0f}%) across {len(big)} rects")
    print(f"  largest 6: {sorted(rects, key=lambda r:-r[0]*r[1])[:6]}")
    print(f"  biggest filler class {dominant[0]}x{dominant[1]} x{dom_n}: "
          f"rectangles supply {cap} slots  -> "
          f"{'ENOUGH' if cap >= dom_n else 'NOT ENOUGH'}")
    print(f"  fillers of area<=4 (gap-fillers that make zoning unnecessary): "
          f"{tiny}/{len(fillers)} ({100*tiny/len(fillers):.0f}%)")
    return {"rects": len(rects), "slivers": dist.get((1, 1), 0),
            "pct_big": 100 * sum(w * h for w, h in big) / tot,
            "slack_pct": 100 * (len(free) - area) / len(free),
            "tiny_pct": 100 * tiny / len(fillers),
            "dominant_ok": cap >= dom_n}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--records", default=None,
                   help="comma-separated record:city pairs; default = built-in list")
    args = p.parse_args(argv)
    pairs = RECORDS
    if args.records:
        pairs = [tuple(x.split(":")) for x in args.records.split(",")]

    print("Baseline for comparison -- the user's OWN city (expert skeleton):")
    print("  23 rectangles, 0 slivers, 98% of area in rects >=16 cells,")
    print("  3 largest supply 85 4x4 slots against 77 4x4 fillers.")

    out = []
    for rec_path, city in pairs:
        if not pathlib.Path(rec_path).exists():
            print(f"skip (missing): {rec_path}")
            continue
        free, W, H, fillers, rec = free_space_of(rec_path, city)
        out.append(report(pathlib.Path(rec_path).stem, free, W, H, fillers,
                          rec.get("achieved")))

    print("\n--- verdict ---")
    print(f"  fragmentation (area in rects >=16 cells): expert 98%, "
          f"search {min(o['pct_big'] for o in out):.0f}-"
          f"{max(o['pct_big'] for o in out):.0f}%")
    print(f"  slack at the packing stage: expert 0.1%, search "
          f"{min(o['slack_pct'] for o in out):.0f}-"
          f"{max(o['slack_pct'] for o in out):.0f}%")
    print(f"  tiny (area<=4) fillers: expert 37% but ZERO 1x1, search "
          f"{min(o['tiny_pct'] for o in out):.0f}-"
          f"{max(o['tiny_pct'] for o in out):.0f}% with 9-45 1x1s")
    print("\n  Zones do still exist, so the premise is not refuted. But the "
          "PROBLEM they solve\n  is largely absent on the cities the search "
          "actually runs on: they have 13-31%\n  slack instead of 0.1%, and "
          "an abundance of 1x1 fillers that make any hole\n  fillable. See "
          "tasks/remaining-work.md section 8.")


if __name__ == "__main__":
    main()
