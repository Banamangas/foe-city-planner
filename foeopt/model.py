from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Footprint:
    x: int
    y: int
    width: int
    length: int

    def cells(self) -> set[tuple[int, int]]:
        return {
            (self.x + dx, self.y + dy)
            for dx in range(self.width)
            for dy in range(self.length)
        }

    def border_cells(self) -> set[tuple[int, int]]:
        own = self.cells()
        border: set[tuple[int, int]] = set()
        for (cx, cy) in own:
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if (nx, ny) not in own:
                    border.add((nx, ny))
        return border


@dataclass
class Building:
    entity_id: int
    cityentity_id: str
    type: str
    footprint: Footprint
    needs_road: bool
    road_level: int
    is_townhall: bool
    set_id: str | None
    chain_id: str | None
    name: str


@dataclass(frozen=True)
class Region:
    cells: frozenset[tuple[int, int]]

    def contains_cell(self, c: tuple[int, int]) -> bool:
        return c in self.cells

    def contains_footprint(self, fp: Footprint) -> bool:
        return fp.cells() <= self.cells


@dataclass
class Layout:
    region: Region
    buildings: list[Building]
    townhall: Building | None
    roads: dict[tuple[int, int], int] = field(default_factory=dict)

    def occupied_cells(self) -> set[tuple[int, int]]:
        occ: set[tuple[int, int]] = set()
        for b in self.buildings:
            occ |= b.footprint.cells()
        return occ

    def road_needing(self) -> list[Building]:
        return [b for b in self.buildings if b.needs_road and not b.is_townhall]
