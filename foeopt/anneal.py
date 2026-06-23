from __future__ import annotations

import math
import random
import time

from foeopt.model import Building, Layout
from foeopt.localsearch import (
    OptimizeResult,
    _move_with_free,
    _swap_with_free,
    free_cells,
)

_T_FLOOR = 1e-9
_COOLING = 0.9995
_WARMUP_SAMPLES = 12


def _random_move_free(
    layout: Layout, rng: random.Random, free: set[tuple[int, int]]
) -> tuple[Layout, set[tuple[int, int]]] | None:
    """One random move, returning (cand, cand_free) using the maintained `free`
    set. Draws from `rng` in the exact same sequence as random_move(), so the SA
    trajectory is identical whether or not the free set is supplied."""
    movable = [b for b in layout.buildings if not b.is_townhall]
    if not movable:
        return None

    if rng.random() < 0.5:
        by_size: dict[tuple[int, int], list[Building]] = {}
        for b in movable:
            by_size.setdefault((b.footprint.width, b.footprint.length), []).append(b)
        groups = [g for g in by_size.values() if len(g) >= 2]
        if groups:
            group = rng.choice(groups)
            a, b = rng.sample(group, 2)
            return _swap_with_free(layout, a, b, free)

    ordered = sorted(free)
    if not ordered:
        return None
    b = rng.choice(movable)
    x, y = rng.choice(ordered)
    return _move_with_free(layout, b, x, y, free)


def random_move(layout: Layout, rng: random.Random) -> Layout | None:
    res = _random_move_free(layout, rng, free_cells(layout))
    return res[0] if res is not None else None


def anneal(
    layout: Layout,
    *,
    seed: int = 0,
    budget_seconds: float = 30.0,
    max_iters: int = 1_000_000,
) -> OptimizeResult:
    """Simulated annealing on the true road count (len(route(candidate))).

    Starts from the input layout, routes it once to seed the cost (capturing any
    free roads-only improvement), and accepts worsening moves probabilistically to
    escape the plateau where hill-climbing stops. The returned `best` is anchored
    at the input and only replaced by a valid layout with strictly fewer roads, so
    the result is never worse than the input. Deterministic for a fixed seed.
    """
    from foeopt.router import RouteError, route
    from foeopt.validate import is_valid

    rng = random.Random(seed)

    best = layout
    best_roads = len(layout.roads)
    moves_applied = 0
    moves_evaluated = 0   # candidate moves scored in the main loop (route() calls)

    # Route the input placement to seed the SA's current cost (also captures the
    # roads-only "Phase 1" win when the input network is not minimal).
    try:
        roads0 = route(layout)
        state = Layout(layout.region, layout.buildings, layout.townhall, roads0)
        cur = len(roads0)
        if is_valid(state) and cur < best_roads:
            best, best_roads = state, cur
            moves_applied = 1
    except RouteError:
        state, cur = layout, len(layout.roads)

    # Free-cell set of the current state, maintained incrementally: _random_move_free
    # returns each candidate's free set by an O(footprint) delta, and route() reuses
    # it instead of rebuilding occupancy from all buildings.
    state_free = free_cells(state)

    # Initial temperature: mean of positive |Δroads| over a few sampled routed
    # moves (small integer deltas); fallback 1.0.
    deltas: list[int] = []
    for _ in range(_WARMUP_SAMPLES):
        moved = _random_move_free(state, rng, state_free)
        if moved is None:
            continue
        cand, cand_free = moved
        try:
            d = abs(len(route(cand, free=cand_free)) - cur)
        except RouteError:
            continue
        if d > 0:
            deltas.append(d)
    temperature = (sum(deltas) / len(deltas)) if deltas else 1.0
    deadline = time.monotonic() + budget_seconds
    for _ in range(max_iters):
        if time.monotonic() >= deadline:
            break
        moved = _random_move_free(state, rng, state_free)
        if moved is None:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        cand, cand_free = moved
        moves_evaluated += 1  # one candidate scored (the route() call below)
        try:
            roads = route(cand, free=cand_free)
        except RouteError:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        delta = len(roads) - cur
        if delta < 0 or rng.random() < math.exp(-delta / max(temperature, _T_FLOOR)):
            state = Layout(cand.region, cand.buildings, cand.townhall, roads)
            cur = len(roads)
            state_free = cand_free   # accepted: the candidate's free set is now current
            if is_valid(state) and cur < best_roads:
                best, best_roads = state, cur
                moves_applied += 1
        temperature = max(temperature * _COOLING, _T_FLOOR)

    return OptimizeResult(layout=best, moves_applied=moves_applied,
                          moves_evaluated=moves_evaluated)
