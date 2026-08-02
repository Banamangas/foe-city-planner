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
          stub_priority: bool = False,
          solver_overrides: dict[str, object] | None = None,
          diag: dict | None = None) -> tuple[str, dict | None]:
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
    n_before = len(cand.buildings)
    unplaced = _place_fillers(grid, fillers, cand)
    if unplaced and exact_repair > 0:
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
        diag["fillers_total"] = len(fillers)
        diag["fillers_placed"] = len(fillers) - len(unplaced)
        diag["unplaced"] = sorted(b.name for b in unplaced)
        diag["repair_ran"] = bool(exact_repair > 0)
    if unplaced:
        return ("SAT_FILLER_FAIL", None, len(roads))
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
_WORKER_SOLVER_OVERRIDES: dict[str, object] | None = None
_WORKER_EXACT_REPAIR: float = 0.0


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int,
                 symmetry_breaking: bool = False, hints=None,
                 stub_priority: bool = False,
                 solver_overrides: dict[str, object] | None = None,
                 exact_repair: float = 0.0) -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    global _WORKER_SYMMETRY_BREAKING, _WORKER_HINTS, _WORKER_STUB_PRIORITY
    global _WORKER_SOLVER_OVERRIDES, _WORKER_EXACT_REPAIR
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    _WORKER_SYMMETRY_BREAKING = symmetry_breaking
    _WORKER_HINTS = hints
    _WORKER_STUB_PRIORITY = stub_priority
    _WORKER_SOLVER_OVERRIDES = solver_overrides
    _WORKER_EXACT_REPAIR = exact_repair


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
                   stub_priority=_WORKER_STUB_PRIORITY,
                   solver_overrides=_WORKER_SOLVER_OVERRIDES)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None,
                "pat_index": pat_index, "pos": None}
    # Clamped to one probe's own limit so a rescue can at worst DOUBLE the cost
    # of the probe that produced it. The repair is charged per rescued layout,
    # not once per run, so an unclamped value would let N filler failures add
    # N x exact_repair seconds to the box -- the same defect class as the
    # seed_polish overrun (tasks/lessons.md 2026-07-30).
    vdiag: dict = {}
    vstat, vlay, achieved = validate(
        layout, pat, pos,
        exact_repair=min(_WORKER_EXACT_REPAIR, _WORKER_PROBE_LIMIT),
        exact_workers=_WORKER_PROBE_WORKERS, diag=vdiag)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay,
                "pat_index": pat_index, "pos": pos}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None, "filler": vdiag,
            "pat_index": pat_index, "pos": pos}


