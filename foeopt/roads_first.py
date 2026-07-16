from __future__ import annotations

import json
import multiprocessing
import random
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.bounds import pick_k_start
from foeopt.corpus import CorpusWriter

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


def _th_anchor_cell(th: Footprint, side: str) -> Cell:
    if side == "top":
        return (th.x, th.y - 1)
    if side == "bottom":
        return (th.x, th.y + th.length)
    if side == "left":
        return (th.x - 1, th.y)
    return (th.x + th.width, th.y)


def generate_lane_patterns(region: set[Cell], tw: int, tl: int, k: int,
                           rng: random.Random, max_patterns: int,
                           th_mode: str = "coarse") -> list[Pattern]:
    """Parallel double-loaded-lane family: unlike generate_patterns's comb
    (single trunk consuming budget//2 regardless of need, short teeth), this
    grows a *minimal* trunk -- only as long as needed to connect the TH to
    the lane seeds on both sides of it along the trunk line -- then grows
    full straight lanes from each seed, mirroring the user's hand-built
    city's near-zero trunk overhead (memory/foe-layout-heuristics: 5
    non-double-row cells out of 142)."""
    out: list[Pattern] = []
    seen: set[frozenset[Cell]] = set()
    for th in th_anchor_candidates(region, tw, tl, mode=th_mode):
        th_cells = th.cells()
        reg = region
        for side in ("top", "bottom", "left", "right"):
            trunk_raw = [c for c in _trunk(reg, th, side) if c not in th_cells]
            if not trunk_raw:
                continue
            anchor = _th_anchor_cell(th, side)
            if anchor not in trunk_raw:
                continue
            anchor_idx = trunk_raw.index(anchor)
            horiz = trunk_raw[0][1] == trunk_raw[-1][1]
            for pitch in (5, 6, 7, 8, 9, 10, 11):
                for use_stubs in (False, True):
                    roads: set[Cell] = set()
                    stubs = _stub_cells(reg, th, roads) if use_stubs else []
                    budget = k - len(stubs)
                    if budget < 1:
                        continue
                    pos_idxs = list(range(anchor_idx + pitch, len(trunk_raw), pitch))
                    neg_idxs = list(range(anchor_idx - pitch, -1, -pitch))
                    seed_idxs = sorted(pos_idxs + neg_idxs)
                    if not seed_idxs:
                        continue
                    lo, hi = min(seed_idxs + [anchor_idx]), max(seed_idxs + [anchor_idx])
                    trunk_used = trunk_raw[lo:hi + 1]
                    roads |= set(trunk_used)
                    remaining = budget - len(trunk_used)
                    if remaining < 0:
                        continue
                    seeds = [trunk_raw[i] for i in seed_idxs]
                    cand_dirs = [(0, -1), (0, 1)] if horiz else [(-1, 0), (1, 0)]
                    fronts = [(s, d, 1) for s in seeds for d in cand_dirs]
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
                        "th": (th.x, th.y), "side": side, "pitch": pitch,
                        "stubs": use_stubs, "trunk_len": len(trunk_used), "k": k}))
    rng.shuffle(out)
    return out[:max_patterns]


def _pattern_generator(family: str):
    # Resolved dynamically (not a frozen dict built at import time) so tests
    # that monkeypatch module-level generate_patterns/generate_lane_patterns
    # still take effect here.
    return generate_lane_patterns if family == "lane" else generate_patterns


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


def _add_symmetry_breaking(m, cand, xs, ys) -> None:
    """Buildings sharing a footprint size are interchangeable in this model
    (_anchor_candidates only looks at width/length), so the solver otherwise
    explores every permutation of them as distinct symmetric solutions. Chain
    a lexicographic (x, y) <= ordering across each size-group to collapse
    that permutation symmetry to one representative assignment."""
    groups: dict[tuple[int, int], list[int]] = {}
    for i, (b, _) in enumerate(cand):
        groups.setdefault((b.footprint.width, b.footprint.length), []).append(i)
    for members in groups.values():
        for a, b_idx in zip(members, members[1:]):
            lt = m.NewBoolVar(f"symlt{a}_{b_idx}")
            eq = m.NewBoolVar(f"symeq{a}_{b_idx}")
            m.Add(xs[a] < xs[b_idx]).OnlyEnforceIf(lt)
            m.Add(xs[a] >= xs[b_idx]).OnlyEnforceIf(lt.Not())
            m.Add(xs[a] == xs[b_idx]).OnlyEnforceIf(eq)
            m.Add(xs[a] != xs[b_idx]).OnlyEnforceIf(eq.Not())
            m.AddBoolOr([lt, eq])
            m.Add(ys[a] <= ys[b_idx]).OnlyEnforceIf(eq)


def _nearest_opt(opts: list[tuple[int, int]], target: tuple[int, int]) -> tuple[int, int]:
    tx, ty = target
    return min(opts, key=lambda o: abs(o[0] - tx) + abs(o[1] - ty))


