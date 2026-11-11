from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache


# Footprint geometry is a pure function of (x, y, width, length). The search
# routes thousands of candidate layouts that differ by a single building, so the
# same footprints are queried over and over; memoizing the cell/border sets turns
# those repeats into O(1) lookups. Keyed by the raw ints (not the Footprint) so
# the cache is shared across equal footprints regardless of identity. Cached
# frozensets are built by the exact same construction as the originals, so
# membership and iteration order are byte-for-byte identical (a golden-corpus
# oracle over route() guards this — see tests/test_router.py).
@lru_cache(maxsize=1 << 17)
def _footprint_cells(x: int, y: int, width: int, length: int) -> frozenset[tuple[int, int]]:
    return frozenset(
        (x + dx, y + dy) for dx in range(width) for dy in range(length)
    )


@lru_cache(maxsize=1 << 17)
def _footprint_border(x: int, y: int, width: int, length: int) -> frozenset[tuple[int, int]]:
    own = _footprint_cells(x, y, width, length)
    border: set[tuple[int, int]] = set()
    for (cx, cy) in own:
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if (nx, ny) not in own:
                border.add((nx, ny))
    return frozenset(border)


@dataclass(frozen=True)
class Footprint:
    x: int
    y: int
    width: int
    length: int

    def cells(self) -> frozenset[tuple[int, int]]:
        return _footprint_cells(self.x, self.y, self.width, self.length)

    def border_cells(self) -> frozenset[tuple[int, int]]:
        return _footprint_border(self.x, self.y, self.width, self.length)


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
    # Catalog chain linkPositions: rectangles (dx0, dy0, dx1, dy1), inclusive,
    # relative to this building's top-left, where the next chain member sits.
    link_positions: tuple[tuple[int, int, int, int], ...] = ()
    # Composite (a linked chain placed as one rigid block, see foeopt.chains):
    # `members` are (building, dx, dy) offsets from the block's top-left, and
    # `contact` the block-relative cells where a road counts as touching it
    # (only the road-needing member's edge). None/() for ordinary buildings.
    members: tuple = ()
    contact: frozenset[tuple[int, int]] | None = None


def contact_cells(b: "Building", x: int, y: int) -> frozenset[tuple[int, int]]:
    """Cells where a road touches `b` if `b` is anchored at (x, y): its whole
    border, or only the composite's declared contact edge."""
    if b.contact is None:
        return _footprint_border(x, y, b.footprint.width, b.footprint.length)
    return frozenset((x + dx, y + dy) for dx, dy in b.contact)


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
    # Whether catalog metadata (chains, road levels) was available at load time.
    # Only meaningful on a loaded (reference) layout; copies keep the default.
    catalog_known: bool = True

    def occupied_cells(self) -> set[tuple[int, int]]:
        occ: set[tuple[int, int]] = set()
        for b in self.buildings:
            occ |= b.footprint.cells()
        return occ

    def road_needing(self) -> list[Building]:
        return [b for b in self.buildings if b.needs_road and not b.is_townhall]
