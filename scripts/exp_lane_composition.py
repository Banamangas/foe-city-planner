"""THROWAWAY EXPERIMENT (2026-07-02 calibration spec, Task A1).

Optimal road cost within the expert layout family: buildings are assigned to
double-loaded straight lanes (uniform depth per side, orientation free), lanes
stack along a perpendicular trunk, optional dead-end stubs at lane ends serve
up to 3 buildings each. Costs: lane = max(side loads); trunk pessimistic =
sum(depthA + 1 + depthB) over used lanes; stub = 1 cell each. The model is a
RESTRICTION of the real problem, so family-optimum >= true optimum wherever
both are computable (checked by --selftest against rl.oracle).

Run (never a repo dep):
  uv run --with ortools python scripts/exp_lane_composition.py --selftest
  uv run --with ortools python scripts/exp_lane_composition.py \
      city-user-data.json city-user-data-foe-helper.json -o output/comp-user.json
  uv run --with ortools python scripts/exp_lane_composition.py darkzig.json \
      -o output/comp-darkzig.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from ortools.sat.python import cp_model

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import bbox


def solve_composition(items, *, k_max, len_max, stack_max, area_budget,
                      stubs=False, time_limit=120.0):
    """items: list of (entity_id, w, l) road-needing buildings.
    Returns a result dict (see report keys)."""
    if not items:
        return {
            "status": "NO_CONSUMERS",
            "model_optimum": 0,
            "proven_bound": 0,
            "gap": 0,
            "trunk_pessimistic": 0,
            "optimistic_total": 0,
            "stub_cells": 0,
            "lanes": [],
        }
    m = cp_model.CpModel()
    n = len(items)
    depths = sorted({d for (_, w, l) in items for d in (w, l)})

    x = {}                       # x[i,k,s,o]=1: item i on lane k side s orient o
    stub_y = {}                  # stub_y[i]=1: item i served by a stub
    for i, (_, w, l) in enumerate(items):
        opts = []
        for k in range(k_max):
            for s in (0, 1):
                for o in (0, 1):
                    v = m.NewBoolVar(f"x_{i}_{k}_{s}_{o}")
                    x[i, k, s, o] = v
                    opts.append(v)
        if stubs:
            stub_y[i] = m.NewBoolVar(f"stub_{i}")
            opts.append(stub_y[i])
        m.AddExactlyOne(opts)

    d = {}                       # d[k,s,dep]=1: lane k side s has depth class dep
    for k in range(k_max):
        for s in (0, 1):
            for dep in depths:
                d[k, s, dep] = m.NewBoolVar(f"d_{k}_{s}_{dep}")
            m.AddAtMostOne(d[k, s, dep] for dep in depths)
    for i, (_, w, l) in enumerate(items):
        for k in range(k_max):
            for s in (0, 1):
                # orientation o=0: extent w, depth l; o=1: extent l, depth w
                m.AddImplication(x[i, k, s, 0], d[k, s, l])
                m.AddImplication(x[i, k, s, 1], d[k, s, w])

    lane_len, thick, used = [], [], []
    for k in range(k_max):
        loads = []
        for s in (0, 1):
            load = m.NewIntVar(0, len_max, f"L_{k}_{s}")
            m.Add(load == sum(
                x[i, k, s, 0] * w + x[i, k, s, 1] * l
                for i, (_, w, l) in enumerate(items)))
            loads.append(load)
        ll = m.NewIntVar(0, len_max, f"len_{k}")
        m.AddMaxEquality(ll, loads)
        lane_len.append(ll)
        u = m.NewBoolVar(f"u_{k}")
        m.Add(ll >= 1).OnlyEnforceIf(u)
        m.Add(ll == 0).OnlyEnforceIf(u.Not())
        used.append(u)
        for s in (0, 1):
            for dep in depths:
                m.AddImplication(u.Not(), d[k, s, dep].Not())
        tk = m.NewIntVar(0, 2 * max(depths) + 1, f"t_{k}")
        m.Add(tk == sum(dep * d[k, 0, dep] for dep in depths)
                  + sum(dep * d[k, 1, dep] for dep in depths) + u)
        thick.append(tk)
    for k in range(k_max - 1):                    # symmetry breaking
        m.Add(lane_len[k] >= lane_len[k + 1])

    stub_cells = m.NewIntVar(0, n, "stub_cells")
    if stubs:
        m.Add(3 * stub_cells >= sum(stub_y.values()))
        m.Add(stub_cells <= 2 * sum(used))        # <=1 stub per lane end
    else:
        m.Add(stub_cells == 0)

    trunk_pess = m.NewIntVar(0, 10000, "trunk")
    m.Add(trunk_pess == sum(thick))
    m.Add(trunk_pess <= stack_max)                # lanes must stack in-region
    total = m.NewIntVar(0, 100000, "total")
    m.Add(total == sum(lane_len) + trunk_pess + stub_cells)
    m.Add(total <= area_budget)                   # buildings + roads fit region
    m.Minimize(total)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": solver.StatusName(status),
            "model_optimum": None,
            "proven_bound": None,
            "gap": None,
            "trunk_pessimistic": None,
            "optimistic_total": None,
            "stub_cells": None,
            "lanes": [],
        }
    lanes = []
    for k in range(k_max):
        if not solver.Value(used[k]):
            continue
        members = [[], []]
        for i, (eid, w, l) in enumerate(items):
            for s in (0, 1):
                if solver.Value(x[i, k, s, 0]) or solver.Value(x[i, k, s, 1]):
                    members[s].append(eid)
        lanes.append({"len": solver.Value(lane_len[k]),
                      "thickness": solver.Value(thick[k]),
                      "side_a": members[0], "side_b": members[1]})
    n_used = sum(solver.Value(u) for u in used)
    lane_total = sum(la["len"] for la in lanes)
    return {
        "status": solver.StatusName(status),
        "model_optimum": solver.Value(total),
        "proven_bound": int(round(solver.BestObjectiveBound())),
        "gap": solver.Value(total) - int(round(solver.BestObjectiveBound())),
        "trunk_pessimistic": solver.Value(trunk_pess),
        "optimistic_total": lane_total + n_used + solver.Value(stub_cells),
        "stub_cells": solver.Value(stub_cells),
        "lanes": lanes,
    }


def _selftest():
    """Family-optimum must be >= the true joint optimum (the family is a
    restriction). Tiny instance sized for rl.oracle's exhaustive search."""
    from rl.oracle import optimal_roads
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2),
                  True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1),
                  True, 1, False, None, None, "b")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1, c2], th, {})
    opt = optimal_roads(layout, budget_s=60.0)
    items = [(b.entity_id, b.footprint.width, b.footprint.length)
             for b in layout.road_needing()]
    res = solve_composition(items, k_max=2, len_max=6, stack_max=6,
                            area_budget=36, time_limit=30.0)
    ok = (opt is not None and res.get("model_optimum") is not None
          and res["model_optimum"] >= opt)
    print(f"selftest: oracle={opt} family={res.get('model_optimum')} "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("helper", nargs="?", default=None)
    p.add_argument("--lanes", type=int, default=12)
    p.add_argument("--stack-max", type=int, default=None,
                   help="cap on summed lane thicknesses (default 2x the bbox max "
                        "dim - real layouts stack lanes in more than one column; "
                        "a single-stack cap can spuriously report INFEASIBLE)")
    p.add_argument("--stubs", action="store_true")
    p.add_argument("--time-limit", type=float, default=120.0)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("-o", "--out", default=None)
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.city:
        p.error("city required unless --selftest")
    layout = load_layout(args.city, args.helper)
    items = [(b.entity_id, b.footprint.width, b.footprint.length)
             for b in layout.road_needing()]
    w, h = bbox(layout.region)
    building_area = sum(b.footprint.width * b.footprint.length
                        for b in layout.buildings)
    res = solve_composition(
        items, k_max=args.lanes, len_max=max(w, h) - 1,
        stack_max=args.stack_max or 2 * max(w, h),
        area_budget=len(layout.region.cells) - building_area,
        stubs=args.stubs, time_limit=args.time_limit)
    res.update({"city": args.city, "n_consumers": len(items)})
    out = json.dumps(res, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(out + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
