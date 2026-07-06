#!/usr/bin/env python3
"""A/B harness for the TH-stub constructor template (2026-07-05).

Runs repack with the template off/on across seeds on darkzig + synthesized
real-like cities, printing unplaced/road distributions and throughput. Gates
for flipping the default (both must hold, 0-unplaced comparisons only):
  1. 0-unplaced road distribution not worse
  2. unplaced distribution no worse

  uv run python scripts/exp_th_ab.py darkzig.json --seeds 8 --budget 120
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from _ab_common import base_parser, load_cities, summarize
from foeopt.packer import repack


def run_arm(layout, *, th_stub, seeds, budget):
    rows = []
    for seed in range(seeds):
        t0 = time.monotonic()
        res = repack(layout, budget_seconds=budget, seed=seed,
                     th_stub_template=th_stub)
        rows.append({"seed": seed, "unplaced": len(res.unplaced),
                     "roads": len(res.layout.roads), "trials": res.trials,
                     "secs": round(time.monotonic() - t0, 1)})
    return rows


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    cities = load_cities(args.city, args.helper, args.fills)
    for name, lay in cities:
        for th_stub in (False, True):
            rows = run_arm(lay, th_stub=th_stub, seeds=args.seeds, budget=args.budget)
            summarize(f"{name} th_stub={th_stub}", rows)


if __name__ == "__main__":
    main()
