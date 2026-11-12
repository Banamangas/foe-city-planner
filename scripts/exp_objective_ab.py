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
from foeopt.legality import check
from foeopt.loader import load_layout
from foeopt.roads_first import RoadsFirstSearch
from foeopt.router import route
from foeopt.validate import canonical_dims, is_valid, rotated_buildings

CITIES = {
    "darkzig": ("darkzig.json",),
    "FR16": ("CityMap-Born-FR16-2026-07-07.json",),
    "FR17": ("CityMap-Born-FR17-2026-07-07.json",),
    "FR24": ("CityMap-Born-FR24-2026-07-07.json",),
    "user": ("city-user-data.json", "city-user-data-foe-helper.json"),
}
PROBE_LIMIT = {"darkzig": 30.0, "FR16": 30.0, "FR17": 90.0, "FR24": 90.0, "user": 90.0}
_CACHE: dict = {}
MILITARY = "connect"

# arm -> RoadsFirstSearch kwargs; "PL" is replaced by the city's probe_limit.
ARMS = {
    "off":    {},
    "on":     {"objective_limit": "PL"},
    "polish": {"objective_polish": 0.3, "exact_finish": True},
    "both":   {"objective_limit": "PL", "objective_polish": 0.3, "exact_finish": True},
    "onx":    {"objective_limit": "PL", "exact_finish": True},
    # loose-k: start the walk above the auto k_start; the objective pulls down
    "on_k4":  {"objective_limit": "PL", "k_offset": 4},
    "on_k8":  {"objective_limit": "PL", "k_offset": 8},
    "both_pos": {"objective_limit": "PL", "objective_polish": 0.3, "exact_finish": True,
                 "probe_model": "position"},
    # the game rules (chains composed, two-lane tile) are always on since
    # 2026-11-11; this arm is BEST_PRESET verbatim (probe_limit 30 everywhere)
    "preset": {"probe_limit": 30.0, "objective_limit": 30.0, "objective_polish": 0.3,
               "exact_finish": True, "probe_model": "position"},
    # Phase B follow-up: shorter probe limits. objective_limit and exact_repair
    # are clamped to probe_limit in the worker, so they shrink with it.
    "pl10": {"probe_limit": 10.0, "objective_limit": 10.0, "objective_polish": 0.3,
             "exact_finish": True, "probe_model": "position"},
    "pl5": {"probe_limit": 5.0, "objective_limit": 5.0, "objective_polish": 0.3,
            "exact_finish": True, "probe_model": "position"},
    # Phase C: fast 10 s first pass, then re-probe unknown levels below the best
    # with 30 s, then 90 s, until the box is spent ("use the leftover box")
    "deep10": {"probe_limit": 10.0, "objective_limit": 10.0, "objective_polish": 0.3,
               "exact_finish": True, "probe_model": "position", "deepen": True},
    # deep10 + retry the walk's timed-out skeletons at 30 s / 90 s first
    "deep10r": {"probe_limit": 10.0, "objective_limit": 10.0, "objective_polish": 0.3,
                "exact_finish": True, "probe_model": "position", "deepen": True,
                "deepen_retry": True},
    # the preset + objective polish keeps going over the stored candidates
    # while time remains (FR17's 103 is made in polish; it ends at ~0.63x)
    "fill": {"probe_limit": 30.0, "objective_limit": 30.0, "objective_polish": 0.3,
             "exact_finish": True, "probe_model": "position",
             "objective_polish_fill": True},
    # fill over a wide candidate store (40 instead of 9)
    "fillw": {"probe_limit": 30.0, "objective_limit": 30.0, "objective_polish": 0.3,
              "exact_finish": True, "probe_model": "position",
              "objective_polish_fill": True, "objective_polish_keep": 40},
    "pl10fw": {"probe_limit": 10.0, "objective_limit": 10.0, "objective_polish": 0.3,
               "exact_finish": True, "probe_model": "position",
               "objective_polish_fill": True, "objective_polish_keep": 40},
    # the preset's 30 s first pass (keeps FR17's 103 path) + deepening
    "deep30": {"probe_limit": 30.0, "objective_limit": 30.0, "objective_polish": 0.3,
               "exact_finish": True, "probe_model": "position", "deepen": True},
}


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
    rep = check(lay, src, military=MILITARY)  # the delivered network, full rules
    return {"legality": rep.status, "violations": rep.violations,
            "roads_delivered": len(lay.roads), "route": len(r), "exact": er.count, "exact_optimal": er.optimal,
            "valid": is_valid(chk),
            "rotated": len(rotated_buildings(lay, canonical_dims(src))),
            "inventory_ok": ids == ids_src,
            "overlap": len(cells) - len(set(cells)),
            "out_of_region": sum(1 for c in cells if c not in region),
            "on_road": sum(1 for c in cells if c in r)}


