"""Thin CLI wrapper around foeopt.roads_first.

The search logic (Pattern, generate_patterns, prefilter, probe, validate,
RoadsFirstSearch) now lives in foeopt/roads_first.py. This script preserves
the original CLI interface for experimentation:
  uv run python scripts/exp_roads_first.py --selftest
  uv run python scripts/exp_roads_first.py darkzig.json --dump-patterns 152
  uv run python scripts/exp_roads_first.py darkzig.json --smoke
  uv run python scripts/exp_roads_first.py darkzig.json --th-anchors full

The k-walk is driven by RoadsFirstSearch.run() from foeopt.roads_first. The
worker plumbing (_worker_init/_run_probe) is still defined here because
--selftest directly exercises the pool path at the worker level to verify
parallel/sequential equivalence.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.model import Layout
from foeopt.roads_first import (
    Pattern, generate_patterns, prefilter, probe, validate,
    _check_pattern, RoadsFirstSearch,
)

# Worker-process globals set by _worker_init (sent once per worker, not per task).
# Kept locally because --selftest exercises the pool path directly to verify
# parallel/sequential equivalence at the worker level.
_WORKER_LAYOUT: Layout | None = None
_WORKER_PROBE_LIMIT: float = 30.0
_WORKER_PROBE_WORKERS: int = 1


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int) -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers


def _run_probe(payload: tuple) -> dict:
    """Worker entry point: run probe() + validate() for one (pattern, k).

    payload = (pattern, k, pat_index). Layout/probe_limit/probe_workers are read
    from the worker-process globals (_WORKER_LAYOUT/_WORKER_PROBE_LIMIT/
    _WORKER_PROBE_WORKERS), set once per worker by _worker_init. Returns a
    result dict with keys: k, params, status, achieved, secs, layout, pat_index.
    """
    pat, k, pat_index = payload
    layout = _WORKER_LAYOUT
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers,
                   probe_limit=_WORKER_PROBE_LIMIT,
                   probe_workers=_WORKER_PROBE_WORKERS)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay, "pat_index": pat_index}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}


def _selftest() -> int:
    from rl.oracle import optimal_roads
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "b")
    region_cells = frozenset((x, y) for x in range(6) for y in range(6))
    lay = Layout(Region(region_cells), [th, c1, c2], th, {})
    oracle = optimal_roads(lay, budget_s=60.0)
    region = set(region_cells)
    rng = random.Random(0)
    ok_k1 = False
    for pat in generate_patterns(region, 2, 2, 1, rng, 50):
        if prefilter(pat, region, [c1, c2]) is not None:
            continue
        st, pos = probe(pat, region, [c1, c2], probe_limit=30.0)
        if st != "SAT":
            continue
        vstat, vlay, achieved = validate(lay, pat, pos)
        if vstat == "OK" and achieved == oracle:
            ok_k1 = True
            break
    ok_k0 = generate_patterns(region, 2, 2, 0, random.Random(0), 50) == []

    import multiprocessing as _mp
    seq_statuses = set()
    rng2 = random.Random(0)
    for pat in generate_patterns(region, 2, 2, 1, rng2, 50):
        if prefilter(pat, region, [c1, c2]) is not None:
            seq_statuses.add(("PREFILTERED", tuple(sorted(pat.params.items()))))
            continue
        st, _ = probe(pat, region, [c1, c2], probe_limit=30.0, probe_workers=1)
        seq_statuses.add((st, tuple(sorted(pat.params.items()))))

    par_statuses = set()
    pool = _mp.Pool(2, initializer=_worker_init, initargs=(lay, 30.0, 1))
    try:
        rng3 = random.Random(0)
        pats3 = [p for p in generate_patterns(region, 2, 2, 1, rng3, 50)]
        surviving = [(p, 1, idx) for idx, p in enumerate(pats3)
                    if prefilter(p, region, [c1, c2]) is None]
        prefiltered = [tuple(sorted(p.params.items())) for p in pats3
                       if prefilter(p, region, [c1, c2]) is not None]
        for pf in prefiltered:
            par_statuses.add(("PREFILTERED", pf))
        for result in pool.imap_unordered(_run_probe, surviving):
            par_statuses.add((result["status"],
                              tuple(sorted(pats3[result["pat_index"]].params.items()))))
    finally:
        pool.close(); pool.join()

    ok_parallel_equiv = par_statuses == seq_statuses
    print(f"selftest: parallel_equiv={ok_parallel_equiv} "
          f"(seq={len(seq_statuses)} par={len(par_statuses)})")
    ok = ok_k1 and ok_k0 and ok_parallel_equiv
    print(f"selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _k_start_type(s: str):
    if s == "auto":
        return "auto"
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("must be 'auto' or an integer")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("--dump-patterns", type=int, default=None, metavar="K")
    p.add_argument("--patterns", type=int, default=200)
    p.add_argument("--th-anchors", choices=("coarse", "full"), default="coarse")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--k-start", type=_k_start_type, default="auto")
    p.add_argument("--probe-limit", type=float, default=120.0)
    p.add_argument("--time-box", type=float, default=21600.0)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--probe-workers", type=int, default=4)
    p.add_argument("--corpus", default=None, metavar="DIR")
    p.add_argument("--symmetry-breaking", action="store_true")
    p.add_argument("--warm-start", action="store_true")
    p.add_argument("--warm-start-budget", type=float, default=30.0)
    args = p.parse_args(argv)
    if args.smoke:
        args.patterns = 20
        args.probe_limit = 20.0
        args.time_box = 600.0
        args.workers = 1
        args.probe_workers = 1
    if args.selftest:
        return _selftest()
    if args.dump_patterns is not None:
        layout = load_layout(args.city)
        region = set(layout.region.cells)
        th = layout.townhall.footprint
        consumers = layout.road_needing()
        rng = random.Random(args.seed)
        pats = generate_patterns(region, th.width, th.length,
                                 args.dump_patterns, rng, args.patterns)
        kept = 0
        for pat in pats:
            _check_pattern(pat, region, args.dump_patterns)
            if prefilter(pat, region, consumers) is None:
                kept += 1
        print(f"k={args.dump_patterns}: {len(pats)} generated, {kept} past prefilter")
        for pat in pats[:5]:
            print("  ", pat.params)
        return 0
    if args.city is None:
        p.error("city is required for the k-walk (or use --selftest / --dump-patterns)")

    layout = load_layout(args.city)
    out_dir = pathlib.Path("output/roads-first")
    out_dir.mkdir(parents=True, exist_ok=True)

    hint_layout = None
    if args.warm_start:
        from foeopt.packer import repack
        hint_layout = repack(layout, budget_seconds=args.warm_start_budget).layout

    def on_status(k, status, _, _2):
        print(f"  k={k}: {status}", flush=True)

    def on_improvement(vlay, k, achieved):
        stem = f"best-k{k}-a{achieved}"
        (out_dir / f"{stem}.json").write_text(json.dumps({
            "k": k, "achieved": achieved,
            "roads": sorted(vlay.roads),
            "buildings": {b.entity_id: [b.footprint.x, b.footprint.y,
                                        b.footprint.width, b.footprint.length]
                          for b in vlay.buildings}}, indent=1), encoding="utf-8")
        try:
            from foeopt.viz import render_html
            (out_dir / f"{stem}.html").write_text(render_html(vlay), encoding="utf-8")
        except Exception:
            pass

    res = RoadsFirstSearch(
        layout,
        time_box=args.time_box,
        patterns=args.patterns,
        probe_limit=args.probe_limit,
        workers=args.workers,
        probe_workers=args.probe_workers,
        th_anchors=args.th_anchors,
        k_start=args.k_start,
        corpus_dir=args.corpus,
        symmetry_breaking=args.symmetry_breaking,
        hint_layout=hint_layout,
    ).run(on_improvement=on_improvement, on_status=on_status)
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, indent=1))
    per_level = {k: v[0] + (f" achieved={v[1]}" if v[1] is not None else "")
                 for k, v in sorted(res["results"].items())}
    print("levels:", json.dumps(per_level, indent=1))
    if any(v[0] == "INFEASIBLE" for v in res["results"].values()):
        print("note: INFEASIBLE = all sampled patterns UNSAT at that k, not a family-wide floor proof")
    return 0


if __name__ == "__main__":
    sys.exit(main())
