"""Track C-bis Stage 1.5 — UNKNOWN autopsy.

Re-solve a sample of the roads-first k-walk's frontier UNKNOWN patterns (the
sub-feasible levels where no SAT was found within the normal probe-limit) under a
large per-probe budget, to decide the fate of Stage 2:
  - >=1 flips to SAT  -> feasible-but-hard -> Stage 2 (CP-SAT warm-start) is the lever.
  - all -> UNSAT      -> infeasible pattern family -> fix topologies, not ML.
  - still UNKNOWN      -> even the big budget can't decide -> harder frontier.

Usage: uv run python scripts/kwalk_autopsy.py
"""
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.model import Footprint
from foeopt.loader import load_layout
from foeopt.roads_first import Pattern, probe

CORPUS = "output/corpus/darkzig/instances.jsonl"
FRONTIER_KS = (107, 109)   # sub-feasible levels (feasible frontier was k>=110/111)
PER_LEVEL = 4              # patterns re-solved per level
BUDGET = 900.0            # seconds per probe (15 min)
PROBE_WORKERS = 12


def main():
    layout = load_layout("darkzig.json")
    region = set(layout.region.cells)
    consumers = layout.road_needing()

    buckets = {k: [] for k in FRONTIER_KS}
    for line in open(CORPUS):
        r = json.loads(line)
        if r["status"] == "UNKNOWN" and r["k"] in buckets:
            buckets[r["k"]].append(r)

    rng = random.Random(0)
    sample = []
    for k in FRONTIER_KS:
        recs = buckets[k]
        rng.shuffle(recs)
        sample.extend(recs[:PER_LEVEL])

    print(f"autopsy: {len(sample)} frontier UNKNOWN patterns, {BUDGET:.0f}s each, "
          f"{PROBE_WORKERS} workers", flush=True)
    tally = {"SAT": 0, "UNSAT": 0, "UNKNOWN": 0}
    for i, r in enumerate(sample):
        pat = Pattern(th=Footprint(*r["th"]),
                      roads=frozenset((x, y) for x, y in r["roads"]), params={})
        t0 = time.monotonic()
        st, _ = probe(pat, region, consumers, probe_limit=BUDGET, probe_workers=PROBE_WORKERS)
        tally[st] = tally.get(st, 0) + 1
        print(f"  [{i+1}/{len(sample)}] k={r['k']} roads={len(r['roads'])} "
              f"-> {st} in {time.monotonic()-t0:.0f}s", flush=True)

    print("AUTOPSY RESULT:", tally, flush=True)
    if tally["SAT"] > 0:
        print("VERDICT: CASE 1 (feasible-but-hard) -> build Stage 2 (CP-SAT warm-start).")
    elif tally["UNKNOWN"] == 0:
        print("VERDICT: CASE 2 (infeasible family) -> fix pattern topologies, not ML/warm-start.")
    else:
        print("VERDICT: INCONCLUSIVE -> frontier still undecided at this budget; "
              "larger budget or a warm-start needed to probe deeper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