def _th_stub_cells_in_pattern(th: Footprint, roads) -> list[Cell]:
    """Which of the 4 candidate TH-flank cells (left/right x top/bottom row
    of the TH footprint -- the two the user's expert city stubs off of,
    each reaching load-3 "for free" via the TH edge) are actually road
    cells in this pattern. Works for any pattern regardless of which
    generator produced it or whether it used an explicit stub mechanism --
    it just looks at the final road-cell set."""
    out = []
    for row in (th.y, th.y + th.length - 1):
        for x in (th.x - 1, th.x + th.width):
            c = (x, row)
            if c in roads:
                out.append(c)
    return out


def _stub_priority_hints(pattern: Pattern,
                         cand: list[tuple[Building, list[tuple[int, int]]]]
                         ) -> dict[int, tuple[int, int]]:
    """Bias the largest buildings toward the TH-flank stub cells present in
    this pattern -- up to 3 buildings per cell, matching the load-3 ceiling
    a stub cell can serve. CP-SAT has no objective in this model, so without
    a nudge it seats whichever building happens to fit there first,
    regardless of size (memory/foe-layout-heuristics: the expert city
    deliberately puts ~3 big buildings next to each TH stub)."""
    stub_cells = _th_stub_cells_in_pattern(pattern.th, pattern.roads)
    if not stub_cells:
        return {}
    hints: dict[int, tuple[int, int]] = {}
    used: set[int] = set()
    for c in stub_cells:
        touching = []
        for i, (b, opts) in enumerate(cand):
            if i in used:
                continue
            w, l = b.footprint.width, b.footprint.length
            for (x, y) in opts:
                if c in Footprint(x, y, w, l).border_cells():
                    touching.append((w * l, i, (x, y)))
                    break
        touching.sort(key=lambda t: t[0], reverse=True)
        for _area, i, xy in touching[:3]:
            hints[i] = xy
            used.add(i)
    return hints


def probe(pattern: Pattern, region: set[Cell], consumers: list[Building],
          *, probe_limit: float, probe_workers: int = 1,
          symmetry_breaking: bool = False,
          hints: dict[int, tuple[int, int]] | None = None,
          stub_priority: bool = False) -> tuple[str, dict | None]:
    from ortools.sat.python import cp_model

    th_cells = set(pattern.th.cells())
    blocked = set(pattern.roads) | th_cells
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            return ("UNSAT", None)
        cand.append((b, opts))

    stub_hints = _stub_priority_hints(pattern, cand) if stub_priority else {}

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
        if hints is not None and b.entity_id in hints:
            hx, hy = _nearest_opt(opts, hints[b.entity_id])
            m.AddHint(x, hx)
            m.AddHint(y, hy)
        elif i in stub_hints:
            hx, hy = stub_hints[i]
            m.AddHint(x, hx)
            m.AddHint(y, hy)
    m.AddNoOverlap2D(xiv, yiv)
    if symmetry_breaking:
        _add_symmetry_breaking(m, cand, xs, ys)

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
_WORKER_SYMMETRY_BREAKING: bool = False
_WORKER_HINTS: dict[int, tuple[int, int]] | None = None
_WORKER_STUB_PRIORITY: bool = False


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int,
                 symmetry_breaking: bool = False, hints=None,
                 stub_priority: bool = False) -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    global _WORKER_SYMMETRY_BREAKING, _WORKER_HINTS, _WORKER_STUB_PRIORITY
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    _WORKER_SYMMETRY_BREAKING = symmetry_breaking
    _WORKER_HINTS = hints
    _WORKER_STUB_PRIORITY = stub_priority


def _run_probe(payload: tuple) -> dict:
    pat, k, pat_index = payload
    layout = _WORKER_LAYOUT
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers,
                   probe_limit=_WORKER_PROBE_LIMIT,
                   probe_workers=_WORKER_PROBE_WORKERS,
                   symmetry_breaking=_WORKER_SYMMETRY_BREAKING,
                   hints=_WORKER_HINTS,
                   stub_priority=_WORKER_STUB_PRIORITY)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None,
                "pat_index": pat_index, "pos": None}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay,
                "pat_index": pat_index, "pos": pos}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None,
            "pat_index": pat_index, "pos": pos}


def _run_probe_seq(payload: tuple) -> dict:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    global _WORKER_SYMMETRY_BREAKING, _WORKER_HINTS, _WORKER_STUB_PRIORITY
    pat, k, layout, probe_limit, probe_workers, *rest = payload
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    _WORKER_SYMMETRY_BREAKING = rest[0] if rest else False
    _WORKER_HINTS = rest[1] if len(rest) > 1 else None
    _WORKER_STUB_PRIORITY = rest[2] if len(rest) > 2 else False
    try:
        return _run_probe((pat, k, 0))
    finally:
        _WORKER_LAYOUT = None

