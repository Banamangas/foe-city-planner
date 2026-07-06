"""THROWAWAY EXPERIMENT (2026-07-06 roads-first feasibility spec).

Fixed comb+stub road networks, exact CP-SAT placement feasibility, downward
iterative deepening on road count k. Gate on the achieved (route-pruned) road
count of the best validated layout: <=148 win; none <153 certificate; between
-> user decides.

Run (never a repo dep):
  uv run --with ortools python scripts/exp_roads_first.py --selftest
  uv run --with ortools python scripts/exp_roads_first.py darkzig.json --dump-patterns 152
  uv run --with ortools python scripts/exp_roads_first.py darkzig.json --smoke
  uv run --with ortools python scripts/exp_roads_first.py darkzig.json          # the real 6h box
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time
from dataclasses import dataclass, replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packing import Grid, first_fit
from foeopt.router import RouteError, route
from foeopt.validate import is_valid
from foeopt.viz import render_html

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


@dataclass(frozen=True)
class Pattern:
    th: Footprint
    roads: frozenset[Cell]
    params: dict


def _bbox(region: set[Cell]) -> tuple[int, int, int, int]:
    xs = [c[0] for c in region]
    ys = [c[1] for c in region]
    return min(xs), min(ys), max(xs), max(ys)


def _fits(region: set[Cell], fp: Footprint) -> bool:
    return fp.cells() <= region


def th_anchor_candidates(region: set[Cell], tw: int, tl: int) -> list[Footprint]:
    """Coarse TH anchors: 4 corner-most fits, offset-by-d variants (d in 2/4/6,
    Chebyshev from that corner), 2 mid-edge fits. Deduplicated, sorted."""
    x0, y0, x1, y1 = _bbox(region)
    corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    out: dict[tuple[int, int], Footprint] = {}

    def scan(keyfn, accept):
        for (x, y) in sorted(region, key=keyfn):
            fp = Footprint(x, y, tw, tl)
            if _fits(region, fp) and accept(x, y):
                return fp
        return None

    for (cx, cy) in corners:
        for d in (0, 2, 4, 6):
            fp = scan(lambda c: (abs(c[0] - cx) + abs(c[1] - cy)),
                      lambda x, y, cx=cx, cy=cy, d=d: max(abs(x - cx), abs(y - cy)) >= d)
            if fp is not None:
                out[(fp.x, fp.y)] = fp
    midx, midy = (x0 + x1) // 2, (y0 + y1) // 2
    for target in ((midx, y0), (x0, midy)):
        fp = scan(lambda c, t=target: (abs(c[0] - t[0]) + abs(c[1] - t[1])), lambda x, y: True)
        if fp is not None:
            out[(fp.x, fp.y)] = fp
    return [out[k] for k in sorted(out)]


def _trunk(region: set[Cell], th: Footprint, side: str) -> list[Cell]:
    """Maximal straight 1-wide run hugging one TH side, clipped to the region.
    side in {"top","bottom","left","right"}; the run extends BOTH ways along
    that side's outer line, so the trunk passes the TH rather than only
    starting at it."""
    if side == "top":
        line = [(x, th.y - 1) for x in range(-1000, 1000)]
        anchor = (th.x, th.y - 1)
    elif side == "bottom":
        line = [(x, th.y + th.length) for x in range(-1000, 1000)]
        anchor = (th.x, th.y + th.length)
    elif side == "left":
        line = [(th.x - 1, y) for y in range(-1000, 1000)]
        anchor = (th.x - 1, th.y)
    else:
        line = [(th.x + th.width, y) for y in range(-1000, 1000)]
        anchor = (th.x + th.width, th.y)
    if anchor not in region:
        return []
    # maximal contiguous in-region run through the anchor
    idx = line.index(anchor)
    run = [anchor]
    for i in range(idx - 1, -1, -1):
        if line[i] in region:
            run.insert(0, line[i])
        else:
            break
    for i in range(idx + 1, len(line)):
        if line[i] in region:
            run.append(line[i])
        else:
            break
    return run


def _stub_cells(region: set[Cell], th: Footprint, roads: set[Cell]) -> list[Cell]:
    """The user's verified TH-corner stub pair: flank cells at both ends of the
    TH's bottom row, else top row; both cells must be in-region and off-road."""
    for row in (th.y + th.length - 1, th.y):
        pair = [(th.x - 1, row), (th.x + th.width, row)]
        if all(c in region and c not in roads for c in pair):
            return pair
    return []


