"""Seed-polish the non-uniform screen's sub-100 frontier (Track F test 1, stage 2).

`probe()` has no objective, so a skeleton's `achieved` is whichever satisfying
placement CP-SAT happens to land on. Re-solving a FIXED skeleton across seeds is
worth up to ~10 roads (tasks/lessons.md 2026-07-23), and it is how today's record
actually happened: the wide screen found a 99 and the polish pass took it to 95.

So the screen's best (97) does NOT settle test 1 on its own -- the frontier has
to go through the same pass before `SATURATED` could be believed.

Rebuilds the frontier patterns by (k, idx) from the same seeded generator stream
as the screen, guarding on the recorded `th` exactly like run_recheck does, then
calls `foeopt.seed_search.seed_minimize_roads` on each.

  uv run --with ortools python scripts/exp_nonuniform_polish.py darkzig.json \
      --rows output/trackf/nonuniform.jsonl --threshold 100 --seeds 16 --workers 12
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from exp_nonuniform_lanes import select_take
from foeopt.loader import load_layout
from foeopt.roads_first import (generate_lane_patterns, generate_patterns,
                                prefilter, th_anchor_candidates)
from foeopt.skeleton_score import SkeletonScorer
from foeopt.validate import canonical_dims, rotated_buildings

_W: dict = {}


def _init(layout, probe_limit):
    _W["layout"] = layout
    _W["probe_limit"] = probe_limit


def _one(payload):
    """One (pattern, seed) solve. Never raises -- a single bad solve must not
    kill the pass."""
    k, idx, pat, seed = payload
    from foeopt.roads_first import probe, validate
    layout = _W["layout"]
    try:
        st, pos = probe(pat, set(layout.region.cells), layout.road_needing(),
                        probe_limit=_W["probe_limit"], probe_workers=1,
                        solver_overrides={"random_seed": seed})
        if st != "SAT":
            return {"k": k, "idx": idx, "seed": seed, "achieved": None}
        vst, vlay, achieved = validate(layout, pat, pos)
        if vst != "OK" or rotated_buildings(vlay, canonical_dims(layout)):
            return {"k": k, "idx": idx, "seed": seed, "achieved": None}
        art = {
            "k": k, "idx": idx, "achieved": achieved, "solver_seed": seed,
            "th": [pat.th.x, pat.th.y, pat.th.width, pat.th.length],
            "pattern_roads": sorted([x, y] for (x, y) in pat.roads),
            "roads": sorted([x, y] for (x, y) in vlay.roads),
            "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                             b.footprint.width, b.footprint.length]
                          for b in vlay.buildings},
        }
        return {"k": k, "idx": idx, "seed": seed, "achieved": achieved, "art": art}
    except Exception as exc:                      # noqa: BLE001
        return {"k": k, "idx": idx, "seed": seed, "achieved": None,
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--rows", default="output/trackf/nonuniform.jsonl")
    ap.add_argument("--threshold", type=int, default=100)
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--pool", type=int, default=12000)
    ap.add_argument("--gen-seed", type=int, default=0)
    ap.add_argument("--probe", type=int, default=120)
    ap.add_argument("--skews", default=None)
    ap.add_argument("--opts-top", type=float, default=0.10)
    ap.add_argument("--quality-top", type=float, default=None)
    ap.add_argument("--sat-dir", default="output/trackf/nonuniform-polish-sats")
    args = ap.parse_args()

    layout = load_layout(args.city)
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th_fp = layout.townhall.footprint
    scorer = SkeletonScorer(region, consumers)
    th_anchors = th_anchor_candidates(region, th_fp.width, th_fp.length, mode="full")

    rows = [json.loads(l) for l in pathlib.Path(args.rows).read_text().splitlines() if l.strip()]
    targets = [r for r in rows if r["status"] == "SAT" and r.get("legal")
               and r.get("achieved") is not None and r["achieved"] <= args.threshold]
    if not targets:
        print(f"no SATs at <= {args.threshold}")
        return 1
    print(f"{len(targets)} targets at <= {args.threshold}: "
          f"{sorted(r['achieved'] for r in targets)}", flush=True)

    # rebuild the exact patterns from the same seeded stream the screen used
    rng = random.Random(args.gen_seed)
    th_anchors = th_anchor_candidates(region, th_fp.width, th_fp.length, mode="full")
    by_k: dict = collections.defaultdict(list)
    for r in targets:
        by_k[r["k"]].append(r)
    payloads = []
    skews = (tuple(float(x) for x in args.skews.split(",")) if args.skews
             else (0.0, 1.0, 2.0))
    for k in sorted({r["k"] for r in rows}):
        take = select_take(region, consumers, scorer, th_anchors, th_fp, k, rng,
                           pool=args.pool, probe=args.probe, skews=skews,
                           opts_top=args.opts_top, quality_top=args.quality_top)
        for r in by_k.get(k, []):
            pat = take[r["idx"]][1]
            if [pat.th.x, pat.th.y] != list(r["th"]):
                raise SystemExit(
                    f"identity mismatch k={k} idx={r['idx']}: regenerated th "
                    f"{[pat.th.x, pat.th.y]} != recorded {r['th']}. "
                    "--pool/--gen-seed/--skews/--quality-top must match the screen run.")
            for s_ in range(args.seeds):
                payloads.append((k, r["idx"], pat, s_))

    n_skeletons = sum(len(v) for v in by_k.values())
    print(f"polishing {n_skeletons} skeletons x {args.seeds} seeds = "
          f"{len(payloads)} solves on {args.workers} workers", flush=True)
    sat_dir = pathlib.Path(args.sat_dir)
    sat_dir.mkdir(parents=True, exist_ok=True)
    best: dict = {}
    best_art: dict = {}
    t0 = time.monotonic()
    with mp.Pool(args.workers, initializer=_init,
                 initargs=(layout, args.budget)) as pool:
        for i, res in enumerate(pool.imap_unordered(_one, payloads), 1):
            key = (res["k"], res["idx"])
            if res.get("achieved") is not None:
                if key not in best or res["achieved"] < best[key]:
                    best[key] = res["achieved"]
                    best_art[key] = res["art"]
                    print(f"  k={key[0]} idx={key[1]} seed={res['seed']} "
                          f"-> {res['achieved']}", flush=True)
            if i % 25 == 0:
                print(f"  [{i}/{len(payloads)}] "
                      f"{i/((time.monotonic()-t0)/60):.1f}/min", flush=True)

    orig = {(r["k"], r["idx"]): r["achieved"] for r in targets}
    improved = {k: v for k, v in best.items() if v < orig.get(k, 10 ** 9)}
    print("\n=== POLISH RESULT ===")
    for key in sorted(orig, key=lambda k: orig[k]):
        b = best.get(key)
        mark = "  IMPROVED" if b is not None and b < orig[key] else ""
        print(f"  k={key[0]} idx={key[1]:3d}  {orig[key]} -> {b}{mark}")
    overall = min(best.values()) if best else None
    print(f"\nimproved {len(improved)}/{len(orig)}; best after polish = {overall}")
    for key, art in best_art.items():
        if best[key] <= 97:
            p = sat_dir / f"polish-k{key[0]}-i{key[1]}-a{best[key]}.json"
            p.write_text(json.dumps(art))
            print(f"  persisted {p}")
    out = {"targets": len(orig), "improved": len(improved),
           "best_after_polish": overall,
           "per_skeleton": {f"{k[0]}:{k[1]}": {"before": orig[k], "after": best.get(k)}
                            for k in orig}}
    pathlib.Path(args.rows).with_suffix(".polish.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {pathlib.Path(args.rows).with_suffix('.polish.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
