"""Track F step 4: does any cheap skeleton feature predict `achieved` among SATs?

The roads-first probe returns *a* feasible placement; `route()` then rebuilds the
road network on it. Feasibility is now cheap to find (Track F step 2), so the
binding question becomes which feasible skeleton routes LOW. Until tonight the
project had ~20 quality labels; the widened-pitch screen produces them by the
hundred, so the correlation study the 2026-07-21 placement-objective spec could
not run at the placement level is now runnable at the *skeleton* level.

Pre-committed bar (same as the 2026-07-21 study): a feature earns Stage 1 only
with |Spearman| >= 0.4 against `achieved` on held-out SATs. Anything less is
another proxy that looks reasonable and steers the search nowhere -- the failure
mode that sank four packer heuristics and P1-P4.

  uv run python scripts/exp_quality_model.py output/trackf/b2.jsonl \
      --city darkzig.json --pitches 12-18 --prefilter-top 0.10 --n 150
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.roads_first import generate_lane_patterns, _trunk
from foeopt.skeleton_score import SkeletonScorer


def spearman(xs, ys) -> float | None:
    """Rank correlation, average ranks for ties. None when either side is constant."""
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0
            for t in range(i, j + 1):
                r[order[t]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy) ** 0.5


def features(pat, scorer, region) -> dict:
    """Cheap, skeleton-intrinsic descriptors -- no CP-SAT, no placement."""
    roads = set(pat.roads)
    th = pat.th
    ortho = ((1, 0), (-1, 0), (0, 1), (0, -1))
    # how road cells sit relative to each other: a double-loaded lane cell has
    # exactly 2 road neighbours; ends have 1; junctions 3+
    deg = collections.Counter(
        sum(1 for dx, dy in ortho if (c[0] + dx, c[1] + dy) in roads) for c in roads)
    n = len(roads)
    free = region - roads - set(th.cells())
    # cells the skeleton can actually serve, and how evenly
    served = collections.Counter()
    for c in roads:
        for dx, dy in ortho:
            nb = (c[0] + dx, c[1] + dy)
            if nb in free:
                served[c] += 1
    loads = list(served.values())
    return {
        "opts_total": scorer.opts_total(th, pat.roads),
        "pitch": pat.params.get("pitch", 0),
        "stubs": int(bool(pat.params.get("stubs"))),
        "trunk_len": pat.params.get("trunk_len", 0),
        "deg1_frac": deg[1] / n,
        "deg2_frac": deg[2] / n,
        "deg3plus_frac": (deg[3] + deg[4]) / n,
        "mean_free_adj": statistics.mean(loads) if loads else 0.0,
        "n_zero_adj": sum(1 for c in roads if served[c] == 0),
        "th_x": th.x, "th_y": th.y,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", nargs="+", help="screen JSONL file(s)")
    ap.add_argument("--city", default="darkzig.json")
    ap.add_argument("--pitches", default=None)
    ap.add_argument("--prefilter-top", type=float, default=None)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--holdout", type=float, default=0.3)
    ap.add_argument("--out", default="output/trackf/quality-model.json")
    args = ap.parse_args()

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from exp_wide_skeleton_screen import parse_pitches, sample_patterns, read_rows

    layout = load_layout(args.city)
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th = layout.townhall.footprint
    scorer = SkeletonScorer(region, consumers)
    pitches = parse_pitches(args.pitches)

    samples = []
    for path in args.rows:
        rows = read_rows(pathlib.Path(path))
        by_k = collections.defaultdict(list)
        for r in rows:
            if r["status"] == "SAT" and r.get("legal") and r.get("achieved") is not None:
                by_k[r["k"]].append(r)
        for k, rs in sorted(by_k.items()):
            pats = sample_patterns(region, th.width, th.length, k, args.n, args.seed,
                                   pitches=pitches, prefilter_top=args.prefilter_top,
                                   consumers=consumers)
            for r in rs:
                pat = pats[r["idx"]]
                if list(pat.params["th"]) != list(r["th"]):
                    raise SystemExit(
                        f"pattern identity mismatch at k={k} idx={r['idx']}: "
                        "--pitches/--prefilter-top/--n/--seed must match the screen run")
                f = features(pat, scorer, region)
                f["achieved"] = r["achieved"]
                f["k"] = k
                samples.append(f)

    if len(samples) < 10:
        raise SystemExit(f"only {len(samples)} labeled SATs -- not enough to correlate")

    rng = random.Random(args.seed)
    idx = list(range(len(samples)))
    rng.shuffle(idx)
    cut = int((1 - args.holdout) * len(idx))
    train = [samples[i] for i in idx[:cut]]
    held = [samples[i] for i in idx[cut:]]

    feats = [k for k in samples[0] if k not in ("achieved",)]
    ach_all = [s["achieved"] for s in samples]
    print(f"n={len(samples)} SATs  achieved min={min(ach_all)} "
          f"median={statistics.median(ach_all)} max={max(ach_all)}")
    print(f"train={len(train)} holdout={len(held)}  bar: |rho| >= 0.4 on holdout\n")
    print(f"{'feature':16s} {'rho(train)':>11s} {'rho(holdout)':>13s}   verdict")
    results = {}
    for f in feats:
        rt = spearman([s[f] for s in train], [s["achieved"] for s in train])
        rh = spearman([s[f] for s in held], [s["achieved"] for s in held])
        results[f] = {"train": rt, "holdout": rh}
        ok = rh is not None and abs(rh) >= 0.4
        rts = "  n/a" if rt is None else f"{rt:+.3f}"
        rhs = "  n/a" if rh is None else f"{rh:+.3f}"
        print(f"{f:16s} {rts:>11s} {rhs:>13s}   {'PASS' if ok else ''}")

    passing = [f for f, v in results.items()
               if v["holdout"] is not None and abs(v["holdout"]) >= 0.4]
    verdict = "ADVANCE" if passing else "NO_QUALIFYING_FEATURE"
    print(f"\nVERDICT: {verdict}  passing={passing}")
    out = {"n": len(samples), "verdict": verdict, "passing": passing,
           "results": results,
           "achieved": {"min": min(ach_all), "median": statistics.median(ach_all),
                        "max": max(ach_all)}}
    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
