"""Wide-shallow lane-skeleton screen.

Screen a large sample of lane skeletons at a SHORT budget with concurrency
across patterns, rather than a tiny sample at a long budget with concurrency
inside one probe. Rationale (spec 2026-07-22): UNSAT is nearly free
(presolve, ~5ms), UNKNOWN does not converge with budget (900s autopsy
resolved 4 of 8), and every SAT in the 1459-instance corpus resolved within
29.2s -- so the binding resource is patterns sampled, not seconds per pattern.

  uv run python scripts/exp_wide_skeleton_screen.py --selftest
  uv run python scripts/exp_wide_skeleton_screen.py darkzig.json \
      --k-levels 105,106,107 --n 5000 --budget 30 --workers 12 \
      --out output/wide-screen.jsonl --sat-dir output/wide-screen-sats
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.roads_first import generate_lane_patterns, prefilter, probe, validate
from foeopt.validate import canonical_dims, rotated_buildings

FLOOR = 102


def rule_of_three(n: int) -> float:
    """95% upper bound on the rate of an event observed ZERO times in n trials.

    Reported on a null screen so "we found nothing" becomes a number: 0 SATs
    in 5,000 patterns bounds p*d below 0.06%, where "0 in 12" bounds nothing.
    The 3/n approximation is only meaningful for large n, so the result is
    capped at 1.0 -- a rate cannot exceed certainty.
    """
    if n <= 0:
        return 1.0
    return min(1.0, 3.0 / n)


def classify_verdict(rows: list[dict], floor: int = FLOOR) -> tuple[str, dict]:
    """Pre-committed verdict (spec section 5). Only a LEGAL, validated SAT
    strictly below `floor` counts as breaking it -- a tie does not."""
    sats = [r for r in rows
            if r["status"] == "SAT" and r.get("legal") and r.get("achieved") is not None]
    detail = {"n": len(rows), "n_sat": len(sats),
              "best_achieved": (min(r["achieved"] for r in sats) if sats else None)}
    if any(r["achieved"] < floor for r in sats):
        return "BREAK_FLOOR", detail
    if sats:
        return "FEASIBLE_NOT_SUPERIOR", detail
    detail["p_bound"] = rule_of_three(len(rows))
    return "NULL_WITH_BOUND", detail


def sample_patterns(region, tw, tl, k, n, seed):
    """Uniform sample without replacement from the full lane population.

    `generate_lane_patterns` builds every pattern for this k, shuffles with the
    supplied rng, then truncates -- so a fixed seed makes the sample and its
    index order reproducible, which is what `--resume` and `--recheck` rely on.
    """
    return generate_lane_patterns(region, tw, tl, k, random.Random(seed), n,
                                  th_mode="full")


def load_done(path: pathlib.Path) -> set[tuple[int, int]]:
    """(k, idx) pairs already recorded. Tolerates any unusable line from a
    killed run -- otherwise one interrupted write would strand the whole file."""
    done: set[tuple[int, int]] = set()
    if not path.exists():
        return done
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(r, dict) or "k" not in r or "idx" not in r:
                continue      # unusable row: skip rather than strand the whole file
            done.add((r["k"], r["idx"]))
    return done


def read_rows(path: pathlib.Path) -> list[dict]:
    """All usable rows from a results file, skipping any unparsable or
    identity-less line -- same tolerance as load_done, so a torn line from a
    killed run cannot crash the summary after the screening itself survived."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(r, dict) or "k" not in r or "idx" not in r:
                continue
            rows.append(r)
    return rows


def append_row(fh, row: dict) -> None:
    """Write and flush immediately: an 8h run must survive a kill -9."""
    fh.write(json.dumps(row) + "\n")
    fh.flush()


_W: dict = {}


def _init_worker(layout, budget):
    """Pool initializer: each worker holds the layout once, not per task."""
    _W["layout"] = layout
    _W["region"] = set(layout.region.cells)
    _W["consumers"] = layout.road_needing()
    _W["budget"] = budget


def _sat_artifact(k, idx, pat, vlay, achieved) -> dict:
    """Serialize a SAT in the existing best-k*.json schema (plus pattern
    identity) so scripts/exp_exact_router.py:reconstruct_fixed consumes it
    unchanged. Built inside the worker so no Layout crosses the process
    boundary."""
    return {
        "k": k, "idx": idx, "achieved": achieved,
        "th": [pat.th.x, pat.th.y, pat.th.width, pat.th.length],
        "pattern_roads": sorted([x, y] for (x, y) in pat.roads),
        "roads": sorted([x, y] for (x, y) in vlay.roads),
        "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                         b.footprint.width, b.footprint.length]
                      for b in vlay.buildings},
    }


