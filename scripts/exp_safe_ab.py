#!/usr/bin/env python3
"""A/B harness for the safe-placements mask (2026-07-02 spec section 5).

Runs repack with the mask off/on across seeds on darkzig + synthesized
real-like cities, printing unplaced/road distributions and throughput. Gates
for flipping the default (both must hold, 0-unplaced comparisons only):
  1. unplaced distribution strictly no worse everywhere, better in the tails
  2. 0-unplaced road distribution not worse AND trials/budget regression < ~30%

  uv run python scripts/exp_safe_ab.py darkzig.json --seeds 8 --budget 120
"""
from __future__ import annotations

import argparse
import pathlib
import random
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.packer import repack
from rl.curriculum import make_real_like_city


def run_arm(layout, *, safe, seeds, budget):
    rows = []
    for seed in range(seeds):
        t0 = time.monotonic()
        res = repack(layout, budget_seconds=budget, seed=seed,
                     safe_placements=safe)
        rows.append({"seed": seed, "unplaced": len(res.unplaced),
                     "roads": len(res.layout.roads), "trials": res.trials,
                     "secs": round(time.monotonic() - t0, 1)})
    return rows


def summary(name, rows):
    unp = [r["unplaced"] for r in rows]
    ok_roads = [r["roads"] for r in rows if r["unplaced"] == 0]
    trials = [r["trials"] for r in rows]
    print(f"{name}: unplaced min/mean/max {min(unp)}/{statistics.mean(unp):.1f}/{max(unp)}"
          f" | 0-unplaced roads {sorted(ok_roads) if ok_roads else 'NONE'}"
          f" | trials/run mean {statistics.mean(trials):.0f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("city")
    p.add_argument("helper", nargs="?", default=None)
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--budget", type=float, default=120.0)
    p.add_argument("--fills", default="0.5,0.7,0.9",
                   help="real-like synthesis fills; empty string = city only")
    args = p.parse_args()
    ref = load_layout(args.city, args.helper)
    cities = [("city", ref)]
    for f in filter(None, args.fills.split(",")):
        cities.append((f"real-like fill={f}",
                       make_real_like_city(random.Random(0), ref, fill=float(f))))
    for name, lay in cities:
        for safe in (False, True):
            rows = run_arm(lay, safe=safe, seeds=args.seeds, budget=args.budget)
            summary(f"{name} safe={safe}", rows)


if __name__ == "__main__":
    main()
