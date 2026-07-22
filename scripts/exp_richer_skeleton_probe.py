"""Richer-skeleton feasibility diagnostic.

Probe lane/hybrid skeletons below comb's 102 floor at a BIG budget and classify the
barrier: do any resolve SAT with a legal achieved route() count < 102 (break the
floor), are they UNSAT (feasibility wall), or UNKNOWN (decidability wall)? comb is a
control. Reuses the roads-first generators + probe + validate. Spec:
docs/superpowers/specs/2026-07-21-richer-skeleton-diagnostic-design.md.

  uv run python scripts/exp_richer_skeleton_probe.py --selftest
  uv run python scripts/exp_richer_skeleton_probe.py darkzig.json \
      --families comb,lane,hybrid --k-levels 96,100,104 --n 12 \
      --budget 300 --workers 8 --out output/richer-skeleton.json
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
from foeopt.roads_first import (
    generate_patterns, generate_lane_patterns, probe, validate,
)
from foeopt.validate import rotated_buildings, canonical_dims

RICHER = ("lane", "hybrid")


def gen_family(family, region, tw, tl, k, rng, n):
    if family == "comb":
        return generate_patterns(region, tw, tl, k, rng, n, th_mode="full")
    if family == "lane":
        return generate_lane_patterns(region, tw, tl, k, rng, n, th_mode="full")
    if family == "hybrid":
        return generate_lane_patterns(region, tw, tl, k, rng, n, th_mode="full", max_lane_len=24)
    raise ValueError(f"unknown family {family}")


def probe_pattern(layout, region, consumers, pat, budget, workers):
    """Returns (status, achieved, legal, diag). achieved/legal set only for a
    valid SAT layout; diag records why the probe ended (see probe()'s `diag`)."""
    diag = {}
    st, pos = probe(pat, region, consumers, probe_limit=budget,
                    probe_workers=workers, diag=diag)
    if st != "SAT":
        return st, None, None, diag
    vst, vlay, achieved = validate(layout, pat, pos)
    if vst != "OK":
        return f"SAT_{vst}", None, None, diag    # SAT placement but not a placeable full layout
    legal = len(rotated_buildings(vlay, canonical_dims(layout))) == 0
    return "SAT", achieved, legal, diag


def run_diagnostic(layout, families, ks, n_per, budget, workers, seed):
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    tw, tl = layout.townhall.footprint.width, layout.townhall.footprint.length
    rng = random.Random(seed)
    rows = []
    for family in families:
        for k in ks:
            pats = gen_family(family, region, tw, tl, k, rng, n_per)
            for pat in pats:
                t0 = time.monotonic()
                status, achieved, legal, diag = probe_pattern(
                    layout, region, consumers, pat, budget, workers)
                rows.append({"family": family, "k": k, "status": status,
                             "achieved": achieved, "legal": legal,
                             "secs": round(time.monotonic() - t0, 1),
                             "th": pat.params.get("th"), **diag})
                print(json.dumps(rows[-1]), flush=True)
    return rows


def classify_verdict(rows, floor=102, unknown_frac=0.5):
    richer = [r for r in rows if r["family"] in RICHER]
    wins = [r for r in richer if r["status"] == "SAT" and r.get("legal")
            and r["achieved"] is not None and r["achieved"] < floor]
    if wins:
        best = min(r["achieved"] for r in wins)
        return "BREAK_FLOOR", f"lane/hybrid SAT achieves legal {best} < {floor}"
    n = len(richer)
    n_unknown = sum(1 for r in richer if r["status"] == "UNKNOWN")
    if n and n_unknown / n >= unknown_frac:
        return "DECIDABILITY_WALL", f"{n_unknown}/{n} richer probes UNKNOWN, no legal SAT < {floor}"
    return "FEASIBILITY_WALL", f"richer probes decided (no legal SAT < {floor}; {n_unknown}/{n} UNKNOWN)"


def _summary(rows, floor=102):
    out = {}
    for fam in sorted({r["family"] for r in rows}):
        fr = [r for r in rows if r["family"] == fam]
        sats = [r["achieved"] for r in fr if r["status"] == "SAT" and r["achieved"] is not None]
        # `reason` splits UNSAT into the two very different things it can mean:
        # presolve-refuted (no search at all) vs proved by real search.
        reasons = {}
        for r in fr:
            reasons[r.get("reason", "n/a")] = reasons.get(r.get("reason", "n/a"), 0) + 1
        searched = [r["branches"] for r in fr if r.get("branches")]
        out[fam] = {"n": len(fr),
                    "SAT": sum(1 for r in fr if r["status"] == "SAT"),
                    "UNSAT": sum(1 for r in fr if r["status"] == "UNSAT"),
                    "UNKNOWN": sum(1 for r in fr if r["status"] == "UNKNOWN"),
                    "min_achieved": (min(sats) if sats else None),
                    "reason": reasons,
                    "max_branches": (max(searched) if searched else 0)}
    verdict, reason = classify_verdict(rows, floor)
    return {"per_family": out, "verdict": verdict, "reason": reason}


def _selftest():
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2), False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1], th, {})
    rows = run_diagnostic(layout, ["comb"], [4], n_per=2, budget=5.0, workers=1, seed=0)
    v, _ = classify_verdict(rows)
    assert v in ("BREAK_FLOOR", "FEASIBILITY_WALL", "DECIDABILITY_WALL")
    # verdict logic sanity on synthetic rows
    assert classify_verdict([{"family": "lane", "k": 100, "status": "SAT",
                              "achieved": 50, "legal": True}])[0] == "BREAK_FLOOR"
    print("SELFTEST OK:", json.dumps(_summary(rows)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("--families", default="comb,lane,hybrid")
    ap.add_argument("--k-levels", default="96,100,104")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--floor", type=int, default=102)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    layout = load_layout(args.city)
    families = args.families.split(",")
    ks = [int(x) for x in args.k_levels.split(",")]
    rows = run_diagnostic(layout, families, ks, args.n, args.budget, args.workers, args.seed)
    summary = _summary(rows, args.floor)
    print("SUMMARY:", json.dumps(summary, indent=2))
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps({"rows": rows, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
