"""Track F test 1: is there headroom INSIDE the trunk-and-branch grammar?

`generate_lane_patterns` forces two things that nothing justifies:
  * **uniform pitch** -- every branch seed is the same distance apart;
  * **round-robin balanced growth** -- fronts grow in lockstep, so branches come
    out equal length (this is why `max_lane_len` could only ever filter, never
    create a shape: tasks/lessons.md 2026-07-22).

The expert 142-road city is not uniform, and the record-holding skeletons sit at
the boundary of every hardcoded range we have checked so far. So: sample
skeletons with **irregular seed gaps and unequal branch lengths**, keep the
trunk-and-branch topology that survives CP-SAT, and see whether anything beats
the standing record of 95.

Decision value (tasks/rl-situation-report.md, Track F step 5):
  * something beats 95  -> the grammar has headroom, and since the per-branch
    space is ~10^19 (not enumerable) a guided search has a real target.
  * nothing beats 95    -> the family is saturated; RL has nothing left to
    search inside it, and (with the OOD result) nothing better outside it.

PRE-FLIGHT GATES, all measured before any solver time -- both of today's failed
OOD generators would have been caught by these:
  1. NOVELTY   -- set-differenced against the full comb + lane + lane12-18
     populations at each k. A generator that only reproduces existing patterns is
     a sampling filter, not a treatment.
  2. FEASIBILITY PROXY -- `opts_total` must reach the band every feasible
     skeleton ever recorded occupies (12,094-13,682). The v2 OOD generator hit
     its mfa target while collapsing opts_total to ~4,000 and returned 0 SAT/240;
     this gate is exactly that lesson.
  3. SPREAD    -- coverage and mean distance-to-road comparable to comb/lane
     (0.066-0.076 and 11-15), since spatial coverage is the binding constraint.

  uv run python scripts/exp_nonuniform_lanes.py darkzig.json --preflight
  uv run --with ortools python scripts/exp_nonuniform_lanes.py darkzig.json \
      --k 105,106 --pool 12000 --probe 120 --budget 300 --workers 12
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
from foeopt.roads_first import (Pattern, _check_pattern, _stub_cells,
                                _th_anchor_cell, _trunk, generate_lane_patterns,
                                generate_patterns, prefilter, th_anchor_candidates)
from foeopt.skeleton_score import SkeletonScorer, mean_free_adjacency

ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
FLOOR = 95           # darkzig record; override per city with --floor


def gen_nonuniform(region, th, k, rng, *, gap_lo, gap_hi, skew, both_prob,
                   use_stubs):
    """One skeleton with irregular seed gaps and unequal branch lengths.

    Same topology as the lane family -- a trunk off the TH with perpendicular
    branches -- but the two uniformity constraints are lifted:
      * seed gaps are drawn per-gap from [gap_lo, gap_hi] instead of a single
        global pitch;
      * the branch-length budget is split by Exponential(1)**skew weights
        instead of grown round-robin, so `skew` dials how unequal branches are
        (skew 0 = near-equal, 2 = a few long branches and many short ones).
    """
    th_cells = th.cells()
    for side in rng.sample(["top", "bottom", "left", "right"], 4):
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

        roads: set = set()
        stubs = _stub_cells(region, th, roads) if use_stubs else []
        budget = k - len(stubs)
        lo, hi = min(seed_idxs + [a]), max(seed_idxs + [a])
        trunk_used = trunk_raw[lo:hi + 1]
        if len(trunk_used) >= budget:
            continue
        roads |= set(trunk_used)
        remaining = budget - len(trunk_used)

        cand_dirs = [(0, -1), (0, 1)] if horiz else [(-1, 0), (1, 0)]
        fronts = []
        for i in seed_idxs:
            s = trunk_raw[i]
            if rng.random() < both_prob:
                fronts += [(s, d) for d in cand_dirs]
            else:
                fronts.append((s, rng.choice(cand_dirs)))
        if not fronts:
            continue

        # unequal split of the branch budget
        w = [rng.expovariate(1.0) ** skew + 1e-9 for _ in fronts]
        tot = sum(w)
        target = [max(1, int(remaining * x / tot)) for x in w]

        state = [(s, d, 1) for (s, d) in fronts]
        grown_len = [0] * len(fronts)
        # first pass: grow each front toward its own target
        for j, (s, d, _dist) in enumerate(state):
            dist = 1
            while grown_len[j] < target[j] and remaining > 0:
                c = (s[0] + d[0] * dist, s[1] + d[1] * dist)
                if c in region and c not in roads and c not in th_cells:
                    roads.add(c)
                    grown_len[j] += 1
                    remaining -= 1
                    dist += 1
                else:
                    break
            state[j] = (s, d, dist)
        # second pass: spend any leftover on whichever fronts can still grow
        progress = True
        while remaining > 0 and progress:
            progress = False
            for j, (s, d, dist) in enumerate(state):
                if remaining == 0:
                    break
                c = (s[0] + d[0] * dist, s[1] + d[1] * dist)
                if c in region and c not in roads and c not in th_cells:
                    roads.add(c)
                    state[j] = (s, d, dist + 1)
                    remaining -= 1
                    progress = True
        if remaining != 0:
            continue
        roads |= set(stubs)
        if len(roads) != k:
            continue
        return roads, {"side": side, "gaps": f"{gap_lo}-{gap_hi}", "skew": skew,
                       "both_prob": both_prob, "stubs": use_stubs,
                       "n_fronts": len(fronts), "trunk_len": len(trunk_used),
                       "branch_lens": sorted(grown_len, reverse=True)[:6]}
    return None, None


def build_pool(region, th_anchors, k, rng, pool):
    """[(family, Pattern)] over a sweep of the two lifted constraints."""
    specs = []
    for gaps in ((8, 14), (10, 18), (12, 22)):
        for skew in (0.0, 1.0, 2.0):
            specs.append((f"g{gaps[0]}-{gaps[1]}-s{skew:g}", gaps, skew))
    out, seen = [], set()
    per = max(1, pool // len(specs))
    for family, gaps, skew in specs:
        made = 0
        for _ in range(per * 30):
            if made >= per:
                break
            th = rng.choice(th_anchors)
            roads, params = gen_nonuniform(
                region, th, k, rng, gap_lo=gaps[0], gap_hi=gaps[1], skew=skew,
                both_prob=rng.choice([0.6, 0.85, 1.0]),
                use_stubs=rng.random() < 0.5)
            if not roads:
                continue
            key = frozenset(roads)
            if key in seen:
                continue
            seen.add(key)
            params.update({"th": (th.x, th.y), "k": k, "family": family})
            pat = Pattern(th=th, roads=key, params=params)
            try:
                _check_pattern(pat, region, k)
            except AssertionError:
                continue
            out.append((family, pat))
            made += 1
    return out


def spread_stats(region, roads, th):
    from collections import deque
    free = region - set(roads) - th.cells()
    touch = sum(1 for c in free
                if any((c[0] + d[0], c[1] + d[1]) in roads for d in ORTHO))
    dist = {c: 0 for c in roads}
    q = deque(roads)
    while q:
        c = q.popleft()
        for d in ORTHO:
            n = (c[0] + d[0], c[1] + d[1])
            if n in region and n not in dist:
                dist[n] = dist[c] + 1
                q.append(n)
    v = [dist[c] for c in free if c in dist]
    return touch / len(free), (statistics.mean(v) if v else 0), (max(v) if v else 0)


def preflight(layout, ks, pool, seed, opts_ref=None):
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th_fp = layout.townhall.footprint
    scorer = SkeletonScorer(region, consumers)
    rng = random.Random(seed)
    th_anchors = th_anchor_candidates(region, th_fp.width, th_fp.length, mode="full")
    ok = True
    for k in ks:
        print(f"\n--- k={k} ---")
        known = set()
        for gen, kw in ((generate_patterns, {}), (generate_lane_patterns, {}),
                        (generate_lane_patterns, {"pitches": tuple(range(12, 19))})):
            known |= {p.roads for p in gen(region, th_fp.width, th_fp.length, k,
                                           random.Random(0), 10 ** 9,
                                           th_mode="full", **kw)}
        cands = build_pool(region, th_anchors, k, rng, pool)
        novel = [(f, p) for f, p in cands if p.roads not in known]
        alive = [(f, p) for f, p in novel if prefilter(p, region, consumers) is None]
        print(f"  generated {len(cands)}; NOVEL {len(novel)}/{len(cands)} "
              f"(known population {len(known)}); prefilter-alive {len(alive)}")
        if not alive:
            ok = False
            continue
        # The gate exists to catch a generator that produces NOTHING new -- the
        # max_lane_len failure was 0 novel out of 67,308. A majority-novel pool
        # is unambiguously a treatment. (An earlier 0.95 threshold was calibrated
        # on darkzig's 98.9% and mis-flagged FR16's 93.9%, which is a smaller
        # city with fewer distinct skeletons and therefore more collisions.)
        if len(cands) and len(novel) / len(cands) < 0.50:
            print("  GATE 1 NOVELTY: FAIL -- generator largely reproduces comb/lane")
            ok = False
        else:
            print("  GATE 1 NOVELTY: PASS")

        opts = sorted(scorer.opts_total(p.th, p.roads) for _, p in alive)
        best = opts[-1]
        msg = (f"  opts_total: {opts[0]}-{best} (median {statistics.median(opts):.0f})")
        if opts_ref is not None:
            n_band = sum(1 for o in opts if o >= opts_ref)
            print(f"{msg}; {n_band} of {len(opts)} reach the city's feasible "
                  f"reference (>={opts_ref})")
            if best < 0.9 * opts_ref:
                print("  GATE 2 FEASIBILITY PROXY: FAIL -- pool falls short of the reference")
                ok = False
            else:
                print("  GATE 2 FEASIBILITY PROXY: PASS")
        else:
            # no known-feasible skeleton for this city -> report, do not gate.
            # opts_total is only interpretable against the same city's own
            # feasible layouts (it scales with consumer count and region size).
            print(f"{msg}; no reference for this city -- reporting only, no gate")

        top = sorted(alive, key=lambda fp: -scorer.opts_total(fp[1].th, fp[1].roads))[:40]
        cov, md, xd = zip(*(spread_stats(region, p.roads, p.th) for _, p in top))
        print(f"  spread (top-40 by opts_total): coverage {statistics.mean(cov):.3f} "
              f"mean-dist {statistics.mean(md):.1f} max-dist {statistics.mean(xd):.1f}"
              f"   [comb 0.066/14.9/37.4, lane12-18 0.076/11.3/38.2]")
        if statistics.mean(md) > 20:
            print("  GATE 3 SPREAD: FAIL -- skeleton does not reach across the region")
            ok = False
        else:
            print("  GATE 3 SPREAD: PASS")

        mfas = [mean_free_adjacency(region, p.th, p.roads) for _, p in alive]
        print(f"  mfa: {min(mfas):.4f}-{max(mfas):.4f} "
              f"(in-distribution 1.9434-2.0094) -- for test 3")
    print(f"\nPRE-FLIGHT: {'PASS -- worth solver time' if ok else 'FAIL -- do not probe'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--k", default="105,106")
    ap.add_argument("--pool", type=int, default=12000)
    ap.add_argument("--probe", type=int, default=120)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--floor", type=int, default=FLOOR,
                   help="record to beat for the HEADROOM/SATURATED verdict")
    ap.add_argument("--opts-ref", type=int, default=None,
                   help="this city's opts_total on a known-feasible skeleton; "
                        "gate 2 is skipped when absent (the value is city-relative)")
    ap.add_argument("--out", default="output/trackf/nonuniform.jsonl")
    args = ap.parse_args()

    layout = load_layout(args.city)
    ks = [int(x) for x in args.k.split(",")]
    if args.preflight:
        return preflight(layout, ks, min(args.pool, 3000), args.seed, args.opts_ref)

    from exp_wide_skeleton_screen import _init_worker, _screen_one, append_row, persist_sat

    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th_fp = layout.townhall.footprint
    scorer = SkeletonScorer(region, consumers)
    rng = random.Random(args.seed)
    th_anchors = th_anchor_candidates(region, th_fp.width, th_fp.length, mode="full")
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sat_dir = out_path.parent / (out_path.stem + "-sats")

    payloads, meta = [], {}
    for k in ks:
        known = set()
        for gen, kw in ((generate_patterns, {}), (generate_lane_patterns, {}),
                        (generate_lane_patterns, {"pitches": tuple(range(12, 19))})):
            known |= {p.roads for p in gen(region, th_fp.width, th_fp.length, k,
                                           random.Random(0), 10 ** 9,
                                           th_mode="full", **kw)}
        cands = build_pool(region, th_anchors, k, rng, args.pool)
        alive = [(f, p) for f, p in cands
                 if p.roads not in known and prefilter(p, region, consumers) is None]
        print(f"k={k}: {len(cands)} generated, {len(alive)} novel+alive", flush=True)
        fams = sorted({f for f, _ in alive})
        share = max(1, args.probe // max(1, len(fams)))
        take = []
        for fam in fams:
            sub = sorted((fp for fp in alive if fp[0] == fam),
                         key=lambda fp: -scorer.opts_total(fp[1].th, fp[1].roads))
            take.extend(sub[:share])
        print(f"  probing {len(take)}: {dict(collections.Counter(f for f, _ in take))}",
              flush=True)
        for idx, (fam, pat) in enumerate(take):
            payloads.append((k, idx, pat))
            meta[(k, idx)] = {
                "family": fam,
                "opts_total": scorer.opts_total(pat.th, pat.roads),
                "mean_free_adjacency": round(mean_free_adjacency(region, pat.th, pat.roads), 5),
                "branch_lens": pat.params.get("branch_lens"),
                "n_fronts": pat.params.get("n_fronts"),
            }

    if not payloads:
        print("nothing to probe")
        return 1
    print(f"\ndispatching {len(payloads)} probes on {args.workers} workers "
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
    print(f"\n=== NON-UNIFORM RESULT ===\nprobes {len(rows)} {dict(st)} legal SATs {len(sats)}")
    res = {"n_probes": len(rows), "status": dict(st), "n_sat": len(sats), "floor": args.floor}
    if sats:
        ach = sorted(r["achieved"] for r in sats)
        res["achieved"] = {"min": ach[0], "median": statistics.median(ach), "max": ach[-1]}
        print(f"achieved min {ach[0]} median {statistics.median(ach)} max {ach[-1]}")
        print(f"  <=95: {sum(1 for a in ach if a <= 95)}   <=102: {sum(1 for a in ach if a <= 102)}")
        print(f"  lowest 12: {ach[:12]}")
        for fam in sorted({r["family"] for r in sats}):
            f = [r for r in sats if r["family"] == fam]
            print(f"   {fam:14s} n={len(f):3d} min={min(r['achieved'] for r in f)}")
        res["verdict"] = ("HEADROOM" if ach[0] < args.floor
                          else "TIES_RECORD" if ach[0] == args.floor
                          else "SATURATED")
    else:
        res["verdict"] = "NO_SAT"
    print(f"\nVERDICT: {res['verdict']}  (floor {args.floor})")
    p = out_path.with_suffix(".summary.json")
    p.write_text(json.dumps(res, indent=2))
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
