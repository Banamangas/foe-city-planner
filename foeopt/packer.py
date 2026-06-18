from __future__ import annotations

from dataclasses import dataclass

from foeopt.model import Building, Layout, Region


@dataclass
class PackConfig:
    orientation: str   # "h" (horizontal road rows) — only mode in Phase 2
    spacing: int       # rows between corridor lines
    trunk_x: int       # column for the vertical connecting trunk


@dataclass
class PackResult:
    layout: Layout
    unplaced: list[Building]


def classify(layout: Layout) -> tuple[Building, list[Building], list[Building]]:
    if layout.townhall is None:
        raise ValueError("layout has no townhall")
    consumers = [b for b in layout.buildings if b.needs_road and not b.is_townhall]
    fillers = [b for b in layout.buildings if not b.needs_road and not b.is_townhall]
    return layout.townhall, consumers, fillers


def bbox(region: Region) -> tuple[int, int]:
    xs = [c[0] for c in region.cells]
    ys = [c[1] for c in region.cells]
    return (max(xs) + 1, max(ys) + 1)