def generate_patterns(region: set[Cell], tw: int, tl: int, k: int,
                      rng: random.Random, max_patterns: int) -> list["Pattern"]:
    """Deterministic parameter grid -> comb patterns with EXACTLY k road cells;
    rng shuffles only the order. Connectivity holds by construction (trunk hugs
    the TH border; branches touch the trunk; stubs touch the TH)."""
    out: list[Pattern] = []
    seen: set[frozenset[Cell]] = set()
    for th in th_anchor_candidates(region, tw, tl):
        th_cells = th.cells()
        reg = region  # roads may not overlap the TH
        for side in ("top", "bottom", "left", "right"):
            trunk = [c for c in _trunk(reg, th, side) if c not in th_cells]
            if not trunk:
                continue
            horiz = trunk[0][1] == trunk[-1][1]
            for spacing in (3, 4, 5, 6, 7):
                for mode in ("both", "alternate"):
                    for use_stubs in (False, True):
                        roads: set[Cell] = set()
                        stubs = _stub_cells(reg, th, roads) if use_stubs else []
                        budget = k - len(stubs)
                        if budget < 1:
                            continue
                        trunk_len = 1 if budget == 1 else max(2, budget // 2)
                        trunk_used = trunk[:min(len(trunk), trunk_len)]
                        roads |= set(trunk_used)
                        remaining = budget - len(trunk_used)
                        if remaining < 0:
                            continue
                        # branch seeds along the trunk at `spacing`, skipping ends
                        seeds = trunk_used[spacing - 1::spacing]
                        dirs = []
                        for i, s in enumerate(seeds):
                            if horiz:
                                cand_dirs = [(0, -1), (0, 1)]
                            else:
                                cand_dirs = [(-1, 0), (1, 0)]
                            if mode == "both":
                                dirs += [(s, d) for d in cand_dirs]
                            else:
                                dirs.append((s, cand_dirs[i % 2]))
                        # grow branches round-robin one cell at a time until budget spent
                        fronts = [ (s, d, 1) for (s, d) in dirs ]
                        grown = True
                        while remaining > 0 and grown:
                            grown = False
                            for j, (s, d, dist) in enumerate(fronts):
                                if remaining == 0:
                                    break
                                c = (s[0] + d[0] * dist, s[1] + d[1] * dist)
                                if c in reg and c not in roads and c not in th_cells:
                                    roads.add(c)
                                    fronts[j] = (s, d, dist + 1)
                                    remaining -= 1
                                    grown = True
                        if remaining != 0:
                            continue          # couldn't hit exactly k: discard
                        roads |= set(stubs)
                        key = frozenset(roads)
                        if len(key) != k or key in seen:
                            continue
                        seen.add(key)
                        out.append(Pattern(th=th, roads=key, params={
                            "th": (th.x, th.y), "side": side, "spacing": spacing,
                            "mode": mode, "stubs": use_stubs,
                            "trunk_len": len(trunk_used), "k": k}))
    rng.shuffle(out)
    return out[:max_patterns]


def prefilter(pattern: Pattern, region: set[Cell],
              consumers: list[Building]) -> str | None:
    """NECESSARY conditions only — a rejection is a proof of UNSAT (spec §5)."""
    th_cells = pattern.th.cells()
    area_needed = sum(b.footprint.width * b.footprint.length for b in consumers)
    if area_needed + len(pattern.roads) > len(region) - len(th_cells):
        return "area"
    free = region - pattern.roads - th_cells
    capacity = sum(3 for c in pattern.roads
                   if any((c[0] + dx, c[1] + dy) in free for dx, dy in _ORTHO))
    if capacity < len(consumers):
        return "adjacency-capacity"
    return None


def _check_pattern(p: Pattern, region: set[Cell], k: int) -> None:
    assert len(p.roads) == k, f"{len(p.roads)} != {k}"
    assert p.roads <= region and not (p.roads & p.th.cells())
    # connected to the TH border: BFS over road cells seeded at TH-adjacent ones
    th_border = p.th.border_cells()
    seeds = [c for c in p.roads if c in th_border]
    assert seeds, "no road cell touches the TH border"
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        cx, cy = stack.pop()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in p.roads and n not in seen:
                seen.add(n)
                stack.append(n)
    assert seen == set(p.roads), "pattern not connected to the TH"


def _anchor_candidates(b: Building, region: set[Cell], blocked: set[Cell],
                       roads: frozenset[Cell]) -> list[tuple[int, int, int]]:
    """All (x, y, orient) with footprint in-region, off blocked cells, and >=1
    border cell on a road. orient 0: w x l; orient 1: l x w (skipped for squares)."""
    out = []
    w0, l0 = b.footprint.width, b.footprint.length
    x0, y0, x1, y1 = _bbox(region)
    dims = [(w0, l0)] if w0 == l0 else [(w0, l0), (l0, w0)]
    for o, (w, l) in enumerate(dims):
        for y in range(y0, y1 - l + 2):
            for x in range(x0, x1 - w + 2):
                fp = Footprint(x, y, w, l)
                cells = fp.cells()
                if not (cells <= region) or (cells & blocked):
                    continue
                if any(c in roads for c in fp.border_cells()):
                    out.append((x, y, o))
    return out


def probe(pattern: Pattern, region: set[Cell], consumers: list[Building],
          *, probe_limit: float) -> tuple[str, dict | None]:
    from ortools.sat.python import cp_model

    th_cells = set(pattern.th.cells())
    blocked = set(pattern.roads) | th_cells
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            return ("UNSAT", None)            # exact fast-fail (spec §6)
        cand.append((b, opts))

    m = cp_model.CpModel()
    x0b, y0b, x1b, y1b = _bbox(region)
    xs, ys, os_, xiv, yiv = [], [], [], [], []
    for i, (b, opts) in enumerate(cand):
        w0, l0 = b.footprint.width, b.footprint.length
        x = m.NewIntVar(x0b, x1b, f"x{i}")
        y = m.NewIntVar(y0b, y1b, f"y{i}")
        o = m.NewIntVar(0, 1, f"o{i}")
        m.AddAllowedAssignments([x, y, o], opts)
        if w0 == l0:
            m.Add(o == 0)
            xiv.append(m.NewFixedSizeIntervalVar(x, w0, f"xi{i}"))
            yiv.append(m.NewFixedSizeIntervalVar(y, l0, f"yi{i}"))
        else:
            lit0 = m.NewBoolVar(f"lit0_{i}")
            m.Add(o == 0).OnlyEnforceIf(lit0)
            m.Add(o == 1).OnlyEnforceIf(lit0.Not())
            xiv.append(m.NewOptionalFixedSizeIntervalVar(x, w0, lit0, f"xi0_{i}"))
            yiv.append(m.NewOptionalFixedSizeIntervalVar(y, l0, lit0, f"yi0_{i}"))
            xiv.append(m.NewOptionalFixedSizeIntervalVar(x, l0, lit0.Not(), f"xi1_{i}"))
            yiv.append(m.NewOptionalFixedSizeIntervalVar(y, w0, lit0.Not(), f"yi1_{i}"))
        xs.append(x); ys.append(y); os_.append(o)
    m.AddNoOverlap2D(xiv, yiv)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = probe_limit
    st = solver.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        pos = {}
        for i, (b, _) in enumerate(cand):
            w0, l0 = b.footprint.width, b.footprint.length
            w, l = (w0, l0) if solver.Value(os_[i]) == 0 else (l0, w0)
            pos[b.entity_id] = (solver.Value(xs[i]), solver.Value(ys[i]), w, l)
        return ("SAT", pos)
    if st == cp_model.INFEASIBLE:
        return ("UNSAT", None)
    return ("UNKNOWN", None)


def validate(layout_src: Layout, pattern: Pattern,
             positions: dict) -> tuple[str, Layout | None, int]:
    """SAT result -> full routed layout or a distinct failure status (spec §7)."""
    consumers = layout_src.road_needing()
    fillers = [b for b in layout_src.buildings
               if not b.needs_road and not b.is_townhall]
    placed = []
    for b in consumers:
        x, y, w, l = positions[b.entity_id]
        placed.append(replace(b, footprint=Footprint(x, y, w, l)))
    th = replace(layout_src.townhall, footprint=pattern.th)
    cand = Layout(layout_src.region, [th, *placed], th, {})
    try:
        roads = route(cand)
    except RouteError:
        return ("ROUTE_FAIL", None, 0)
    cand.roads = roads
    if not is_valid(cand):
        return ("INVALID", None, 0)
    # gap-fill ALL fillers (explicit acceptance condition, spec §7.2)
    region = set(layout_src.region.cells)
    x0, y0, x1, y1 = _bbox(region)
    w, h = x1 + 1, y1 + 1
    occupied = set(roads) | set(th.footprint.cells())
    for b in placed:
        occupied |= b.footprint.cells()
    free = region - occupied
    grid = Grid(w, h, {(x, y) for x in range(w) for y in range(h)} - free)
    for b in sorted(fillers, key=lambda b: -(b.footprint.width * b.footprint.length)):
        bw, bl = b.footprint.width, b.footprint.length
        spot = first_fit(grid, bw, bl)
        if spot is None and bw != bl:
            bw, bl = bl, bw
            spot = first_fit(grid, bw, bl)
        if spot is None:
            return ("SAT_FILLER_FAIL", None, len(roads))
        grid.occupy(spot[0], spot[1], bw, bl)
        cand.buildings.append(replace(b, footprint=Footprint(spot[0], spot[1], bw, bl)))
    return ("OK", cand, len(roads))


def _selftest() -> int:
    from rl.oracle import optimal_roads
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "b")
    region_cells = frozenset((x, y) for x in range(6) for y in range(6))
    lay = Layout(Region(region_cells), [th, c1, c2], th, {})
    oracle = optimal_roads(lay, budget_s=60.0)
    region = set(region_cells)
    rng = random.Random(0)
    ok_k1 = False
    for pat in generate_patterns(region, 2, 2, 1, rng, 50):
        if prefilter(pat, region, [c1, c2]) is not None:
            continue
        st, pos = probe(pat, region, [c1, c2], probe_limit=30.0)
        if st != "SAT":
            continue
        vstat, vlay, achieved = validate(lay, pat, pos)
        if vstat == "OK" and achieved == oracle:
            ok_k1 = True
            break
    # k=0 is UNSAT by definition (no pattern has road cells -> no anchors);
    # generate_patterns(k=0) yields nothing, which is the same statement.
    ok_k0 = generate_patterns(region, 2, 2, 0, random.Random(0), 50) == []
    print(f"selftest: oracle={oracle} k1_validated={ok_k1} k0_empty={ok_k0} "
          f"{'PASS' if (ok_k1 and ok_k0) else 'FAIL'}")
    return 0 if (ok_k1 and ok_k0) else 1


