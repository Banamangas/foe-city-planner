"""Stage-0 proxy correlation study for the roads-first placement objective.

Throwaway R&D driver (spec: docs/superpowers/specs/2026-07-21-roads-first-placement-objective-design.md).

Feasible skeletons are ~2% of probes at the frontier, so random sampling almost
never hits one. Instead we REUSE the known-SAT skeletons already recorded in a
roads-first corpus (output/corpus/<city>/instances.jsonl), and collect placement
diversity on each by re-running roads_first.probe() under different random_seeds
(no objective — this is exactly today's first-feasible model). For every distinct
placement we record route()'s road count and all four proxy values, then report
per-skeleton oracle_gap plus per-proxy Spearman correlation and realized road
reduction — the go/kill evidence.

  uv run python scripts/exp_placement_objective.py --selftest
  uv run python scripts/exp_placement_objective.py darkzig.json \
      --corpus output/corpus/darkzig --n-seeds 8 --probe-limit 15 \
      --out output/stage0-placement.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dataclasses import replace

from foeopt.loader import load_layout
from foeopt.model import Footprint, Layout
from foeopt.router import route, RouteError
from foeopt.roads_first import Pattern, probe
from foeopt.corpus import load_instances
from foeopt.placement_proxies import (
    proxy_touched_cells, proxy_subtree, proxy_double_loaded, proxy_same_size_clusters,
)

# (name, fn, sign): sign folds each proxy into a "minimize" orientation so that
# argmin(sign*raw) is the placement the proxy would pick and a POSITIVE
# spearman(sign*raw, roads) means the proxy tracks the real road count.
PROXIES = [
    ("P1_touched", proxy_touched_cells, +1),
    ("P2_subtree", proxy_subtree, +1),
    ("P3_double_loaded", proxy_double_loaded, -1),
    ("P4_same_size", proxy_same_size_clusters, -1),
]

FRONTIER_K = 118  # at/below this k is the tight frontier where the real floor lives


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    if len(xs) < 2:
        return 0.0
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def load_sat_skeletons(corpus_dir: str) -> list[Pattern]:
    """Reconstruct a Pattern for every SAT record in a roads-first corpus."""
    pats: list[Pattern] = []
    for rec in load_instances(corpus_dir):
        if rec.get("status") != "SAT":
            continue
        thx, thy, thw, thl = rec["th"]
        roads = frozenset((x, y) for x, y in rec["roads"])
        pats.append(Pattern(th=Footprint(thx, thy, thw, thl), roads=roads,
                            params={"k": rec["k"]}))
    return pats


def collect_placements(layout: Layout, pattern, n_seeds: int, probe_limit: float) -> list[dict]:
    """Distinct feasible placements on a fixed skeleton, one per random_seed.

    Re-runs roads_first.probe() (the real first-feasible model, no objective) with
    random_seed 0..n_seeds-1; single-worker so each seed is deterministic. Dedupes
    identical placements, preserving seed order (index 0 == seed-0's first-feasible)."""
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    seen: set = set()
    out: list[dict] = []
    for seed in range(n_seeds):
        st, pos = probe(pattern, region, consumers, probe_limit=probe_limit,
                        probe_workers=1, solver_overrides={"random_seed": seed})
        if st != "SAT" or pos is None:
            continue
        key = tuple(sorted((eid, tuple(v)) for eid, v in pos.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(pos)
    return out


def roads_for_placement(layout: Layout, pattern, positions) -> int | None:
    """route() road count for a consumer placement (fillers ignored — they do not
    affect the road count, which route() derives from the consumers before fill)."""
    placed = [replace(b, footprint=Footprint(*positions[b.entity_id]))
              for b in layout.road_needing()]
    th = replace(layout.townhall, footprint=pattern.th)
    cand = Layout(layout.region, [th, *placed], th, {})
    try:
        return len(route(cand))
    except RouteError:
        return None


def score_skeleton(layout: Layout, pattern, n_seeds: int, probe_limit: float) -> dict | None:
    """Per-skeleton oracle_gap + proxy stats. None if <2 distinct usable placements
    (nothing to correlate)."""
    placements = collect_placements(layout, pattern, n_seeds, probe_limit)
    rows = []
    for pos in placements:
        r = roads_for_placement(layout, pattern, pos)
        if r is None:
            continue
        vals = {name: sign * fn(pattern, pos) for name, fn, sign in PROXIES}
        rows.append((r, vals))
    if len(rows) < 2:
        return None
    roads = [r for r, _ in rows]
    first_roads = roads[0]  # seed-0's placement == the first-feasible baseline proxy
    out = {"k": pattern.params.get("k"), "n_placements": len(rows),
           "first_roads": first_roads, "min_roads": min(roads),
           "oracle_gap": first_roads - min(roads), "proxies": {}}
    for name, _, _ in PROXIES:
        col = [vals[name] for _, vals in rows]
        # ties (common for low-resolution proxies like P4) break to the earliest
        # seed, so realized_reduction is conservative: biased toward the null, never
        # a false "advance".
        best_idx = min(range(len(rows)), key=lambda i: col[i])
        out["proxies"][name] = {
            "spearman": round(spearman(col, roads), 3),
            "realized_reduction": first_roads - roads[best_idx],
        }
    return out


def _aggregate(results: list[dict]) -> dict:
    gaps = [r["oracle_gap"] for r in results]
    d = {"skeletons": len(results),
         "mean_oracle_gap": round(sum(gaps) / len(results), 3),
         "max_oracle_gap": max(gaps), "proxies": {}}
    for name, _, _ in PROXIES:
        corrs = [r["proxies"][name]["spearman"] for r in results]
        reds = [r["proxies"][name]["realized_reduction"] for r in results]
        d["proxies"][name] = {
            "mean_spearman": round(sum(corrs) / len(corrs), 3),
            "mean_realized_reduction": round(sum(reds) / len(reds), 3),
        }
    return d


def summarize(results: list[dict]) -> dict:
    if not results:
        return {"skeletons_scored": 0, "note": "no skeleton yielded >=2 distinct placements"}
    out = {"all": _aggregate(results)}
    frontier = [r for r in results if (r.get("k") or 10 ** 9) <= FRONTIER_K]
    if frontier:
        out[f"frontier_k<={FRONTIER_K}"] = _aggregate(frontier)
    out["per_skeleton"] = sorted(
        ({"k": r["k"], "n": r["n_placements"], "oracle_gap": r["oracle_gap"]}
         for r in results), key=lambda r: (r["k"] or 0))
    return out


def run_study(layout: Layout, corpus_dir: str, n_seeds: int, probe_limit: float,
              max_skeletons: int | None = None) -> dict:
    pats = load_sat_skeletons(corpus_dir)
    if max_skeletons is not None:
        pats = pats[:max_skeletons]
    results = []
    for pat in pats:
        s = score_skeleton(layout, pat, n_seeds, probe_limit)
        if s is not None:
            results.append(s)
    return summarize(results)


def _selftest() -> int:
    # Tiny synthetic instance + a hand-made SAT skeleton, no corpus/data files.
    from foeopt.model import Building, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 1),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "b")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1, c2], th, {})
    pat = Pattern(th=Footprint(0, 0, 2, 1),
                  roads=frozenset({(2, 0), (2, 1), (2, 2), (2, 3)}), params={"k": 4})
    res = score_skeleton(layout, pat, n_seeds=4, probe_limit=5.0)  # dict or None; must not raise
    assert spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert res is None or ("oracle_gap" in res and "proxies" in res)
    print("SELFTEST OK:", "toy scored" if res else "toy <2 placements (ok)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("helper", nargs="?")
    ap.add_argument("--corpus", help="roads-first corpus dir (has instances.jsonl)")
    ap.add_argument("--n-seeds", type=int, default=8)
    ap.add_argument("--probe-limit", type=float, default=15.0)
    ap.add_argument("--max-skeletons", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    if not args.corpus:
        ap.error("--corpus DIR required (or --selftest)")
    layout = load_layout(args.city, args.helper)
    out = run_study(layout, args.corpus, args.n_seeds, args.probe_limit, args.max_skeletons)
    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