def _run_probe_seq(payload: tuple) -> dict:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    global _WORKER_SYMMETRY_BREAKING, _WORKER_HINTS, _WORKER_STUB_PRIORITY
    global _WORKER_SOLVER_OVERRIDES, _WORKER_EXACT_REPAIR
    pat, k, layout, probe_limit, probe_workers, *rest = payload
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    _WORKER_SYMMETRY_BREAKING = rest[0] if rest else False
    _WORKER_HINTS = rest[1] if len(rest) > 1 else None
    _WORKER_STUB_PRIORITY = rest[2] if len(rest) > 2 else False
    _WORKER_SOLVER_OVERRIDES = rest[3] if len(rest) > 3 else None
    _WORKER_EXACT_REPAIR = rest[4] if len(rest) > 4 else 0.0
    try:
        return _run_probe((pat, k, 0))
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
                        coverage: dict | None = None) -> dict[int, tuple[str, int | None]]:
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
    th_mode = getattr(params, "th_anchors", "coarse")
    family = getattr(params, "pattern_family", "comb")
    gen_fn = _pattern_generator(family)

    state: dict[int, dict] = {}
    for k in ks:
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
        state[k] = {"pats": pats, "surviving": surviving, "best_achieved": None,
                    "saw_nonproof_failure": False, "order": 0}

    def handle_result(k, result, pat):
        st = state[k]
        st["order"] += 1
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
            if st["best_achieved"] is None or achieved < st["best_achieved"]:
                st["best_achieved"] = achieved
                if on_improvement is not None:
                    on_improvement(vlay, k, achieved)
                recorder = getattr(params, "best_recorder", None)
                if recorder is not None:
                    recorder(k, achieved, pat, vlay)
        elif status in ("UNKNOWN", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"):
            st["saw_nonproof_failure"] = True
        return time.monotonic() > params.deadline

    if pool is None:
        for i, k in enumerate(ks):
            interrupted = False
            for pat in state[k]["surviving"]:
                result = _run_probe_seq((pat, k, layout, params.probe_limit, params.probe_workers,
                                         getattr(params, "symmetry_breaking", False),
                                         getattr(params, "hints", None),
                                         getattr(params, "stub_priority", False),
                                         None,
                                         getattr(params, "exact_repair", 0.0)))
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
        payloads = [(pat, k, idx) for k in ks for idx, pat in enumerate(state[k]["surviving"])]
        for result in pool.imap_unordered(_run_probe, payloads):
            k = result["k"]
            idx = result["pat_index"]
            pat = state[k]["surviving"][idx]
            if handle_result(k, result, pat):
                pool.terminate()
                break

    _fill_coverage(state, ks, coverage)
    return {k: classify_level(state[k]) for k in ks}


def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None, corpus=None, scorer=None, score_threshold=None,
                 filler_stats=None, coverage=None) -> tuple[str, int | None]:
    return _probe_levels_batch(layout, region, consumers, [k], rng, params, log, pool=pool,
                               on_improvement=on_improvement, corpus=corpus,
                               scorer=scorer, score_threshold=score_threshold,
                               filler_stats=filler_stats, coverage=coverage)[k]


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
                 comb_modes: tuple[str, ...] | None = None):
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
        self.lane_cap = lane_cap
        self.lane_pitches = lane_pitches
        self.quality_index_band = quality_index_band
        self.concurrent_levels = concurrent_levels
        self.seed_polish = seed_polish
        self.exact_repair = exact_repair
        self.comb_modes = comb_modes

    def _apply_seed_polish(self, best_holder: dict, on_improvement,
                           should_stop=None) -> dict | None:
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
        baseline = best_holder.get("achieved")
        improved = (res.achieved is not None and baseline is not None
                    and res.achieved < baseline)
        if improved and on_improvement is not None:
            on_improvement(res.layout, best_holder.get("k"), res.achieved)
        return {"before": baseline, "after": res.achieved if improved else baseline,
                "improved": improved, "seed": res.seed if improved else None,
                "seeds_tried": res.n_tried, "n_legal": res.n_legal,
                "stopped_early": res.n_tried < self.seed_polish}

    def run(self, on_improvement=None, on_status=None, should_stop=None) -> dict:
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
        deadline = time.monotonic() + self.time_box
        walk_deadline = deadline - polish_reserve
        filler_stats = new_filler_stats()
        level_coverage: dict[int, dict] = {}

        pool = None
        if self.workers > 1:
            pool = multiprocessing.Pool(
                self.workers,
                initializer=_worker_init,
                initargs=(layout, self.probe_limit, self.probe_workers,
                         self.symmetry_breaking, self.hints, self.stub_priority,
                         None, self.exact_repair))

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
            comb_modes=self.comb_modes,
        )

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

        def _should_stop():
            """Walk phase: stops early enough to leave the polish reserve."""
            if should_stop is not None and should_stop():
                return True
            return time.monotonic() >= walk_deadline

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

        def level(k):
            if k not in results:
                results[k] = _probe_level(layout, region, consumers, k, rng,
                                          params, lambda r: None, pool=pool,
                                          on_improvement=on_improvement, corpus=corpus,
                                          scorer=self.scorer, score_threshold=self.score_threshold,
                                          filler_stats=filler_stats,
                                          coverage=level_coverage)
                if on_status is not None:
                    on_status(k, results[k][0], 0, 0)
            return results[k]

        def levels(ks):
            missing = [kk for kk in ks if kk not in results]
            if missing:
                batch = _probe_levels_batch(layout, region, consumers, missing, rng,
                                            params, lambda r: None, pool=pool,
                                            on_improvement=on_improvement, corpus=corpus,
                                            scorer=self.scorer, score_threshold=self.score_threshold,
                                            filler_stats=filler_stats,
                                            coverage=level_coverage)
                for kk, res in batch.items():
                    results[kk] = res
                    if on_status is not None:
                        on_status(kk, res[0], 0, 0)
            return {kk: results[kk] for kk in ks}

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
                if st != "FEASIBLE":
                    return {"verdict": "FAMILY_TOO_WEAK", "walk_complete": not truncated,
                            "deadline_hit": _should_stop(), "results": results,
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
            polish_info = None
            if best is not None and self.seed_polish > 0:
                polish_info = self._apply_seed_polish(best_holder, on_improvement,
                                                      should_stop=_stop_polish)
                if polish_info is not None and polish_info["improved"]:
                    best = polish_info["after"]
            # UNDERSAMPLED counts as unknown: the level was not finished, so it
            # is no more a refutation than an undecided probe is.
            unknowns = sum(1 for r in results.values()
                           if r[0] in ("INCONCLUSIVE", "UNDERSAMPLED"))
            return {"verdict": "DONE",
                    "lowest_feasible_k_probed": hi if best is not None else None,
                    "best_achieved": best, "inconclusive_levels": unknowns,
                    "walk_complete": not truncated, "deadline_hit": _should_stop(),
                    "seed_polish": polish_info,
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
