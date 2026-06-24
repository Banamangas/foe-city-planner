from __future__ import annotations

from foeopt.model import Building, Layout

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


# Layout-quality rules (placement grading), distinct from validity in validate.py.
# These DESCRIBE good Forge-of-Empires placement; they are measured/reported, not
# enforced — see tasks/lessons.md on why optimizing the packer toward adjacency
# proxies has historically hurt the real road-count objective.


def filler_road_adjacencies(layout: Layout) -> list[Building]:
    """Rule 1 violations: a building that does NOT need a road must not sit next
    to one. Returns the offending fillers (orthogonally adjacent to a road tile),
    sorted by entity_id.

    The Townhall is exempt — it never needs a road, but the network roots at its
    border, so it is always road-adjacent by design. Road-needing consumers are
    of course allowed (and required) to touch a road.
    """
    roads = layout.roads
    bad = [
        b
        for b in layout.buildings
        if not b.is_townhall
        and not b.needs_road
        and any(c in roads for c in b.footprint.border_cells())
    ]
    return sorted(bad, key=lambda b: b.entity_id)


def _occupancy(layout: Layout) -> dict[tuple[int, int], int]:
    occ: dict[tuple[int, int], int] = {}
    for b in layout.buildings:
        for c in b.footprint.cells():
            occ[c] = b.entity_id
    return occ


def underused_roads(layout: Layout) -> list[tuple[int, int]]:
    """Rule 2 violations: a road tile should be adjacent to >=2 buildings (the
    double-row ideal). A tile touching exactly 1 building is tolerated only as a
    junction — its other 3 orthogonal neighbours are all roads. Everything else
    (0 buildings, or 1 building without being a junction) is flagged.

    The Townhall counts as a building here. Returns offending road cells, sorted.
    """
    roads = layout.roads
    occ = _occupancy(layout)
    bad: list[tuple[int, int]] = []
    for (rx, ry) in roads:
        building_ids: set[int] = set()
        road_neighbours = 0
        for dx, dy in _ORTHO:
            n = (rx + dx, ry + dy)
            if n in roads:
                road_neighbours += 1
            elif n in occ:
                building_ids.add(occ[n])
        n_buildings = len(building_ids)
        if n_buildings >= 2:
            continue
        if n_buildings == 1 and road_neighbours == 3:
            continue  # junction: 3 road-neighbours + 1 building is acceptable
        bad.append((rx, ry))
    return sorted(bad)


def quality_report(layout: Layout) -> dict[str, int]:
    """Counts of Rule 1 / Rule 2 violations for a placed, routed layout."""
    fillers = filler_road_adjacencies(layout)
    roads_bad = underused_roads(layout)
    n_fillers = sum(1 for b in layout.buildings if not b.is_townhall and not b.needs_road)
    return {
        "filler_road_adjacent": len(fillers),   # Rule 1 violations
        "fillers_total": n_fillers,
        "underused_roads": len(roads_bad),       # Rule 2 violations
        "roads_total": len(layout.roads),
    }


def format_quality(layout: Layout) -> str:
    """One-line human summary for the CLI."""
    q = quality_report(layout)
    return (
        f"placement quality: fillers touching a road {q['filler_road_adjacent']}"
        f"/{q['fillers_total']} (rule 1) | "
        f"under-used roads {q['underused_roads']}/{q['roads_total']} (rule 2)"
    )
