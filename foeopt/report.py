from __future__ import annotations

from foeopt.model import Layout
from foeopt.validate import unsatisfied


def road_diff(current: dict, optimized: dict) -> dict:
    remove = [
        {"x": x, "y": y, "level": lvl}
        for (x, y), lvl in sorted(current.items())
        if (x, y) not in optimized
    ]
    add = [
        {"x": x, "y": y, "level": lvl}
        for (x, y), lvl in sorted(optimized.items())
        if current.get((x, y)) != lvl
    ]
    return {"remove": remove, "add": add}


def stats(layout: Layout, optimized_roads: dict) -> dict:
    probe = Layout(layout.region, layout.buildings, layout.townhall, optimized_roads)
    bad = unsatisfied(probe)
    needing = len(layout.road_needing())
    return {
        "current_roads": len(layout.roads),
        "optimized_roads": len(optimized_roads),
        "tiles_saved": len(layout.roads) - len(optimized_roads),
        "road_needing": needing,
        "satisfied": needing - len(bad),
        "unsatisfied": len(bad),
    }


def road_estimate(layout: Layout) -> int:
    """Target road-tile count: a road serves a double row of buildings, so the
    minimal road is ~ (sum of each road-needing building's shorter side) / 2."""
    return sum(min(b.footprint.width, b.footprint.length)
               for b in layout.road_needing()) // 2
