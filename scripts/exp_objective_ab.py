"""End-to-end A/B for the placement objective (objective_limit). Strictly sequential.

Arms, equal boxes, the shipped BEST_PRESET-like config (nonuniform + band,
6x2 workers, per-city probe_limit as calibrated 2026-08-01, exact_repair 5):

    off   objective_limit = 0                 (today)
    on    objective_limit = probe_limit       (clamped to it anyway)

Cells alternate off/on so slow machine drift hits both arms equally. Each
cell's best layout is saved and independently re-verified (route(),
exact_route(), is_valid, rotated, every building placed) -- a road count that
fails verification is reported as such, never as a result.

Pre-committed adoption rule: no city worse in any paired repeat AND at least
one city better.
"""
import argparse
import json
import pathlib
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.bounds import pick_k_start
from foeopt.exact_router import exact_route
from foeopt.loader import load_layout
from foeopt.roads_first import RoadsFirstSearch
from foeopt.router import route
from foeopt.validate import canonical_dims, is_valid, rotated_buildings

CITIES = {
    "darkzig": ("darkzig.json",),
    "FR16": ("CityMap-Born-FR16-2026-07-07.json",),
    "FR17": ("CityMap-Born-FR17-2026-07-07.json",),
}
PROBE_LIMIT = {"darkzig": 30.0, "FR16": 30.0, "FR17": 90.0}
_CACHE: dict = {}


def city(name):
    if name not in _CACHE:
        _CACHE[name] = load_layout(*CITIES[name])
    return _CACHE[name]


def verify(src, lay) -> dict:
    ids_src = sorted(b.entity_id for b in src.buildings)
    ids = sorted(b.entity_id for b in lay.buildings)
    cells = [c for b in lay.buildings for c in b.footprint.cells()]
    region = src.region.cells
    r = route(lay)
    er = exact_route(lay, time_limit=60)
    chk = type(lay)(lay.region, lay.buildings, lay.townhall, r)
    return {"route": len(r), "exact": er.count, "exact_optimal": er.optimal,
            "valid": is_valid(chk),
            "rotated": len(rotated_buildings(lay, canonical_dims(src))),
            "inventory_ok": ids == ids_src,
            "overlap": len(cells) - len(set(cells)),
            "out_of_region": sum(1 for c in cells if c not in region),
            "on_road": sum(1 for c in cells if c in r)}


def run_cell(arm, name, box, rep, outdir):
    lay = city(name)
    pl = PROBE_LIMIT[name]
    rec = {"arm": arm, "city": name, "rep": rep, "box": box, "probe_limit": pl,
           "k_start": pick_k_start(lay, "nonuniform")}
    best = {"achieved": None, "layout": None, "k": None, "t": None}
    t0 = time.monotonic()

    def on_imp(best_layout, k, achieved):
        if best["achieved"] is None or achieved < best["achieved"]:
            best.update(achieved=achieved, layout=best_layout, k=k,
                        t=round(time.monotonic() - t0, 1))
        rec.setdefault("first_s", round(time.monotonic() - t0, 1))

    try:
        res = RoadsFirstSearch(
            lay, time_box=box, patterns=200, probe_limit=pl,
            workers=6, probe_workers=2, th_anchors="full", concurrent_levels=4,
            pattern_family="nonuniform", quality_index_band=(3, 4),
            k_start="auto", exact_repair=5.0,
            objective_limit=(pl if arm == "on" else 0.0)).run(on_improvement=on_imp)
        rec.update(ok=True, best=res.get("best_achieved"), verdict=res.get("verdict"),
                   best_k=best["k"], best_t=best["t"],
                   levels={str(k): v[0] for k, v in res.get("results", {}).items()})
        if best["layout"] is not None:
            rec["verify"] = verify(lay, best["layout"])
            fn = outdir / f"{name}-{arm}-r{rep}-a{best['achieved']}.json"
            fn.write_text(json.dumps({
                "city": name, "arm": arm, "achieved": best["achieved"], "k": best["k"],
                "roads": sorted(route(best["layout"])),
                "buildings": {b.entity_id: [b.footprint.x, b.footprint.y,
                                            b.footprint.width, b.footprint.length]
                              for b in best["layout"].buildings}}))
    except Exception as exc:
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}",
                   traceback=traceback.format_exc()[-1500:])
    rec["wall_s"] = round(time.monotonic() - t0, 1)
    rec["overrun_x"] = round(rec["wall_s"] / box, 2)
    return rec


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="scripts/_objective_ab.jsonl")
    p.add_argument("--box", type=float, default=600.0)
    p.add_argument("--reps", type=int, default=2)
    p.add_argument("--cities", default="darkzig,FR16,FR17")
    args = p.parse_args(argv)
    outdir = pathlib.Path("output/objective-ab")
    outdir.mkdir(parents=True, exist_ok=True)
    cells = [(arm, c, rep) for rep in range(args.reps)
             for c in args.cities.split(",") for arm in ("off", "on")]
    print(f"{len(cells)} cells x {args.box}s = {len(cells)*args.box/60:.0f} min. SEQUENTIAL.",
          flush=True)
    t0 = time.monotonic()
    with pathlib.Path(args.out).open("a") as fh:
        for i, (arm, c, rep) in enumerate(cells, 1):
            print(f"[{i}/{len(cells)}] {c} rep{rep} {arm} "
                  f"(elapsed {(time.monotonic()-t0)/60:.0f}m)", flush=True)
            rec = run_cell(arm, c, args.box, rep, outdir)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            v = rec.get("verify") or {}
            print(f"    -> best={rec.get('best')} k={rec.get('best_k')} "
                  f"verify(route={v.get('route')} exact={v.get('exact')} valid={v.get('valid')} "
                  f"rot={v.get('rotated')} inv={v.get('inventory_ok')} ovl={v.get('overlap')}) "
                  f"wall={rec['wall_s']}s ({rec['overrun_x']}x)"
                  + ("" if rec["ok"] else f" ERROR {rec.get('error')}"), flush=True)
    print(f"ALL DONE in {(time.monotonic()-t0)/60:.0f} min", flush=True)


if __name__ == "__main__":
    main()