def manifest(name, kwargs) -> dict:
    """Enough to reproduce and compare a row honestly (Codex plan, Task 0)."""
    import hashlib
    import os
    import subprocess
    import ortools
    from foeopt.legality import LEGALITY_VERSION
    root = pathlib.Path(__file__).resolve().parent.parent

    def git(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True).stdout.strip()

    h = hashlib.sha256()
    for f in CITIES[name]:
        h.update((root / f).read_bytes())
    return {"git_rev": git("rev-parse", "--short", "HEAD"),
            "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
            "input_sha256": h.hexdigest()[:16], "rules_version": LEGALITY_VERSION,
            "ortools": ortools.__version__, "cpus": os.cpu_count(),
            "effective_options": {k: (list(v) if isinstance(v, tuple) else v)
                                  for k, v in kwargs.items()}}


def run_cell(arm, name, box, rep, outdir):
    lay = city(name)
    pl = ARMS[arm].get("probe_limit", PROBE_LIMIT[name])
    rec = {"arm": arm, "city": name, "rep": rep, "box": box, "probe_limit": pl,
           "k_start": pick_k_start(lay, "nonuniform") + ARMS[arm].get("k_offset", 0)}
    best = {"achieved": None, "layout": None, "k": None, "t": None}
    t0 = time.monotonic()

    def on_imp(best_layout, k, achieved):
        if best["achieved"] is None or achieved < best["achieved"]:
            best.update(achieved=achieved, layout=best_layout, k=k,
                        t=round(time.monotonic() - t0, 1))
        rec.setdefault("first_s", round(time.monotonic() - t0, 1))

    kwargs = dict(time_box=box, patterns=200, probe_limit=pl,
                  workers=6, probe_workers=2, th_anchors="full", concurrent_levels=4,
                  pattern_family="nonuniform", quality_index_band=(3, 4),
                  k_start=rec["k_start"], exact_repair=5.0,
                  **{key: (pl if v == "PL" else v) for key, v in ARMS[arm].items()
                     if key not in ("k_offset", "probe_limit")})
    rec["manifest"] = manifest(name, kwargs)
    try:
        res = RoadsFirstSearch(lay, **kwargs).run(on_improvement=on_imp)
        rec["profile"] = res.get("profile")
        rec["deepen"] = res.get("deepen")
        rec["results"] = {k: v[0] for k, v in (res.get("results") or {}).items()}
        rec.update(ok=True, best=res.get("best_achieved"), verdict=res.get("verdict"),
                   best_k=best["k"], best_t=best["t"],
                   levels={str(k): v[0] for k, v in res.get("results", {}).items()},
                   objective_polish=res.get("objective_polish"),
                   exact_finish=res.get("exact_finish"))
        rec["search_s"] = round(time.monotonic() - t0, 1)  # before verification work
        if best["layout"] is not None:
            rec["verify"] = verify(lay, best["layout"])
            v = rec["verify"]
            # a result that fails the gate or disagrees with its count is NOT a result
            rec["accepted"] = (v["legality"] == "valid"
                               and v["roads_delivered"] == best["achieved"])
            fn = outdir / f"{name}-{arm}-r{rep}-a{best['achieved']}.json"
            fn.write_text(json.dumps({
                "city": name, "arm": arm, "achieved": best["achieved"], "k": best["k"],
                # the ACCEPTED network (with levels), not a fresh reroute
                "roads": sorted([x, y, lvl] for (x, y), lvl in best["layout"].roads.items()),
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
    p.add_argument("--arms", default="off,on")
    args = p.parse_args(argv)
    outdir = pathlib.Path("output/objective-ab")
    outdir.mkdir(parents=True, exist_ok=True)
    cells = [(arm, c, rep) for rep in range(args.reps)
             for c in args.cities.split(",") for arm in args.arms.split(",")]
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
