#!/usr/bin/env python3
"""Parallel multi-start sweep for the `layout` packer.

Runs `repack` across many seeds in parallel and keeps the lowest-road layout
that places every building. Each seed is an independent, deterministic repack,
so this parallelizes across CPU cores with bit-identical results.

    python scripts/sweep.py darkzig.json --budget 300 --seeds 16
    python scripts/sweep.py city.json helper.json --budget 120 --seeds 8 -o out

Notes:
- Compare only 0-unplaced results: at short budgets a seed may not place every
  building, and a partial layout shows artificially LOW roads (fewer buildings
  to connect). Raise --budget until every seed reports unplaced=0.
- Run it in the foreground; a long 16-core job can be killed by some sandboxed
  background runners.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.validate import is_valid
from foeopt.viz import render_comparison


def _run_seed(args: tuple) -> tuple:
    seed, city, helper, budget = args
    layout = load_layout(city, helper)
    res = repack(layout, budget_seconds=budget, seed=seed)
    ok = not res.unplaced and is_valid(res.layout)
    return seed, len(res.layout.roads), len(res.unplaced), res.trials, ok, res.layout


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Parallel multi-start packer sweep.")
    p.add_argument("city", help="city export (single combined file or old city file)")
    p.add_argument("helper", nargs="?", default=None, help="optional helper file")
    p.add_argument("--budget", type=float, default=300.0,
                   help="seconds per seed (default 300)")
    p.add_argument("--seeds", type=int, default=16,
                   help="number of seeds, 0..N-1 (default 16)")
    p.add_argument("--workers", type=int, default=None,
                   help="parallel workers (default min(seeds, cpu count))")
    p.add_argument("-o", "--out-dir", default="output",
                   help="directory for the winner's before/after map (default output)")
    args = p.parse_args(argv)

    base = load_layout(args.city, args.helper)
    est = road_estimate(base)
    workers = args.workers or min(args.seeds, os.cpu_count() or 1)
    print(f"sweep {args.city} | {args.seeds} seeds x {args.budget:.0f}s "
          f"| {workers} workers | estimate {est}", flush=True)

    t = time.time()
    tasks = [(s, args.city, args.helper, args.budget) for s in range(args.seeds)]
    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_run_seed, tasks):
            results.append(r)
            print(f"  seed {r[0]}: roads={r[1]} unplaced={r[2]} "
                  f"trials={r[3]} valid={r[4]}", flush=True)

    valid = [r for r in results if r[4]]
    winner = (min(valid, key=lambda r: r[1]) if valid
              else min(results, key=lambda r: (r[2], r[1])))
    seed, roads, unplaced, _trials, _ok, layout = winner

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"sweep_best_seed{seed}.html")
    pathlib.Path(out).write_text(render_comparison(base, layout), encoding="utf-8")

    if valid:
        print(f"\n0-unplaced roads: {sorted(r[1] for r in valid)}", flush=True)
    else:
        print("\nWARNING: no seed placed every building in this budget "
              "— increase --budget.", flush=True)
    print(f"WINNER: seed {seed} | roads={roads} unplaced={unplaced} "
          f"(estimate {est}) | {time.time() - t:.0f}s -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
