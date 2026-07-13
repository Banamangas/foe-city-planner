from __future__ import annotations

import json
import multiprocessing
import random
import time
from dataclasses import dataclass, replace

from foeopt.model import Building, Footprint, Layout, Region

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


def th_anchor_candidates(region: set[Cell], tw: int, tl: int,
                         mode: str = "coarse") -> list[Footprint]:
    if mode == "full":
        x0, y0, x1, y1 = _bbox(region)
        out: dict[tuple[int, int], Footprint] = {}
        for x in range(x0, x1 - tw + 2):
            for y in range(y0, y1 - tl + 2):
                fp = Footprint(x, y, tw, tl)
                if _fits(region, fp):
                    out[(x, y)] = fp
        return [out[k] for k in sorted(out)]
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
    for row in (th.y + th.length - 1, th.y):
        pair = [(th.x - 1, row), (th.x + th.width, row)]
        if all(c in region and c not in roads for c in pair):
            return pair
    return []


def generate_patterns(region: set[Cell], tw: int, tl: int, k: int,
                      rng: random.Random, max_patterns: int,
                      th_mode: str = "coarse") -> list[Pattern]:
    out: list[Pattern] = []
    seen: set[frozenset[Cell]] = set()
    for th in th_anchor_candidates(region, tw, tl, mode=th_mode):
        th_cells = th.cells()
        reg = region
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
                        fronts = [(s, d, 1) for (s, d) in dirs]
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
                            continue
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


from foeopt.packing import Grid, first_fit
from foeopt.router import RouteError, route
from foeopt.validate import canonical_dims, is_valid, rotated_buildings


def _check_pattern(p: Pattern, region: set[Cell], k: int) -> None:
    assert len(p.roads) == k, f"{len(p.roads)} != {k}"
    assert p.roads <= region and not (p.roads & p.th.cells())
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
                       roads: frozenset[Cell]) -> list[tuple[int, int]]:
    out = []
    w, l = b.footprint.width, b.footprint.length
    x0, y0, x1, y1 = _bbox(region)
    for y in range(y0, y1 - l + 2):
        for x in range(x0, x1 - w + 2):
            fp = Footprint(x, y, w, l)
            cells = fp.cells()
            if not (cells <= region) or (cells & blocked):
                continue
            if any(c in roads for c in fp.border_cells()):
                out.append((x, y))
    return out


def probe(pattern: Pattern, region: set[Cell], consumers: list[Building],
          *, probe_limit: float, probe_workers: int = 1) -> tuple[str, dict | None]:
    from ortools.sat.python import cp_model

    th_cells = set(pattern.th.cells())
    blocked = set(pattern.roads) | th_cells
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            return ("UNSAT", None)
        cand.append((b, opts))

    m = cp_model.CpModel()
    x0b, y0b, x1b, y1b = _bbox(region)
    xs, ys, xiv, yiv = [], [], [], []
    for i, (b, opts) in enumerate(cand):
        w0, l0 = b.footprint.width, b.footprint.length
        x = m.NewIntVar(x0b, x1b, f"x{i}")
        y = m.NewIntVar(y0b, y1b, f"y{i}")
        m.AddAllowedAssignments([x, y], opts)
        xiv.append(m.NewFixedSizeIntervalVar(x, w0, f"xi{i}"))
        yiv.append(m.NewFixedSizeIntervalVar(y, l0, f"yi{i}"))
        xs.append(x); ys.append(y)
    m.AddNoOverlap2D(xiv, yiv)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = probe_workers
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = probe_limit
    st = solver.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        pos = {}
        for i, (b, _) in enumerate(cand):
            w, l = b.footprint.width, b.footprint.length
            pos[b.entity_id] = (solver.Value(xs[i]), solver.Value(ys[i]), w, l)
        return ("SAT", pos)
    if st == cp_model.INFEASIBLE:
        return ("UNSAT", None)
    return ("UNKNOWN", None)


def validate(layout_src: Layout, pattern: Pattern,
             positions: dict) -> tuple[str, Layout | None, int]:
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
        if spot is None:
            return ("SAT_FILLER_FAIL", None, len(roads))
        grid.occupy(spot[0], spot[1], bw, bl)
        cand.buildings.append(replace(b, footprint=Footprint(spot[0], spot[1], bw, bl)))
    bad = rotated_buildings(cand, canonical_dims(layout_src))
    if bad:
        return ("SAT_ROTATED", None, len(roads))
    return ("OK", cand, len(roads))


_WORKER_LAYOUT: Layout | None = None
_WORKER_PROBE_LIMIT: float = 30.0
_WORKER_PROBE_WORKERS: int = 1


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int) -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers


def _run_probe(payload: tuple) -> dict:
    pat, k, pat_index = payload
    layout = _WORKER_LAYOUT
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers,
                   probe_limit=_WORKER_PROBE_LIMIT,
                   probe_workers=_WORKER_PROBE_WORKERS)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay, "pat_index": pat_index}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}


def _run_probe_seq(payload: tuple) -> dict:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    pat, k, layout, probe_limit, probe_workers = payload
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    try:
        return _run_probe((pat, k, 0))
    finally:
        _WORKER_LAYOUT = None

def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None) -> tuple[str, int | None]:
    th = layout.townhall.footprint
    th_mode = getattr(params, "th_anchors", "coarse")
    pats = generate_patterns(region, th.width, th.length, k, rng, params.patterns,
                             th_mode=th_mode)
    best_achieved = None
    saw_nonproof_failure = False
    order = 0

    def handle_result(result, pat):
        nonlocal best_achieved, order, saw_nonproof_failure
        order += 1
        status = result["status"]
        achieved = result["achieved"]
        log({"k": k, "params": pat.params, "status": status,
             "achieved": achieved, "secs": result["secs"], "order": order})
        if status == "SAT":
            vlay = result["layout"]
            if best_achieved is None or achieved < best_achieved:
                best_achieved = achieved
                if on_improvement is not None:
                    on_improvement(vlay, k, achieved)
        elif status in ("UNKNOWN", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"):
            saw_nonproof_failure = True
        if time.monotonic() > params.deadline:
            return True
        return False

    surviving = []
    for pat in pats:
        reason = prefilter(pat, region, consumers)
        if reason is not None:
            log({"k": k, "params": pat.params, "status": "PREFILTERED",
                 "reason": reason, "secs": 0.0, "order": 0})
            continue
        surviving.append(pat)

    if pool is None:
        for pat in surviving:
            result = _run_probe_seq((pat, k, layout, params.probe_limit, params.probe_workers))
            if handle_result(result, pat):
                return ("INCONCLUSIVE" if best_achieved is None else "FEASIBLE", best_achieved)
    else:
        payloads = [(pat, k, idx) for idx, pat in enumerate(surviving)]
        for result in pool.imap_unordered(_run_probe, payloads):
            idx = result["pat_index"]
            pat = surviving[idx]
            if handle_result(result, pat):
                pool.terminate()
                break

    if best_achieved is not None:
        return ("FEASIBLE", best_achieved)
    if not pats:
        return ("INCONCLUSIVE", None)
    return ("INCONCLUSIVE" if saw_nonproof_failure else "INFEASIBLE", None)
