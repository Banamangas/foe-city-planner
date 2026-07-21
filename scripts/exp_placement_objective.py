"""Stage-0 proxy correlation study for the roads-first placement objective.

Throwaway R&D driver (spec: docs/superpowers/specs/2026-07-21-roads-first-placement-objective-design.md).
For a sample of comb skeletons it collects N feasible consumer placements, scores
each with route() and all four proxies, and reports oracle_gap plus per-proxy
Spearman rank-correlation and realized road reduction — the go/kill evidence.

  uv run python scripts/exp_placement_objective.py --selftest
  uv run python scripts/exp_placement_objective.py darkzig.json --skeletons 30 \
      --placements 20 --k-levels 112,118,125 --probe-limit 20 --out output/stage0.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dataclasses import replace

from foeopt.loader import load_layout
from foeopt.model import Footprint, Layout, Region
from foeopt.router import route, RouteError
from foeopt.roads_first import (
    generate_patterns, probe, _anchor_candidates, _bbox,
)
from foeopt.placement_proxies import (
    proxy_touched_cells, proxy_subtree, proxy_double_loaded, proxy_same_size_clusters,
)

# (name, fn, sign): sign folds each proxy into a "minimize" orientation so that
# argmin(sign*raw) is the placement the proxy would pick and a POSITIVE
# spearman(sign*raw, roads) means the proxy tracks the real road count.
PROXIES = [
    ("P1_touched", proxy_touched_cells, +1),
    ("P2_subtree", proxy_subtree, +1),
    ("P3_double_loaded", proxy_double_loaded, -1),
    ("P4_same_size", proxy_same_size_clusters, -1),
]


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    if len(xs) < 2:
        return 0.0
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def roads_for_placement(layout: Layout, pattern, positions) -> int | None:
    """route() road count for a consumer placement (fillers ignored — they do not
    affect the road count, which route() derives from the consumers before fill)."""
    placed = [replace(b, footprint=Footprint(*positions[b.entity_id]))
              for b in layout.road_needing()]
    th = replace(layout.townhall, footprint=pattern.th)
    cand = Layout(layout.region, [th, *placed], th, {})
    try:
        return len(route(cand))
    except RouteError:
        return None


def feasible_placements(layout: Layout, pattern, n: int, probe_limit: float) -> list[dict]:
    """Up to n distinct feasible consumer placements on a fixed skeleton, via the
    CP-SAT solution pool. Same model as roads_first.probe(), no objective."""
    from ortools.sat.python import cp_model

    region = set(layout.region.cells)
    consumers = layout.road_needing()
    blocked = set(pattern.roads) | set(pattern.th.cells())
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            return []
        cand.append((b, opts))

    m = cp_model.CpModel()
    x0b, y0b, x1b, y1b = _bbox(region)
    xs, ys, xiv, yiv = [], [], [], []
    for i, (b, opts) in enumerate(cand):
        x = m.NewIntVar(x0b, x1b, f"x{i}")
        y = m.NewIntVar(y0b, y1b, f"y{i}")
        m.AddAllowedAssignments([x, y], opts)
        xiv.append(m.NewFixedSizeIntervalVar(x, b.footprint.width, f"xi{i}"))
        yiv.append(m.NewFixedSizeIntervalVar(y, b.footprint.length, f"yi{i}"))
        xs.append(x); ys.append(y)
    m.AddNoOverlap2D(xiv, yiv)

    collected: list[dict] = []

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()  # required: SWIG-wrapped base

        def on_solution_callback(self):
            pos = {}
            for i, (b, _) in enumerate(cand):
                pos[b.entity_id] = (self.Value(xs[i]), self.Value(ys[i]),
                                    b.footprint.width, b.footprint.length)
            collected.append(pos)
            if len(collected) >= n:
                self.StopSearch()

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = probe_limit
    solver.parameters.enumerate_all_solutions = True
    solver.Solve(m, _Collector())
    return collected


def score_skeleton(layout: Layout, pattern, n: int, probe_limit: float) -> dict | None:
    """Collect placements, score each; return per-skeleton oracle_gap + proxy stats.
    None if <2 usable placements (nothing to correlate)."""
    placements = feasible_placements(layout, pattern, n, probe_limit)
    rows = []
    for pos in placements:
        r = roads_for_placement(layout, pattern, pos)
        if r is None:
            continue
        vals = {name: sign * fn(pattern, pos) for name, fn, sign in PROXIES}
        rows.append((r, vals))
    if len(rows) < 2:
        return None
    roads = [r for r, _ in rows]
    first_roads = roads[0]  # first solution found == today's first-feasible probe result
    oracle_gap = first_roads - min(roads)
    out = {"n_placements": len(rows), "first_roads": first_roads,
           "min_roads": min(roads), "oracle_gap": oracle_gap, "proxies": {}}
    for name, _, _ in PROXIES:
        col = [vals[name] for _, vals in rows]
        best_idx = min(range(len(rows)), key=lambda i: col[i])
        out["proxies"][name] = {
            "spearman": round(spearman(col, roads), 3),
            "realized_reduction": first_roads - roads[best_idx],
        }
    return out


def run_study(layout: Layout, k_levels, skeletons: int, placements: int,
              probe_limit: float, seed: int) -> dict:
    rng = random.Random(seed)
    region = set(layout.region.cells)
    tw, tl = layout.townhall.footprint.width, layout.townhall.footprint.length
    per_level = max(1, skeletons // len(k_levels))
    results = []
    for k in k_levels:
        pats = generate_patterns(region, tw, tl, k, rng, per_level, th_mode="full")
        for pat in pats:
            s = score_skeleton(layout, pat, placements, probe_limit)
            if s is not None:
                s["k"] = k
                results.append(s)
    return summarize(results)


def summarize(results: list[dict]) -> dict:
    if not results:
        return {"skeletons_scored": 0, "note": "no skeleton yielded >=2 placements"}
    gaps = [r["oracle_gap"] for r in results]
    summary = {"skeletons_scored": len(results),
               "mean_oracle_gap": round(sum(gaps) / len(gaps), 3),
               "max_oracle_gap": max(gaps), "proxies": {}}
    for name, _, _ in PROXIES:
        corrs = [r["proxies"][name]["spearman"] for r in results]
        reds = [r["proxies"][name]["realized_reduction"] for r in results]
        summary["proxies"][name] = {
            "mean_spearman": round(sum(corrs) / len(corrs), 3),
            "mean_realized_reduction": round(sum(reds) / len(reds), 3),
        }
    return summary


def _selftest() -> int:
    # Tiny synthetic instance: TH + 2 same-size consumers in a 6x6 region.
    from foeopt.model import Building
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "b")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1, c2], th, {})
    out = run_study(layout, [6], skeletons=4, placements=6, probe_limit=5.0, seed=0)
    assert spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert "skeletons_scored" in out
    print("SELFTEST OK:", json.dumps(out))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("helper", nargs="?")
    ap.add_argument("--k-levels", default="112,118,125")
    ap.add_argument("--skeletons", type=int, default=30)
    ap.add_argument("--placements", type=int, default=20)
    ap.add_argument("--probe-limit", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    layout = load_layout(args.city, args.helper)
    k_levels = [int(x) for x in args.k_levels.split(",")]
    out = run_study(layout, k_levels, args.skeletons, args.placements,
                    args.probe_limit, args.seed)
    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
