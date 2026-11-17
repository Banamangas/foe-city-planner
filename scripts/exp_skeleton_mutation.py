"""N5 experiment: directed search over CONCRETE skeletons (2026-11-17).

Start from one skeleton (a saved record's road network, the uploaded city's
network, or the best of a short nonuniform walk at the record's TH), then hill
climb: each generation makes `lam` mutants of the parent with the operators in
foeopt/skeleton_mutation.py (1-2 moves each, plus the parent's pruned network
when it has one), judges every mutant with the production worker
(`roads_first._run_probe`: position-model probe, objective, validate with the
road witness), and accepts the best mutant if its achieved roads are no worse
than the parent's (ties accepted; smaller k preferred). At the end, one rebased
polish (foeopt.incumbent_polish) on the best layout, as the production pipeline
does after its walk.

Every new best and the final layout pass scripts/bench.py `verify()` (full
legality on the delivered roads, rotation, inventory, overlap); a count that
fails it is not a result.

    flock output/bench/.lock .venv/bin/python scripts/exp_skeleton_mutation.py \
        --city FR17 --start walk --record docs/records/fr17-103-roads-preset.json \
        --budget 1500
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as _dt
import json
import multiprocessing as mp
import pathlib
import random
import sys
import time
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import foeopt.roads_first as rf  # noqa: E402
from foeopt import skeleton_mutation as sm  # noqa: E402
from foeopt.chains import compose  # noqa: E402
from foeopt.incumbent_polish import incumbent_positions, polish_rebased  # noqa: E402
from foeopt.loader import load_layout  # noqa: E402
from foeopt.roads_first import Pattern, _check_pattern  # noqa: E402
from scripts.bench import CITIES, verify  # noqa: E402
from scripts.verify_layout_file import load_saved  # noqa: E402

WARM_ALWAYS = True    # set from --warm in main() before the pool forks
RECORDS = {"darkzig": 88, "FR16": 67, "FR17": 103, "FR24": 220}


def accepted(v: dict, achieved: int) -> bool:
    """bench.run_cell's acceptance rule."""
    return (v["legality"] == "valid" and v["rotated"] == 0 and v["inventory_ok"]
            and v["overlap"] == 0 and v["roads_delivered"] == achieved)


def save_layout(path: pathlib.Path, city: str, achieved: int, lay, pat, extra: dict):
    path.write_text(json.dumps({
        "city": city, "arm": "n5-mutation", "achieved": achieved, "k": len(pat.roads),
        "roads": sorted([x, y, lvl] for (x, y), lvl in lay.roads.items()),
        "buildings": {b.entity_id: [b.footprint.x, b.footprint.y,
                                    b.footprint.width, b.footprint.length]
                      for b in lay.buildings},
        "pattern_th": [pat.th.x, pat.th.y, pat.th.width, pat.th.length],
        "pattern_roads": sorted([x, y] for (x, y) in pat.roads), **extra}))


def _warm(pat, hint):
    """Fallback when the cold probe is not SAT: the production objective
    (minimize_needed, position model) hinted from the PARENT's placement, as
    rebased polish does, then validate with the road witness. A hint the
    mutant blocks is only a hint; CP-SAT repairs or finds nothing."""
    layout = rf._WORKER_LAYOUT
    region, consumers = set(layout.region.cells), layout.road_needing()
    d: dict = {}
    opos = rf.minimize_needed(pat, region, consumers, hint, limit=rf._WORKER_OBJECTIVE_LIMIT,
                              workers=rf._WORKER_PROBE_WORKERS, model="position", diag=d,
                              hint_roads=set(pat.roads))
    if opos is None:
        return d.get("objective_status") or "NONE", None, None, None
    vst, vlay, vach = rf.validate(layout, pat, opos, exact_repair=rf._WORKER_EXACT_REPAIR,
                                  exact_workers=rf._WORKER_PROBE_WORKERS,
                                  witness=d.get("witness"))
    return ("SAT", vach, vlay, opos) if vst == "OK" else (vst, None, None, None)


def _eval(payload):
    """Worker: one mutant through the production probe+objective+validate
    ("cold"), then, if that is not SAT and a hint is given, `_warm`."""
    pat, k, idx, deadline, ops, hint = payload
    t0 = time.monotonic()
    r = rf._run_probe((pat, k, idx, deadline))
    out = {"idx": idx, "ops": ops, "k": k, "status": r["status"], "cold": r["status"],
           "mode": "cold", "achieved": r["achieved"], "layout": r["layout"],
           "pos": r["pos"] if r["status"] == "SAT" else None, "pattern": pat}
    out["cold_achieved"] = r["achieved"]
    if hint is not None and (WARM_ALWAYS or r["status"] != "SAT"):
        st, ach, lay, pos = _warm(pat, hint)
        out["warm"], out["warm_achieved"] = st, ach
        if st == "SAT" and (out["status"] != "SAT" or ach < out["achieved"]):
            out.update(status=st, achieved=ach, layout=lay, pos=pos, mode="warm")
    out["secs"] = round(time.monotonic() - t0, 1)
    return out