def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None, corpus=None, scorer=None, score_threshold=None) -> tuple[str, int | None]:
    th = layout.townhall.footprint
    th_mode = getattr(params, "th_anchors", "coarse")
    gen_fn = _pattern_generator(getattr(params, "pattern_family", "comb"))
    pats = gen_fn(region, th.width, th.length, k, rng, params.patterns,
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
        if corpus is not None:
            corpus.record(k=k, roads=pat.roads, th=pat.th, status=status,
                          secs=result["secs"], pos=result.get("pos"))
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

    if scorer is not None and surviving:
        scored = [(scorer(pat), pat) for pat in surviving]
        if score_threshold is not None:
            scored = [sp for sp in scored if sp[0] >= score_threshold]
        scored.sort(key=lambda sp: sp[0], reverse=True)
        surviving = [pat for _, pat in scored]

    if pool is None:
        for pat in surviving:
            result = _run_probe_seq((pat, k, layout, params.probe_limit, params.probe_workers,
                                     getattr(params, "symmetry_breaking", False),
                                     getattr(params, "hints", None),
                                     getattr(params, "stub_priority", False)))
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


class RoadsFirstSearch:
    def __init__(self, layout: Layout, *, time_box: float, patterns: int = 200,
                 probe_limit: float = 60.0, workers: int = 4,
                 probe_workers: int = 4, th_anchors: str = "full",
                 k_start="auto", corpus_dir=None, scorer=None, score_threshold=None,
                 symmetry_breaking: bool = False, hint_layout: Layout | None = None,
                 pattern_family: str = "comb", stub_priority: bool = False):
        self.layout = layout
        self.time_box = time_box
        self.patterns = patterns
        self.probe_limit = probe_limit
        self.workers = workers
        self.probe_workers = probe_workers
        self.th_anchors = th_anchors
        self.k_start = k_start
        self.corpus_dir = corpus_dir
        self.scorer = scorer
        self.score_threshold = score_threshold
        self.symmetry_breaking = symmetry_breaking
        self.hints = ({b.entity_id: (b.footprint.x, b.footprint.y) for b in hint_layout.buildings}
                     if hint_layout is not None else None)
        self.pattern_family = pattern_family
        self.stub_priority = stub_priority

    def run(self, on_improvement=None, on_status=None, should_stop=None) -> dict:
        layout = self.layout
        region = set(layout.region.cells)
        consumers = layout.road_needing()
        rng = random.Random(0)
        deadline = time.monotonic() + self.time_box

        pool = None
        if self.workers > 1:
            pool = multiprocessing.Pool(
                self.workers,
                initializer=_worker_init,
                initargs=(layout, self.probe_limit, self.probe_workers,
                         self.symmetry_breaking, self.hints, self.stub_priority))

        corpus = None

        params = SimpleNamespace(
            patterns=self.patterns,
            probe_limit=self.probe_limit,
            probe_workers=self.probe_workers,
            deadline=deadline,
            th_anchors=self.th_anchors,
            symmetry_breaking=self.symmetry_breaking,
            hints=self.hints,
            pattern_family=self.pattern_family,
            stub_priority=self.stub_priority,
        )

        results: dict[int, tuple[str, int | None]] = {}

        def _should_stop():
            if should_stop is not None and should_stop():
                return True
            return time.monotonic() >= deadline

        def level(k):
            if k not in results:
                results[k] = _probe_level(layout, region, consumers, k, rng,
                                          params, lambda r: None, pool=pool,
                                          on_improvement=on_improvement, corpus=corpus,
                                          scorer=self.scorer, score_threshold=self.score_threshold)
                if on_status is not None:
                    on_status(k, results[k][0], 0, 0)
            return results[k]

        try:
            if self.corpus_dir:
                corpus = CorpusWriter(self.corpus_dir, layout)
            truncated = False

            if self.k_start == "auto":
                k = pick_k_start(layout)
            else:
                k = self.k_start

            st, _ = level(k)
            if st != "FEASIBLE":
                k_max = len(layout.region.cells) - sum(
                    b.footprint.width * b.footprint.length for b in layout.buildings)
                while st != "FEASIBLE" and k < k_max:
                    if _should_stop():
                        truncated = True
                        break
                    k += 4
                    st, _ = level(k)
                if st != "FEASIBLE":
                    return {"verdict": "FAMILY_TOO_WEAK", "walk_complete": not truncated,
                            "deadline_hit": _should_stop(), "results": results}

            lo_feasible = k
            while True:
                if _should_stop():
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

            lo, hi = lo_feasible - 4, lo_feasible
            while hi - lo > 1:
                if _should_stop():
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
            return {"verdict": "DONE",
                    "lowest_feasible_k_probed": hi if best is not None else None,
                    "best_achieved": best, "inconclusive_levels": unknowns,
                    "walk_complete": not truncated, "deadline_hit": _should_stop(),
                    "results": results}
        finally:
            if corpus is not None:
                corpus.close()
            if pool is not None:
                pool.close()
                pool.join()
