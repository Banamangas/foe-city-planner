from __future__ import annotations

import math
import random
import time

from foeopt.model import Building, Layout
from foeopt.localsearch import OptimizeResult, free_cells, move_building, swap_buildings


def _mst_length(points: list[tuple[float, float]]) -> float:
    n = len(points)
    if n <= 1:
        return 0.0
    in_tree = [False] * n
    dist = [math.inf] * n
    dist[0] = 0.0
    total = 0.0
    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: dist[i])
        in_tree[u] = True
        total += dist[u]
        ux, uy = points[u]
        for v in range(n):
            if not in_tree[v]:
                d = abs(ux - points[v][0]) + abs(uy - points[v][1])
                if d < dist[v]:
                    dist[v] = d
    return total


def _centroid(b: Building) -> tuple[float, float]:
    return (b.footprint.x + b.footprint.width / 2,
            b.footprint.y + b.footprint.length / 2)


def mst_cost(layout: Layout) -> float:
    points = [_centroid(b) for b in layout.road_needing()]
    if layout.townhall is not None:
        points.append(_centroid(layout.townhall))
    return _mst_length(points)


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


_T_FLOOR = 1e-9
_COOLING = 0.9995


def _initial_temperature(layout: Layout, rng: random.Random, samples: int = 20) -> float:
    base = mst_cost(layout)
    deltas: list[float] = []
    for _ in range(samples):
        cand = random_move(layout, rng)
        if cand is not None:
            deltas.append(abs(mst_cost(cand) - base))
    positive = [d for d in deltas if d > 0]
    return (sum(positive) / len(positive)) if positive else 1.0


def anneal(
    layout: Layout,
    *,
    seed: int = 0,
    budget_seconds: float = 30.0,
    max_iters: int = 1_000_000,
) -> OptimizeResult:
    from foeopt.router import RouteError, route
    from foeopt.validate import is_valid

    rng = random.Random(seed)
    temperature = _initial_temperature(layout, rng)

    state = layout
    cost = mst_cost(state)
    best = layout
    best_roads = len(layout.roads)
    best_proxy = cost
    moves_applied = 0

    deadline = time.monotonic() + budget_seconds
    for _ in range(max_iters):
        if time.monotonic() >= deadline:
            break
        cand = random_move(state, rng)
        if cand is None:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        new_cost = mst_cost(cand)
        delta = new_cost - cost
        if delta < 0 or rng.random() < math.exp(-delta / max(temperature, _T_FLOOR)):
            state, cost = cand, new_cost
            if new_cost < best_proxy:
                best_proxy = new_cost
                try:
                    roads = route(state)
                except RouteError:
                    roads = None
                if roads is not None:
                    confirmed = Layout(state.region, state.buildings,
                                       state.townhall, roads)
                    if is_valid(confirmed) and len(roads) < best_roads:
                        best, best_roads = confirmed, len(roads)
                        moves_applied += 1
        temperature = max(temperature * _COOLING, _T_FLOOR)

    return OptimizeResult(layout=best, moves_applied=moves_applied)