def _screen_one(payload):
    """Probe one pattern at probe_workers=1. Returns (row, sat_artifact|None)."""
    k, idx, pat = payload
    diag: dict = {}
    t0 = time.monotonic()
    st, pos = probe(pat, _W["region"], _W["consumers"],
                    probe_limit=_W["budget"], probe_workers=1, diag=diag)
    row = {"k": k, "idx": idx, "status": st, "achieved": None, "legal": None,
           "secs": round(time.monotonic() - t0, 2),
           "th": list(pat.params["th"]), "reason": diag.get("reason"),
           "branches": diag.get("branches"), "solve_s": diag.get("solve_s")}
    if st != "SAT":
        return row, None
    vst, vlay, achieved = validate(_W["layout"], pat, pos)
    if vst != "OK":
        # validate() already returns terminal statuses (ROUTE_FAIL, INVALID,
        # SAT_FILLER_FAIL, SAT_ROTATED) -- re-prefixing them would emit
        # "SAT_SAT_ROTATED" and break the codebase's status vocabulary.
        row["status"] = vst
        return row, None
    row["achieved"] = achieved
    # validate() only returns "OK" when this predicate already holds, so it
    # can never be False here -- deliberate belt-and-braces recheck, kept
    # after the project's prior retracted-record incident (rotated buildings
    # slipping through as a valid SAT).
    row["legal"] = len(rotated_buildings(vlay, canonical_dims(_W["layout"]))) == 0
    return row, _sat_artifact(k, idx, pat, vlay, achieved)


def persist_sat(sat_dir: pathlib.Path, art: dict) -> pathlib.Path:
    sat_dir.mkdir(parents=True, exist_ok=True)
    p = sat_dir / f"sat-k{art['k']}-i{art['idx']}-a{art['achieved']}.json"
    p.write_text(json.dumps(art, indent=1), encoding="utf-8")
    return p


def run_screen(layout, ks, n_per, budget, workers, seed, out_path, sat_dir,
               resume=False):
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th = layout.townhall.footprint
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out_path) if resume else set()
    if done:
        print(f"resume: skipping {len(done)} already-recorded probes", flush=True)

    rows: list[dict] = []
    payloads = []
    with out_path.open("a") as fh:
        for k in ks:
            pats = sample_patterns(region, th.width, th.length, k, n_per, seed)
            print(f"k={k}: sampled {len(pats)} lane patterns", flush=True)
            for idx, pat in enumerate(pats):
                if (k, idx) in done:
                    continue
                reason = prefilter(pat, region, consumers)
                if reason is not None:
                    # provably dead without a solver call; still a determination,
                    # so it counts toward n in the rule-of-three bound
                    row = {"k": k, "idx": idx, "status": "PREFILTERED",
                           "achieved": None, "legal": None, "secs": 0.0,
                           "th": list(pat.params["th"]),
                           "reason": f"prefilter:{reason}",
                           "branches": None, "solve_s": None}
                    append_row(fh, row)
                    rows.append(row)
                    continue
                payloads.append((k, idx, pat))

        print(f"dispatching {len(payloads)} probes on {workers} workers "
              f"at {budget:.0f}s each", flush=True)
        t0 = time.monotonic()
        with mp.Pool(workers, initializer=_init_worker,
                     initargs=(layout, budget)) as pool:
            for i, (row, art) in enumerate(pool.imap_unordered(_screen_one, payloads), 1):
                append_row(fh, row)
                rows.append(row)
                if art is not None:
                    p = persist_sat(sat_dir, art)
                    print(f"  SAT k={art['k']} idx={art['idx']} "
                          f"achieved={art['achieved']} legal={row['legal']} -> {p}",
                          flush=True)
                if i % 200 == 0:
                    rate = i / ((time.monotonic() - t0) / 60)
                    print(f"  [{i}/{len(payloads)}] {rate:.1f} probes/min", flush=True)
    return rows


def pick_recheck_targets(rows_path: pathlib.Path, sample_n: int, seed: int):
    """A random subsample of the screen's UNKNOWNs, as (k, idx) pairs."""
    unknown = []
    with rows_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r["status"] == "UNKNOWN":
                unknown.append((r["k"], r["idx"]))
    unknown.sort()
    random.Random(seed).shuffle(unknown)
    return unknown[:sample_n]


