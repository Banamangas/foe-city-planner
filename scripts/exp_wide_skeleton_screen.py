"""Wide-shallow lane-skeleton screen.

Screen a large sample of lane skeletons at a SHORT budget with concurrency
across patterns, rather than a tiny sample at a long budget with concurrency
inside one probe. Rationale (spec 2026-07-22): UNSAT is nearly free
(presolve, ~5ms), UNKNOWN does not converge with budget (900s autopsy
resolved 4 of 8), and every SAT in the 1459-instance corpus resolved within
29.2s -- so the binding resource is patterns sampled, not seconds per pattern.

  uv run python scripts/exp_wide_skeleton_screen.py --selftest
  uv run python scripts/exp_wide_skeleton_screen.py darkzig.json \
      --k-levels 105,106,107 --n 5000 --budget 30 --workers 12 \
      --out output/wide-screen.jsonl --sat-dir output/wide-screen-sats
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.roads_first import generate_lane_patterns, prefilter

FLOOR = 102


def rule_of_three(n: int) -> float:
    """95% upper bound on the rate of an event observed ZERO times in n trials.

    Reported on a null screen so "we found nothing" becomes a number: 0 SATs
    in 5,000 patterns bounds p*d below 0.06%, where "0 in 12" bounds nothing.
    The 3/n approximation is only meaningful for large n, so the result is
    capped at 1.0 -- a rate cannot exceed certainty.
    """
    if n <= 0:
        return 1.0
    return min(1.0, 3.0 / n)


def classify_verdict(rows: list[dict], floor: int = FLOOR) -> tuple[str, dict]:
    """Pre-committed verdict (spec section 5). Only a LEGAL, validated SAT
    strictly below `floor` counts as breaking it -- a tie does not."""
    sats = [r for r in rows
            if r["status"] == "SAT" and r.get("legal") and r.get("achieved") is not None]
    detail = {"n": len(rows), "n_sat": len(sats),
              "best_achieved": (min(r["achieved"] for r in sats) if sats else None)}
    if any(r["achieved"] < floor for r in sats):
        return "BREAK_FLOOR", detail
    if sats:
        return "FEASIBLE_NOT_SUPERIOR", detail
    detail["p_bound"] = rule_of_three(len(rows))
    return "NULL_WITH_BOUND", detail


def sample_patterns(region, tw, tl, k, n, seed):
    """Uniform sample without replacement from the full lane population.

    `generate_lane_patterns` builds every pattern for this k, shuffles with the
    supplied rng, then truncates -- so a fixed seed makes the sample and its
    index order reproducible, which is what `--resume` and `--recheck` rely on.
    """
    return generate_lane_patterns(region, tw, tl, k, random.Random(seed), n,
                                  th_mode="full")


def load_done(path: pathlib.Path) -> set[tuple[int, int]]:
    """(k, idx) pairs already recorded. Tolerates a torn final line from a
    killed run -- otherwise one interrupted write would strand the whole file."""
    done: set[tuple[int, int]] = set()
    if not path.exists():
        return done
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add((r["k"], r["idx"]))
    return done


def append_row(fh, row: dict) -> None:
    """Write and flush immediately: an 8h run must survive a kill -9."""
    fh.write(json.dumps(row) + "\n")
    fh.flush()
