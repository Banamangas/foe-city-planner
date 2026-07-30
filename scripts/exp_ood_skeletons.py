"""Out-of-distribution check: does `mean_free_adjacency` still predict `achieved`
on skeletons that are NOT comb and NOT lane?

Why this exists. `mean_free_adjacency` predicts the final road count at Spearman
+0.76 / +0.64 (tasks/lessons.md 2026-07-30) -- but every skeleton in both of
those datasets came from `generate_patterns` (comb) or `generate_lane_patterns`
(lane). So the measured claim is only "among combs and lanes, tighter is
better". Any RL/GFlowNet at Track F step 5 exists precisely to generate
topologies those two hand-written generators cannot, and would optimise this
statistic on shapes it has never been tested on -- the same trap that made
Track C-bis's 0.999-AUC classifier deliver zero end-to-end benefit.

Design.
  * Three OOD generators (below), none of which is a trunk-plus-perpendicular-
    branches template.
  * **Novelty is proven, not asserted**: every candidate is set-differenced
    against the FULL comb and lane populations at its own k. A generator that
    only reproduces existing patterns is a sampling filter, not a treatment
    (the `max_lane_len` lesson, tasks/lessons.md 2026-07-22).
  * Candidates pass the same sound `prefilter()` and the same `opts_total`
    ranking used in production, then the same `probe()`/`validate()` pipeline
    (reused verbatim from exp_wide_skeleton_screen, so legality checking and
    the rotated-buildings guard are identical).

Pre-committed verdict (decide before looking):
  TRANSFERS      rho >= 0.4 on OOD SATs  -> the surrogate is safe for step 5
  DEGRADED       0.0 <= rho < 0.4        -> weak; step 5 needs a new signal
  INVERTED       rho < 0.0               -> actively misleading off-distribution
  NO_VERDICT     fewer than 12 OOD SATs  -> underpowered, do not read anything in

  uv run --with ortools python scripts/exp_ood_skeletons.py darkzig.json \
      --k 105,106 --pool 20000 --probe 60 --budget 300 --workers 12
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import pathlib
import random
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from foeopt.loader import load_layout
from foeopt.model import Footprint
from foeopt.roads_first import (Pattern, _check_pattern, generate_lane_patterns,
                                generate_patterns, prefilter)
from foeopt.skeleton_score import SkeletonScorer, mean_free_adjacency

ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


# --------------------------------------------------------------------------
# OOD generators. Each returns a set of exactly k cells, inside the region,
# disjoint from the TH, forming ONE connected component that touches the TH
# border (strictly stronger than _check_pattern's forest-of-TH-touching-
# components rule, so anything produced here is always a legal skeleton).
# --------------------------------------------------------------------------

def _seeds(region, th):
    return [c for c in th.border_cells() if c in region]


def gen_random_walk(region, th, k, rng, *, p_straight):
    """Wandering corridors. Grows from a random existing road cell, continuing
    in the same direction with probability p_straight. p_straight ~ 0.95 gives
    long meandering snakes with turns at random places; ~0.3 gives dense
    organic blobs. Neither has a trunk, so neither is expressible as a comb or
    a lane."""
    th_cells = th.cells()
    starts = _seeds(region, th)
    if not starts:
        return None
    cur = rng.choice(starts)
    roads = {cur}
    last = rng.choice(ORTHO)
    stall = 0
    while len(roads) < k and stall < k * 40:
        if rng.random() < p_straight:
            d = last
        else:
            d = rng.choice(ORTHO)
        nxt = (cur[0] + d[0], cur[1] + d[1])
        if nxt in region and nxt not in th_cells and nxt not in roads:
            roads.add(nxt)
            cur, last = nxt, d
            stall = 0
        else:
            cur = rng.choice(tuple(roads))       # jump to another growth point
            last = rng.choice(ORTHO)
            stall += 1
    return roads if len(roads) == k else None


def gen_scatter_tree(region, th, k, rng, *, n_targets):
    """Steiner-ish: pick scattered target cells across the region and connect
    each to the growing network by an L-shaped path. Produces multi-junction
    networks with no dominant trunk axis."""
    th_cells = th.cells()
    starts = _seeds(region, th)
    if not starts:
        return None
    roads = {rng.choice(starts)}
    cells = sorted(region - th_cells)
    for _ in range(n_targets):
        if len(roads) >= k:
            break
        target = rng.choice(cells)
        anchor = min(roads, key=lambda c: abs(c[0] - target[0]) + abs(c[1] - target[1]))
        x, y = anchor
        tx, ty = target
        path = []
        step = 1 if tx >= x else -1
        for xx in range(x, tx + step, step):
            path.append((xx, y))
        step = 1 if ty >= y else -1
        for yy in range(y, ty + step, step):
            path.append((tx, yy))
        for c in path:
            if len(roads) >= k:
                break
            if c in region and c not in th_cells:
                roads.add(c)
            else:
                break                              # path left the region: stop here
    if len(roads) != k:
        return None
    return roads


def gen_perturbed_lane(region, th_unused, k, rng, *, base_pool, n_moves):
    """Take a real lane skeleton and relocate n_moves of its cells to random
    free positions adjacent to the remainder. A graded distance from the
    training distribution -- the dose-response arm: if the predictor degrades
    smoothly with n_moves, that tells us how far off-distribution it survives.
    """
    base = rng.choice(base_pool)
    th = base.th
    th_cells = th.cells()
    roads = set(base.roads)
    border = set(th.border_cells())
    for _ in range(n_moves):
        # Only LEAF cells may be removed: deleting a degree-<=1 cell cannot
        # disconnect the rest, whereas deleting an interior lane cell splits the
        # skeleton in two (which is why the first version of this generator
        # produced zero valid candidates). Never strip the last TH-border cell.
        movable = []
        for c in roads:
            deg = sum(1 for d in ORTHO if (c[0] + d[0], c[1] + d[1]) in roads)
            if deg <= 1 and not (c in border and
                                 sum(1 for r in roads if r in border) <= 1):
                movable.append(c)
        if not movable:
            break
        roads.discard(rng.choice(sorted(movable)))
        cands = set()
        for c in roads:
            for d in ORTHO:
                n = (c[0] + d[0], c[1] + d[1])
                if n in region and n not in th_cells and n not in roads:
                    cands.add(n)
        if not cands:
            return None, None
        roads.add(rng.choice(sorted(cands)))
    return (roads, th) if len(roads) == k else (None, None)


def gen_tunable(region, th, k, rng, *, n_comp, bias):
    """Corrected OOD generator: spans the predictor's real operating range.

    v1's generators all landed at mean_free_adjacency ~2.00 and so could not
    exercise the statistic at all. The arithmetic says why, and says how to fix
    it. For a k-cell skeleton with c components and `losses` adjacencies spent
    on the region boundary / TH:

        mean_free_adjacency = 2 + (2c - losses) / k

    So at k=105 the in-distribution range 1.94-2.03 is reached by
      * mfa ~1.94  ->  c=1 and losses ~8   (touch the boundary/TH ~8 times)
      * mfa ~2.00  ->  c=1 and losses ~2   (v1 lived here, by accident)
      * mfa ~2.03  ->  c=2-3 and losses ~1-3

    `n_comp` sets c directly (each component is seeded from its own TH-border
    cell, so every one satisfies _check_pattern's reachability rule -- this is
    exactly the shape comb/lane stubs already take). `hug_bias` is the
    probability of extending into the candidate cell with the FEWEST free
    neighbours, which both raises `losses` (boundary/TH contact) and creates
    cycles (each cycle costs 2 more free adjacencies) -- the two ways to push
    mfa down.
    """
    th_cells = th.cells()
    starts = sorted(_seeds(region, th))
    if len(starts) < n_comp:
        return None
    # spread the component seeds apart so they don't immediately merge
    picked = [rng.choice(starts)]
    while len(picked) < n_comp:
        far = max(starts, key=lambda c: min(abs(c[0] - p[0]) + abs(c[1] - p[1])
                                            for p in picked))
        if far in picked:
            break
        picked.append(far)
    if len(picked) < n_comp:
        return None
    roads = set(picked)
    stall = 0
    while len(roads) < k and stall < k * 30:
        # TREE growth only: a candidate may touch the skeleton exactly once.
        # Admitting a cell with 2+ road neighbours closes a cycle, and each
        # cycle costs 2 free adjacencies (mfa -= 2/k). Unrestricted "grow into
        # any adjacent cell" is Eden growth, which builds compact cycle-riddled
        # blobs and lands at mfa 0.2-1.2 -- an order of magnitude off the target
        # band. The pre-flight caught exactly that.
        cands = []
        for (x, y) in roads:
            for dx, dy in ORTHO:
                n = (x + dx, y + dy)
                if n in region and n not in th_cells and n not in roads:
                    touch = sum(1 for ex, ey in ORTHO if (n[0] + ex, n[1] + ey) in roads)
                    if touch == 1:
                        cands.append(n)
        if not cands:
            break
        cands = sorted(set(cands))
        if rng.random() < abs(bias):
            def onward(c):
                return sum(1 for dx, dy in ORTHO
                           if (c[0] + dx, c[1] + dy) in region
                           and (c[0] + dx, c[1] + dy) not in th_cells
                           and (c[0] + dx, c[1] + dy) not in roads)
            # bias > 0 AVOIDS the boundary (prefer cells with the most onward
            # free neighbours) -> fewer `losses` -> mfa UP toward 2 + 2c/k.
            # bias < 0 hugs it -> more losses -> mfa DOWN.
            # The sign here was originally backwards: measured, random trees in
            # this region already spend ~15 adjacencies on the boundary/TH while
            # comb/lane spend only ~8, so reaching the in-distribution band needs
            # LESS boundary contact than random growth gives, not more.
            want = max if bias > 0 else min
            target = want(onward(c) for c in cands)
            cands = [c for c in cands if onward(c) == target]
        roads.add(rng.choice(cands))
        stall += 1
    return roads if len(roads) == k else None


def components_touching_th(region, th, roads):
    """Every component must contain a TH-border cell -- _check_pattern's actual
    rule (comb/lane stubs are themselves separate TH-touching components), which
    v1 needlessly tightened to a single component and thereby pinned mfa."""
    if not roads:
        return False
    border = set(th.border_cells())
    remaining = set(roads)
    while remaining:
        start = next(iter(remaining))
        seen = {start}
        stack = [start]
        while stack:
            cx, cy = stack.pop()
            for dx, dy in ORTHO:
                n = (cx + dx, cy + dy)
                if n in remaining and n not in seen:
                    seen.add(n)
                    stack.append(n)
        if not (seen & border):
            return False
        remaining -= seen
    return True


def one_component_touching_th(region, th, roads):
    """Single connected component containing a TH-border cell."""
    if not roads:
        return False
    seeds = [c for c in roads if c in th.border_cells()]
    if not seeds:
        return False
    seen = {seeds[0]}
    stack = [seeds[0]]
    while stack:
        cx, cy = stack.pop()
        for dx, dy in ORTHO:
            n = (cx + dx, cy + dy)
            if n in roads and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen == set(roads)


def build_candidates(region, th_fp, k, rng, pool, base_pool, mode='v2'):
    """Returns [(family, Pattern)] of legal, distinct OOD candidates."""
    out = []
    seen = set()
    if mode == "v1":
        specs = [
            ("walk-straight", lambda: (gen_random_walk(region, th_fp, k, rng, p_straight=0.93), th_fp)),
            ("walk-organic", lambda: (gen_random_walk(region, th_fp, k, rng, p_straight=0.35), th_fp)),
            ("scatter-8", lambda: (gen_scatter_tree(region, th_fp, k, rng, n_targets=8), th_fp)),
            ("scatter-16", lambda: (gen_scatter_tree(region, th_fp, k, rng, n_targets=16), th_fp)),
            ("perturb-25", lambda: gen_perturbed_lane(region, None, k, rng, base_pool=base_pool, n_moves=25)),
            ("perturb-50", lambda: gen_perturbed_lane(region, None, k, rng, base_pool=base_pool, n_moves=50)),
        ]
        accept = one_component_touching_th
    else:
        # sweep the two knobs that move mean_free_adjacency, per the arithmetic
        # in gen_tunable: component count lifts it, boundary/TH hugging (and the
        # cycles hugging creates) pushes it down.
        specs = []
        for c in (1, 2, 3):
            for b in (-0.6, 0.0, 0.6, 0.9, 1.0):
                specs.append((f"c{c}-b{b:+.1f}",
                              (lambda c=c, b=b: (gen_tunable(region, th_fp, k, rng,
                                                             n_comp=c, bias=b), th_fp))))
        accept = components_touching_th
    per = max(1, pool // len(specs))
    for family, fn in specs:
        made = 0
        for _ in range(per * 8):
            if made >= per:
                break
            roads, th = fn()
            if not roads or len(roads) != k or th is None:
                continue
            if not accept(region, th, roads):
                continue
            key = frozenset(roads)
            if key in seen:
                continue
            seen.add(key)
            pat = Pattern(th=th, roads=key,
                          params={"th": (th.x, th.y), "family": family, "k": k})
            try:
                _check_pattern(pat, region, k)
            except AssertionError:
                continue
            out.append((family, pat))
            made += 1
    return out


def straightness(roads):
    """Fraction of road cells with exactly 2 neighbours that are collinear --
    high for trunk/teeth templates, lower for wandering corridors. Reported as
    a structural descriptor, not as the novelty proof."""
    roads = set(roads)
    coll = tot = 0
    for (x, y) in roads:
        nb = [(dx, dy) for dx, dy in ORTHO if (x + dx, y + dy) in roads]
        if len(nb) == 2:
            tot += 1
            if nb[0][0] == -nb[1][0] and nb[0][1] == -nb[1][1]:
                coll += 1
    return coll / tot if tot else 0.0


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2.0
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy) ** 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--k", default="105,106")
    ap.add_argument("--pool", type=int, default=18000, help="OOD candidates generated per k")
    ap.add_argument("--probe", type=int, default=60, help="candidates probed per k")
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", choices=("v1", "v2"), default="v2",
                   help="v1 = the original (range-restricted) generators; "
                        "v2 = the corrected component/hug sweep")
    ap.add_argument("--out", default="output/trackf/ood.jsonl")
    args = ap.parse_args()

    from exp_wide_skeleton_screen import _init_worker, _screen_one, append_row, persist_sat

    layout = load_layout(args.city)
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th_fp = layout.townhall.footprint
    scorer = SkeletonScorer(region, consumers)
    ks = [int(x) for x in args.k.split(",")]
    rng = random.Random(args.seed)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sat_dir = out_path.parent / (out_path.stem + "-sats")

    payloads, meta = [], {}
    for k in ks:
        print(f"--- k={k} ---", flush=True)
        comb = generate_patterns(region, th_fp.width, th_fp.length, k,
                                 random.Random(0), 10 ** 9, th_mode="full")
        lane = generate_lane_patterns(region, th_fp.width, th_fp.length, k,
                                      random.Random(0), 10 ** 9, th_mode="full")
        lane_wide = generate_lane_patterns(region, th_fp.width, th_fp.length, k,
                                           random.Random(0), 10 ** 9, th_mode="full",
                                           pitches=tuple(range(12, 19)))
        known = {p.roads for p in comb} | {p.roads for p in lane} | {p.roads for p in lane_wide}
        print(f"  known comb+lane population: {len(known)}", flush=True)

        cands = build_candidates(region, th_fp, k, rng, args.pool, lane_wide, args.mode)
        novel = [(f, p) for f, p in cands if p.roads not in known]
        print(f"  generated {len(cands)} legal OOD candidates, "
              f"{len(novel)} NOVEL ({len(cands)-len(novel)} collided with comb/lane)",
              flush=True)
        if len(cands) and len(novel) / len(cands) < 0.99:
            print("  WARNING: generator overlaps the known population", flush=True)

        alive = [(f, p) for f, p in novel if prefilter(p, region, consumers) is None]
        print(f"  {len(alive)} survive the sound prefilter", flush=True)
        if not alive:
            continue
        # Rank by opts_total WITHIN each family and take an equal share, rather
        # than taking the global top. A global top-N would likely come from one
        # or two families and collapse the mean_free_adjacency range (families
        # span 1.02 to 1.98) -- and range restriction attenuates rank
        # correlation, which would depress the very number this test reads.
        fams = sorted({f for f, _ in alive})
        share = max(1, args.probe // len(fams))
        take = []
        for fam in fams:
            sub = sorted((fp for fp in alive if fp[0] == fam),
                         key=lambda fp: -scorer.opts_total(fp[1].th, fp[1].roads))
            take.extend(sub[:share])
        by_fam = collections.Counter(f for f, _ in take)
        print(f"  probing {len(take)}: {dict(by_fam)}", flush=True)
        for idx, (fam, pat) in enumerate(take):
            payloads.append((k, idx, pat))
            meta[(k, idx)] = {
                "family": fam,
                "mean_free_adjacency": round(mean_free_adjacency(region, pat.th, pat.roads), 5),
                "opts_total": scorer.opts_total(pat.th, pat.roads),
                "straightness": round(straightness(pat.roads), 4),
            }

    if not payloads:
        print("no candidates to probe")
        return 1

    # structural comparison against the in-distribution families
    for name, gen, kw in (("comb", generate_patterns, {}),
                          ("lane", generate_lane_patterns, {}),
                          ("lane12-18", generate_lane_patterns, {"pitches": tuple(range(12, 19))})):
        ref = gen(region, th_fp.width, th_fp.length, ks[0], random.Random(0), 400,
                  th_mode="full", **kw)
        print(f"structural: {name:10s} straightness "
              f"{statistics.mean(straightness(p.roads) for p in ref):.3f}  "
              f"mfa {statistics.mean(mean_free_adjacency(region, p.th, p.roads) for p in ref):.3f}")
    print(f"structural: {'OOD':10s} straightness "
          f"{statistics.mean(m['straightness'] for m in meta.values()):.3f}  "
          f"mfa {statistics.mean(m['mean_free_adjacency'] for m in meta.values()):.3f}")

    print(f"\ndispatching {len(payloads)} OOD probes on {args.workers} workers "
          f"at {args.budget:.0f}s", flush=True)
    rows = []
    t0 = time.monotonic()
    with out_path.open("a") as fh:
        with mp.Pool(args.workers, initializer=_init_worker,
                     initargs=(layout, args.budget)) as pool:
            for i, (row, art) in enumerate(pool.imap_unordered(_screen_one, payloads), 1):
                row.update(meta[(row["k"], row["idx"])])
                append_row(fh, row)
                rows.append(row)
                if art is not None:
                    persist_sat(sat_dir, art)
                    print(f"  SAT k={row['k']} idx={row['idx']} fam={row['family']} "
                          f"achieved={row['achieved']} legal={row['legal']}", flush=True)
                if i % 25 == 0:
                    print(f"  [{i}/{len(payloads)}] "
                          f"{i/((time.monotonic()-t0)/60):.1f}/min", flush=True)

    sats = [r for r in rows if r["status"] == "SAT" and r.get("legal")
            and r.get("achieved") is not None]
    st = collections.Counter(r["status"] for r in rows)
    print(f"\n=== OOD RESULT ===\nprobes {len(rows)}  {dict(st)}  legal SATs {len(sats)}")
    res = {"n_probes": len(rows), "status": dict(st), "n_sat": len(sats)}
    if len(sats) < 12:
        verdict = "NO_VERDICT"
        print(f"only {len(sats)} legal OOD SATs -- underpowered, no verdict")
    else:
        rho = spearman([r["mean_free_adjacency"] for r in sats],
                       [r["achieved"] for r in sats])
        res["rho_mean_free_adjacency"] = rho
        res["rho_opts_total"] = spearman([r["opts_total"] for r in sats],
                                         [r["achieved"] for r in sats])
        ach = sorted(r["achieved"] for r in sats)
        res["achieved"] = {"min": ach[0], "median": statistics.median(ach), "max": ach[-1]}
        print(f"achieved: min {ach[0]} median {statistics.median(ach)} max {ach[-1]}")
        print(f"rho(mean_free_adjacency, achieved) on OOD = {rho:+.3f}"
              f"   [in-distribution: +0.76 / +0.64]")
        print(f"rho(opts_total, achieved) on OOD        = {res['rho_opts_total']:+.3f}"
              f"   [in-distribution: +0.50]")
        # Range-restriction guard. rho is a rank statistic: if the predictor is
        # near-constant across the sample, rho is noise around 0 no matter
        # whether the predictor works, and reading DEGRADED/INVERTED off it is a
        # mechanical call on nothing (the 2026-07-22 knife-edge-verdict lesson).
        # mean_free_adjacency is pinned to ~2 + (2-losses)/k for connected trees,
        # so this is the expected failure of a naive OOD generator, not an edge
        # case -- it must be detected, never silently labelled.
        mfas = [r["mean_free_adjacency"] for r in sats]
        distinct = len(set(mfas))
        width = max(mfas) - min(mfas)
        res["mfa_distinct"] = distinct
        res["mfa_width"] = round(width, 5)
        IN_DIST_WIDTH = 0.0660        # baseline SATs span 1.9434-2.0094
        if distinct < 8 or width < 0.4 * IN_DIST_WIDTH:
            verdict = "NO_VERDICT_RANGE_RESTRICTED"
            print(f"\n!! predictor is near-constant on this sample: {distinct} distinct "
                  f"mean_free_adjacency values spanning {width:.4f} "
                  f"(in-distribution span {IN_DIST_WIDTH:.4f}).")
            print("   rho over a degenerate axis cannot distinguish 'the predictor "
                  "fails off-distribution' from 'there was nothing to measure'.")
        else:
            verdict = ("TRANSFERS" if rho >= 0.4
                       else "INVERTED" if rho < 0.0
                       else "DEGRADED")
        for fam in sorted({r["family"] for r in sats}):
            f = [r for r in sats if r["family"] == fam]
            print(f"   {fam:16s} n={len(f):3d} min={min(r['achieved'] for r in f)} "
                  f"median={statistics.median([r['achieved'] for r in f]):.1f}")
    res["verdict"] = verdict
    print(f"\nVERDICT: {verdict}")
    p = out_path.with_suffix(".summary.json")
    p.write_text(json.dumps(res, indent=2))
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
