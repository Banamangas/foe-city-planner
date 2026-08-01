"""Does the exact filler repair rescue the layouts a REAL search throws away?

Everything measured so far about exact_pack came from the user's own city --
the expert's free space, not a search-produced one. This runs it against the
actual production workload: FR16 skeletons that CP-SAT solves for every
road-needing building and that then die at SAT_FILLER_FAIL.

Each SAT pattern is validated three ways on identical input:
    greedy            -- the shipped best-fit packer (exact_repair=0)
    greedy + repair   -- exact_repair seconds of CP-SAT, hinted with greedy
and the repair's wall-clock cost is recorded, because the whole question is
whether it is worth its seconds inside a real time box.

Sampled at two k: the record k (tight, few SATs, expensive probes) and a looser
k (more road cells, so less free space and MORE filler pressure).
"""
import argparse
import json
import multiprocessing
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout
from foeopt.roads_first import _pattern_generator, prefilter, probe, validate
from foeopt.skeleton_score import SkeletonScorer

CITY = 'CityMap-Born-FR16-2026-07-07.json'


def _job(payload):
    (pat, k, city, probe_limit, repair_s) = payload
    layout = load_layout(city)
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers, probe_limit=probe_limit,
                    probe_workers=1)
    probe_s = time.monotonic() - t0
    if st != "SAT":
        return {"k": k, "status": st, "probe_s": round(probe_s, 1)}

    t1 = time.monotonic()
    g_stat, _, g_roads = validate(layout, pat, pos)
    greedy_s = time.monotonic() - t1

    out = {"k": k, "status": st, "probe_s": round(probe_s, 1),
           "greedy": g_stat, "greedy_s": round(greedy_s, 2), "roads": g_roads}
    if g_stat == "SAT_FILLER_FAIL":
        t2 = time.monotonic()
        r_stat, r_lay, r_roads = validate(layout, pat, pos,
                                          exact_repair=repair_s,
                                          exact_workers=4)
        out["repair"] = r_stat
        out["repair_s"] = round(time.monotonic() - t2, 2)
        out["repair_roads"] = r_roads
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--ks", default="84,88")
    p.add_argument("--patterns", type=int, default=40)
    p.add_argument("--probe-limit", type=float, default=300.0)
    p.add_argument("--repair", type=float, default=5.0)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--band", default="3,4",
                   help="quality_index band, as in BEST_PRESET; 'off' to disable")
    args = p.parse_args(argv)

    layout = load_layout(CITY)
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    fillers = [b for b in layout.buildings
               if not b.needs_road and not b.is_townhall]
    th = layout.townhall.footprint
    scorer = SkeletonScorer(region, consumers)
    gen = _pattern_generator("nonuniform")
    rng = random.Random(args.seed)

    payloads = []
    for k in [int(x) for x in args.ks.split(",")]:
        kw = {"th_mode": "full"}
        if args.band != "off":
            lo, hi = (int(v) for v in args.band.split(","))
            kw["quality_index_band"] = (lo, hi)
        pats = gen(region, th.width, th.length, k, rng, args.patterns * 80, **kw)
        # prefilter, then rank by opts_total -- dropping this ranking is what
        # produced 3 SAT in 48 probes the last time (tasks/lessons.md).
        alive = [pt for pt in pats
                 if prefilter(pt, region, consumers, fillers) is None]
        alive.sort(key=lambda pt: -scorer.opts_total(pt.th, pt.roads))
        for pt in alive[:args.patterns]:
            payloads.append((pt, k, CITY, args.probe_limit, args.repair))
        print(f"k={k}: {len(pats)} generated, {len(alive)} survive prefilter, "
              f"{min(len(alive), args.patterns)} probed", flush=True)

    t0 = time.monotonic()
    rows = []
    with multiprocessing.Pool(args.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(_job, payloads), 1):
            rows.append(r)
            print(f"[{i}/{len(payloads)}] {json.dumps(r)}", flush=True)

    print(f"\n=== {len(rows)} probes in {time.monotonic()-t0:.0f}s ===", flush=True)
    for k in sorted({r["k"] for r in rows}):
        sub = [r for r in rows if r["k"] == k]
        sats = [r for r in sub if r["status"] == "SAT"]
        ok = [r for r in sats if r["greedy"] == "OK"]
        fails = [r for r in sats if r["greedy"] == "SAT_FILLER_FAIL"]
        rescued = [r for r in fails if r.get("repair") == "OK"]
        print(f"\nk={k}: {len(sub)} probes -> {len(sats)} SAT "
              f"({len(ok)} OK, {len(fails)} SAT_FILLER_FAIL, "
              f"{len(sub)-len(sats)} not SAT)")
        if fails:
            cost = [r["repair_s"] for r in fails]
            print(f"  RESCUED BY EXACT REPAIR: {len(rescued)}/{len(fails)}")
            print(f"  repair cost: min {min(cost):.2f}s  max {max(cost):.2f}s  "
                  f"mean {sum(cost)/len(cost):.2f}s")
            if rescued:
                print(f"  rescued road counts: "
                      f"{sorted(r['repair_roads'] for r in rescued)}")
            print(f"  best road count among greedy-OK: "
                  f"{min((r['roads'] for r in ok), default=None)}")
    pathlib.Path("scripts/_fr16_repair_rows.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
