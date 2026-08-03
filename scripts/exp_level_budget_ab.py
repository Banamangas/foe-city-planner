"""A/B for level budget allocation. Strictly sequential.

Four arms, equal 600 s boxes, per-city probe_limit as calibrated 2026-08-01:

    old         level-grouped payloads, no slice   (pre-2026-08-03 behaviour)
    interleave  round-robin payloads, no slice     (D2 only)
    slice35     interleave + 35% per-level slice   (D2+D1+D3)
    slice50     interleave + 50% per-level slice

Each arm is run twice per city: from the DEFAULT k_start, and from a
deliberately-too-low one. The second is the point -- robustness to a bad start
is what slicing buys. The first is the guard: at record k feasibility is ~1%, so
capping a genuinely feasible level can lose the SAT that produces the good road
count, and a change that only rescues the broken case is not worth shipping if
it degrades the healthy one.

Adopt only if no city regresses at its default start AND at least one bad-start
case improves.
"""
import argparse
import json
import pathlib
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.bounds import pick_k_start
from foeopt.loader import load_layout
from foeopt.roads_first import RoadsFirstSearch

CITIES = {
    "darkzig": ("darkzig.json",),
    "FR16": ("CityMap-Born-FR16-2026-07-07.json",),
    "FR17": ("CityMap-Born-FR17-2026-07-07.json",),
}
PROBE_LIMIT = {"darkzig": 30.0, "FR16": 30.0, "FR17": 90.0}
# Starts known to sit below the productive region -- the failure this addresses.
BAD_START = {"darkzig": 104, "FR16": 76, "FR17": 117}

ARMS = {
    "old":        dict(interleave_levels=False, level_slice_frac=None),
    "interleave": dict(interleave_levels=True,  level_slice_frac=None),
    "slice35":    dict(interleave_levels=True,  level_slice_frac=0.35),
    "slice50":    dict(interleave_levels=True,  level_slice_frac=0.50),
}
_CACHE: dict = {}


def city(name):
    if name not in _CACHE:
        _CACHE[name] = load_layout(*CITIES[name])
    return _CACHE[name]


def run_cell(arm, city_name, start_kind, box):
    lay = city(city_name)
    k_start = (pick_k_start(lay, "nonuniform") if start_kind == "default"
               else BAD_START[city_name])
    rec = {"arm": arm, "city": city_name, "start": start_kind,
           "k_start": k_start, "box": box, "probe_limit": PROBE_LIMIT[city_name]}
    t0 = time.monotonic()
    try:
        res = RoadsFirstSearch(
            lay, time_box=box, patterns=200, probe_limit=PROBE_LIMIT[city_name],
            workers=6, probe_workers=2, th_anchors="full", concurrent_levels=4,
            pattern_family="nonuniform", quality_index_band=(3, 4),
            k_start=k_start, exact_repair=5.0, **ARMS[arm]).run()
        cov = res.get("level_coverage") or {}
        rec.update({
            "ok": True, "best": res.get("best_achieved"),
            "verdict": res.get("verdict"),
            "undersampled": res.get("undersampled_levels"),
            "levels_touched": len(cov),
            "levels": {str(k): v[0] for k, v in res.get("results", {}).items()},
            "coverage": {str(k): [c["probed"], c["surviving"]]
                         for k, c in cov.items()},
        })
    except Exception as exc:
        rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-1200:]})
    rec["wall_s"] = round(time.monotonic() - t0, 1)
    rec["overrun_x"] = round(rec["wall_s"] / box, 2)
    return rec


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="scripts/_levelbudget.jsonl")
    p.add_argument("--box", type=float, default=600.0)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--cities", default="darkzig,FR16,FR17")
    args = p.parse_args(argv)
    box = 30.0 if args.quick else args.box

    cells = [(arm, c, start)
             for c in args.cities.split(",")
             for start in ("default", "bad")
             for arm in ARMS]
    print(f"{len(cells)} cells x {box}s = {len(cells)*box/60:.0f} min. SEQUENTIAL.",
          flush=True)

    out = pathlib.Path(args.out)
    t0 = time.monotonic()
    with out.open("a") as fh:
        for i, (arm, c, start) in enumerate(cells, 1):
            print(f"\n[{i}/{len(cells)}] {c} {start}-start {arm} "
                  f"(elapsed {(time.monotonic()-t0)/60:.0f}m)", flush=True)
            rec = run_cell(arm, c, start, box)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"    -> best={rec.get('best')} verdict={rec.get('verdict')} "
                  f"levels={rec.get('levels_touched')} "
                  f"undersampled={rec.get('undersampled')} "
                  f"wall={rec['wall_s']}s ({rec['overrun_x']}x)"
                  + ("" if rec["ok"] else f" ERROR {rec.get('error')}"), flush=True)
    print(f"\nALL DONE in {(time.monotonic()-t0)/60:.0f} min -> {out}", flush=True)


if __name__ == "__main__":
    main()
