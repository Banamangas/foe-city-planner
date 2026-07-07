from __future__ import annotations

from collections import deque

from foeopt.model import Building, Layout

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def connected_road_cells(layout: Layout) -> set[tuple[int, int]]:
    roads = layout.roads
    if layout.townhall is None:
        return set()
    th_border = layout.townhall.footprint.border_cells()
    sources = [c for c in roads if c in th_border]

    seen: set[tuple[int, int]] = set(sources)
    queue: deque[tuple[int, int]] = deque(sources)
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in roads and n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


def unsatisfied(layout: Layout) -> list[Building]:
    connected = connected_road_cells(layout)
    roads = layout.roads
    bad: list[Building] = []
    for b in layout.road_needing():
        border = b.footprint.border_cells()
        ok = any(
            c in connected and roads[c] >= b.road_level
            for c in border
        )
        if not ok:
            bad.append(b)
    return bad


def is_valid(layout: Layout) -> bool:
    return not unsatisfied(layout)


def canonical_dims(reference: Layout) -> dict[int, tuple[int, int]]:
    """The canonical (width, length) of every building in a reference layout,
    keyed by entity_id. FoE buildings cannot rotate, so the loaded layout's
    ordered dimensions are the only legal orientation for each building."""
    return {b.entity_id: (b.footprint.width, b.footprint.length)
            for b in reference.buildings}


def rotated_buildings(layout: Layout,
                      canonical: dict[int, tuple[int, int]]) -> list[Building]:
    """Buildings placed with their width/length swapped relative to the
    canonical dimensions — illegal, because FoE buildings cannot be rotated.
    `is_valid`/`unsatisfied` check road satisfaction only and are blind to
    orientation, so any NEW placement method must call this against
    `canonical_dims(loaded_layout)` to prove its output is legal. Buildings
    absent from `canonical` are skipped (nothing to compare against)."""
    bad: list[Building] = []
    for b in layout.buildings:
        canon = canonical.get(b.entity_id)
        if canon is None:
            continue
        if (b.footprint.width, b.footprint.length) != canon:
            bad.append(b)
    return bad
