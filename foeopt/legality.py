"""Full game-legality check of a finished layout against the city it came from.

`validate.is_valid` checks only that every road-needing building touches a road
connected to the Town Hall. That is a helper. This module is the authoritative
gate. It reports structured violations, plus checks it could not perform
because metadata was missing (`unknown`).

Game rules (user-confirmed 2026-11-11):
- Buildings keep their inventory and orientation (no rotation). They do not
  overlap, they stay in the unlocked region, and they never sit on a road.
- Two-lane roads are 2x2 tiles. A two-lane (road_level 2) building needs a
  path made ENTIRELY of two-lane cells from the Town Hall to its border.
- Chain members must sit at the catalog linkPositions of the member they link
  to. Every link active in the input must still be active in the output.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from foeopt.model import Building, Layout
from foeopt.validate import canonical_dims, rotated_buildings, unsatisfied

LEGALITY_VERSION = 1
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
MILITARY_POLICIES = ("connect", "unconnected")


@dataclass
class LegalityReport:
    violations: list[dict] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    version: int = LEGALITY_VERSION

    @property
    def ok(self) -> bool:
        """True only when nothing is violated AND nothing is unknown."""
        return not self.violations and not self.unknown

    @property
    def status(self) -> str:
        if self.violations:
            return "invalid"
        return "unknown" if self.unknown else "valid"

    def as_dict(self) -> dict:
        return {"status": self.status, "version": self.version,
                "violations": self.violations, "unknown": self.unknown}


def two_lane_tiles(roads: dict[tuple[int, int], int]) -> list[tuple[int, int]] | None:
    """Split the level-2 cells into disjoint 2x2 tiles (top-left anchors).
    Returns None if they cannot be split. Greedy in row-major order is exact:
    the first uncovered cell must be the top-left of its tile."""
    left = {c for c, lvl in roads.items() if lvl >= 2}
    tiles = []
    for (x, y) in sorted(left, key=lambda c: (c[1], c[0])):
        if (x, y) not in left:
            continue
        sq = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
        if not sq <= left:
            return None
        left -= sq
        tiles.append((x, y))
    return tiles


def two_lane_connected(layout: Layout) -> set[tuple[int, int]]:
    """Level-2 cells reachable from the Town Hall border via level-2 cells only."""
    if layout.townhall is None:
        return set()
    lane = {c for c, lvl in layout.roads.items() if lvl >= 2}
    src = [c for c in layout.townhall.footprint.border_cells() if c in lane]
    seen, q = set(src), deque(src)
    while q:
        cx, cy = q.popleft()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in lane and n not in seen:
                seen.add(n)
                q.append(n)
    return seen


def chain_links(layout: Layout) -> set[tuple[int, int]]:
    """Active chain links (from_entity, to_entity): `to` occupies exactly one of
    `from`'s linkPositions rectangles and shares its chain_id."""
    by_chain: dict[str, list[Building]] = {}
    for b in layout.buildings:
        if b.chain_id:
            by_chain.setdefault(b.chain_id, []).append(b)
    links = set()
    for members in by_chain.values():
        for a in members:
            for (dx0, dy0, dx1, dy1) in a.link_positions:
                rx, ry = a.footprint.x + dx0, a.footprint.y + dy0
                rw, rl = dx1 - dx0 + 1, dy1 - dy0 + 1
                for b in members:
                    fb = b.footprint
                    if b is not a and (fb.x, fb.y, fb.width, fb.length) == (rx, ry, rw, rl):
                        links.add((a.entity_id, b.entity_id))
    return links


def two_lane_buildings(layout: Layout) -> list[Building]:
    return [b for b in layout.road_needing() if b.road_level >= 2]


def check(layout: Layout, reference: Layout, military: str = "connect") -> LegalityReport:
    """Every rule, against the loaded `reference` city. `military="unconnected"`
    exempts two-lane buildings from the road requirement. It is an explicit
    per-run choice and is reported, never applied silently."""
    if military not in MILITARY_POLICIES:
        raise ValueError(f"military must be one of {MILITARY_POLICIES}")
    rep = LegalityReport()
    v = rep.violations

    ref_ids = sorted(b.entity_id for b in reference.buildings)
    ids = sorted(b.entity_id for b in layout.buildings)
    if ids != ref_ids:
        v.append({"rule": "inventory",
                  "missing": sorted(set(ref_ids) - set(ids)),
                  "extra": sorted(set(ids) - set(ref_ids)),
                  "duplicates": len(ids) - len(set(ids))})
    rot = rotated_buildings(layout, canonical_dims(reference))
    if rot:
        v.append({"rule": "rotated", "entities": [b.entity_id for b in rot]})

    seen: dict[tuple[int, int], int] = {}
    overlap, outside, on_road = set(), set(), set()
    region = reference.region.cells
    for b in layout.buildings:
        for c in b.footprint.cells():
            if c in seen:
                overlap.update((seen[c], b.entity_id))
            seen[c] = b.entity_id
            if c not in region:
                outside.add(b.entity_id)
            if c in layout.roads:
                on_road.add(b.entity_id)
    for rule, ents in (("overlap", overlap), ("out_of_region", outside),
                       ("on_road", on_road)):
        if ents:
            v.append({"rule": rule, "entities": sorted(ents)})
    bad_road = [c for c in layout.roads if c not in region]
    if bad_road:
        v.append({"rule": "road_out_of_region", "cells": sorted(bad_road)[:20]})

    level1 = [b.entity_id for b in unsatisfied(layout) if b.road_level < 2]
    if level1:
        v.append({"rule": "no_road", "entities": sorted(level1)})

    if two_lane_tiles(layout.roads) is None:
        v.append({"rule": "two_lane_not_2x2",
                  "cells": sorted(c for c, l in layout.roads.items() if l >= 2)})
    if military == "connect":
        lane = two_lane_connected(layout)
        bad2 = [b.entity_id for b in two_lane_buildings(layout)
                if not (b.footprint.border_cells() & lane)]
        if bad2:
            v.append({"rule": "two_lane_path", "entities": sorted(bad2)})

    if not getattr(reference, "catalog_known", True):
        rep.unknown.append("chains: no catalog metadata, chain links cannot be checked")
    else:
        broken = chain_links(reference) - chain_links(layout)
        if broken:
            v.append({"rule": "chain_broken", "links": sorted(broken)})
    return rep
