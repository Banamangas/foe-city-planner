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
                        if budget < 2:
                            continue
                        trunk_used = trunk[:min(len(trunk), max(2, budget // 2))]
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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("--dump-patterns", type=int, default=None, metavar="K")
    p.add_argument("--patterns", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)
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
    p.error("no mode selected (T2/T3 add --selftest and the k-walk)")


if __name__ == "__main__":
    sys.exit(main())
