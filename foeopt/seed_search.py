"""Squeeze the road count out of a *fixed* feasible skeleton by re-solving it
under several CP-SAT random seeds.

`probe()` is a pure feasibility model with no objective, so the placement it
returns -- and therefore the `route()` road count of the resulting layout --
is an arbitrary satisfying assignment that varies with CP-SAT's random seed.
Measured spread on real darkzig skeletons was up to 10 roads for one fixed
skeleton, and re-seeding took a lane skeleton from 103 to 102 and two others
from 102 to 99 (see tasks/lessons.md, 2026-07-23). This module packages that
lever: given a skeleton already known (or suspected) to be feasible, try N
seeds and keep the placement with the fewest roads that is a LEGAL, validated
full layout.

Distinct from `foeopt.polish`, which moves *buildings* (repack/anneal); this
holds the placement's skeleton fixed and only varies the solver.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from foeopt.model import Layout
from foeopt.roads_first import Pattern, probe, validate
from foeopt.validate import canonical_dims, rotated_buildings


@dataclass
class SeedMinResult:
    achieved: int | None          # fewest roads found across the seeds, or None
    layout: Layout | None         # the validated layout that achieved it
    seed: int | None              # the seed that produced it
    n_legal: int                  # seeds that yielded a legal validated layout
    n_tried: int                  # seeds attempted


def _solve_one(layout: Layout, pattern: Pattern, seed: int, *,
               probe_limit: float, probe_workers: int = 1):
    """Solve `pattern` under one CP-SAT seed. Returns (achieved, layout) for a
    legal validated full layout, else None. Legality (no rotated buildings) is
    re-checked explicitly -- FoE forbids rotation, and a rotated 'record' has
    been retracted before, so this gate is belt-and-braces on top of validate."""
    st, pos = probe(pattern, set(layout.region.cells), layout.road_needing(),
                    probe_limit=probe_limit, probe_workers=probe_workers,
                    solver_overrides={"random_seed": seed})
    if st != "SAT":
        return None
    vst, vlay, achieved = validate(layout, pattern, pos)
    if vst != "OK":
        return None
    if rotated_buildings(vlay, canonical_dims(layout)):
        return None
    return achieved, vlay


def seed_minimize_roads(layout: Layout, pattern: Pattern, *,
                        seeds: Iterable[int] = range(12),
                        probe_limit: float = 60.0,
                        probe_workers: int = 1,
                        should_stop=None) -> SeedMinResult:
    """Re-solve `pattern` across `seeds` and keep the lowest legal road count.

    Sequential by design: each probe already uses `probe_workers` CP-SAT
    threads, and a caller that wants to fan out across many patterns (e.g. a
    batch screen) parallelizes at that outer level. On a tie the earliest seed
    wins, so the result is deterministic for a fixed `seeds` order.
    """
    best_achieved: int | None = None
    best_layout: Layout | None = None
    best_seed: int | None = None
    n_legal = n_tried = 0
    for seed in seeds:
        # Budget/cancel check BEFORE each solve. Without it this loop is
        # bounded by len(seeds) * probe_limit rather than by the caller's
        # remaining budget -- measured at a 120 s box, seeds=12 took 281 s
        # (2.34x) and bought one road. It also made the Stop button inert
        # for the whole polish phase.
        if should_stop is not None and should_stop():
            break
        n_tried += 1
        got = _solve_one(layout, pattern, seed,
                         probe_limit=probe_limit, probe_workers=probe_workers)
        if got is None:
            continue
        achieved, vlay = got
        n_legal += 1
        if best_achieved is None or achieved < best_achieved:
            best_achieved, best_layout, best_seed = achieved, vlay, seed
    return SeedMinResult(best_achieved, best_layout, best_seed, n_legal, n_tried)
