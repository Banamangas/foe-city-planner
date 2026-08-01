"""Overnight experiment driver -- strictly sequential, one cell at a time.

CP-SAT budgets are wall-clock, not CPU time, so running two experiments at once
inflates both their UNKNOWN rates and understates their SAT rates (measured this
session: FR16 went 2.7-3.1 -> 4.2 probes/min purely by killing a competing job).
Everything here therefore runs one after another, never in parallel, and each
cell gets an identical budget to the arm it is being compared against.

Results stream to a JSONL file so a crash mid-night loses one cell, not the run.
Every cell is wrapped: an exception is recorded and the driver moves on.

Plan and rationale: tasks/todo.md, "Overnight plan -- 2026-08-01".
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
_CACHE: dict = {}


def city(name):
    if name not in _CACHE:
        _CACHE[name] = load_layout(*CITIES[name])
    return _CACHE[name]


def run_cell(exp, label, city_name, box, **kw):
    lay = city(city_name)
    t0 = time.monotonic()
    rec = {"exp": exp, "label": label, "city": city_name, "box": box,
           "params": {k: (list(v) if isinstance(v, tuple) else v)
                      for k, v in kw.items()}}
    try:
        search = RoadsFirstSearch(
            lay, time_box=box, patterns=200, probe_limit=30.0,
            workers=6, probe_workers=2, th_anchors="full",
            concurrent_levels=4, exact_repair=5.0, **kw)
        res = search.run()
        rec.update({
            "ok": True,
            "best": res.get("best_achieved"),
            "verdict": res.get("verdict"),
            "k_lowest": res.get("lowest_feasible_k_probed"),
            "inconclusive": res.get("inconclusive_levels"),
            "walk_complete": res.get("walk_complete"),
            "filler_failures": res.get("filler_failures"),
            "levels": {str(k): [v[0], v[1]] for k, v in res.get("results", {}).items()},
        })
    except Exception as exc:                                  # keep the night going
        rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-1500:]})
    rec["wall_s"] = round(time.monotonic() - t0, 1)
    rec["overrun_x"] = round(rec["wall_s"] / box, 2)
    return rec


def plan(quick=False):
    """The full matrix, in priority order so a truncated night still yields the
    most valuable results first."""
    b = (lambda full, fast: fast if quick else full)
    cells = []

    # E1 -- alternate vs both (comb). 9/9 vs 0/528 in pooled logs, never tested.
    for c in ("FR16", "FR17"):
        for modes, lab in ((("both",), "both"), (("alternate",), "alternate")):
            cells.append(dict(exp="E1", label=f"comb-{lab}", city_name=c,
                              box=b(600.0, 30.0), pattern_family="comb",
                              comb_modes=modes))

    # E2 -- family x city. BEST_PRESET hard-codes nonuniform on n=2; FR17 disagrees.
    for c in ("darkzig", "FR16", "FR17"):
        cells.append(dict(exp="E2", label="comb", city_name=c, box=b(900.0, 30.0),
                          pattern_family="comb"))
        cells.append(dict(exp="E2", label="nonuniform", city_name=c, box=b(900.0, 30.0),
                          pattern_family="nonuniform"))
        cells.append(dict(exp="E2", label="nonuniform+band", city_name=c,
                          box=b(900.0, 30.0), pattern_family="nonuniform",
                          quality_index_band=(3, 4)))

    # E3 -- k_start margin. K_START_MARGIN["nonuniform"] = -4 is n=2 and its sign
    # reverses on FR17; this knob decides where the whole budget is spent.
    for c in ("FR16", "FR17"):
        auto = pick_k_start(city(c), "nonuniform")
        base = auto + 4                     # undo the -4 margin to recover sigma/2
        for delta in (-4, 0, 8, 12):
            cells.append(dict(exp="E3", label=f"margin{delta:+d}", city_name=c,
                              box=b(600.0, 30.0), pattern_family="nonuniform",
                              quality_index_band=(3, 4), k_start=base + delta))

    # E4 -- is the default box longer than it needs to be? 60 s already matched 120 s.
    for rep in range(3):
        for box in (30.0, 45.0, 60.0):
            cells.append(dict(exp="E4", label=f"box{int(box)}s-r{rep}", city_name="darkzig",
                              box=b(box, 15.0), pattern_family="nonuniform",
                              quality_index_band=(3, 4)))

    # E5 -- the polish path has never run end-to-end in a box big enough to use it.
    for sp in (0, 12):
        cells.append(dict(exp="E5", label=f"seed_polish{sp}", city_name="darkzig",
                          box=b(600.0, 60.0), pattern_family="nonuniform",
                          quality_index_band=(3, 4), seed_polish=sp))
    return cells


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="scripts/_overnight.jsonl")
    p.add_argument("--quick", action="store_true",
                   help="tiny budgets -- smoke-test the harness, not a measurement")
    p.add_argument("--only", default=None, help="comma-separated exp ids, e.g. E1,E4")
    args = p.parse_args(argv)

    cells = plan(quick=args.quick)
    if args.only:
        keep = set(args.only.split(","))
        cells = [c for c in cells if c["exp"] in keep]
    total_budget = sum(c["box"] for c in cells)
    print(f"{len(cells)} cells, {total_budget/60:.0f} min of budget "
          f"(+ overhead). SEQUENTIAL.", flush=True)

    out = pathlib.Path(args.out)
    t0 = time.monotonic()
    with out.open("a") as fh:
        for i, cell in enumerate(cells, 1):
            spent = time.monotonic() - t0
            print(f"\n[{i}/{len(cells)}] {cell['exp']} {cell['label']} "
                  f"{cell['city_name']} box={cell['box']}s "
                  f"(elapsed {spent/60:.0f}m)", flush=True)
            rec = run_cell(**cell)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"    -> ok={rec['ok']} best={rec.get('best')} "
                  f"wall={rec['wall_s']}s ({rec['overrun_x']}x)"
                  + (f" ERROR {rec.get('error')}" if not rec["ok"] else ""),
                  flush=True)
    print(f"\nALL DONE in {(time.monotonic()-t0)/60:.0f} min -> {out}", flush=True)


if __name__ == "__main__":
    main()
