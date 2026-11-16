"""Topology of legal road networks vs the skeleton grammar (backlog Q3, analysis half).

The skeleton grammar (`generate_patterns` / `generate_lane_patterns` /
`generate_nonuniform_patterns` in foeopt/roads_first.py) is: ONE trunk on the line
flush to ONE Townhall side, straight branches perpendicular to it, optional
TH-flank stub cells. This script measures, for every legal network we hold
(the uploaded cities and the saved records), how far each one is from that
grammar, and which single extension of the grammar would cover the rest.

Core measure: **turn level**. A 0-1 BFS over (cell, axis) states from a seed set
counts the minimum number of turns needed to reach each road cell, travelling
only on road cells; level = turns + 1. With the seed = the trunk run on the line
at offset d from TH side s (axis along the trunk), the grammar is exactly
"level <= 2" (trunk = 1, perpendicular branches = 2). Extensions:

  two_sides   union of the grammar on the best two TH sides
  offset      trunk line at offset d in 0..MAX_OFFSET from the TH side, joined to
              the TH by a straight perpendicular connector (which is level 2)
  depth3      level <= 3 from the best flush trunk (sub-branches and bent branches)
  stub_roots  grammar plus level <= 2 from the TH-flank stub cells

Everything is pure Python, no solver, a few ms per network.

    .venv/bin/python scripts/analyze_network_topology.py [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import glob
import itertools
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

Cell = tuple[int, int]
SIDES = ("top", "bottom", "left", "right")
MAX_OFFSET = 60
H, V = 0, 1                      # axes
_STEPS = {H: ((1, 0), (-1, 0)), V: ((0, 1), (0, -1))}


# ---------------------------------------------------------------- primitives
def nbrs(c: Cell):
    x, y = c
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def th_cells(th) -> set[Cell]:
    x, y, w, l = th
    return {(i, j) for i in range(x, x + w) for j in range(y, y + l)}


def th_side_of(c: Cell, th) -> str | None:
    """Which TH border side the road cell `c` touches (None if not adjacent)."""
    x, y, w, l = th
    cx, cy = c
    if x <= cx < x + w and cy == y - 1:
        return "top"
    if x <= cx < x + w and cy == y + l:
        return "bottom"
    if y <= cy < y + l and cx == x - 1:
        return "left"
    if y <= cy < y + l and cx == x + w:
        return "right"
    return None


def components(cells: set[Cell]) -> list[set[Cell]]:
    seen, out = set(), []
    for s in cells:
        if s in seen:
            continue
        comp, stack = {s}, [s]
        seen.add(s)
        while stack:
            c = stack.pop()
            for n in nbrs(c):
                if n in cells and n not in seen:
                    seen.add(n); comp.add(n); stack.append(n)
        out.append(comp)
    return out


def runs(cells: set[Cell]) -> list[tuple[int, list[Cell]]]:
    """Maximal straight runs of length >= 2, as (axis, cells)."""
    out = []
    for axis, (dx, dy) in ((H, (1, 0)), (V, (0, 1))):
        for c in cells:
            if (c[0] - dx, c[1] - dy) in cells:
                continue            # not a run start
            run = [c]
            while (run[-1][0] + dx, run[-1][1] + dy) in cells:
                run.append((run[-1][0] + dx, run[-1][1] + dy))
            if len(run) >= 2:
                out.append((axis, run))
    return out


def turn_levels(cells: set[Cell], seeds: list[tuple[Cell, int]],
                per_axis: bool = False) -> dict:
    """Min turns+1 to reach each cell from `seeds` [(cell, axis)], moving only on
    `cells`. Going straight along the current axis is free, switching axis costs 1."""
    INF = 1 << 30
    dist: dict[tuple[Cell, int], int] = {}
    dq = collections.deque()
    for c, a in seeds:
        if c in cells and dist.get((c, a), INF) > 0:
            dist[(c, a)] = 0
            dq.appendleft((c, a))
    while dq:
        c, a = dq.popleft()
        d = dist[(c, a)]
        o = 1 - a
        if dist.get((c, o), INF) > d + 1:     # turn here
            dist[(c, o)] = d + 1
            dq.append((c, o))
        for dx, dy in _STEPS[a]:              # go straight
            n = (c[0] + dx, c[1] + dy)
            if n in cells and dist.get((n, a), INF) > d:
                dist[(n, a)] = d
                dq.appendleft((n, a))
    if per_axis:
        return {k: d + 1 for k, d in dist.items()}
    best: dict[Cell, int] = {}
    for (c, _a), d in dist.items():
        if d + 1 < best.get(c, INF):
            best[c] = d + 1
    return best


# ---------------------------------------------------------------- grammar
def trunk_line(side: str, d: int, th) -> tuple[int, callable]:
    """(axis along the trunk, predicate 'cell is on the line at offset d')."""
    x, y, w, l = th
    if side == "top":
        return H, lambda c: c[1] == y - 1 - d
    if side == "bottom":
        return H, lambda c: c[1] == y + l + d
    if side == "left":
        return V, lambda c: c[0] == x - 1 - d
    return V, lambda c: c[0] == x + w + d


def _toward_th(side: str) -> tuple[int, int]:
    return {"top": (0, 1), "bottom": (0, -1), "left": (1, 0), "right": (-1, 0)}[side]


def trunk_cells(cells: set[Cell], th, side: str, d: int) -> set[Cell]:
    """Maximal runs of road on the offset-d line of `side` that reach the TH: at
    d=0 a run containing a TH-adjacent cell (the grammar's trunk through the
    anchor); at d>0 a run with a straight road connector down to the TH."""
    axis, on = trunk_line(side, d, th)
    line = {c for c in cells if on(c)}
    if not line:
        return set()
    tdx, tdy = _toward_th(side)
    anchors = set()
    for c in line:
        p = c
        ok = True
        for _ in range(d):
            p = (p[0] + tdx, p[1] + tdy)
            if p not in cells:
                ok = False
                break
        if ok and th_side_of(p, th) == side:
            anchors.add(c)
    out = set()
    for comp in components(line):          # a component of a line = one run
        if comp & anchors:
            out |= comp
    return out


def stub_positions(th) -> set[Cell]:
    x, y, w, l = th
    return {(x - 1, r) for r in (y, y + l - 1)} | {(x + w, r) for r in (y, y + l - 1)}


def grammar_cover(cells, th, side, d, max_level=2) -> set[Cell]:
    trunk = trunk_cells(cells, th, side, d)
    if not trunk:
        return set()
    axis, _ = trunk_line(side, d, th)
    lv = turn_levels(cells, [(c, axis) for c in trunk])
    return {c for c, v in lv.items() if v <= max_level}


# ---------------------------------------------------------------- metrics
def analyze(roads: dict[Cell, int], th, consumers: list[tuple[int, int, int, int]],
            region: set[Cell] | None = None) -> dict:
    """All topology metrics for one network. `roads` cell->level, `th` and
    `consumers` as (x, y, w, l)."""
    N = set(roads)
    thc = th_cells(th)
    assert not (N & thc), "road on the Townhall"
    deg = {c: sum(n in N for n in nbrs(c)) for c in N}
    E = sum(deg.values()) // 2
    comps = components(N)
    roots = {c: th_side_of(c, th) for c in N if th_side_of(c, th)}
    sides_used = collections.Counter(roots.values())
    stubs_all = stub_positions(th) & N

    # loops: cyclomatic number of the road graph = unit squares + larger holes
    cyc = E - len(N) + len(comps)
    squares = sum(1 for (x, y) in N if {(x + 1, y), (x, y + 1), (x + 1, y + 1)} <= N)
    # loops through the TH: a component touching the TH in >1 separate root groups
    th_loops = 0
    for comp in comps:
        r = {c for c in comp if c in roots}
        if r:
            th_loops += len(components(r)) - 1
    detached = sum(1 for comp in comps if not any(c in roots for c in comp))

    # straight segments, bends, junctions, dead-end stubs
    segs = runs(N)
    seg_hist = collections.Counter(min(len(r), 30) for _, r in segs)
    bends = sum(1 for c in N if deg[c] == 2 and not (
        ((c[0] + 1, c[1]) in N and (c[0] - 1, c[1]) in N) or
        ((c[0], c[1] + 1) in N and (c[0], c[1] - 1) in N)))
    junctions = collections.Counter(deg[c] for c in N if deg[c] >= 3)
    dead_short = 0                    # leaf paths of 1-2 cells hanging off a junction
    for c in N:
        if deg[c] != 1:
            continue
        prev, cur, length = None, c, 1
        while length <= 2:
            nxt = next(n for n in nbrs(cur) if n in N and n != prev)
            if deg[nxt] >= 3:
                dead_short += 1
                break
            if deg[nxt] == 1:
                break                 # an isolated path, not a stub
            prev, cur, length = cur, nxt, length + 1
    th_stubs = sum(1 for comp in comps if len(comp) <= 2 and any(c in roots for c in comp))

    # TH-rooted turn depth (any initial direction from a root cell)
    th_seeds = [(c, a) for c in roots for a in (H, V)]
    lv_th = turn_levels(N, th_seeds)
    lv_th_ax = turn_levels(N, th_seeds, per_axis=True)
    depth_hist = collections.Counter(min(v, 5) for v in lv_th.values())
    unreached = len(N) - len(lv_th)

    # trunk: longest run travelled straight within one turn of the TH; its offset
    trunk_run, trunk_off, trunk_rel = None, None, None
    for axis, r in sorted(segs, key=lambda ar: -len(ar[1])):
        if max(lv_th_ax.get((c, axis), 99) for c in r) <= 2:   # reached straight
            trunk_run = r
            break
    if trunk_run:
        x, y, w, l = th
        if trunk_run[0][1] == trunk_run[-1][1]:     # horizontal
            ty = trunk_run[0][1]
            lo, hi = y, y + l - 1
            pos = ty
        else:
            ty = trunk_run[0][0]
            lo, hi = x, x + w - 1
            pos = ty
        if pos < lo:
            trunk_off, trunk_rel = lo - 1 - pos, "parallel"
        elif pos > hi:
            trunk_off, trunk_rel = pos - hi - 1, "parallel"
        else:
            trunk_off, trunk_rel = 0, "end-on"

    # load: distinct consumers bordering each road cell; both-sides share
    owner: dict[Cell, int] = {}
    for i, (bx, by, bw, bl) in enumerate(consumers):
        for cx in range(bx, bx + bw):
            for cy in range(by, by + bl):
                owner[(cx, cy)] = i
    load = collections.Counter()
    both = 0
    for c in N:
        ids = {owner[n] for n in nbrs(c) if n in owner}
        load[min(len(ids), 4)] += 1
        (x_, y_) = c
        if ((x_ - 1, y_) in owner and (x_ + 1, y_) in owner) or \
           ((x_, y_ - 1) in owner and (x_, y_ + 1) in owner):
            both += 1
    mean_load = sum(len({owner[n] for n in nbrs(c) if n in owner}) for c in N) / max(1, len(N))

    # grammar coverage and extensions
    # Candidate trunks: the grammar's flush run on each side, and every "spoke" --
    # the straight run leaving a TH-adjacent cell perpendicular to that side.
    trunks: dict[tuple, tuple[set[Cell], int]] = {}
    for s in SIDES:
        t = trunk_cells(N, th, s, 0)
        if t:
            trunks[("flush", s)] = (t, trunk_line(s, 0, th)[0])
    for r, s in roots.items():
        dx, dy = _toward_th(s)
        run, c = [], r
        while c in N:
            run.append(c)
            c = (c[0] - dx, c[1] - dy)
        trunks[("spoke", r)] = (set(run), V if s in ("top", "bottom") else H)
    cov2, cov3 = {}, {}
    for key, (cells_, axis) in trunks.items():
        lv = turn_levels(N, [(c, axis) for c in cells_])
        cov2[key] = {c for c, v in lv.items() if v <= 2}
        cov3[key] = {c for c, v in lv.items() if v <= 3}
    G = {(s, d): grammar_cover(N, th, s, d) for s in SIDES for d in range(MAX_OFFSET + 1)}
    stub_lv = turn_levels(N, [(c, a) for c in stubs_all for a in (H, V)])
    stub_cov = {c for c, v in stub_lv.items() if v <= 2}

    def best(sets):
        return max(sets, key=len, default=set())

    flush = [k for k in trunks if k[0] == "flush"]
    pairs = list(itertools.combinations(trunks, 2))
    th2 = {c for c, v in lv_th.items() if v <= 2}
    th3 = {c for c, v in lv_th.items() if v <= 3}
    ext = {
        "base": best([cov2[k] | stubs_all for k in flush]),
        "spoke": best([cov2[k] | stubs_all for k in trunks]),
        "offset": best([G[k] | stubs_all for k in G]),
        "two_trunks": best([cov2[a] | cov2[b] | stubs_all for a, b in pairs]),
        "depth3": best([cov3[k] | stubs_all for k in trunks]),
        "two_trunks+depth3": best([cov3[a] | cov3[b] | stubs_all for a, b in pairs]),
        "th_depth2": th2 | stubs_all,
        "th_depth3": th3 | stubs_all,
        "stub_roots": best([cov2[k] | stub_cov for k in flush]),
    }
    oog = {k: len(N) - len(v) for k, v in ext.items()}
    best_side = max(SIDES, key=lambda s: len(cov2.get(("flush", s), set())))
    best_off = max(G, key=lambda k: len(G[k]))
    best_trunk = max(trunks, key=lambda k: len(cov2[k]), default=None)

    violations = []
    if oog["base"]:
        if oog["spoke"] < oog["base"]:
            violations.append("spoke trunk")
        if oog["offset"] < oog["base"] and best_off[1] > 0:
            violations.append(f"offset trunk(d={best_off[1]})")
        if oog["two_trunks"] < oog["spoke"]:
            violations.append("2nd trunk")
        if oog["depth3"] < oog["spoke"]:
            violations.append("depth3/bent")
        if oog["th_depth3"]:
            violations.append(f"depth4+({oog['th_depth3']})")
        if oog["stub_roots"] < oog["base"]:
            violations.append("branch from stub")
    if cyc - squares > 0:
        violations.append(f"loops({cyc - squares})")
    if th_loops:
        violations.append(f"TH-loops({th_loops})")
    if squares:
        violations.append(f"fat({squares} sq)")
    if detached:
        violations.append(f"detached({detached})")

    # spatial coverage (the binding constraint per the 2026-07-30 OOD study):
    # mean grid distance from a free region cell to the nearest road
    mean_dist = None
    if region:
        dist = {c: 0 for c in N}
        frontier = list(N)
        while frontier:
            nxt = []
            for c in frontier:
                for n in nbrs(c):
                    if n in region and n not in dist and n not in thc:
                        dist[n] = dist[c] + 1
                        nxt.append(n)
            frontier = nxt
        free = [v for c, v in dist.items() if c not in N]
        mean_dist = round(sum(free) / max(1, len(free)), 2)

    return {
        "mean_dist": mean_dist,
        "roads": len(N), "level2": sum(1 for v in roads.values() if v >= 2),
        "components": len(comps), "detached": detached,
        "roots": len(roots), "sides_used": dict(sides_used),
        "n_sides": len(sides_used), "stub_cells": len(stubs_all),
        "n_sides_nonstub": len({s for c, s in roots.items()
                                if not (c in stubs_all and deg[c] == 0)}),
        "cyclomatic": cyc, "unit_squares": squares, "holes": cyc - squares,
        "th_loops": th_loops,
        "depth_max": max(lv_th.values()) if lv_th else 0,
        "depth_hist": dict(sorted(depth_hist.items())), "unreached": unreached,
        "segments": len(segs), "seg_len_hist": dict(sorted(seg_hist.items())),
        "bends": bends, "junctions": dict(sorted(junctions.items())),
        "dead_end_stubs_1_2": dead_short, "th_stub_components": th_stubs,
        "trunk_len": len(trunk_run) if trunk_run else 0,
        "trunk_offset": trunk_off, "trunk_rel": trunk_rel,
        "load_hist": dict(sorted(load.items())), "mean_load": round(mean_load, 3),
        "both_sides_share": round(both / max(1, len(N)), 3),
        "best_side": best_side, "best_offset": list(best_off),
        "best_trunk": str(best_trunk),
        "oog": oog, "violations": violations,
    }


# ---------------------------------------------------------------- loading
CITY_FILES = {
    "darkzig": ("darkzig.json",),
    "FR16": ("CityMap-Born-FR16-2026-07-07.json",),
    "FR17": ("CityMap-Born-FR17-2026-07-07.json",),
    "FR24": ("CityMap-Born-FR24-2026-07-07.json",),
    "user": ("city-user-data.json", "city-user-data-foe-helper.json"),
    "agrou": ("agrou-city.json",),
}
BENCH_GLOB = "/home/born/Github/foe-city-planner/output/bench/*/*.json"


def city_of(path: str) -> str | None:
    name = pathlib.Path(path).name.lower()
    for c in CITY_FILES:
        if name.startswith(c.lower()):
            return c
    return None


def from_layout(layout):
    t = layout.townhall.footprint
    th = (t.x, t.y, t.width, t.length)
    cons = [(b.footprint.x, b.footprint.y, b.footprint.width, b.footprint.length)
            for b in layout.road_needing()]
    return dict(layout.roads), th, cons


def from_record(d: dict, layout):
    roads = {}
    for r in d["roads"]:
        roads[(r[0], r[1])] = r[2] if len(r) > 2 else 1
    pos = d["buildings"]
    th = tuple(pos[str(layout.townhall.entity_id)])
    cons, missing = [], 0
    for b in layout.road_needing():
        p = pos.get(str(b.entity_id))
        if p is None:
            missing += 1
            continue
        cons.append(tuple(p))
    return roads, th, cons, missing


def collect(root: pathlib.Path):
    from foeopt.loader import load_layout
    layouts = {}
    for c, files in CITY_FILES.items():
        paths = [str(root / f) for f in files]
        if all(pathlib.Path(p).exists() for p in paths):
            layouts[c] = load_layout(*paths)
    nets = []
    for c, lay in layouts.items():
        nets.append((f"{c} upload", c, *from_layout(lay), 0, set(lay.region.cells)))
    rec = sorted(glob.glob(str(root / "docs/records/*.json"))) + sorted(glob.glob(BENCH_GLOB))
    for p in rec:
        c = city_of(p)
        if c not in layouts:
            continue
        d = json.loads(pathlib.Path(p).read_text())
        roads, th, cons, missing = from_record(d, layouts[c])
        tag = "bench:" if "/output/bench/" in p else ""
        nets.append((tag + pathlib.Path(p).stem, c, roads, th, cons, missing,
                     set(layouts[c].region.cells)))
    return nets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    nets = collect(pathlib.Path(args.root))
    rows = []
    print("columns: rd roads, L2 level-2 cells, sd TH sides with a non-stub root, rt roots,"
          " cyc cyclomatic, hol holes (loops beyond 2x2 squares), dep TH-rooted turn depth,"
          " seg straight runs, bnd bends, j3/4 junctions, st 1-2 dead-end stubs, trk/off"
          " trunk length/offset (end = end-on spoke), load consumers per road cell,"
          " 2sd both-sides share; then road cells OUT of: G grammar, sp spoke-or-flush"
          " trunk, of offset trunk, 2t two trunks, d3 depth-3, 2t3 two trunks depth-3,"
          " T2/T3 TH-rooted depth<=2/3; dist = mean distance free cell -> road")
    hdr = (f"{'network':40s} {'rd':>4s} {'L2':>2s} {'sd':>2s} {'rt':>3s} {'cyc':>3s} {'hol':>3s}"
           f" {'dep':>3s} {'seg':>3s} {'bnd':>3s} {'j3/4':>5s} {'st':>2s} {'trk':>3s} {'off':>3s}"
           f" {'load':>4s} {'2sd':>4s} |{'G':>4s} {'sp':>4s} {'of':>4s} {'2t':>4s} {'d3':>4s}"
           f" {'2t3':>4s} {'T2':>4s} {'T3':>4s} {'dist':>4s}  violations")
    print(hdr)
    for name, city, roads, th, cons, missing, region in nets:
        m = analyze(roads, th, cons, region)
        m.update(name=name, city=city, consumers_missing=missing)
        rows.append(m)
        o = m["oog"]
        j = m["junctions"]
        off = "end" if m["trunk_rel"] == "end-on" else m["trunk_offset"]
        print(f"{name[:40]:40s} {m['roads']:4d} {m['level2']:2d} {m['n_sides_nonstub']:2d}"
              f" {m['roots']:3d} {m['cyclomatic']:3d} {m['holes']:3d} {m['depth_max']:3d}"
              f" {m['segments']:3d} {m['bends']:3d} {j.get(3, 0):2d}/{j.get(4, 0):<2d}"
              f" {m['dead_end_stubs_1_2']:2d} {m['trunk_len']:3d} {str(off):>3s}"
              f" {m['mean_load']:4.2f} {m['both_sides_share']:4.2f} |{o['base']:4d}"
              f" {o['spoke']:4d} {o['offset']:4d} {o['two_trunks']:4d} {o['depth3']:4d}"
              f" {o['two_trunks+depth3']:4d} {o['th_depth2']:4d} {o['th_depth3']:4d} {m['mean_dist']:4.1f}"
              f"  {', '.join(m['violations'])}"
              + (f"  [missing {missing} consumers]" if missing else ""))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
