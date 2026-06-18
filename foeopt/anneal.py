from __future__ import annotations

import math

from foeopt.model import Building, Layout


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
