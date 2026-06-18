from __future__ import annotations

from collections.abc import Iterable


class Grid:
    """Occupancy over a [0,width) x [0,height) box. `blocked` cells (region
    holes) are unavailable from the start; `occupy` adds placed footprints and
    `reserve` adds road corridors — both make cells unavailable for placement."""

    def __init__(self, width: int, height: int, blocked: set[tuple[int, int]]):
        self.width = width
        self.height = height
        self._unavail: set[tuple[int, int]] = set(blocked)

    def is_available(self, cell: tuple[int, int]) -> bool:
        return cell not in self._unavail

    def fits(self, x: int, y: int, w: int, l: int) -> bool:
        if x < 0 or y < 0 or x + w > self.width or y + l > self.height:
            return False
        for dx in range(w):
            for dy in range(l):
                if (x + dx, y + dy) in self._unavail:
                    return False
        return True

    def occupy(self, x: int, y: int, w: int, l: int) -> None:
        for dx in range(w):
            for dy in range(l):
                self._unavail.add((x + dx, y + dy))

    def reserve(self, cells: Iterable[tuple[int, int]]) -> None:
        self._unavail.update(cells)


def first_fit(grid: Grid, w: int, l: int) -> tuple[int, int] | None:
    for y in range(grid.height):
        for x in range(grid.width):
            if grid.fits(x, y, w, l):
                return (x, y)
    return None
