"""Q2 offline evidence: does re-solving the UNION of saved road networks that
share a Townhall beat the best member?

Members are the legal saved layouts of one city (docs/records/*.json and
output/bench/*/*.json), grouped by TH footprint. For every group with >= 2
distinct networks (or one network with its original skeleton saved) this runs
the same plans the search's union polish would (foeopt.union_polish), plus two
controls on the best member alone:
  * "rebase-bfs":  rebased polish as shipped (hard cells, bfs closure);
  * "solo-soft":   the best member's own network with soft cells (closure as
                   given), so a union gain is not just the soft-cell effect.
Strictly sequential; one CP-SAT solve at a time; keep total wall <= ~120 s.

    .venv/bin/python scripts/exp_union_polish.py --city darkzig --limit 20 --threads 8
"""
import argparse
import glob
import json
import pathlib
import sys
import time
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from foeopt.chains import compose  # noqa: E402
from foeopt.incumbent_polish import (hint_is_feasible, incumbent_positions,  # noqa: E402
                                     rebase_pattern)
from foeopt.legality import check  # noqa: E402
from foeopt.loader import load_layout  # noqa: E402
from foeopt.roads_first import (Pattern, minimize_needed, skeleton_layers,  # noqa: E402
                                validate)
from foeopt.union_polish import (plan_unions, solve_union, th_key,  # noqa: E402
                                 union_pattern)
from scripts.verify_layout_file import load_saved  # noqa: E402

CITIES = {"darkzig": "darkzig.json", "fr16": "CityMap-Born-FR16-2026-07-07.json",
          "fr17": "CityMap-Born-FR17-2026-07-07.json",
          "fr24": "CityMap-Born-FR24-2026-07-07.json"}


def saved_members(city: str, src, extra_globs=()):
    """(achieved, layout, original skeleton or None, file) for every LEGAL
    saved layout of `city`."""
    files = sorted(glob.glob(str(ROOT / "docs/records" / f"{city}-*.json")))
    benches = [ROOT / "output/bench"]
    if ROOT.parent.name == "worktrees":       # an agent worktree: the main checkout's runs
        benches.append(ROOT.parents[2] / "output/bench")
    for g in (*(str(b / "*/*.json") for b in benches), *extra_globs):
        files += sorted(glob.glob(g))
    out = []
    for f in files:
        name = pathlib.Path(f).name.lower()
        if not name.startswith(city.lower()) or name == "runs.jsonl":
            continue
        rec = json.loads(pathlib.Path(f).read_text())
        try:
            lay = load_saved(src, rec)
        except (KeyError, ValueError):
            continue
        if check(lay, src).status != "valid":
            continue
        pat = None
        if rec.get("pattern_roads"):
            pat = Pattern(th=lay.townhall.footprint,
                          roads=frozenset(tuple(c[:2]) for c in rec["pattern_roads"]),
                          params={})
        out.append((len(lay.roads), lay, pat, name))
    return out


def cyclic_share(pat):
    """Share of non-root cells with more than one predecessor one layer closer
    (where layered differs from bfs)."""
    dist = skeleton_layers(pat)
    multi = 0
    for (x, y), d in dist.items():
        if d == 0:
            continue
        preds = [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                 if dist.get(n) == d - 1]
        multi += len(preds) > 1
    return multi, len(dist)


def control(search, lay, *, soft, closure, limit, threads):
    pat = rebase_pattern(lay)
    pos = incumbent_positions(search.layout, lay)
    if pos is None or (not soft and not hint_is_feasible(search.layout, pat, pos)):
        return {"status": "NO_HINT"}
    diag: dict = {}
    t0 = time.monotonic()
    opos = minimize_needed(pat, set(search.layout.region.cells), search.layout.road_needing(),
                           pos, limit=limit, workers=threads, model="position", diag=diag,
                           closure=closure, soft=soft,
                           hint_roads=set(lay.roads))
    row = {"solve_s": round(time.monotonic() - t0, 1), "status": diag.get("objective_status"),
           "objective": diag.get("objective"), "model_size": diag.get("model_size")}
    if opos is None:
        return row
    vst, vlay, vach = validate(search.layout, pat, opos, exact_repair=5.0,
                               exact_workers=threads, witness=diag.get("witness"))
    row["validate"] = vst
    if vst == "OK":
        row["after"] = vach
        row["legality"] = check(vlay, search.source_layout).status
    return row


