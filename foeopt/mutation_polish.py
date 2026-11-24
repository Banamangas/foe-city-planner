"""N6 (2026-11-17): skeleton-mutation search as an end-of-run phase.

N5 (`scripts/exp_skeleton_mutation.py`) found darkzig 87 and FR17 102 offline
with a (1+lambda) hill climb over CONCRETE road networks: mutate one arm of
the parent (foeopt/skeleton_mutation.py), judge every mutant by its roads
after the objective, accept the best mutant when it is no worse than the
parent (ties accepted, so the climb drifts along plateaus).

This module runs that climb inside `RoadsFirstSearch.run`, after the other
polish phases, in the time left before the deadline (option `mutation_polish`;
`mutation_reserve` seconds can be held back for it). It never borrows the
objective-polish window (lessons: that cost FR17 3 roads).

Starts: the incumbent's own network (N5's darkzig start), then optionally the
original skeletons of the next-best layouts objective polish validated (N5's
FR17 start: a walk skeleton with cells to prune). The time left is split
evenly over the starts still to go.

Evaluator (N5's, both halves, keep the better):
  * cold: the production worker `_run_probe` (position probe, in-walk
    objective, validate with the road witness) in a fresh worker pool, started
    only when a whole probe still fits before the end;
  * warm: `minimize_needed` hinted from the PARENT's placement and the
    mutant's cells, all threads, sequential (2 threads did not recover even a
    complete hint in 20 s; 12 proved it in 5 s -- lessons 2026-11-17).
Every result went through `validate` (route, witness, fillers, rotation); a
mutant that would be accepted also passes the full legality gate, and only a
strictly better layout is published. Buildings are never rotated: the
operators touch road cells only.
"""
from __future__ import annotations

import multiprocessing
import random
import time

from foeopt import skeleton_mutation as sm
from foeopt.incumbent_polish import incumbent_positions
from foeopt.legality import check as legality_check
from foeopt.model import Layout
from foeopt.roads_first import (OBJECTIVE_MARGIN_S, OBJECTIVE_MIN_S, Pattern, _check_pattern,
                                _run_probe, _worker_init, minimize_needed, model_fillers,
                                validate)

WARM_LIMIT_S = 10.0      # N5's per-mutant warm solve
TWO_MOVES_P = 0.3        # N5: 1 move 70%, 2 moves 30%


def warm_solve(layout: Layout, pat: Pattern, hint: dict, *, limit: float, threads: int,
               exact_repair: float, fillers=None, closure: str = "bfs",
               witness: bool = True):
    """The production objective hinted from `hint` (the parent's placement)
    and the mutant's own cells, then `validate`. Returns (status, roads,
    layout, positions); roads/layout/positions are None unless status is SAT."""
    region, consumers = set(layout.region.cells), layout.road_needing()
    d: dict = {}
    opos = minimize_needed(pat, region, consumers, hint, limit=limit, workers=threads,
                           model="position", diag=d, hint_roads=set(pat.roads),
                           fillers=fillers, closure=closure)
    if opos is None:
        return d.get("objective_status") or "NONE", None, None, None
    vst, vlay, vach = validate(layout, pat, opos, exact_repair=min(exact_repair, limit),
                               exact_workers=threads,
                               witness=d.get("witness") if witness else None)
    return ("SAT", vach, vlay, opos) if vst == "OK" else (vst, None, None, None)


def cold_need(search) -> float:
    """Seconds a cold batch needs: a full probe (not clamped by the batch
    pool), one filler repair, and a margin."""
    return search.probe_limit + search.exact_repair + OBJECTIVE_MARGIN_S


def plan_starts(incumbent: Layout, achieved: int, solved: list, n: int) -> list:
    """[(achieved, layout, skeleton_roads)], best first: the incumbent's own
    network, then up to n-1 other validated layouts (objective polish's
    `solved_networks`: (roads, layout, original skeleton)) with distinct
    skeletons, by road count."""
    out = [(achieved, incumbent, frozenset(incumbent.roads))]
    seen = {out[0][2]}
    for ach, lay, pat in sorted(solved, key=lambda t: t[0]):
        if len(out) >= n:
            break
        if lay is incumbent or pat is None or pat.roads in seen:
            continue
        seen.add(pat.roads)
        out.append((ach, lay, pat.roads))
    return out


