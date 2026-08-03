"""Repeat study: does slice35 regress a CORRECT k_start?

The 24-cell A/B adopted 0.35 on two claims of very different strength. The
bad-start rescues (NOTHING -> a real layout) are far outside run-to-run noise.
The "no regression at the default start" claim is three single samples, and a
standalone repeat of one cell moved by 5 roads -- so it is exactly the kind of
claim n=1 cannot carry.

This re-measures only that half: old vs slice35, default k_start, 3 repeats.
"""
import argparse, json, pathlib, sys, time, traceback
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from foeopt.bounds import pick_k_start
from foeopt.loader import load_layout
from foeopt.roads_first import RoadsFirstSearch
from scripts.exp_level_budget_ab import CITIES, PROBE_LIMIT, city


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="scripts/_slicerepeats.jsonl")
    p.add_argument("--box", type=float, default=600.0)
    p.add_argument("--repeats", type=int, default=3)
    args = p.parse_args(argv)

    arms = {"old": dict(level_slice_frac=None),
            "slice35": dict(level_slice_frac=0.35)}
    cells = [(r, c, a) for r in range(args.repeats)
             for c in ("darkzig", "FR16", "FR17") for a in arms]
    print(f"{len(cells)} cells x {args.box}s = {len(cells)*args.box/60:.0f} min. "
          f"SEQUENTIAL.", flush=True)

    out = pathlib.Path(args.out)
    t0 = time.monotonic()
    with out.open("a") as fh:
        for i, (rep, c, arm) in enumerate(cells, 1):
            lay = city(c)
            k0 = pick_k_start(lay, "nonuniform")
            print(f"\n[{i}/{len(cells)}] {c} {arm} rep{rep} k0={k0} "
                  f"(elapsed {(time.monotonic()-t0)/60:.0f}m)", flush=True)
            rec = {"rep": rep, "city": c, "arm": arm, "k_start": k0,
                   "box": args.box}
            t1 = time.monotonic()
            try:
                res = RoadsFirstSearch(
                    lay, time_box=args.box, patterns=200,
                    probe_limit=PROBE_LIMIT[c], workers=6, probe_workers=2,
                    th_anchors="full", concurrent_levels=4,
                    pattern_family="nonuniform", quality_index_band=(3, 4),
                    k_start=k0, exact_repair=5.0, **arms[arm]).run()
                rec.update({"ok": True, "best": res.get("best_achieved"),
                            "verdict": res.get("verdict"),
                            "levels": len(res.get("level_coverage") or {})})
            except Exception as exc:
                rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc()[-800:]})
            rec["wall_s"] = round(time.monotonic() - t1, 1)
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            print(f"    -> best={rec.get('best')} levels={rec.get('levels')} "
                  f"wall={rec['wall_s']}s", flush=True)
    print(f"\nALL DONE in {(time.monotonic()-t0)/60:.0f} min", flush=True)


if __name__ == "__main__":
    main()
