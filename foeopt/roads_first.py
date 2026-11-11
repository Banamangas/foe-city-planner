from __future__ import annotations

import itertools
import json
import multiprocessing
import random
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace

from foeopt.model import Building, Footprint, Layout, Region, contact_cells
from foeopt.bounds import pick_k_start
from foeopt.corpus import CorpusWriter
from foeopt.exact_packing import apply_placements, exact_pack

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


COMB_MODES = ("both", "alternate")


def generate_patterns(region: set[Cell], tw: int, tl: int, k: int,
                      rng: random.Random, max_patterns: int,
                      th_mode: str = "coarse",
                      modes: tuple[str, ...] | None = None) -> list[Pattern]:
    """Comb family: a trunk along one town-hall side plus perpendicular teeth.

    `modes` selects which branch policies to emit. "both" grows a tooth from
    each seed in both perpendicular directions; "alternate" grows one tooth per
    seed, alternating sides. Left unset the generator emits both, which is the
    historical behaviour and is byte-identical to before this parameter existed.

    Worth selecting because pooled FR16+FR17 probe logs show `alternate`
    holding 9 of 9 SATs while `both` is 0 of 528 -- a lead found for free in
    existing logs and, until this parameter, impossible to act on.
    """
    modes = tuple(modes) if modes else COMB_MODES
    bad = set(modes) - set(COMB_MODES)
    if bad:
        raise ValueError(f"unknown comb mode(s): {sorted(bad)}")
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
                for mode in modes:
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


LANE_PITCHES = (5, 6, 7, 8, 9, 10, 11)


def generate_lane_patterns(region: set[Cell], tw: int, tl: int, k: int,
                           rng: random.Random, max_patterns: int,
                           th_mode: str = "coarse",
                           max_lane_len: int | None = None,
                           pitches: tuple[int, ...] | None = None) -> list[Pattern]:
    """Parallel double-loaded-lane family: unlike generate_patterns's comb
    (single trunk consuming budget//2 regardless of need, short teeth), this
    grows a *minimal* trunk -- only as long as needed to connect the TH to
    the lane seeds on both sides of it along the trunk line -- then grows
    full straight lanes from each seed, mirroring the user's hand-built
    city's near-zero trunk overhead (memory/foe-layout-heuristics: 5
    non-double-row cells out of 142).

    `max_lane_len` (default None = unbounded, today's behavior) caps how far
    a lane grows from its seed before stopping -- a hybrid dial between this
    family's uncapped lanes (structurally efficient but harder for CP-SAT to
    decide, per the idea #5 mechanism finding) and the comb family's short
    teeth (easier to decide). Capping only bounds individual lane length; the
    trunk and seed spacing are unaffected.

    `pitches` (default None = today's exact `LANE_PITCHES` = 5..11) sets which
    trunk-seed spacings to enumerate. The default range is truncated at exactly
    the value that performs best: on darkzig the measured SAT rate rises
    monotonically with pitch (0/0/0/0/1.0/3.2/6.2% for 5->11, tasks/todo.md
    Track F step 1), and FR16's comb analogue (`spacing`) shows the same shape
    at its own cap of 7. Larger pitches mean fewer, longer lanes; they generate
    a large population that has never been probed (93,284 extra patterns per k
    at pitch 12-24 on darkzig, vs 67,308 for the whole default range)."""
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
            for pitch in (LANE_PITCHES if pitches is None else pitches):
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
                            if max_lane_len is not None and dist > max_lane_len:
                                continue
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
                        "stubs": use_stubs, "trunk_len": len(trunk_used),
                        "max_lane_len": max_lane_len, "k": k}))
    rng.shuffle(out)
    return out[:max_patterns]


NONUNIFORM_GAPS = (10, 18)
NONUNIFORM_SKEW = 1.5
QUALITY_INDEX_BAND = (3, 4)


def quality_index(region: set[Cell], th: Footprint, roads: frozenset[Cell]) -> int:
    """`losses - 2c` for this skeleton: adjacencies spent on the region boundary
    or the Townhall, minus twice the number of connected components.

    Equivalently `(2 - mean_free_adjacency) * k`, an integer and k-normalised, so
    it compares across cities and budgets. Measured on every record this project
    holds, the productive band is **3-4 on both darkzig (k=105/106) and FR16
    (k=84)**, while both >=98-road layouts sit at 2. Costs ~0.1 ms -- 15x cheaper
    than `opts_total`, which is what makes a whole-population filter fit inside a
    user-facing time box (15 s vs 239 s for 160k patterns on darkzig).

    Filtering to the band is the single highest-leverage lever measured: it took
    the darkzig SAT rate from 46.7% (bottom-40%-by-mfa cut) to ~100% at equal
    quality, because the below-band tail is skeletons too tight to pack, which
    return only UNKNOWN. See tasks/lessons.md 2026-07-31.
    """
    n = len(roads)
    if n == 0:
        return 0
    free = region - roads - th.cells()
    total = 0
    for (x, y) in roads:
        for dx, dy in _ORTHO:
            if (x + dx, y + dy) in free:
                total += 1
    return round(2 * n - total)


def generate_nonuniform_patterns(region: set[Cell], tw: int, tl: int, k: int,
                                 rng: random.Random, max_patterns: int,
                                 th_mode: str = "coarse",
                                 gaps: tuple[int, int] = NONUNIFORM_GAPS,
                                 skew: float = NONUNIFORM_SKEW,
                                 quality_index_band: tuple[int, int] | None = None
                                 ) -> list[Pattern]:
    """Trunk-and-branch skeletons with IRREGULAR seed gaps and UNEQUAL branch
    lengths -- the comb/lane topology with its two arbitrary uniformity
    constraints lifted.

    `generate_lane_patterns` fixes one global pitch and grows every front in
    lockstep, so branches come out equal. Nothing justifies either: the expert
    142-road city is not uniform, and measurement showed uniform branches bottom
    out at 101 roads on darkzig in all three gap ranges tried while unequal ones
    reach 97-99 (and 94 after seed-polish). This family holds the records on both
    cities: darkzig 94, FR16 76.

    Unlike comb/lane this space is ~10^19 and cannot be enumerated, so patterns
    are SAMPLED: `max_patterns` distinct draws, deduplicated. `quality_index_band`
    filters during generation (see `quality_index`) rather than after, so the
    cost is a cheap predicate per draw instead of scoring a materialised
    population.
    """
    out: list[Pattern] = []
    seen: set[frozenset[Cell]] = set()
    anchors = th_anchor_candidates(region, tw, tl, mode=th_mode)
    if not anchors:
        return []
    gap_lo, gap_hi = gaps
    attempts = 0
    limit = max_patterns * 30
    while len(out) < max_patterns and attempts < limit:
        attempts += 1
        th = rng.choice(anchors)
        th_cells = th.cells()
        side = rng.choice(("top", "bottom", "left", "right"))
        trunk_raw = [c for c in _trunk(region, th, side) if c not in th_cells]
        if not trunk_raw:
            continue
        anchor = _th_anchor_cell(th, side)
        if anchor not in trunk_raw:
            continue
        a = trunk_raw.index(anchor)
        horiz = trunk_raw[0][1] == trunk_raw[-1][1]

        seed_idxs = []
        pos = a + rng.randint(gap_lo, gap_hi)
        while pos < len(trunk_raw):
            seed_idxs.append(pos)
            pos += rng.randint(gap_lo, gap_hi)
        pos = a - rng.randint(gap_lo, gap_hi)
        while pos >= 0:
            seed_idxs.append(pos)
            pos -= rng.randint(gap_lo, gap_hi)
        if not seed_idxs:
            continue
        seed_idxs.sort()

        use_stubs = rng.random() < 0.5
        roads: set[Cell] = set()
        stubs = _stub_cells(region, th, roads) if use_stubs else []
        budget = k - len(stubs)
        lo, hi = min(seed_idxs + [a]), max(seed_idxs + [a])
        trunk_used = trunk_raw[lo:hi + 1]
        if len(trunk_used) >= budget:
            continue
        roads |= set(trunk_used)
        remaining = budget - len(trunk_used)

        cand_dirs = [(0, -1), (0, 1)] if horiz else [(-1, 0), (1, 0)]
        both_prob = rng.choice((0.6, 0.85, 1.0))
        fronts = []
        for i in seed_idxs:
            sc_ = trunk_raw[i]
            if rng.random() < both_prob:
                fronts += [(sc_, d) for d in cand_dirs]
            else:
                fronts.append((sc_, rng.choice(cand_dirs)))
        if not fronts:
            continue

        w = [rng.expovariate(1.0) ** skew + 1e-9 for _ in fronts]
        tot = sum(w)
        target = [max(1, int(remaining * x / tot)) for x in w]
        state = [(sc_, d, 1) for (sc_, d) in fronts]
        grown = [0] * len(fronts)
        for j, (sc_, d, _dist) in enumerate(state):
            dist = 1
            while grown[j] < target[j] and remaining > 0:
                c = (sc_[0] + d[0] * dist, sc_[1] + d[1] * dist)
                if c in region and c not in roads and c not in th_cells:
                    roads.add(c); grown[j] += 1; remaining -= 1; dist += 1
                else:
                    break
            state[j] = (sc_, d, dist)
        progress = True
        while remaining > 0 and progress:
            progress = False
            for j, (sc_, d, dist) in enumerate(state):
                if remaining == 0:
                    break
                c = (sc_[0] + d[0] * dist, sc_[1] + d[1] * dist)
                if c in region and c not in roads and c not in th_cells:
                    roads.add(c); state[j] = (sc_, d, dist + 1); remaining -= 1
                    progress = True
        if remaining != 0:
            continue
        roads |= set(stubs)
        key = frozenset(roads)
        if len(key) != k or key in seen:
            continue
        if quality_index_band is not None:
            qi = quality_index(region, th, key)
            if not (quality_index_band[0] <= qi <= quality_index_band[1]):
                continue
        seen.add(key)
        out.append(Pattern(th=th, roads=key, params={
            "th": (th.x, th.y), "side": side, "gaps": f"{gap_lo}-{gap_hi}",
            "skew": skew, "stubs": use_stubs, "n_fronts": len(fronts),
            "trunk_len": len(trunk_used), "k": k}))
    return out


