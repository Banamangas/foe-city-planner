from __future__ import annotations

import math
import random
import time

from foeopt.model import Building, Layout
from foeopt.localsearch import OptimizeResult, free_cells, move_building, swap_buildings

_T_FLOOR = 1e-9
_COOLING = 0.9995
_WARMUP_SAMPLES = 12


def random_move(layout: Layout, rng: random.Random) -> Layout | None:
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
            return swap_buildings(layout, a.entity_id, b.entity_id)

    free = sorted(free_cells(layout))
    if not free:
        return None
    b = rng.choice(movable)
    x, y = rng.choice(free)
    return move_building(layout, b.entity_id, x, y)


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

    # Initial temperature: mean of positive |Δroads| over a few sampled routed
    # moves (small integer deltas); fallback 1.0.
    deltas: list[int] = []
    for _ in range(_WARMUP_SAMPLES):
        cand = random_move(state, rng)
        if cand is None:
            continue
        try:
            d = abs(len(route(cand)) - cur)
        except RouteError:
            continue
        if d > 0:
            deltas.append(d)
    temperature = (sum(deltas) / len(deltas)) if deltas else 1.0
    deadline = time.monotonic() + budget_seconds
    for _ in range(max_iters):
        if time.monotonic() >= deadline:
            break
        cand = random_move(state, rng)
        if cand is None:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        try:
            roads = route(cand)
        except RouteError:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        delta = len(roads) - cur
        if delta < 0 or rng.random() < math.exp(-delta / max(temperature, _T_FLOOR)):
            state = Layout(cand.region, cand.buildings, cand.townhall, roads)
            cur = len(roads)
            if is_valid(state) and cur < best_roads:
                best, best_roads = state, cur
                moves_applied += 1
        temperature = max(temperature * _COOLING, _T_FLOOR)

    return OptimizeResult(layout=best, moves_applied=moves_applied)
