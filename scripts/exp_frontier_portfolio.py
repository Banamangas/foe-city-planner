"""next-things-to-try #8 -- CP-SAT parameter portfolio for the hard frontier.

Re-solves a deterministic sample of already-known-UNKNOWN-at-default patterns
(reused from the existing darkzig corpus, k=107-123, the k-walk's real
operating range) under a small set of alternate CP-SAT solver_overrides, at
the SAME realistic budget the real walk uses (probe_limit=30s,
probe_workers=2) -- not an inflated one. Baseline decision rate is 0 by
construction (every sampled record is already UNKNOWN at that budget); the
question is whether any alternate strategy decides some of them within the
same budget, which the Stage 1.5 autopsy (900s+12 workers, tasks/lessons.md
2026-07-15) didn't test since it only varied time/workers, not strategy.

Runs sequentially (one probe at a time) per next-things-to-try #7's Phase 0
finding: oversubscribing outer parallelism causes CP-SAT thread contention
that confounds a fair per-probe comparison.

Usage:
  uv run --extra rl python scripts/exp_frontier_portfolio.py --smoke
  uv run --extra rl python scripts/exp_frontier_portfolio.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ortools.sat.python import cp_model_helper as _sat_helper
from foeopt.model import Footprint
from foeopt.loader import load_layout
from foeopt.roads_first import Pattern, probe

CORPUS = "output/corpus/darkzig/instances.jsonl"
FRONTIER_KS = (107, 109, 110, 111, 115, 119, 123)
PROBE_LIMIT = 30.0
PROBE_WORKERS = 2

# search_branching is a pybind-native enum, not a plain int -- must use the
# type's own class attribute (a bare int raises TypeError at solve time).
_SB = _sat_helper.SatParameters

CONFIGS = {
    "default_reconfirm": (PROBE_WORKERS, {}),
    "portfolio_search": (PROBE_WORKERS, {"search_branching": _SB.PORTFOLIO_SEARCH}),
    "lp_search": (PROBE_WORKERS, {"search_branching": _SB.LP_SEARCH}),
    "linearization_max": (PROBE_WORKERS, {"linearization_level": 2}),
    "more_probe_workers_4": (4, {}),
    "lns_only": (PROBE_WORKERS, {"use_lns_only": True}),
}


def _sample(n: int) -> list[dict]:
    buckets = {k: [] for k in FRONTIER_KS}
    for line in open(CORPUS):
        r = json.loads(line)
        if r["status"] == "UNKNOWN" and r["k"] in buckets:
            buckets[r["k"]].append(r)
    rng = random.Random(0)
    pool = [r for k in FRONTIER_KS for r in buckets[k]]
    rng.shuffle(pool)
    return pool[:n]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--configs", nargs="+", default=None,
                   help="subset of CONFIGS names to run (default: all)")
    args = p.parse_args(argv)
    n = 4 if args.smoke else args.n
    config_names = args.configs or (list(CONFIGS)[:2] if args.smoke else list(CONFIGS))

    layout = load_layout("darkzig.json")
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    sample = _sample(n)
    print(f"frontier_portfolio: {len(sample)} patterns, configs={config_names}", flush=True)

    results = {}
    for name in config_names:
        workers, overrides = CONFIGS[name]
        tally = {"SAT": 0, "UNSAT": 0, "UNKNOWN": 0}
        t0 = time.monotonic()
        for i, r in enumerate(sample):
            pat = Pattern(th=Footprint(*r["th"]),
                          roads=frozenset((x, y) for x, y in r["roads"]), params={})
            st, _ = probe(pat, region, consumers, probe_limit=PROBE_LIMIT,
                         probe_workers=workers, solver_overrides=overrides or None)
            tally[st] = tally.get(st, 0) + 1
            print(f"  [{name}] [{i+1}/{len(sample)}] k={r['k']} -> {st}", flush=True)
        decided = tally["SAT"] + tally["UNSAT"]
        secs = time.monotonic() - t0
        print(f"[{name}] tally={tally} decided={decided}/{len(sample)} "
             f"({100*decided/len(sample):.0f}%) wall={secs:.0f}s", flush=True)
        results[name] = {"tally": tally, "decided": decided, "n": len(sample), "wall_s": secs}

    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