def _pattern_generator(family: str):
    # Resolved dynamically (not a frozen dict built at import time) so tests
    # that monkeypatch module-level generate_patterns/generate_lane_patterns
    # still take effect here.
    if family == "lane":
        return generate_lane_patterns
    if family == "nonuniform":
        return generate_nonuniform_patterns
    return generate_patterns


def prefilter(pattern: Pattern, region: set[Cell],
              consumers: list[Building],
              fillers: list[Building] | None = None) -> str | None:
    """Sound rejections only -- never rejects a pattern that could have worked.

    `fillers` (the non-road-needing buildings) are optional for backwards
    compatibility, but SHOULD be passed: they occupy region cells too, and
    without them the area check can pass a pattern that has room for the
    consumers and no room for everything else. That failure surfaces much later
    as SAT_FILLER_FAIL, after a full CP-SAT probe has been spent on it."""
    th_cells = pattern.th.cells()
    area_needed = sum(b.footprint.width * b.footprint.length for b in consumers)
    if fillers:
        area_needed += sum(b.footprint.width * b.footprint.length for b in fillers)
    if area_needed + len(pattern.roads) > len(region) - len(th_cells):
        return "area"
    free = region - pattern.roads - th_cells
    # Each road cell serves at most 3 consumers (bound_adjacency's argument:
    # 4 orthogonal neighbors, at least 1 taken by road/TH connectivity) --
    # but a specific cell may have fewer than 3 *actually* free neighbors
    # once this pattern's own roads/TH occupy some of them, so cap by the
    # real count instead of granting a flat 3 to any cell with >=1 free
    # neighbor. Strictly tighter than the old flat-3 check, still sound.
    capacity = sum(min(3, sum(1 for dx, dy in _ORTHO if (c[0] + dx, c[1] + dy) in free))
                   for c in pattern.roads)
    if capacity < len(consumers):
        return "adjacency-capacity"
    return None


from foeopt.chains import compose, expand, expand_buildings
from foeopt.legality import MILITARY_POLICIES
from foeopt.profiling import Profile
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
            if any(c in roads for c in contact_cells(b, x, y)):
                out.append((x, y))
    return out


def _lane_anchor_candidates(b: Building, region: set[Cell], blocked: set[Cell],
                            lane_cells: set[Cell]) -> list[tuple[int, int]]:
    """Anchors for a two-lane building: its contact edge must reach a candidate
    two-lane tile cell (the tile, not the skeleton, connects it to the TH)."""
    out = []
    w, l = b.footprint.width, b.footprint.length
    x0, y0, x1, y1 = _bbox(region)
    for y in range(y0, y1 - l + 2):
        for x in range(x0, x1 - w + 2):
            cells = Footprint(x, y, w, l).cells()
            if not (cells <= region) or (cells & blocked):
                continue
            if contact_cells(b, x, y) & lane_cells:
                out.append((x, y))
    return out


def _add_symmetry_breaking(m, cand, xs, ys) -> None:
    """Buildings sharing a footprint size are interchangeable in this model
    (_anchor_candidates only looks at width/length), so the solver otherwise
    explores every permutation of them as distinct symmetric solutions. Chain
    a lexicographic (x, y) <= ordering across each size-group to collapse
    that permutation symmetry to one representative assignment."""
    groups: dict[tuple, list[int]] = {}
    for i, (b, _) in enumerate(cand):
        groups.setdefault(_class_key(b), []).append(i)
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
                if c in contact_cells(b, x, y):
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
          stub_priority: bool = False,
          solver_overrides: dict[str, object] | None = None,
          diag: dict | None = None,
          model: str = "item") -> tuple[str, dict | None]:
    """`diag`, if given a dict, is filled with why this probe ended the way it
    did -- `reason` is one of:
      no_anchor  some consumer has zero road-adjacent anchors; returns UNSAT
                 without ever building a model (pure python cost).
      presolve   CP-SAT closed the problem with *zero* search branches.
      search     CP-SAT actually searched (branches > 0).
    plus the python-vs-solver time split and branch/conflict counts. Without
    this, a fast UNSAT and a slow one are indistinguishable in the logs even
    though they mean completely different things about the pattern."""
    from ortools.sat.python import cp_model

    if model == "position":
        return _probe_position(pattern, region, consumers, probe_limit=probe_limit,
                               probe_workers=probe_workers,
                               solver_overrides=solver_overrides, diag=diag)
    t_start = time.monotonic()
    th_cells = set(pattern.th.cells())
    blocked = set(pattern.roads) | th_cells
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            if diag is not None:
                diag.update(reason="no_anchor", no_anchor_entity=b.entity_id,
                            cand_s=round(time.monotonic() - t_start, 3),
                            solve_s=0.0, branches=0, conflicts=0)
            return ("UNSAT", None)
        cand.append((b, opts))
    if diag is not None:
        diag.update(cand_s=round(time.monotonic() - t_start, 3),
                    opts_total=sum(len(o) for _, o in cand),
                    opts_min=min(len(o) for _, o in cand))

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
    if solver_overrides:
        for key, value in solver_overrides.items():
            setattr(solver.parameters, key, value)
    t_solve = time.monotonic()
    st = solver.Solve(m)
    if diag is not None:
        branches = solver.NumBranches()
        diag.update(reason="presolve" if branches == 0 else "search",
                    solve_s=round(time.monotonic() - t_solve, 3),
                    branches=branches, conflicts=solver.NumConflicts(),
                    solver_status=solver.status_name(st))
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        pos = {}
        for i, (b, _) in enumerate(cand):
            w, l = b.footprint.width, b.footprint.length
            pos[b.entity_id] = (solver.Value(xs[i]), solver.Value(ys[i]), w, l)
        return ("SAT", pos)
    if st == cp_model.INFEASIBLE:
        return ("UNSAT", None)
    return ("UNKNOWN", None)


PROBE_MODELS = ("item", "position")


def _class_key(b: Building) -> tuple:
    """Buildings are interchangeable in the placement model only if EVERY
    placement-relevant property matches: size, road-contact edge (composite
    chains) and road level. Size alone is not enough (review 2026-11-11)."""
    return (b.footprint.width, b.footprint.length, b.contact, b.road_level)


def _size_classes(consumers: list[Building]) -> dict[tuple, list[Building]]:
    out: dict[tuple, list[Building]] = {}
    for b in consumers:
        out.setdefault(_class_key(b), []).append(b)
    return out


# Two-lane roads (user-confirmed 2026-11-11): 2x2 tiles, and a road_level-2
# building needs an all-two-lane path to the TH. Modelled here as the layout the
# player uses: ONE tile touching the TH, with the building touching that tile.
# Longer two-lane paths are not modelled (no such skeleton -> UNSAT).
LANE_KEY = (2, 2, "two-lane tile", 2)   # lits key; [0], [1] are the tile size
LANE_PREFIX = "lane2:"                  # positions key prefix for chosen tiles


def _lane_tiles(pattern: Pattern, region: set[Cell]) -> list[tuple[int, int]]:
    """Top-left anchors of 2x2 tiles inside the region, off the TH, with at
    least one cell on the TH border. Tiles may overlap skeleton road cells
    (those just become two-lane)."""
    th = pattern.th
    th_cells, th_border = th.cells(), th.border_cells()
    out = []
    for tx in range(th.x - 2, th.x + th.width + 1):
        for ty in range(th.y - 2, th.y + th.length + 1):
            cells = Footprint(tx, ty, 2, 2).cells()
            if cells <= region and not (cells & th_cells) and (cells & th_border):
                out.append((tx, ty))
    return out


def lane_tiles_of(positions: dict) -> list[tuple[int, int]]:
    return [tuple(v[:2]) for k, v in positions.items()
            if isinstance(k, str) and k.startswith(LANE_PREFIX)]


def _position_model(pattern: Pattern, region: set[Cell], consumers: list[Building],
                    needed: dict | None = None, m=None):
    """Position-indexed placement: one boolean per (size class, anchor), a count
    per class, and at most one coverer per cell. Identical buildings have no
    identity here, so the N! permutation symmetry of the item model is gone.

    Measured 2026-11-11 on 11 FR17 skeletons (k=121, 52 identical 3x3s among 77
    consumers): the item model returned UNKNOWN on 11/11 at 30 s x 12 threads;
    this model decided all 11 in 0.1-0.3 s (6 UNSAT, 5 SAT). Same constraints --
    road-adjacent anchor per building, no overlap -- so UNSAT is a proof.

    With `needed` (skeleton-cell booleans), each anchor literal forces at least
    one needed cell on its border, as in minimize_needed. Returns
    (model, {size: [(xy, lit), ...]}, classes) or None if some class has fewer
    anchors than members (trivially UNSAT)."""
    blocked = set(pattern.roads) | set(pattern.th.cells())
    classes = _size_classes(consumers)
    cover: dict[Cell, list] = {}
    lits: dict[tuple, list] = {}
    tiles: list = []                       # [((tx, ty), literal, tile cells)]
    if any(key[3] >= 2 for key in classes):
        for (tx, ty) in _lane_tiles(pattern, region):
            cells = Footprint(tx, ty, 2, 2).cells()
            u = m.NewBoolVar(f"lane_{tx}_{ty}")
            tiles.append(((tx, ty), u, cells))
            for c in cells - blocked:      # tile cells off the skeleton occupy space
                cover.setdefault(c, []).append(u)
        if not tiles:
            return None
        lits[LANE_KEY] = [(xy, u) for xy, u, _ in tiles]
    tile_users: dict = {}
    for key, members in classes.items():
        w, l = key[0], key[1]
        lane = key[3] >= 2
        if lane:
            lane_cells = set().union(*(cells for _, _, cells in tiles))
            opts = _lane_anchor_candidates(members[0], region, blocked, lane_cells)
        else:
            opts = _anchor_candidates(members[0], region, blocked, pattern.roads)
        row = []
        for (x, y) in opts:
            touch = None
            if lane:
                ctc = contact_cells(members[0], x, y)
                users = [(xy, u) for xy, u, cells in tiles if cells & ctc
                         and not (cells & Footprint(x, y, w, l).cells())]
                if not users:
                    continue
                v = m.NewBoolVar(f"z{w}x{l}L_{x}_{y}")
                m.AddBoolOr([u for _, u in users]).OnlyEnforceIf(v)
                for xy, _ in users:
                    tile_users.setdefault(xy, []).append(v)
                row.append(((x, y), v))
                for c in Footprint(x, y, w, l).cells():
                    cover.setdefault(c, []).append(v)
                continue
            if needed is not None:
                touch = [needed[c] for c in contact_cells(members[0], x, y)
                         if c in needed]
                if not touch:
                    continue
            v = m.NewBoolVar(f"z{w}x{l}_{x}_{y}")
            if touch is not None:
                m.AddBoolOr(touch).OnlyEnforceIf(v)
            row.append(((x, y), v))
            for c in Footprint(x, y, w, l).cells():
                cover.setdefault(c, []).append(v)
        if len(row) < len(members):
            return None
        m.Add(sum(v for _, v in row) == len(members))
        lits[key] = row
    for xy, u, _ in tiles:                 # a tile exists only to serve a building
        m.AddBoolOr(tile_users.get(xy, [])).OnlyEnforceIf(u)
    for vs in cover.values():
        if len(vs) > 1:
            m.AddAtMostOne(vs)
    return m, lits, classes


