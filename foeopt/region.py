from __future__ import annotations

from foeopt.model import Region


def build_region(unlocked_areas: list[dict]) -> Region:
    cells: set[tuple[int, int]] = set()
    for area in unlocked_areas:
        x0 = area.get("x", 0)
        y0 = area.get("y", 0)
        w = area.get("width", 0)
        length = area.get("length", 0)
        for dx in range(w):
            for dy in range(length):
                cells.add((x0 + dx, y0 + dy))
    return Region(cells=frozenset(cells))