def run_recheck(layout, rows_path, sample_n, budget, workers, seed, n_per):
    """Re-probe screen UNKNOWNs at a LONG budget to test whether the 30s cut
    is hiding slow-resolving SATs. `n_per`/`seed` must match the screen run --
    that is what regenerates the same patterns from (k, idx)."""
    targets = pick_recheck_targets(rows_path, sample_n, seed)
    if not targets:
        print("no UNKNOWN rows to recheck")
        return {"n": 0, "converted": 0, "rows": []}
    region = set(layout.region.cells)
    th = layout.townhall.footprint
    by_k: dict = {}
    for k, idx in targets:
        by_k.setdefault(k, []).append(idx)
    payloads = []
    for k, idxs in sorted(by_k.items()):
        pats = sample_patterns(region, th.width, th.length, k, n_per, seed)
        for idx in idxs:
            payloads.append((k, idx, pats[idx]))
    print(f"recheck: {len(payloads)} UNKNOWNs at {budget:.0f}s each", flush=True)
    out = []
    with mp.Pool(workers, initializer=_init_worker,
                 initargs=(layout, budget)) as pool:
        for row, art in pool.imap_unordered(_screen_one, payloads):
            out.append(row)
            print(f"  k={row['k']} idx={row['idx']} -> {row['status']} "
                  f"in {row['secs']}s", flush=True)
    converted = sum(1 for r in out if r["status"] != "UNKNOWN")
    res = {"n": len(out), "converted": converted,
           "sat": sum(1 for r in out if r["status"] == "SAT"), "rows": out}
    print("RECHECK:", json.dumps({k: v for k, v in res.items() if k != "rows"}))
    return res


_TALLY_STATUSES = ("SAT", "UNSAT", "UNKNOWN", "PREFILTERED")


def summarize(rows, floor: int = FLOOR) -> dict:
    per_k: dict = {}
    for r in rows:
        d = per_k.setdefault(r["k"], {"n": 0, "SAT": 0, "UNSAT": 0, "UNKNOWN": 0,
                                      "PREFILTERED": 0, "other": 0,
                                      "min_achieved": None})
        d["n"] += 1
        if r["status"] in _TALLY_STATUSES:
            d[r["status"]] += 1
        else:
            d["other"] += 1      # SAT_ROTATED, SAT_FILLER_FAIL, ... (raw JSONL keeps the detail)
        if r["status"] == "SAT" and r.get("achieved") is not None:
            if d["min_achieved"] is None or r["achieved"] < d["min_achieved"]:
                d["min_achieved"] = r["achieved"]
    verdict, detail = classify_verdict(rows, floor)
    return {"per_k": per_k, "verdict": verdict, "detail": detail}


def _selftest() -> int:
    """End-to-end on a toy layout: exercises sampling -> prefilter -> pool ->
    JSONL -> summary, which the unit tests deliberately do not (no solver)."""
    import tempfile
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(10) for y in range(10)))
    layout = Layout(region, [th, c1], th, {})
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "rows.jsonl"
        rows = run_screen(layout, [6], n_per=6, budget=5.0, workers=2, seed=0,
                          out_path=out, sat_dir=pathlib.Path(td) / "sats")
        assert rows, "selftest produced no rows"
        assert out.exists() and out.read_text().strip(), "no JSONL written"
        assert load_done(out) == {(r["k"], r["idx"]) for r in rows}, "resume keys mismatch"
        s = summarize(rows)
        assert s["verdict"] in ("BREAK_FLOOR", "FEASIBLE_NOT_SUPERIOR", "NULL_WITH_BOUND")
    print("SELFTEST OK:", json.dumps(s))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("--k-levels", default="105,106,107")
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--floor", type=int, default=FLOOR)
    ap.add_argument("--out", default="output/wide-screen.jsonl")
    ap.add_argument("--sat-dir", default="output/wide-screen-sats")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--recheck", type=int, default=0,
                   help="re-probe N screen UNKNOWNs at --recheck-budget (spec section 6)")
    ap.add_argument("--recheck-budget", type=float, default=300.0)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    layout = load_layout(args.city)
    if args.recheck:
        res = run_recheck(layout, pathlib.Path(args.out), args.recheck,
                          args.recheck_budget, args.workers, args.seed, args.n)
        pathlib.Path(args.out).with_suffix(".recheck.json").write_text(
            json.dumps(res, indent=2))
        return 0
    ks = [int(x) for x in args.k_levels.split(",")]
    out_path = pathlib.Path(args.out)
    rows = run_screen(layout, ks, args.n, args.budget, args.workers, args.seed,
                      out_path, pathlib.Path(args.sat_dir), resume=args.resume)
    if args.resume:
        rows = read_rows(out_path)
    summary = summarize(rows, args.floor)
    print("SUMMARY:", json.dumps(summary, indent=2))
    out_path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