def _position_solution(solver, lits, classes) -> dict:
    """Map chosen anchors back to entity ids. Members of a size class are
    interchangeable, so the assignment within a class is arbitrary but
    deterministic (sorted anchors, input order of buildings)."""
    pos = {}
    for size, members in classes.items():
        chosen = sorted(xy for xy, v in lits[size] if solver.Value(v))
        for b, (x, y) in zip(members, chosen):
            pos[b.entity_id] = (x, y, size[0], size[1])
    for i, (tx, ty) in enumerate(sorted(xy for xy, v in lits.get(LANE_KEY, ())
                                        if solver.Value(v))):
        pos[f"{LANE_PREFIX}{i}"] = (tx, ty, 2, 2)
    return pos


def _probe_position(pattern, region, consumers, *, probe_limit, probe_workers=1,
                    solver_overrides=None, diag=None):
    from ortools.sat.python import cp_model
    t0 = time.monotonic()
    built = _position_model(pattern, region, consumers, m=cp_model.CpModel())
    if built is None:
        if diag is not None:
            diag.update(reason="no_anchor", cand_s=round(time.monotonic() - t0, 3),
                        solve_s=0.0, branches=0, conflicts=0)
        return ("UNSAT", None)
    m, lits, classes = built
    if diag is not None:
        diag.update(cand_s=round(time.monotonic() - t0, 3),
                    opts_total=sum(len(r) for r in lits.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = probe_workers
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = probe_limit
    if solver_overrides:
        for key, value in solver_overrides.items():
            setattr(solver.parameters, key, value)
    t1 = time.monotonic()
    st = solver.Solve(m)
    if diag is not None:
        branches = solver.NumBranches()
        diag.update(reason="presolve" if branches == 0 else "search",
                    solve_s=round(time.monotonic() - t1, 3), branches=branches,
                    conflicts=solver.NumConflicts(), solver_status=solver.status_name(st))
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ("SAT", _position_solution(solver, lits, classes))
    if st == cp_model.INFEASIBLE:
        return ("UNSAT", None)
    return ("UNKNOWN", None)


def skeleton_parents(pattern: Pattern) -> dict[Cell, Cell | None]:
    """BFS parent of every skeleton cell on its path to the Townhall (roots --
    cells touching the TH footprint -- map to None). Cells not reachable from
    the TH are absent."""
    roads = pattern.roads
    th_cells = pattern.th.cells()
    roots = sorted(c for c in roads
                   if any((c[0] + dx, c[1] + dy) in th_cells for dx, dy in _ORTHO))
    parent: dict[Cell, Cell | None] = {r: None for r in roots}
    queue = list(roots)
    i = 0
    while i < len(queue):
        c = queue[i]
        i += 1
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in roads and nb not in parent:
                parent[nb] = c
                queue.append(nb)
    return parent


def needed_skeleton_cells(pattern: Pattern, positions: dict) -> int | None:
    """Exact objective of `minimize_needed` for a FIXED placement: the fewest
    skeleton cells, closed under the path to the TH, such that every consumer
    borders at least one of them. Brute force over choices is exponential, so
    this is only for tests on toy instances -- returns None above 12 consumers."""
    parent = skeleton_parents(pattern)
    touch = []
    for (x, y, w, l) in positions.values():
        t = [c for c in Footprint(x, y, w, l).border_cells() if c in parent]
        if not t:
            return None
        touch.append(t)
    if len(touch) > 12:
        return None
    best = None
    for choice in itertools.product(*touch):
        keep: set[Cell] = set()
        for c in choice:
            cur: Cell | None = c
            while cur is not None and cur not in keep:
                keep.add(cur)
                cur = parent[cur]
        if best is None or len(keep) < best:
            best = len(keep)
    return best


def minimize_needed(pattern: Pattern, region: set[Cell], consumers: list[Building],
                    positions: dict, *, limit: float, workers: int = 1,
                    seed: int = 0, diag: dict | None = None,
                    model: str = "item") -> dict | None:
    """Re-place the consumers on `pattern` minimizing the skeleton cells they
    actually NEED, hinted from a known-feasible `positions` (from `probe`).

    Why: `probe` is pure feasibility, so the routed road count is whatever the
    first satisfying placement happens to give -- up to 10 roads of spread on
    one skeleton (lessons 2026-07-22). The objective here is exact for the
    skeleton: `needed[c]` booleans closed under the BFS parent toward the TH,
    and each anchor option forces >= 1 needed cell on its border. `route()`
    searches all free cells, so it can only match or beat this count.

    Cold, the one-hot model did not find a first solution in 120 s on darkzig;
    hinted, it improves immediately (2026-11-11: every stored record beaten,
    darkzig 94 -> 91 and 97 -> 90, FR16 76 -> 71). Hence two phases: the cheap
    table-constraint `probe` finds feasibility, this pushes quality.

    The 2026-07-21 study that closed this lever measured proxy P2, which kept
    EVERY touched cell -- in a dense packing that is always k, so it could not
    correlate. That is a different (degenerate) quantity from this objective.

    Returns new positions, or None if the solver produced nothing (the caller
    keeps the hint placement, so this can never lose a feasible result)."""
    from ortools.sat.python import cp_model

    parent = skeleton_parents(pattern)
    blocked = set(pattern.roads) | set(pattern.th.cells())
    m = cp_model.CpModel()
    needed = {c: m.NewBoolVar(f"n{c[0]}_{c[1]}") for c in sorted(parent)}
    for c, p in parent.items():
        if p is not None:
            m.AddImplication(needed[c], needed[p])
    if model == "position":
        return _minimize_needed_position(m, needed, pattern, region, consumers,
                                         positions, limit, workers, seed, diag)
    x0b, y0b, x1b, y1b = _bbox(region)
    xiv, yiv, lits = [], [], []
    for i, b in enumerate(consumers):
        w, l = b.footprint.width, b.footprint.length
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        hint_xy = tuple(positions[b.entity_id][:2])
        ol = []
        for (x, y) in opts:
            touch = [needed[c] for c in contact_cells(b, x, y) if c in needed]
            if not touch:
                continue  # borders only TH-unreachable skeleton cells
            o = m.NewBoolVar(f"o{i}_{x}_{y}")
            m.AddBoolOr(touch).OnlyEnforceIf(o)
            m.AddHint(o, (x, y) == hint_xy)
            ol.append(((x, y), o))
        if not ol:
            return None
        m.AddExactlyOne([o for _, o in ol])
        xv = m.NewIntVar(x0b, x1b, f"x{i}")
        yv = m.NewIntVar(y0b, y1b, f"y{i}")
        m.Add(xv == sum(xy[0] * o for xy, o in ol))
        m.Add(yv == sum(xy[1] * o for xy, o in ol))
        xiv.append(m.NewFixedSizeIntervalVar(xv, w, f"xi{i}"))
        yiv.append(m.NewFixedSizeIntervalVar(yv, l, f"yi{i}"))
        lits.append((b, ol))
    m.AddNoOverlap2D(xiv, yiv)
    m.Minimize(sum(needed.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = limit
    t0 = time.monotonic()
    st = solver.Solve(m)
    ok = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if diag is not None:
        diag.update(objective_status=solver.status_name(st),
                    objective_s=round(time.monotonic() - t0, 3),
                    objective=solver.ObjectiveValue() if ok else None,
                    objective_bound=solver.BestObjectiveBound() if ok else None)
    if not ok:
        return None
    out = {}
    for b, ol in lits:
        for xy, o in ol:
            if solver.Value(o):
                out[b.entity_id] = (xy[0], xy[1], b.footprint.width, b.footprint.length)
                break
    return out


def _minimize_needed_position(m, needed, pattern, region, consumers, positions,
                              limit, workers, seed, diag):
    from ortools.sat.python import cp_model
    built = _position_model(pattern, region, consumers, needed=needed, m=m)
    if built is None:
        return None
    m, lits, classes = built
    used = {(x, y, w, l) for (x, y, w, l) in positions.values()}
    for key, row in lits.items():
        w, l = key[0], key[1]
        for (x, y), v in row:
            m.AddHint(v, (x, y, w, l) in used)
    # a two-lane tile's cells off the skeleton are extra road
    tile_cost = [len(Footprint(x, y, 2, 2).cells() - set(pattern.roads)) * u
                 for (x, y), u in lits.get(LANE_KEY, ())]
    m.Minimize(sum(needed.values()) + sum(tile_cost))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = limit
    t0 = time.monotonic()
    st = solver.Solve(m)
    ok = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if diag is not None:
        diag.update(objective_status=solver.status_name(st),
                    objective_s=round(time.monotonic() - t0, 3),
                    objective=solver.ObjectiveValue() if ok else None,
                    objective_bound=solver.BestObjectiveBound() if ok else None)
    return _position_solution(solver, lits, classes) if ok else None


def _place_fillers(grid: Grid, fillers: list[Building], cand: Layout) -> list[Building]:
    """Pack the non-road-needing buildings into whatever the consumers left.

    Returns the ones that did not fit (empty list == success). Appends the
    placed ones to `cand.buildings`.

    Two deliberate choices, both measured on 12 real FR16 failures
    (tasks/lessons.md 2026-07-31):

    **best-fit, not first-fit.** Placing each building in the TIGHTEST spot --
    the one with most blocked neighbours -- instead of the first spot found
    stops a large early building from cutting a usable region in half. It
    recovered **6 of 12** otherwise-failed layouts; first-fit recovered 0 and a
    cheaper reordering recovered 2. It costs 16x more than first-fit but that is
    2.7ms -> 42ms on FR16 and 27ms -> 434ms on darkzig: **at most 1.45% of a
    single 30s probe**, and it runs once per SAT.

    **No early exit.** The old code returned at the first building that did not
    fit, discarding every placement it could still have made -- measured, it
    placed 11 of 32 where continuing places 31. Continuing costs nothing and
    means the caller can report "placed 30 of 32" instead of a bare failure.
    """
    placed_any: list[Building] = []
    unplaced: list[Building] = []
    for b in sorted(fillers, key=lambda b: -(b.footprint.width * b.footprint.length)):
        bw, bl = b.footprint.width, b.footprint.length
        best, best_score = None, -1
        for y in range(grid.height - bl + 1):
            for x in range(grid.width - bw + 1):
                if not grid.fits(x, y, bw, bl):
                    continue
                # tightness = how enclosed this spot is; prefer the most enclosed
                score = 0
                for dx in range(bw):
                    for yy in (y - 1, y + bl):
                        if not grid.fits(x + dx, yy, 1, 1):
                            score += 1
                for dy in range(bl):
                    for xx in (x - 1, x + bw):
                        if not grid.fits(xx, y + dy, 1, 1):
                            score += 1
                if score > best_score:
                    best, best_score = (x, y), score
        if best is None:
            unplaced.append(b)
            continue
        grid.occupy(best[0], best[1], bw, bl)
        cand.buildings.append(replace(b, footprint=Footprint(best[0], best[1], bw, bl)))
        placed_any.append(b)
    return unplaced


def validate(layout_src: Layout, pattern: Pattern, positions: dict,
             exact_repair: float = 0.0, exact_workers: int = 8,
             exact_objective: str = "count",
             diag: dict | None = None) -> tuple[str, Layout | None, int]:
    """Turn a SAT consumer placement into a full, legal layout.

    `diag`, if given, is filled with how the filler stage went -- `placed`,
    `total` and the names of what did not fit. `_place_fillers` never exits
    early, so on failure this is a real "placed N of M" rather than a bare
    rejection, and the webapp can say which buildings had nowhere to go.

    `exact_repair` > 0 gives the CP-SAT filler packer that many seconds to
    rescue layouts the greedy packer cannot finish. It runs *only* on layouts
    that would otherwise be thrown away as SAT_FILLER_FAIL, and is hinted with
    the greedy packing so it can never do worse. See foeopt/exact_packing.py.
    """
    consumers = layout_src.road_needing()
    fillers = [b for b in layout_src.buildings
               if not b.needs_road and not b.is_townhall]
    placed = []
    for b in consumers:
        x, y, w, l = positions[b.entity_id]
        placed.append(replace(b, footprint=Footprint(x, y, w, l)))
    # Composite chains become their real members before routing: the router
    # and validators only ever see real buildings (foeopt/chains.py).
    placed = expand_buildings(placed)
    th = replace(layout_src.townhall, footprint=pattern.th)
    cand = Layout(layout_src.region, [th, *placed], th, {})
    # Two-lane buildings: the placement's chosen 2x2 tiles are fixed level-2
    # roads; with none chosen, route() refuses rather than fake a 1x1 tile.
    fixed = None
    if any(b.road_level >= 2 for b in placed if b.needs_road):
        fixed = {c: 2 for (tx, ty) in lane_tiles_of(positions)
                 for c in Footprint(tx, ty, 2, 2).cells()}
    t_route = time.monotonic()
    try:
        roads = route(cand, fixed=fixed)
    except RouteError:
        return ("ROUTE_FAIL", None, 0)
    finally:
        if diag is not None:
            diag["route_s"] = time.monotonic() - t_route
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
    n_before = len(cand.buildings)
    t_fill = time.monotonic()
    unplaced = _place_fillers(grid, fillers, cand)
    if diag is not None:
        diag["fillers_s"] = time.monotonic() - t_fill
    if unplaced and exact_repair > 0:
        t_rep = time.monotonic()
        hint = [(b, b.footprint.x, b.footprint.y)
                for b in cand.buildings[n_before:]]
        placements, still = exact_pack(free, w, h, fillers, exact_repair,
                                       workers=exact_workers, hint=hint,
                                       objective=exact_objective)
        if len(still) < len(unplaced):
            del cand.buildings[n_before:]
            cand.buildings.extend(apply_placements(placements))
            unplaced = still
        if diag is not None:
            diag["repair_s"] = time.monotonic() - t_rep
    if diag is not None:
        diag["fillers_total"] = len(fillers)
        diag["fillers_placed"] = len(fillers) - len(unplaced)
        diag["unplaced"] = sorted(b.name for b in unplaced)
        diag["repair_ran"] = bool(exact_repair > 0)
    if unplaced:
        return ("SAT_FILLER_FAIL", None, len(roads))
    cand.buildings = expand_buildings(cand.buildings)
    bad = rotated_buildings(cand, canonical_dims(expand(layout_src)))
    if bad:
        return ("SAT_ROTATED", None, len(roads))
    return ("OK", cand, len(roads))


_WORKER_LAYOUT: Layout | None = None
_WORKER_PROBE_LIMIT: float = 30.0
_WORKER_PROBE_WORKERS: int = 1
_WORKER_SYMMETRY_BREAKING: bool = False
_WORKER_HINTS: dict[int, tuple[int, int]] | None = None
_WORKER_STUB_PRIORITY: bool = False
_WORKER_SOLVER_OVERRIDES: dict[str, object] | None = None
_WORKER_EXACT_REPAIR: float = 0.0
_WORKER_OBJECTIVE_LIMIT: float = 0.0
# Below this many banded skeletons a level is topped up with unbanded ones.
BAND_MIN_PATTERNS = 10
_WORKER_MODEL: str = "item"
# Seconds kept back for validate() after the objective solve, and the smallest
# objective budget worth starting (hinted, it improves within seconds).
OBJECTIVE_MARGIN_S = 3.0
BOUNDARY_LEVELS = 4        # levels probed below the walk's lowest when nothing was feasible
EXACT_FINISH_S = 10.0      # exact_route cap on the final layout
EXACT_FINISH_MIN_S = 1.0  # below this, skip exact finish rather than start it
OBJECTIVE_MIN_S = 2.0


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int,
                 symmetry_breaking: bool = False, hints=None,
                 stub_priority: bool = False,
                 solver_overrides: dict[str, object] | None = None,
                 exact_repair: float = 0.0, objective_limit: float = 0.0,
                 model: str = "item") -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    global _WORKER_SYMMETRY_BREAKING, _WORKER_HINTS, _WORKER_STUB_PRIORITY
    global _WORKER_SOLVER_OVERRIDES, _WORKER_EXACT_REPAIR, _WORKER_OBJECTIVE_LIMIT
    global _WORKER_MODEL
    _WORKER_MODEL = model
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    _WORKER_SYMMETRY_BREAKING = symmetry_breaking
    _WORKER_HINTS = hints
    _WORKER_STUB_PRIORITY = stub_priority
    _WORKER_SOLVER_OVERRIDES = solver_overrides
    _WORKER_EXACT_REPAIR = exact_repair
    _WORKER_OBJECTIVE_LIMIT = objective_limit


def _run_probe(payload: tuple) -> dict:
    pat, k, pat_index = payload[:3]
    deadline = payload[3] if len(payload) > 3 else None
    layout = _WORKER_LAYOUT
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    pdiag: dict = {}
    st, pos = probe(pat, region, consumers,
                   probe_limit=_WORKER_PROBE_LIMIT,
                   probe_workers=_WORKER_PROBE_WORKERS,
                   symmetry_breaking=_WORKER_SYMMETRY_BREAKING,
                   hints=_WORKER_HINTS,
                   stub_priority=_WORKER_STUB_PRIORITY,
                   solver_overrides=_WORKER_SOLVER_OVERRIDES,
                   diag=pdiag,
                   # only when non-default: the item-model call stays identical
                   **({"model": _WORKER_MODEL} if _WORKER_MODEL != "item" else {}))
    secs = round(time.monotonic() - t0, 1)
    # Phase timings travel back with the result (worker seconds; see profiling.py).
    phases = {"probe_total": time.monotonic() - t0,
              "probe_build": pdiag.get("cand_s", 0.0), "probe_solve": pdiag.get("solve_s", 0.0),
              f"probe_{st.lower()}": time.monotonic() - t0}
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None,
                "pat_index": pat_index, "pos": None, "phases": phases}
    # Clamped to one probe's own limit so a rescue can at worst DOUBLE the cost
    # of the probe that produced it. The repair is charged per rescued layout,
    # not once per run, so an unclamped value would let N filler failures add
    # N x exact_repair seconds to the box -- the same defect class as the
    # seed_polish overrun (tasks/lessons.md 2026-07-30).
    vdiag: dict = {}
    t_val = time.monotonic()
    vstat, vlay, achieved = validate(
        layout, pat, pos,
        exact_repair=min(_WORKER_EXACT_REPAIR, _WORKER_PROBE_LIMIT),
        exact_workers=_WORKER_PROBE_WORKERS, diag=vdiag)
    phases["validate_total"] = time.monotonic() - t_val
    for key in ("route_s", "fillers_s", "repair_s"):
        if key in vdiag:
            phases["validate_" + key[:-2]] = vdiag[key]
    objective_cmp = None
    # Clamped to one probe's own limit, for the same reason as exact_repair
    # above (charged per SAT, an unclamped value lets N SATs add N x limit),
    # AND to the caller's deadline less a margin for validate(): a result that
    # arrives after the deadline is thrown away with the pool.
    olimit = min(_WORKER_OBJECTIVE_LIMIT, _WORKER_PROBE_LIMIT)
    if deadline is not None:
        olimit = min(olimit, deadline - time.monotonic() - OBJECTIVE_MARGIN_S)
    if _WORKER_OBJECTIVE_LIMIT > 0 and olimit >= OBJECTIVE_MIN_S:
        odiag: dict = {}
        t_obj = time.monotonic()
        opos = minimize_needed(pat, region, consumers, pos, limit=olimit,
                               workers=_WORKER_PROBE_WORKERS, diag=odiag,
                               model=_WORKER_MODEL)
        obj_total = time.monotonic() - t_obj
        phases["objective_total"] = obj_total
        phases["objective_solve"] = odiag.get("objective_s", 0.0)
        phases["objective_build"] = max(0.0, obj_total - odiag.get("objective_s", 0.0))
        if opos is not None:
            t_val2 = time.monotonic()
            ostat, olay, oach = validate(
                layout, pat, opos,
                exact_repair=min(_WORKER_EXACT_REPAIR, _WORKER_PROBE_LIMIT),
                exact_workers=_WORKER_PROBE_WORKERS)
            phases["objective_validate"] = time.monotonic() - t_val2
            if ostat == "OK":
                objective_cmp = (odiag.get("objective"), oach,
                                 achieved if vstat == "OK" else None)
            # Keep the better LEGAL layout; the feasibility one is never lost.
            if ostat == "OK" and (vstat != "OK" or oach < achieved):
                vstat, vlay, achieved, pos = ostat, olay, oach, opos
        secs = round(time.monotonic() - t0, 1)
    phases["worker_total"] = time.monotonic() - t0
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay,
                "pat_index": pat_index, "pos": pos, "phases": phases,
                "objective_cmp": objective_cmp}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None, "filler": vdiag,
            "pat_index": pat_index, "pos": pos, "phases": phases,
            "objective_cmp": objective_cmp}