def _probe_level(layout, region, consumers, k, rng, args, log) -> tuple[str, int | None]:
    """Probe up to --patterns patterns at level k. Returns (level_status, best_achieved):
    level_status in {"FEASIBLE", "INFEASIBLE", "INCONCLUSIVE"} — INFEASIBLE only if
    every attempted pattern was UNSAT (incl. prefilter rejections, which are proofs);
    any UNKNOWN or SAT_FILLER_FAIL/ROUTE_FAIL/INVALID makes a failed level INCONCLUSIVE."""
    th = layout.townhall.footprint
    pats = generate_patterns(region, th.width, th.length, k, rng, args.patterns)
    best_achieved = None
    saw_nonproof_failure = False
    for pat in pats:
        t0 = time.monotonic()
        reason = prefilter(pat, region, consumers)
        if reason is not None:
            log({"k": k, "params": pat.params, "status": "PREFILTERED",
                 "reason": reason, "secs": 0.0})
            continue
        st, pos = probe(pat, region, consumers, probe_limit=args.probe_limit)
        secs = round(time.monotonic() - t0, 1)
        if st == "SAT":
            vstat, vlay, achieved = validate(layout, pat, pos)
            log({"k": k, "params": pat.params, "status": vstat if vstat != "OK" else "SAT",
                 "achieved": achieved if vstat == "OK" else None, "secs": secs})
            if vstat == "OK":
                if best_achieved is None or achieved < best_achieved:
                    best_achieved = achieved
                    out_dir = pathlib.Path("output/roads-first")
                    out_dir.mkdir(parents=True, exist_ok=True)
                    stem = f"best-k{k}-a{achieved}"
                    (out_dir / f"{stem}.json").write_text(json.dumps({
                        "k": k, "achieved": achieved, "pattern": pat.params,
                        "roads": sorted(vlay.roads),
                        "buildings": {b.entity_id: [b.footprint.x, b.footprint.y,
                                                    b.footprint.width, b.footprint.length]
                                      for b in vlay.buildings}}, indent=1), encoding="utf-8")
                    (out_dir / f"{stem}.html").write_text(render_html(vlay), encoding="utf-8")
            else:
                saw_nonproof_failure = True
        else:
            log({"k": k, "params": pat.params, "status": st, "secs": secs})
            if st == "UNKNOWN":
                saw_nonproof_failure = True
        if time.monotonic() > args.deadline:
            return ("INCONCLUSIVE" if best_achieved is None else "FEASIBLE", best_achieved)
    if best_achieved is not None:
        return ("FEASIBLE", best_achieved)
    if not pats:
        return ("INCONCLUSIVE", None)         # generator produced nothing: no proof either way
    return ("INCONCLUSIVE" if saw_nonproof_failure else "INFEASIBLE", None)


