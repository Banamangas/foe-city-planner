from __future__ import annotations

import math
import random

from foeopt.model import Building, Layout
from foeopt.localsearch import free_cells, move_building, swap_buildings


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