def _run_probe_seq(payload: tuple) -> dict:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    global _WORKER_SYMMETRY_BREAKING, _WORKER_HINTS, _WORKER_STUB_PRIORITY
    global _WORKER_SOLVER_OVERRIDES, _WORKER_EXACT_REPAIR, _WORKER_OBJECTIVE_LIMIT
    global _WORKER_MODEL
    pat, k, layout, probe_limit, probe_workers, *rest = payload
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    _WORKER_SYMMETRY_BREAKING = rest[0] if rest else False
    _WORKER_HINTS = rest[1] if len(rest) > 1 else None
    _WORKER_STUB_PRIORITY = rest[2] if len(rest) > 2 else False
    _WORKER_SOLVER_OVERRIDES = rest[3] if len(rest) > 3 else None
    _WORKER_EXACT_REPAIR = rest[4] if len(rest) > 4 else 0.0
    _WORKER_OBJECTIVE_LIMIT = rest[5] if len(rest) > 5 else 0.0
    # Only forwarded when the objective is on: off stays byte-identical.
    deadline = rest[6] if len(rest) > 6 and _WORKER_OBJECTIVE_LIMIT > 0 else None
    _WORKER_MODEL = rest[7] if len(rest) > 7 else "item"
    try:
        return _run_probe((pat, k, 0) if deadline is None else (pat, k, 0, deadline))
    finally:
        _WORKER_LAYOUT = None

