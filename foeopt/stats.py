"""City statistics shown to the player: roads, road efficiency, coverage."""
from __future__ import annotations

from foeopt.model import Layout
from foeopt.validate import unsatisfied


def _pct(n: float, d: float) -> float:
    return round(100 * n / d, 1)


def city_stats(layout: Layout) -> dict:
    cells = layout.region.cells
    area = len(cells)
    occ = layout.occupied_cells()
    if layout.townhall is not None:
        occ |= layout.townhall.footprint.cells()
    building_cells = len(occ & cells)
    road_cells = len(set(layout.roads) & cells)
    free = area - building_cells - road_cells

    bad = {b.entity_id for b in unsatisfied(layout)}
    needing = layout.road_needing()
    connected = [b for b in needing if b.entity_id not in bad]
    # Road efficiency: how much road-frontage a built road cell serves.
    # A building contributes shorter side * road level / 2.
    served = sum(min(b.footprint.width, b.footprint.length) * b.road_level / 2
                 for b in connected)
    eff = _pct(served, road_cells) if road_cells and connected else None
    return {
        "area": area,
        "roads": road_cells,
        "road_efficiency_pct": eff,
        "buildings_pct": _pct(building_cells, area) if area else 0.0,
        "roads_pct": _pct(road_cells, area) if area else 0.0,
        "free_pct": _pct(free, area) if area else 0.0,
        "free_cells": free,
        "with_roads": len(needing),
        "without_roads": len([b for b in layout.buildings
                              if not b.needs_road and not b.is_townhall]),
        "unconnected": sorted(bad),
    }
