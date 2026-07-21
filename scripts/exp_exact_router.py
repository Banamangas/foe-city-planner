"""Stage-0 spike: does an exact router beat greedy route() on a fixed placement?

Reconstructs the fixed placement from a roads-first best-k*.json layout, runs the
exact router, and compares its optimum to route() on the same placement.

  uv run python scripts/exp_exact_router.py --selftest
  uv run python scripts/exp_exact_router.py darkzig.json \
      output/roads-first/best-k110-a102.json --time-limit 300
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dataclasses import replace

from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.exact_router import exact_route


def reconstruct_fixed(layout: Layout, best: dict) -> Layout:
    """Fixed placement = loaded building metadata with footprints overridden by `best`."""
    by_id = {b.entity_id: b for b in layout.buildings}
    placed, th = [], None
    for eid_str, (x, y, w, l) in best["buildings"].items():
        b = by_id[int(eid_str)]
        nb = replace(b, footprint=Footprint(x, y, w, l))
        placed.append(nb)
        if nb.is_townhall:
            th = nb
    return Layout(layout.region, placed, th, {})


def run_layout(layout: Layout, best: dict, time_limit: float) -> dict:
    fixed = reconstruct_fixed(layout, best)
    route_roads = len(route(fixed))
    res = exact_route(fixed, time_limit=time_limit)
    valid = None
    if res.roads is not None:
        chk = Layout(fixed.region, fixed.buildings, fixed.townhall, res.roads)
        valid = is_valid(chk) and len(res.roads) == res.count
    return {"achieved_json": best.get("achieved"), "route_roads": route_roads,
            "exact_status": res.status, "exact_count": res.count,
            "optimal": res.optimal, "wall_s": res.wall_s, "exact_valid": valid,
            "slack": (route_roads - res.count) if res.count is not None else None}


def _selftest() -> int:
    region = Region(frozenset((x, y) for x in range(3) for y in range(3)))
    th = Building(1, "c1", "main_building", Footprint(1, 0, 1, 1), False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 2, 1, 1), True, 1, False, None, None, "a")
    c2 = Building(3, "c3", "g", Footprint(2, 2, 1, 1), True, 1, False, None, None, "b")
    layout = Layout(region, [th, c1, c2], th, {})
    best = {"achieved": len(route(layout)),
            "buildings": {"1": [1, 0, 1, 1], "2": [0, 2, 1, 1], "3": [2, 2, 1, 1]}}
    row = run_layout(layout, best, time_limit=10)
    assert row["exact_status"] == "OPTIMAL" and row["exact_valid"] is True
    assert row["exact_count"] == 2 and row["slack"] == row["route_roads"] - 2
    print("SELFTEST OK:", json.dumps(row))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("best", nargs="*", help="best-k*.json layout file(s)")
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city or not args.best:
        ap.error("city file and at least one best-k*.json required (or --selftest)")
    layout = load_layout(args.city)
    rows = []
    for p in args.best:
        best = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        row = run_layout(layout, best, args.time_limit)
        row["file"] = pathlib.Path(p).name
        rows.append(row)
        print(json.dumps(row))
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