LEVEL_STATUSES = ("FEASIBLE", "INFEASIBLE", "INCONCLUSIVE", "UNDERSAMPLED")


def classify_level(st: dict) -> tuple[str, int | None]:
    """Four outcomes, distinguished by WHY no layout was found.

    The distinction is not cosmetic. Before 2026-08-03 a level that was
    never probed -- or barely probed -- reported INFEASIBLE, because it had
    seen no non-proof failure to contradict it. When the deadline fires the
    pool terminates and *every* level is classified, so levels with ZERO
    probes were reporting a refutation on no evidence whatsoever. That
    produced two wrong conclusions in tasks/remaining-work.md, and made the
    same k on FR17 read FEASIBLE, INCONCLUSIVE or INFEASIBLE depending only
    on the order the walk happened to reach it (section 9).

      FEASIBLE      a legal layout was found.
      INFEASIBLE    every surviving pattern was probed and refuted. Still
                    only a statement about THIS SAMPLE, never about the
                    family -- but it is at least exhaustive over the sample.
      INCONCLUSIVE  fully probed, but some probes came back undecided
                    (UNKNOWN/ROUTE_FAIL/...). Act on it by raising
                    `probe_limit`: the solver ran out of time per pattern.
      UNDERSAMPLED  the sample was not finished. Says nothing at all about
                    feasibility. Act on it by raising `time_box`.
    """
    if st["best_achieved"] is not None:
        return ("FEASIBLE", st["best_achieved"])
    if not st["pats"]:
        return ("INCONCLUSIVE", None)
    if st["order"] < len(st["surviving"]):
        return ("UNDERSAMPLED", None)
    return ("INCONCLUSIVE" if st["saw_nonproof_failure"] else "INFEASIBLE", None)



def _fill_coverage(state: dict, ks, coverage: dict | None) -> None:
    """How much of each level's sample actually got probed.

    Without this a caller cannot tell an exhaustive negative from a level that
    the deadline cut off after two patterns -- which is exactly the confusion
    UNDERSAMPLED exists to remove.
    """
    if coverage is None:
        return
    for k in ks:
        st = state.get(k)
        if st is None:
            continue
        coverage[k] = {"generated": len(st["pats"]),
                       "surviving": len(st["surviving"]),
                       "probed": min(st["order"], len(st["surviving"]))}


def new_filler_stats() -> dict:
    """Running tally of the SAT_FILLER_FAIL population for one run."""
    return {"failures": 0, "placed": 0, "total": 0, "worst": None,
            "by_building": {}}


def summarise_fillers(fs: dict) -> dict | None:
    """Human-facing summary, or None when no layout died this way."""
    if not fs or not fs["failures"]:
        return None
    worst_names = sorted(fs["by_building"].items(), key=lambda kv: -kv[1])[:5]
    return {
        "failures": fs["failures"],
        "mean_placed": round(fs["placed"] / fs["failures"], 1),
        "mean_total": round(fs["total"] / fs["failures"], 1),
        "worst_placed": fs["worst"],
        "top_unplaced": [{"name": n, "times": c} for n, c in worst_names],
    }


