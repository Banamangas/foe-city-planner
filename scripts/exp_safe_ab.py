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

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from _ab_common import base_parser, load_cities, summarize
from foeopt.packer import repack


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


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    cities = load_cities(args.city, args.helper, args.fills)
    for name, lay in cities:
        for safe in (False, True):
            rows = run_arm(lay, safe=safe, seeds=args.seeds, budget=args.budget)
            summarize(f"{name} safe={safe}", rows)


if __name__ == "__main__":
    main()