class _Climb:
    """One phase: the shared evaluator state (pool, fillers, global best)."""

    def __init__(self, search, best: int, on_improvement, should_stop, pool_factory):
        self.s = search
        self.layout = search.layout
        self.region = frozenset(search.layout.region.cells)
        self.best = best
        self.on_improvement = on_improvement
        self.should_stop = should_stop
        self.pool_factory = pool_factory
        self.pool = None
        self.threads = max(1, search.workers * search.probe_workers)
        self.fillers = model_fillers(search.layout, getattr(search, "fillers_in_model", False),
                                     "position")
        self.src = getattr(search, "source_layout", search.layout)
        self.military = getattr(search, "military", "connect")
        self.off_road = getattr(search, "off_road", frozenset())
        self.evals = self.cold_batches = 0

    def stopped(self) -> bool:
        return self.should_stop is not None and self.should_stop()

    def close(self):
        if self.pool is not None:
            self.pool.terminate()
            self.pool.join()
            self.pool = None

    def evaluate(self, items, hint, end):
        """items: [(Pattern, ops)] -> [result dict] in input order."""
        out = [{"pattern": p, "ops": ops, "k": len(p.roads), "status": "NONE",
                "achieved": None, "layout": None, "pos": None} for p, ops in items]
        self.evals += len(out)
        if end - time.monotonic() >= cold_need(self.s):
            if self.pool is None:
                self.pool = self.pool_factory()
            self.cold_batches += 1
            dl = end - self.s.exact_repair
            res = self.pool.map(_run_probe, [(r["pattern"], r["k"], i, dl)
                                             for i, r in enumerate(out)])
            for r, c in zip(out, res):
                if c["status"] == "SAT":
                    r.update(status="SAT", achieved=c["achieved"], layout=c["layout"],
                             pos=c["pos"])
        for r in out:
            if hint is None or self.stopped():
                break
            limit = min(WARM_LIMIT_S,
                        end - time.monotonic() - OBJECTIVE_MARGIN_S - self.s.exact_repair)
            if limit < OBJECTIVE_MIN_S:
                break
            st, ach, lay, pos = warm_solve(self.layout, r["pattern"], hint, limit=limit,
                                           threads=self.threads,
                                           exact_repair=self.s.exact_repair,
                                           fillers=self.fillers,
                                           closure=getattr(self.s, "closure", "bfs"),
                                           witness=getattr(self.s, "road_witness", False))
            if st == "SAT" and (r["status"] != "SAT" or ach < r["achieved"]):
                r.update(status="SAT", achieved=ach, layout=lay, pos=pos)
        return out

    def legal(self, lay) -> bool:
        return legality_check(lay, self.src, military=self.military,
                              off_road=self.off_road).status == "valid"

    def climb(self, start, end, rng) -> dict:
        """(1+lambda) hill climb from one start until `end`."""
        ach, lay, skel = start
        th = lay.townhall.footprint
        parent = {"roads": skel, "achieved": ach, "layout": lay,
                  "pos": incumbent_positions(self.layout, lay, self.fillers)}
        seen = {skel}
        lam = max(1, self.s.workers)
        row = {"start": ach, "k": len(skel), "generations": 0, "accepted": 0,
               "best": ach}
        while not self.stopped():
            left = end - time.monotonic()
            if left < OBJECTIVE_MIN_S + OBJECTIVE_MARGIN_S + self.s.exact_repair:
                break
            if parent["pos"] is None and left < cold_need(self.s):
                break   # no warm hint and no room for a cold probe
            items = []
            pr = sm.prune(parent["roads"], th, self.region, parent["layout"].roads)
            if pr is not None and pr not in seen:
                seen.add(pr)
                items.append((Pattern(th, pr, {"n6": "prune"}), ["prune"]))
            guard = 0
            while len(items) < lam and guard < 50 * lam:
                guard += 1
                m = sm.mutate(parent["roads"], th, self.region, rng,
                              n_ops=2 if rng.random() < TWO_MOVES_P else 1)
                if m is None or m[0] in seen:
                    continue
                seen.add(m[0])
                items.append((Pattern(th, m[0], {"n6": "mut"}), m[1]))
            if not items:
                break
            for p, _ in items:
                _check_pattern(p, set(self.region), len(p.roads))
            row["generations"] += 1
            res = self.evaluate(items, parent["pos"], end)
            sat = sorted((r for r in res if r["status"] == "SAT"),
                         key=lambda r: (r["achieved"], r["k"]))
            for r in sat:
                if r["achieved"] > parent["achieved"]:
                    break
                if not self.legal(r["layout"]):
                    continue
                parent = {"roads": r["pattern"].roads, "achieved": r["achieved"],
                          "layout": r["layout"], "pos": r["pos"]}
                row["accepted"] += 1
                row["best"] = min(row["best"], r["achieved"])
                if r["achieved"] < self.best:
                    self.best = r["achieved"]
                    if self.on_improvement is not None:
                        self.on_improvement(r["layout"], r["k"], r["achieved"])
                break
        return row


def polish_mutation(search, incumbent: Layout, achieved: int, end: float,
                    solved=(), on_improvement=None, should_stop=None, *,
                    starts: int = 1, init_args=None, pool_factory=None,
                    seed: int = 0) -> dict:
    """Hill-climb from `starts` start networks until `end` (monotonic).
    `search` is the RoadsFirstSearch; `init_args` are its worker-pool
    initializer arguments (cold half). Publishes strict improvements only."""
    t0 = time.monotonic()
    if pool_factory is None:
        def pool_factory():
            return multiprocessing.Pool(max(1, search.workers), initializer=_worker_init,
                                        initargs=init_args)
    plan = plan_starts(incumbent, achieved, list(solved), max(1, starts))
    c = _Climb(search, achieved, on_improvement, should_stop, pool_factory)
    rows = []
    try:
        for i, st in enumerate(plan):
            if c.stopped():
                break
            left = end - time.monotonic()
            rows.append(c.climb(st, time.monotonic() + left / (len(plan) - i),
                                random.Random(seed + i)))
    finally:
        c.close()
    return {"before": achieved, "after": c.best, "starts": rows, "evals": c.evals,
            "cold_batches": c.cold_batches, "wall_s": round(time.monotonic() - t0, 1)}