class Runner:
    def __init__(self, a, src, layout):
        self.a, self.src, self.layout = a, src, layout
        self.region = frozenset(layout.region.cells)
        ctx = mp.get_context("fork")
        self.pool = cf.ProcessPoolExecutor(
            a.workers, mp_context=ctx, initializer=rf._worker_init,
            initargs=(layout, a.probe_limit, a.probe_workers, False, None, False, None,
                      a.exact_repair, a.objective_limit, "position", True, False))
        self.t0 = time.monotonic()
        self.n_eval = 0
        self.log = open(a.log, "a")

    def elapsed(self):
        return time.monotonic() - self.t0

    def evaluate(self, items, hint=None):
        """items: [(Pattern, ops)] -> results in input order. `hint`: the
        parent's positions for the warm fallback (None = cold only)."""
        hint = hint if self.a.warm != "off" else None
        dl = time.monotonic() + self.a.probe_limit + self.a.objective_limit + 60
        futs = []
        for pat, ops in items:
            _check_pattern(pat, set(self.region), len(pat.roads))
            futs.append(self.pool.submit(
                _eval, (pat, len(pat.roads), self.n_eval, dl, ops, hint)))
            self.n_eval += 1
        out = [f.result() for f in futs]
        for r in out:
            row = {k: v for k, v in r.items() if k not in ("layout", "pattern", "pos")}
            row["t"] = round(self.elapsed(), 1)
            self.log.write(json.dumps({"kind": "eval", **row}) + "\n")
        self.log.flush()
        return out