def generate_members(search, inc, k, n, *, probe_s, obj_s, threads, budget_s, seed=0):
    """Fresh skeletons at the incumbent's TH (the walk's nonuniform family,
    k and k+-4), each probed, objective-polished (bfs) and validated: a
    DIVERSE same-TH member set, which the saved layouts are not."""
    import random
    import foeopt.roads_first as rf
    region = set(search.layout.region.cells)
    consumers = search.layout.road_needing()
    fillers = [b for b in search.layout.buildings if not b.needs_road and not b.is_townhall]
    th = inc.townhall.footprint
    real = rf.th_anchor_candidates
    rf.th_anchor_candidates = lambda *a, **kw: [th]
    try:
        pats = []
        for kk in (k, k - 4, k + 4):
            pats += rf.generate_nonuniform_patterns(region, th.width, th.length, kk,
                                                    random.Random(seed + kk), n,
                                                    quality_index_band=rf.QUALITY_INDEX_BAND)
    finally:
        rf.th_anchor_candidates = real
    out, stats = [], {"patterns": len(pats), "prefiltered": 0, "probed": 0, "sat": 0, "ok": 0}
    t0 = time.monotonic()
    for pat in pats:
        if time.monotonic() - t0 > budget_s:
            break
        if rf.prefilter(pat, region, consumers, fillers):
            stats["prefiltered"] += 1
            continue
        stats["probed"] += 1
        st, pos = rf.probe(pat, region, consumers, probe_limit=probe_s,
                           probe_workers=threads, model="position")
        if st != "SAT":
            continue
        stats["sat"] += 1
        diag: dict = {}
        opos = minimize_needed(pat, region, consumers, pos, limit=obj_s, workers=threads,
                               model="position", diag=diag) or pos
        vst, vlay, vach = validate(search.layout, pat, opos, exact_repair=5.0,
                                   exact_workers=threads, witness=diag.get("witness"))
        if vst == "OK" and check(vlay, search.source_layout).status == "valid":
            stats["ok"] += 1
            out.append((vach, vlay, pat, f"gen-k{len(pat.roads)}"))
    stats["time_s"] = round(time.monotonic() - t0, 1)
    return out, stats


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--city", required=True, choices=sorted(CITIES))
    p.add_argument("--limit", type=float, default=20.0, help="seconds per solve")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--closure", default="flow", choices=["layered", "flow"])
    p.add_argument("--m", type=int, default=3)
    p.add_argument("--soft", default="new", choices=["new", "all"])
    p.add_argument("--max-solves", type=int, default=5)
    p.add_argument("--controls", action="store_true", help="also run the two controls")
    p.add_argument("--out", default=None, help="append JSON rows here")
    p.add_argument("--generate", type=int, default=0,
                   help="also generate this many fresh skeletons per level at the best TH")
    p.add_argument("--gen-budget", type=float, default=60.0)
    p.add_argument("--gen-k", type=int, required=False, default=0,
                   help="skeleton k for --generate")
    p.add_argument("--members", nargs="*", default=[],
                   help="extra globs of saved layouts (e.g. the main checkout's output/bench)")
    a = p.parse_args(argv)
    src = load_layout(str(ROOT / CITIES[a.city]))
    search = SimpleNamespace(layout=compose(src), source_layout=src, exact_repair=5.0,
                             road_witness=True, military="connect", fillers_in_model=False,
                             workers=1, probe_workers=a.threads, closure=a.closure,
                             union_m=a.m)
    mem = saved_members(a.city, src, a.members)
    print(f"{a.city}: {len(mem)} legal saved layouts")
    for ach, lay, pat, name in mem:
        mc, n = cyclic_share(rebase_pattern(lay))
        print(f"  {name:45s} {ach:4d} TH {th_key(lay)[:2]} skeleton={'y' if pat else 'n'}"
              f"  network cells with >1 layered predecessor: {mc}/{n}")
    best = min(mem, key=lambda t: t[0])
    if a.generate:
        gen, stats = generate_members(search, best[1], a.gen_k, a.generate, probe_s=3.0,
                                      obj_s=5.0, threads=a.threads, budget_s=a.gen_budget)
        print(f"generated at TH {th_key(best[1])[:2]} k={a.gen_k}: {stats}; members "
              f"{sorted(t[0] for t in gen)}")
        for t in gen:
            print(f"  gen {t[0]}: shared cells with best {len(set(t[1].roads) & set(best[1].roads))}"
                  f", new cells {len(set(t[1].roads) - set(best[1].roads))}")
        mem = [t for t in mem if th_key(t[1]) == th_key(best[1])] + gen
    plans = []
    for key in sorted({th_key(t[1]) for t in mem}):
        g = [(t[0], t[1], t[2]) for t in mem if th_key(t[1]) == key]
        inc = min(g, key=lambda t: t[0])[1]
        plans += [(pl, len(inc.roads)) for pl in plan_unions(g, inc, m=a.m)]
    print(f"planned unions: {len(plans)}")
    rows, solves = [], 0
    t_all = time.monotonic()
    for pl, inc_roads in plans:
        if solves >= a.max_solves:
            break
        u = union_pattern(pl["members"], pl["extra"])
        new = len(u.roads) - len(set(pl["members"][0].roads) - pl["members"][0].townhall.footprint.cells())
        row, lay = solve_union(search, pl, limit=a.limit, threads=a.threads, closure=a.closure,
                               soft=a.soft)
        solves += 1
        row.update(city=a.city, best_member=inc_roads, cells_beyond_best=new,
                   gain=(inc_roads - row["after"]) if row.get("after") else None)
        rows.append(row)
        print(json.dumps(row))
        if a.controls and solves < a.max_solves:
            b = pl["members"][0]
            ctl = (("solo-soft", True, a.closure) if a.soft == "all"
                   else (f"rebase-{a.closure}", False, a.closure))
            for name, soft, clo in (("rebase-bfs", False, "bfs"), ctl):
                c = control(search, b, soft=soft, closure=clo, limit=a.limit, threads=a.threads)
                solves += 1
                c.update(city=a.city, kind=name, best_member=len(b.roads))
                rows.append(c)
                print(json.dumps(c))
    print(f"total wall {time.monotonic() - t_all:.1f}s; overall best saved {best[0]}")
    if a.out:
        with open(a.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
