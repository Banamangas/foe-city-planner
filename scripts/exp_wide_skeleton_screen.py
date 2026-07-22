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

FLOOR = 102


def rule_of_three(n: int) -> float:
    """95% upper bound on the rate of an event observed ZERO times in n trials.

    Reported on a null screen so "we found nothing" becomes a number: 0 SATs
    in 5,000 patterns bounds p*d below 0.06%, where "0 in 12" bounds nothing.
    """
    if n <= 0:
        return 1.0
    return 3.0 / n


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