def walk_start(run: Runner, th, k, n, budget, seed):
    """Best of a short nonuniform walk at a fixed TH (the record's), judged by
    the same evaluator: stands in for the walk skeleton records don't save."""
    real = rf.th_anchor_candidates
    rf.th_anchor_candidates = lambda *a, **kw: [th]
    try:
        pats = rf.generate_nonuniform_patterns(set(run.region), th.width, th.length, k,
                                               random.Random(seed), n,
                                               quality_index_band=rf.QUALITY_INDEX_BAND)
    finally:
        rf.th_anchor_candidates = real
    consumers = run.layout.road_needing()
    fillers = [b for b in run.layout.buildings if not b.needs_road and not b.is_townhall]
    pats = [p for p in pats if p.th == th and not rf.prefilter(p, set(run.region), consumers, fillers)]
    print(f"walk start: {len(pats)} nonuniform k={k} skeletons at TH {th} pass the prefilter",
          flush=True)
    best = None
    t_end = run.elapsed() + budget
    i = 0
    while i < len(pats) and run.elapsed() < t_end:
        batch = pats[i:i + run.a.workers]
        i += len(batch)
        for r in run.evaluate([(p, ["walk"]) for p in batch]):
            if r["status"] == "SAT" and (best is None or r["achieved"] < best["achieved"]):
                best = r
        print(f"  [{run.elapsed():6.0f}s] walk probed {i}: best "
              f"{best and best['achieved']}", flush=True)
    return best


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--city", required=True, choices=sorted(RECORDS))
    p.add_argument("--start", required=True, choices=["record", "upload", "walk"])
    p.add_argument("--record", help="saved layout JSON (record start / TH for walk)")
    p.add_argument("--budget", type=float, default=1500, help="mutation search seconds")
    p.add_argument("--walk-k", type=int, default=116)
    p.add_argument("--walk-n", type=int, default=60)
    p.add_argument("--walk-budget", type=float, default=300)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--probe-workers", type=int, default=2)
    p.add_argument("--lam", type=int, default=0, help="mutants per generation (0 = workers)")
    p.add_argument("--probe-limit", type=float, default=30.0)
    p.add_argument("--objective-limit", type=float, default=30.0)
    p.add_argument("--exact-repair", type=float, default=5.0)
    p.add_argument("--rebase-s", type=float, default=60.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--warm", default="always", choices=["always", "fallback", "off"],
                   help="parent-hinted objective per mutant: always (keep the better of "
                        "cold and warm), only when the cold probe is not SAT, or never")
    p.add_argument("--out", default=str(ROOT / "output/n5"))
    a = p.parse_args(argv)
    lam = a.lam or a.workers
    global WARM_ALWAYS
    WARM_ALWAYS = a.warm == "always"
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.city}-{a.start}-s{a.seed}-{_dt.datetime.now():%m%d-%H%M}"
    a.log = out / f"{tag}.jsonl"
    src = load_layout(*(str(ROOT / f) for f in CITIES[a.city]))
    layout = compose(src)
    run = Runner(a, src, layout)
    rng = random.Random(a.seed)
    record = RECORDS[a.city]

    # ---- start skeleton
    hint0 = None
    if a.start == "upload":
        th, roads = src.townhall.footprint, frozenset(src.roads)
        start = [(Pattern(th, roads, {"n5": "upload"}), ["start"])]
        hint0 = incumbent_positions(layout, src)
    else:
        rec = load_saved(src, json.loads(pathlib.Path(a.record).read_text()))
        th = rec.townhall.footprint
        if a.start == "record":
            start = [(Pattern(th, frozenset(rec.roads), {"n5": "record"}), ["start"])]
            hint0 = incumbent_positions(layout, rec)
    if a.start == "walk":
        res = walk_start(run, th, a.walk_k, a.walk_n, a.walk_budget, a.seed)
        if res is None:
            raise SystemExit("walk start: no SAT skeleton")
        parent = res
    else:
        parent = run.evaluate(start, hint0)[0]
    print(f"[{run.elapsed():6.0f}s] start {a.start}: k={parent['k']} status={parent['status']}"
          f" achieved={parent['achieved']} mode={parent['mode']} (record {record})", flush=True)

    best = parent if parent["status"] == "SAT" else None
    traj = [[round(run.elapsed(), 1), best and best["achieved"]]]
    seen = {parent["pattern"].roads}
    gen = acc = 0
    budget_end = run.elapsed() + a.budget
    verified = []

    def new_best(r):
        v = verify(src, r["layout"])
        ok = accepted(v, r["achieved"])
        verified.append({"achieved": r["achieved"], "ok": ok, "legality": v["legality"]})
        print(f"    new best {r['achieved']} k={r['k']} ops={r['ops']} verify="
              f"{v['legality']} accepted={ok}", flush=True)
        return ok

    while run.elapsed() < budget_end:
        gen += 1
        pat0 = parent["pattern"]
        items = []
        if parent["status"] == "SAT":
            pr = sm.prune(pat0.roads, th, run.region, parent["layout"].roads)
            if pr is not None and pr not in seen:
                items.append((Pattern(th, pr, {"n5": "mut"}), ["prune"]))
                seen.add(pr)
        guard = 0
        while len(items) < lam and guard < 50 * lam:
            guard += 1
            m = sm.mutate(pat0.roads, th, run.region, rng,
                          n_ops=1 if rng.random() < 0.7 else 2)
            if m is None or m[0] in seen:
                continue
            seen.add(m[0])
            items.append((Pattern(th, m[0], {"n5": "mut"}), m[1]))
        if not items:
            print("no new mutants; stop", flush=True)
            break
        res = run.evaluate(items, parent["pos"] or hint0)
        sat = [r for r in res if r["status"] == "SAT"]
        cand = min(sat, key=lambda r: (r["achieved"], r["k"])) if sat else None
        moved = False
        if cand is not None and (parent["status"] != "SAT"
                                 or cand["achieved"] <= parent["achieved"]):
            parent, moved = cand, True
            acc += 1
            if best is None or cand["achieved"] < best["achieved"]:
                if new_best(cand):
                    best = cand
                    traj.append([round(run.elapsed(), 1), best["achieved"]])
        summ = sorted((str(r["achieved"]) + ("w" if r["mode"] == "warm" else ""))
                      if r["status"] == "SAT" else r["status"][:3] for r in res)
        print(f"[{run.elapsed():6.0f}s] gen {gen:3d} parent {parent['achieved']}/k{parent['k']}"
              f" {'ACC ' + '+'.join(parent['ops']) if moved else '     '} batch "
              f"{" ".join(summ)} best {best and best['achieved']}", flush=True)
        run.log.write(json.dumps({"kind": "gen", "gen": gen, "t": round(run.elapsed(), 1),
                                  "parent": parent["achieved"], "parent_k": parent["k"],
                                  "moved": moved, "best": best and best["achieved"]}) + "\n")

    run.pool.shutdown(cancel_futures=True)
    summary = {"city": a.city, "start": a.start, "seed": a.seed, "record": record,
               "evals": run.n_eval, "generations": gen, "accepted_moves": acc,
               "trajectory": traj, "verified": verified,
               "search_best": best and best["achieved"], "search_best_k": best and best["k"]}
    if best is not None:
        # one rebased polish on the best layout, as production does after its walk
        ns = SimpleNamespace(layout=layout, workers=a.workers, probe_workers=a.probe_workers,
                             exact_repair=a.exact_repair, closure="bfs", road_witness=True,
                             fillers_in_model=False)
        holder = {"lay": best["layout"], "ach": best["achieved"]}
        rep = polish_rebased(ns, best["layout"], best["achieved"], time.monotonic() + a.rebase_s,
                             on_improvement=lambda lay, k, ach: holder.update(lay=lay, ach=ach))
        final_lay, final_ach = holder["lay"], holder["ach"]
        v = verify(src, final_lay)
        summary.update(rebased=rep, final=final_ach,
                       final_verify={k: v[k] for k in ("legality", "rotated", "inventory_ok",
                                                       "overlap", "roads_delivered", "exact")},
                       final_accepted=accepted(v, final_ach))
        fn = out / f"{tag}-a{final_ach}.json"
        save_layout(fn, a.city, final_ach, final_lay, best["pattern"],
                    {"verify": summary["final_verify"], "accepted": summary["final_accepted"]})
        summary["layout_file"] = str(fn)
    summary["wall_s"] = round(run.elapsed(), 1)
    run.log.write(json.dumps({"kind": "summary", **summary}) + "\n")
    run.log.close()
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