def run_search(layout, args) -> dict:
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    rng = random.Random(args.seed)
    out_dir = pathlib.Path("output/roads-first")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "probes.jsonl").open("a", encoding="utf-8") as logf:

        def log(row):
            logf.write(json.dumps(row) + "\n")
            logf.flush()

        def timed_out():
            return time.monotonic() >= args.deadline

        results: dict[int, tuple[str, int | None]] = {}

        def level(k):
            if k not in results:
                print(f"probing k={k} ...", flush=True)
                results[k] = _probe_level(layout, region, consumers, k, rng, args, log)
                print(f"  k={k}: {results[k][0]}"
                      f"{' achieved=' + str(results[k][1]) if results[k][1] is not None else ''}",
                      flush=True)
            return results[k]

        truncated = False                     # any loop cut short by the deadline
        k = args.k_start
        st, _ = level(k)
        if st != "FEASIBLE":                  # spec §8: family-too-weak fallback
            while st != "FEASIBLE" and k < 168:
                if timed_out():
                    truncated = True
                    break
                k += 4
                st, _ = level(k)
            if st != "FEASIBLE":
                return {"verdict": "FAMILY_TOO_WEAK", "walk_complete": not truncated,
                        "deadline_hit": timed_out(), "results": results}
        lo_feasible = k
        while True:                           # walk down in steps of 4
            if timed_out():
                truncated = True
                break
            nxt = lo_feasible - 4
            if nxt < 1:
                break
            st, _ = level(nxt)
            if st == "FEASIBLE":
                lo_feasible = nxt
            else:
                break
        # bisect the gap [nxt, lo_feasible)
        lo, hi = lo_feasible - 4, lo_feasible
        while hi - lo > 1:
            if timed_out():
                truncated = True
                break
            mid = (lo + hi) // 2
            st, _ = level(mid)
            if st == "FEASIBLE":
                hi = mid
            else:
                lo = mid
        best = min((r[1] for r in results.values() if r[1] is not None), default=None)
        unknowns = sum(1 for r in results.values() if r[0] == "INCONCLUSIVE")
        # `lowest_feasible_k_probed` is exactly that: the lowest level this (possibly
        # deadline-truncated) walk probed FEASIBLE — not a proven floor. Levels below it
        # may be unprobed or INCONCLUSIVE; see walk_complete/deadline_hit and `results`.
        return {"verdict": "DONE",
                "lowest_feasible_k_probed": hi if best is not None else None,
                "best_achieved": best, "inconclusive_levels": unknowns,
                "walk_complete": not truncated, "deadline_hit": timed_out(),
                "results": results}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("--dump-patterns", type=int, default=None, metavar="K")
    p.add_argument("--patterns", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--k-start", type=int, default=152)
    p.add_argument("--probe-limit", type=float, default=120.0)
    p.add_argument("--time-box", type=float, default=21600.0)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args(argv)
    if args.smoke:
        args.k_start = 156
        args.patterns = 20
        args.probe_limit = 20.0
        args.time_box = 600.0
    if args.selftest:
        return _selftest()
    if args.dump_patterns is not None:
        layout = load_layout(args.city)
        region = set(layout.region.cells)
        th = layout.townhall.footprint
        consumers = layout.road_needing()
        rng = random.Random(args.seed)
        pats = generate_patterns(region, th.width, th.length,
                                 args.dump_patterns, rng, args.patterns)
        kept = 0
        for pat in pats:
            _check_pattern(pat, region, args.dump_patterns)
            if prefilter(pat, region, consumers) is None:
                kept += 1
        print(f"k={args.dump_patterns}: {len(pats)} generated, {kept} past prefilter")
        for pat in pats[:5]:
            print("  ", pat.params)
        return 0
    if args.city is None:
        p.error("city is required for the k-walk (or use --selftest / --dump-patterns)")
    args.deadline = time.monotonic() + args.time_box
    layout = load_layout(args.city)
    res = run_search(layout, args)
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, indent=1))
    per_level = {k: v[0] + (f" achieved={v[1]}" if v[1] is not None else "")
                 for k, v in sorted(res["results"].items())}
    print("levels:", json.dumps(per_level, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