def _probe_levels_batch(layout, region, consumers, ks, rng, params, log, pool=None,
                        on_improvement=None, corpus=None, scorer=None,
                        score_threshold=None,
                        filler_stats: dict | None = None,
                        coverage: dict | None = None,
                        runtime: dict | None = None) -> dict[int, tuple[str, int | None]]:
    """Generate + probe several k-levels' patterns in one shared pool dispatch
    instead of draining one level's ~200 patterns before the next level's are
    even generated. `_run_probe`'s payload/result already carry `k`, so this
    only changes dispatch/demux, not the worker-side probe logic.

    Levels are generated in `ks` order against the *same* `rng` stream, so
    pattern content for a given k is identical to what a sequential run of
    `_probe_level` would have produced -- this is the determinism invariant
    that makes batching a pure speed change, not a different search."""
    th = layout.townhall.footprint
    if filler_stats is None:
        filler_stats = new_filler_stats()
    # A slice caps THIS call, so one level cannot eat the whole box. Measured on
    # FR17 at k_start=117: the first level alone could consume 525 s of a 600 s
    # box (35 patterns x 90 s / 6 workers) and then return INCONCLUSIVE, leaving
    # every later level with one probe or none.
    slice_deadline = getattr(params, "slice_deadline", None)
    effective_deadline = (params.deadline if slice_deadline is None
                          else min(params.deadline, slice_deadline))
    th_mode = getattr(params, "th_anchors", "coarse")
    family = getattr(params, "pattern_family", "comb")
    gen_fn = _pattern_generator(family)

    # Fillers occupy region cells too; without them the prefilter's area check
    # passes patterns with no room for everything, which then burn a full probe
    # before failing as SAT_FILLER_FAIL. (Documented as shipped 2026-07-31 but
    # never passed on this, the production path, until 2026-11-11.)
    fillers = [b for b in layout.buildings if not b.needs_road and not b.is_townhall]
    profile = getattr(params, "profile", None)
    state: dict[int, dict] = {}
    for k in ks:
        t_gen = time.monotonic()
        gen_kwargs = {"th_mode": th_mode}
        if family == "lane":
            gen_kwargs["max_lane_len"] = getattr(params, "lane_cap", None)
            if getattr(params, "lane_pitches", None) is not None:
                gen_kwargs["pitches"] = params.lane_pitches
        elif family == "nonuniform":
            gen_kwargs["quality_index_band"] = getattr(params, "quality_index_band", None)
        elif family == "comb" and getattr(params, "comb_modes", None) is not None:
            gen_kwargs["modes"] = params.comb_modes
        pats = gen_fn(region, th.width, th.length, k, rng, params.patterns,
                      **gen_kwargs)
        if (family == "nonuniform" and gen_kwargs.get("quality_index_band") is not None
                and len(pats) < BAND_MIN_PATTERNS):
            # The band was calibrated on darkzig/FR16 and can be EMPTY elsewhere:
            # on FR24 it yields 0 skeletons at every k >= 220, so every level
            # was empty and the run ended FAMILY_TOO_WEAK in 4 s without one
            # probe. Top up with unbanded skeletons. The threshold is below
            # every measured city's banded count (FR17: 21-51 per level), so
            # their behaviour is unchanged.
            seen_roads = {p.roads for p in pats}
            extra = gen_fn(region, th.width, th.length, k, rng, params.patterns,
                           **{**gen_kwargs, "quality_index_band": None})
            pats = pats + [p for p in extra if p.roads not in seen_roads]
        if profile is not None:
            profile.add("generate", time.monotonic() - t_gen)
        t_pre = time.monotonic()
        surviving = []
        for pat in pats:
            reason = prefilter(pat, region, consumers, fillers)
            if reason is not None:
                log({"k": k, "params": pat.params, "status": "PREFILTERED",
                     "reason": reason, "secs": 0.0, "order": 0})
                continue
            surviving.append(pat)
        if profile is not None:
            profile.add("prefilter", time.monotonic() - t_pre)
        if scorer is not None and surviving:
            scored = [(scorer(pat), pat) for pat in surviving]
            if score_threshold is not None:
                scored = [sp for sp in scored if sp[0] >= score_threshold]
            scored.sort(key=lambda sp: sp[0], reverse=True)
            surviving = [pat for _, pat in scored]
        state[k] = {"pats": pats, "surviving": surviving, "best_achieved": None,
                    "saw_nonproof_failure": False, "order": 0}

    def handle_result(k, result, pat):
        st = state[k]
        st["order"] += 1
        if profile is not None:
            profile.merge(result.get("phases"))
            if result.get("objective_cmp"):
                profile.objective_row(*result["objective_cmp"])
            if result["status"] == "SAT":
                profile.event("first_sat")
        status = result["status"]
        achieved = result["achieved"]
        row = {"k": k, "params": pat.params, "status": status,
               "achieved": achieved, "secs": result["secs"], "order": st["order"]}
        if result.get("filler"):
            row["filler"] = result["filler"]
        log(row)
        if status == "SAT_FILLER_FAIL" and result.get("filler"):
            # Accumulated so the run can report WHY it found nothing, instead of
            # a bare "no layout". _place_fillers never exits early, so these are
            # real "placed N of M" counts.
            f = result["filler"]
            fs = filler_stats
            fs["failures"] += 1
            fs["placed"] += f.get("fillers_placed", 0)
            fs["total"] += f.get("fillers_total", 0)
            fs["worst"] = (f.get("fillers_placed", 0) if fs["worst"] is None
                           else min(fs["worst"], f.get("fillers_placed", 0)))
            for nm in f.get("unplaced", []):
                fs["by_building"][nm] = fs["by_building"].get(nm, 0) + 1
        if corpus is not None:
            corpus.record(k=k, roads=pat.roads, th=pat.th, status=status,
                          secs=result["secs"], pos=result.get("pos"))
        if status == "SAT":
            vlay = result["layout"]
            sat_recorder = getattr(params, "sat_recorder", None)
            if sat_recorder is not None:
                sat_recorder(k, achieved, pat, result.get("pos"))
            if st["best_achieved"] is None or achieved < st["best_achieved"]:
                st["best_achieved"] = achieved
                if on_improvement is not None:
                    on_improvement(vlay, k, achieved)
                recorder = getattr(params, "best_recorder", None)
                if recorder is not None:
                    recorder(k, achieved, pat, vlay)
        elif status in ("UNKNOWN", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"):
            st["saw_nonproof_failure"] = True
        return time.monotonic() > effective_deadline

    if pool is None:
        for i, k in enumerate(ks):
            interrupted = False
            for pat in state[k]["surviving"]:
                result = _run_probe_seq((pat, k, layout, params.probe_limit, params.probe_workers,
                                         getattr(params, "symmetry_breaking", False),
                                         getattr(params, "hints", None),
                                         getattr(params, "stub_priority", False),
                                         None,
                                         getattr(params, "exact_repair", 0.0),
                                         getattr(params, "objective_limit", 0.0),
                                         effective_deadline,
                                         getattr(params, "probe_model", "item")))
                if handle_result(k, result, pat):
                    interrupted = True
                    break
            if interrupted:
                # classify() already reports UNDERSAMPLED for the interrupted
                # level and for every level after it (probed 0 of N), so there
                # is nothing to special-case here any more.
                _fill_coverage(state, ks, coverage)
                return {kk: classify_level(state[kk]) for kk in ks}
    else:
        # Round-robin across levels, not grouped by level. Grouped payloads make
        # imap_unordered drain k1 entirely before touching k2, so a "concurrent"
        # batch is concurrent only in generation -- exactly what this function's
        # docstring says it exists to avoid. Measured consequence: on a deadline
        # the later levels of a batch had probed 0 of 28 patterns and were still
        # being classified (see tasks/remaining-work.md section 10).
        if getattr(params, "interleave_levels", True):
            _by_level = [[(pat, k, idx) for idx, pat in enumerate(state[k]["surviving"])]
                         for k in ks]
            payloads = [p for row in itertools.zip_longest(*_by_level) for p in row
                        if p is not None]
        else:
            # Pre-2026-08-03 order, retained ONLY so the A/B can reproduce it.
            payloads = [(pat, k, idx) for k in ks
                        for idx, pat in enumerate(state[k]["surviving"])]
        if getattr(params, "objective_limit", 0.0) > 0:
            # The objective phase must know the deadline: probe + objective can
            # exceed a level slice, and a slice expiry terminates the pool,
            # killing every in-flight SAT with it (measured: FR16 at a 60 s box
            # found NOTHING with the objective on). time.monotonic is
            # system-wide on Linux, so it is comparable inside the workers.
            payloads = [(*p, effective_deadline) for p in payloads]
        for result in pool.imap_unordered(_run_probe, payloads):
            k = result["k"]
            idx = result["pat_index"]
            pat = state[k]["surviving"][idx]
            if handle_result(k, result, pat):
                # Kills in-flight probes, which is what we want -- but it also
                # leaves the pool permanently unusable. Before slicing this only
                # ever happened at the walk deadline, when the pool was about to
                # be discarded anyway; a slice fires mid-run, so the caller MUST
                # be told to rebuild or every later level dies with
                # "ValueError: Pool not running".
                pool.terminate()
                if runtime is not None:
                    runtime["pool_terminated"] = True
                break

    _fill_coverage(state, ks, coverage)
    return {k: classify_level(state[k]) for k in ks}


def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None, corpus=None, scorer=None, score_threshold=None,
                 filler_stats=None, coverage=None, runtime=None) -> tuple[str, int | None]:
    return _probe_levels_batch(layout, region, consumers, [k], rng, params, log, pool=pool,
                               on_improvement=on_improvement, corpus=corpus,
                               scorer=scorer, score_threshold=score_threshold,
                               filler_stats=filler_stats, coverage=coverage,
                               runtime=runtime)[k]


