"""Prototype: position-indexed (symmetry-free) consumer placement vs today's probe().

Today's probe() has one (x, y) item per building + NoOverlap2D, so N identical
buildings are N interchangeable items (FR17: 52 3x3s -> 52! symmetric
assignments), which is poison for proving and slow for finding. The classic
alternative indexes by POSITION: one boolean per (size class, anchor), with
    sum_a z[s, a] == count[s]            for each size class
    sum_{(s,a) covering c} z[s, a] <= 1   for each cell
No item identity, so no permutation symmetry.

Run on the same skeletons as today's probe at the same budget and threads; report
SAT/UNSAT/UNKNOWN per skeleton for both, and route() of any SAT (fillers via the
production validate()).

Usage: exp_position_model.py CITY.json K N_PATTERNS LIMIT THREADS [GEN_SEED]
"""
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foeopt.loader import load_layout
from foeopt.model import Footprint
from foeopt.roads_first import (_anchor_candidates, generate_nonuniform_patterns,
                                prefilter, probe, validate)


def position_probe(pattern, region, consumers, limit, threads, seed=0):
    from ortools.sat.python import cp_model
    blocked = set(pattern.roads) | set(pattern.th.cells())
    by_size = defaultdict(list)
    for b in consumers:
        by_size[(b.footprint.width, b.footprint.length)].append(b)
    m = cp_model.CpModel()
    cover = defaultdict(list)
    z = {}
    for (w, l), bs in by_size.items():
        opts = _anchor_candidates(bs[0], region, blocked, pattern.roads)
        if len(opts) < len(bs):
            return "UNSAT", None
        lits = []
        for (x, y) in opts:
            v = m.NewBoolVar("")
            z[(w, l, x, y)] = v
            lits.append(v)
            for c in Footprint(x, y, w, l).cells():
                cover[c].append(v)
        m.Add(sum(lits) == len(bs))
    for c, vs in cover.items():
        if len(vs) > 1:
            m.AddAtMostOne(vs)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = threads
    s.parameters.max_time_in_seconds = limit
    s.parameters.random_seed = seed
    st = s.Solve(m)
    if st == cp_model.INFEASIBLE:
        return "UNSAT", None
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return "UNKNOWN", None
    # assign entity ids to chosen anchors per size class (arbitrary: identical)
    pos = {}
    chosen = defaultdict(list)
    for (w, l, x, y), v in z.items():
        if s.Value(v):
            chosen[(w, l)].append((x, y))
    for size, bs in by_size.items():
        for b, (x, y) in zip(bs, sorted(chosen[size])):
            pos[b.entity_id] = (x, y, size[0], size[1])
    return "SAT", pos


def main(argv):
    city, k, n, limit, threads = argv[0], int(argv[1]), int(argv[2]), float(argv[3]), int(argv[4])
    gen_seed = int(argv[5]) if len(argv) > 5 else 0
    L = load_layout(city)
    region = set(L.region.cells)
    cons = L.road_needing()
    fillers = [b for b in L.buildings if not b.needs_road and not b.is_townhall]
    tw, tl = L.townhall.footprint.width, L.townhall.footprint.length
    pats = generate_nonuniform_patterns(region, tw, tl, k, random.Random(gen_seed), 60,
                                        th_mode="full", quality_index_band=(3, 4))
    pats = [p for p in pats if prefilter(p, region, cons, fillers) is None][:n]
    print(f"{city} k={k} patterns={len(pats)} limit={limit}s threads={threads}", flush=True)
    tally = {"item": defaultdict(int), "position": defaultdict(int)}
    for i, p in enumerate(pats):
        row = {"i": i}
        for name, fn in (("item", lambda: probe(p, region, cons, probe_limit=limit,
                                                 probe_workers=threads)),
                         ("position", lambda: position_probe(p, region, cons, limit, threads))):
            t = time.monotonic()
            st, pos = fn()
            row[name] = st
            row[name + "_s"] = round(time.monotonic() - t, 1)
            tally[name][st] += 1
            if st == "SAT":
                vs, _lay, ach = validate(L, p, pos, exact_repair=5)
                row[name + "_validate"] = vs
                row[name + "_achieved"] = ach
        print(json.dumps(row), flush=True)
    print(json.dumps({k: dict(v) for k, v in tally.items()}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