class RoadsFirstSearch:
    def __init__(self, layout: Layout, *, time_box: float, patterns: int = 200,
                 probe_limit: float = 60.0, workers: int = 4,
                 probe_workers: int = 4, th_anchors: str = "full",
                 k_start="auto", corpus_dir=None, scorer=None, score_threshold=None,
                 symmetry_breaking: bool = False, hint_layout: Layout | None = None,
                 pattern_family: str = "comb", stub_priority: bool = False,
                 lane_cap: int | None = None, concurrent_levels: int = 1,
                 seed_polish: int = 0, lane_pitches: tuple[int, ...] | None = None,
                 quality_index_band: tuple[int, int] | None = None,
                 exact_repair: float = 0.0,
                 comb_modes: tuple[str, ...] | None = None,
                 level_slice_frac: float | None = 0.35,
                 interleave_levels: bool = True,
                 objective_limit: float = 0.0,
                 objective_polish: float = 0.0,
                 objective_polish_top: int = 3,
                 exact_finish: bool = False,
                 probe_model: str = "position",
                 keep_chains: bool = True,
                 military: str = "connect"):
        # Linked chains are placed as rigid composites so their links survive
        # (user-confirmed rule, 2026-11-11); every emitted layout is expanded
        # back to real buildings inside validate().
        if military not in MILITARY_POLICIES:
            raise ValueError(f"military must be one of {MILITARY_POLICIES}")
        self.military = military
        self.source_layout = layout
        if military == "unconnected":
            # Explicit per-run choice: two-lane buildings are left off the road
            # and packed like any building that needs none.
            layout = Layout(layout.region,
                            [replace(b, needs_road=False)
                             if b.needs_road and b.road_level >= 2 else b
                             for b in layout.buildings],
                            layout.townhall, dict(layout.roads))
        elif probe_model != "position" and any(
                b.road_level >= 2 for b in layout.road_needing()):
            raise ValueError("a two-lane building with military='connect' needs "
                             "probe_model='position' (the item model has no "
                             "two-lane tiles); or pass military='unconnected'")
        self.layout = compose(layout) if keep_chains else layout
        if probe_model not in PROBE_MODELS:
            raise ValueError(f"probe_model must be one of {PROBE_MODELS}")
        # "position": symmetry-free CP-SAT encoding (see _position_model). The
        # item-model-only levers (symmetry_breaking, hints, stub_priority) are
        # ignored under it.
        self.probe_model = probe_model
        # Re-route the final best layout with exact_route (min connected road
        # cover for the fixed placement, typically < 0.1 s) and keep it when it
        # is strictly smaller. route() is greedy: on 2026-11-11 A/B layouts it
        # left one road on the table in both arms (99 -> 98, 94 -> 93).
        self.exact_finish = exact_finish
        # > 0: reserve this FRACTION of the box, after the walk, to re-solve the
        # best `objective_polish_top` distinct SAT skeletons with minimize_needed
        # using every solver thread (workers x probe_workers). The in-walk
        # objective_limit gets one probe's threads and is clamped to probe_limit;
        # the record-breaking runs used 120 s x 12 threads on one skeleton.
        self.objective_polish = objective_polish
        self.objective_polish_top = objective_polish_top
        # > 0: after every SAT, spend up to this many seconds (clamped to
        # probe_limit) minimizing the skeleton cells the placement needs. See
        # minimize_needed. 0 = feasibility only, the historical behaviour.
        self.objective_limit = objective_limit
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
        self.lane_cap = lane_cap
        self.lane_pitches = lane_pitches
        self.quality_index_band = quality_index_band
        self.concurrent_levels = concurrent_levels
        self.seed_polish = seed_polish
        self.exact_repair = exact_repair
        self.comb_modes = comb_modes
        # Caps each probing call at this share of the REMAINING budget, so one
        # level cannot consume the box. None restores the pre-2026-08-03
        # behaviour.
        #
        # 0.35 from the 24-cell A/B (tasks/remaining-work.md section 11). From a
        # k_start below the productive region the unsliced walk returns NOTHING
        # on all three cities; 0.35 returns 101 / 81 / 130. From the correct
        # k_start it changes no result on any city (104 / 77 / 115 either way),
        # so it is insurance with no measured cost. 0.50 was rejected: it costs
        # a road on FR16's correct start and fails to rescue FR17 at all.
        self.level_slice_frac = level_slice_frac
        # Measurement knob only: False restores the level-grouped payload order
        # that made a "concurrent" batch drain one level at a time.
        self.interleave_levels = interleave_levels

    def _apply_exact_finish(self, latest: dict, on_improvement,
                            deadline: float | None = None, should_stop=None) -> dict:
        """exact_route on the best layout; emit it only if strictly smaller and
        still valid. Capped at EXACT_FINISH_S and at the time left before
        `deadline`; skipped (never started) when stopped or out of time."""
        from foeopt.exact_router import exact_route
        lay, before = latest["layout"], latest["achieved"]
        limit = EXACT_FINISH_S
        if deadline is not None:
            limit = min(limit, deadline - time.monotonic())
        if (should_stop is not None and should_stop()) or limit < EXACT_FINISH_MIN_S:
            return {"before": before, "after": before, "status": "SKIPPED",
                    "optimal": False}
        lane = {c: lvl for c, lvl in lay.roads.items() if lvl >= 2}
        res = exact_route(lay, time_limit=limit, **({"fixed": lane} if lane else {}))
        after = before
        if res.roads is not None and res.count is not None and res.count < before:
            cand = Layout(lay.region, lay.buildings, lay.townhall, dict(res.roads))
            if is_valid(cand) and len(cand.roads) == res.count:
                after = res.count
                on_improvement(cand, latest["k"], after)
        return {"before": before, "after": after, "status": res.status,
                "optimal": res.optimal}

    def _apply_objective_polish(self, cands, best, on_improvement, end,
                                should_stop=None) -> dict:
        """Re-solve the top distinct SAT skeletons with minimize_needed, all
        solver threads, splitting the time left before `end` evenly across the
        candidates still to go. Keeps only fully validated strict improvements."""
        region = set(self.layout.region.cells)
        consumers = self.layout.road_needing()
        threads = max(1, self.workers * self.probe_workers)
        top = cands[:max(1, self.objective_polish_top)]
        tried, after, per = 0, best, []
        for i, (ach, k, pat, pos) in enumerate(top):
            if should_stop is not None and should_stop():
                break
            limit = (end - time.monotonic() - OBJECTIVE_MARGIN_S) / (len(top) - i)
            if limit < OBJECTIVE_MIN_S:
                break
            tried += 1
            opos = minimize_needed(pat, region, consumers, pos, limit=limit,
                                   workers=threads, model=self.probe_model)
            got = None
            if opos is not None:
                vst, vlay, vach = validate(self.layout, pat, opos,
                                           exact_repair=min(self.exact_repair, limit),
                                           exact_workers=threads)
                if vst == "OK":
                    got = vach
                    if after is None or vach < after:
                        after = vach
                        if on_improvement is not None:
                            on_improvement(vlay, k, vach)
            per.append({"k": k, "before": ach, "after": got, "limit_s": round(limit, 1)})
        return {"before": best, "after": after, "tried": tried,
                "candidates": len(cands), "per_skeleton": per}

    def _apply_seed_polish(self, best_holder: dict, on_improvement,
                           should_stop=None, incumbent: int | None = None) -> dict | None:
        """Opt-in (seed_polish>0): re-solve the best skeleton under N CP-SAT
        seeds and keep a strictly-lower legal road count. probe() has no
        objective, so the placement it returns -- and thus route()'s count --
        varies with the solver seed; this samples that spread on the single
        best skeleton found. Returns an info dict (or None if it didn't run),
        and emits the improved layout through on_improvement so streaming
        callers see it.

        `should_stop` is polled before every seed, so this phase is bounded by
        the caller's REMAINING budget rather than by `seed_polish x probe_limit`.
        Without it a 120 s box with seed_polish=12 measured 281 s (2.34x) for a
        one-road gain, and the Stop button did nothing during the phase."""
        if self.seed_polish <= 0 or best_holder.get("pattern") is None:
            return None
        from foeopt.seed_search import seed_minimize_roads
        res = seed_minimize_roads(self.layout, best_holder["pattern"],
                                  seeds=range(self.seed_polish),
                                  probe_limit=self.probe_limit,
                                  probe_workers=self.probe_workers,
                                  should_stop=should_stop)
        # Compare against the GLOBAL incumbent (objective polish may already
        # have beaten the walk's best skeleton), not just that skeleton's count.
        baseline = best_holder.get("achieved")
        if incumbent is not None and (baseline is None or incumbent < baseline):
            baseline = incumbent
        improved = (res.achieved is not None and baseline is not None
                    and res.achieved < baseline)
        if improved and on_improvement is not None:
            on_improvement(res.layout, best_holder.get("k"), res.achieved)
        return {"before": baseline, "after": res.achieved if improved else baseline,
                "improved": improved, "seed": res.seed if improved else None,
                "seeds_tried": res.n_tried, "n_legal": res.n_legal,
                "stopped_early": res.n_tried < self.seed_polish}

    def run(self, on_improvement=None, on_status=None, should_stop=None) -> dict:
        # ONE incumbent for every phase (walk, objective polish, seed polish,
        # exact finish): a layout reaches the caller only if it strictly beats
        # everything published before, so emitted counts never go up and the
        # returned best is the last emitted layout. (Before: seed polish compared
        # against the stale walk best and could publish 95 after 90.)
        latest: dict = {"layout": None, "k": None, "achieved": None}
        user_cb = on_improvement
        profile = Profile()
        self.profile = profile

        def on_improvement(vlay, k, achieved):  # noqa: F811 -- wraps the caller's
            if latest["achieved"] is not None and achieved >= latest["achieved"]:
                return
            profile.event("first_valid")
            profile.events["last_improvement"] = round(time.monotonic() - profile.t0, 2)
            latest.update(layout=vlay, k=k, achieved=achieved)
            if user_cb is not None:
                user_cb(vlay, k, achieved)
        layout = self.layout
        region = set(layout.region.cells)
        consumers = layout.road_needing()
        rng = random.Random(0)
        # A phase that is bounded by the remaining budget does nothing when the
        # budget is already spent -- so if seed_polish is requested, RESERVE a
        # slice for it rather than letting the walk consume everything. Without
        # this the parameter is silently inert (measured: seeds_tried=0 at a
        # 120 s box). Capped at a quarter of the box so polish can never starve
        # the search that finds the skeleton it polishes.
        polish_reserve = 0.0
        if self.seed_polish > 0:
            want = min(self.seed_polish * self.probe_limit, self.time_box * 0.25)
            # Only take the reserve if it can actually fit a seed. A reserve
            # smaller than one probe shortens the walk and then gets refused by
            # _stop_polish, spending nothing -- measured 92 s on a 120 s box
            # (0.77x) with seeds_tried=0, strictly worse than not reserving.
            # The margin covers the walk's own probe-granularity overshoot.
            polish_reserve = want if want >= self.probe_limit * 1.2 else 0.0
        objective_reserve = 0.0
        if self.objective_polish > 0:
            objective_reserve = self.time_box * self.objective_polish
            if objective_reserve < OBJECTIVE_MIN_S + OBJECTIVE_MARGIN_S:
                objective_reserve = 0.0  # cannot fit one useful solve
        # exact_finish runs last, inside the box: reserve its (small) solve.
        exact_reserve = min(EXACT_FINISH_S, self.time_box * 0.05) if self.exact_finish else 0.0
        deadline = time.monotonic() + self.time_box - exact_reserve
        walk_deadline = deadline - polish_reserve - objective_reserve
        polish_deadline = deadline - polish_reserve  # objective polish ends here
        hard_deadline = deadline + exact_reserve
        filler_stats = new_filler_stats()
        level_coverage: dict[int, dict] = {}

        def _new_pool():
            return multiprocessing.Pool(
                self.workers,
                initializer=_worker_init,
                initargs=(layout, self.probe_limit, self.probe_workers,
                         self.symmetry_breaking, self.hints, self.stub_priority,
                         None, self.exact_repair, self.objective_limit,
                         self.probe_model))

        pool = _new_pool() if self.workers > 1 else None

        corpus = None

        params = SimpleNamespace(
            patterns=self.patterns,
            probe_limit=self.probe_limit,
            probe_workers=self.probe_workers,
            deadline=walk_deadline,
            th_anchors=self.th_anchors,
            symmetry_breaking=self.symmetry_breaking,
            hints=self.hints,
            pattern_family=self.pattern_family,
            stub_priority=self.stub_priority,
            lane_cap=self.lane_cap,
            lane_pitches=self.lane_pitches,
            quality_index_band=self.quality_index_band,
            exact_repair=self.exact_repair,
            objective_limit=self.objective_limit,
            probe_model=self.probe_model,
            comb_modes=self.comb_modes,
            interleave_levels=self.interleave_levels,
        )
        params.profile = profile

        results: dict[int, tuple[str, int | None]] = {}

        # Capture the single best skeleton for optional seed-polish. Read off
        # `params` by handle_result via getattr, so no probe-plumbing signature
        # changes -- and it only records when seed_polish is on.
        best_holder: dict = {"achieved": None, "pattern": None, "k": None,
                             "layout": None}

        def _record_best(k, achieved, pat, vlay):
            if best_holder["achieved"] is None or achieved < best_holder["achieved"]:
                best_holder.update(achieved=achieved, pattern=pat, k=k, layout=vlay)

        if self.seed_polish > 0:
            params.best_recorder = _record_best

        # Every SAT, for objective polish: the best feasibility count is a poor
        # predictor of the best count after the objective, so keep several.
        sat_cands: list[tuple[int, int, Pattern, dict]] = []

        def _record_sat(k, achieved, pat, pos):
            if pos is None or any(c[2].roads == pat.roads for c in sat_cands):
                return
            sat_cands.append((achieved, k, pat, pos))
            sat_cands.sort(key=lambda c: (c[0], c[1]))
            del sat_cands[max(1, self.objective_polish_top) * 3:]

        if objective_reserve > 0:
            params.sat_recorder = _record_sat

        def _walk_end():
            """The walk leaves the objective-polish reserve free only once there
            is something to polish. With no layout yet, it may use the reserve
            (measured on the 97%-full city: 30% of the box sat idle after a
            fruitless walk). The seed-polish reserve is never touched."""
            if objective_reserve > 0 and latest["achieved"] is None:
                return polish_deadline
            return walk_deadline

        def _should_stop():
            """Walk phase: stops early enough to leave the polish reserve."""
            if should_stop is not None and should_stop():
                return True
            return time.monotonic() >= _walk_end()

        def _stop_polish():
            """Polish phase: may use the reserve, but not exceed the real box.

            Stops before starting a seed it cannot finish. The polish loop is
            sequential and each seed costs up to `probe_limit`, so checking only
            `now >= deadline` lets the last seed run past the box by up to a
            full probe -- measured 141.7 s on a 120 s box (1.18x). Requiring
            room for a whole seed converts that overshoot into an early stop.
            (The k-walk cannot do this as cleanly: its probes are dispatched in
            a pool batch, so its granularity remains one probe.)"""
            if should_stop is not None and should_stop():
                return True
            return time.monotonic() + self.probe_limit >= deadline

        attempts: dict[int, int] = {}
        runtime: dict = {}

        def _restore_pool():
            """A slice expiry terminates the pool mid-run, which leaves it
            permanently unusable -- every later level would raise "Pool not
            running". Rebuild it, but only while there is still budget to use it
            for; at the walk deadline the run is over anyway."""
            nonlocal pool
            if not runtime.pop("pool_terminated", False):
                return
            if pool is not None and not _should_stop():
                pool = _new_pool()

        def _set_slice():
            """Cap the next probing call at a share of what is left."""
            if self.level_slice_frac is None:
                params.slice_deadline = None
                return
            params.deadline = _walk_end()
            remaining = params.deadline - time.monotonic()
            params.slice_deadline = (time.monotonic()
                                     + max(self.probe_limit,
                                           remaining * self.level_slice_frac))

        def _needs_probe(kk):
            """Re-probe a level that merely ran out of slice, at most twice.

            Without this, D1 turns every truncated level into a permanent
            'not feasible' and the walk gives up with budget still on the clock
            -- trading one bug for a worse one."""
            if kk not in results:
                return True
            return (self.level_slice_frac is not None
                    and results[kk][0] == "UNDERSAMPLED"
                    and attempts.get(kk, 0) < 2
                    and not _should_stop())

        def level(k):
            if _needs_probe(k):
                attempts[k] = attempts.get(k, 0) + 1
                _set_slice()
                results[k] = _probe_level(layout, region, consumers, k, rng,
                                          params, lambda r: None, pool=pool,
                                          on_improvement=on_improvement, corpus=corpus,
                                          scorer=self.scorer, score_threshold=self.score_threshold,
                                          filler_stats=filler_stats,
                                          coverage=level_coverage, runtime=runtime)
                _restore_pool()
                if on_status is not None:
                    on_status(k, results[k][0], 0, 0)
            return results[k]

        def levels(ks):
            missing = [kk for kk in ks if _needs_probe(kk)]
            if missing:
                for kk in missing:
                    attempts[kk] = attempts.get(kk, 0) + 1
                _set_slice()
                batch = _probe_levels_batch(layout, region, consumers, missing, rng,
                                            params, lambda r: None, pool=pool,
                                            on_improvement=on_improvement, corpus=corpus,
                                            scorer=self.scorer, score_threshold=self.score_threshold,
                                            filler_stats=filler_stats,
                                            coverage=level_coverage,
                                            runtime=runtime)
                _restore_pool()
                for kk, res in batch.items():
                    results[kk] = res
                    if on_status is not None:
                        on_status(kk, res[0], 0, 0)
            return {kk: results[kk] for kk in ks}

        def _probe_ks(ks):
            if self.concurrent_levels > 1:
                return levels(ks)
            return {kk: level(kk) for kk in ks}

        def _boundary_search(k_top):
            """The ascent ended without a feasible level. Before giving up:
            (1) finish levels that merely ran out of slice (bounded by
            _needs_probe), then (2) search DOWNWARD from the top level. At or
            near k_max the skeleton fills almost every free cell, so the walk
            had nowhere to climb (the 97%-full user city: k_start = k_max = 145,
            the player's own city uses 142). Fewer roads leave spare cells
            for packing, so feasibility is not monotone here. Returns the
            lowest feasible k found, or None."""
            retry = sorted(kk for kk in results if _needs_probe(kk))
            if retry:
                ok = [kk for kk, r in _probe_ks(retry).items() if r[0] == "FEASIBLE"]
                if ok:
                    return min(ok)
            # Bounded window: 4 levels below the lowest tried. Far below the
            # cap the skeleton is too short to serve every consumer, and
            # marching on only spreads the budget thinner (measured: the user
            # city went down to k=97 with every level unfinished).
            lowest = min(results) if results else k_top
            window = [kk for kk in (lowest - 4 * i for i in range(1, BOUNDARY_LEVELS + 1))
                      if kk >= 1]
            step = max(1, self.concurrent_levels)
            for i in range(0, len(window), step):
                if _should_stop():
                    return None
                ks = window[i:i + step]
                boundary_info["probed"].extend(ks)
                ok = [kk for kk, r in _probe_ks(ks).items() if r[0] == "FEASIBLE"]
                if ok:
                    return min(ok)
            # Then spend what is left finishing unfinished levels, top first.
            while not _should_stop():
                retry = sorted((kk for kk in results if _needs_probe(kk)), reverse=True)
                if not retry:
                    return None
                ok = [kk for kk, r in _probe_ks(retry[:step]).items() if r[0] == "FEASIBLE"]
                if ok:
                    return min(ok)
            return None

        boundary_info: dict = {"probed": []}

        try:
            if self.corpus_dir:
                corpus = CorpusWriter(self.corpus_dir, layout)
            truncated = False

            if self.k_start == "auto":
                k = pick_k_start(layout, self.pattern_family)
            else:
                k = self.k_start

            st, _ = level(k)
            if st != "FEASIBLE":
                k_max = len(layout.region.cells) - sum(
                    b.footprint.width * b.footprint.length for b in layout.buildings)
                if self.concurrent_levels > 1:
                    while st != "FEASIBLE" and k < k_max:
                        if _should_stop():
                            truncated = True
                            break
                        batch_ks = [kk for kk in
                                   (k + 4 * i for i in range(1, self.concurrent_levels + 1))
                                   if kk <= k_max]
                        if not batch_ks:
                            break
                        batch = levels(batch_ks)
                        feasible_ks = [kk for kk in batch_ks if batch[kk][0] == "FEASIBLE"]
                        if feasible_ks:
                            k = min(feasible_ks)
                            st = "FEASIBLE"
                        elif any(batch[kk][0] == "UNDERSAMPLED" and _needs_probe(kk)
                                 for kk in batch_ks):
                            # Levels that merely ran out of slice are not
                            # refutations. Climbing past them would abandon
                            # untested ground AND move away from the good k.
                            continue
                        else:
                            k = max(batch_ks)
                            st = batch[k][0]
                else:
                    while st != "FEASIBLE" and k < k_max:
                        if _should_stop():
                            truncated = True
                            break
                        k += 4
                        st, _ = level(k)
                if st != "FEASIBLE" and not _should_stop():
                    found = _boundary_search(k)
                    if found is not None:
                        k, st = found, "FEASIBLE"
                if st != "FEASIBLE":
                    return {"verdict": "FAMILY_TOO_WEAK", "walk_complete": not truncated,
                            "deadline_hit": _should_stop(), "results": results,
                            "boundary_descent": boundary_info["probed"],
                            "profile": profile.as_dict(self.workers),
                            "filler_failures": summarise_fillers(filler_stats),
                            "level_coverage": level_coverage,
                            "undersampled_levels": sum(
                                1 for r in results.values() if r[0] == "UNDERSAMPLED")}

            lo_feasible = k
            if self.concurrent_levels > 1:
                while True:
                    if _should_stop():
                        truncated = True
                        break
                    batch_ks = [kk for kk in
                               (lo_feasible - 4 * i for i in range(1, self.concurrent_levels + 1))
                               if kk >= 1]
                    if not batch_ks:
                        break
                    batch = levels(batch_ks)
                    feasible_ks = [kk for kk in batch_ks if batch[kk][0] == "FEASIBLE"]
                    if len(feasible_ks) == len(batch_ks):
                        lo_feasible = min(batch_ks)
                    elif any(batch[kk][0] == "UNDERSAMPLED" and _needs_probe(kk)
                             for kk in batch_ks):
                        # Do not end the descent on levels we never finished
                        # probing -- that is giving up with budget on the clock.
                        continue
                    elif feasible_ks:
                        lo_feasible = min(feasible_ks)
                        break
                    else:
                        break
            else:
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
            objective_info = None
            profile.event("walk_end")
            if best is not None and objective_reserve > 0:
                with profile.timed("finish_objective_polish"):
                    objective_info = self._apply_objective_polish(
                        sat_cands, best, on_improvement, polish_deadline, should_stop)
                if objective_info["after"] is not None and objective_info["after"] < best:
                    best = objective_info["after"]
            polish_info = None
            if best is not None and self.seed_polish > 0:
                with profile.timed("finish_seed_polish"):
                    polish_info = self._apply_seed_polish(best_holder, on_improvement,
                                                          should_stop=_stop_polish,
                                                          incumbent=latest["achieved"])
            exact_info = None
            if self.exact_finish and latest["layout"] is not None:
                with profile.timed("finish_exact"):
                    exact_info = self._apply_exact_finish(latest, on_improvement,
                                                          hard_deadline, should_stop)
            if latest["achieved"] is not None:
                best = latest["achieved"] if best is None else min(best, latest["achieved"])
            # UNDERSAMPLED counts as unknown: the level was not finished, so it
            # is no more a refutation than an undecided probe is.
            unknowns = sum(1 for r in results.values()
                           if r[0] in ("INCONCLUSIVE", "UNDERSAMPLED"))
            return {"verdict": "DONE",
                    "lowest_feasible_k_probed": hi if best is not None else None,
                    "best_achieved": best, "inconclusive_levels": unknowns,
                    "walk_complete": not truncated, "deadline_hit": _should_stop(),
                    "seed_polish": polish_info,
                    "boundary_descent": boundary_info["probed"],
                    "profile": profile.as_dict(self.workers),
                    "objective_polish": objective_info,
                    "exact_finish": exact_info,
                    "filler_failures": summarise_fillers(filler_stats),
                    "level_coverage": level_coverage,
                    "undersampled_levels": sum(
                        1 for r in results.values() if r[0] == "UNDERSAMPLED"),
                    "results": results}
        finally:
            if corpus is not None:
                corpus.close()
            if pool is not None:
                pool.close()
                pool.join()
