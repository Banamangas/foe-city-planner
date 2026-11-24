"""Export an optimized layout as a v3 city file (Forge Hammer planner format, plan X).

The v3 file has two views of a city: `cityData` (the city as it is in game) and
`mapBuildings` (the planner layout, `{metaId, x, y, era, custom}` per building
INCLUDING streets). On every upload that is not a plan in progress,
`mapBuildings` mirrors cityData exactly: one entry per on-grid entity in
cityData order, x/y = top-left like cityData, a zero coordinate OMITTED like
cityData, era = the entity's cityData era, custom = false. Off-grid entities
(expansion hub, tavern, ships, off_grid) are not in it.

The export (user decisions 2026-11-17, tasks/todo.md plan X):
- the original file, cityData and every other top-level field untouched;
- `mapBuildings` REPLACED by the optimized layout;
- `storedBuildings` REPLACED by exactly the buildings removed in the
  optimizer (plan E `to_store`), at their cityData position;
- buildings added in the optimizer (plan E `added`): custom = true,
  era = currentEra;
- one street entity per street: a level-1 street is one 1x1 entity per cell, a
  two-lane street one 2x2 entity per tile (catalog: every `*CarStreet*` is 2x2
  and provides level 2; cityData stores them as one entity at the tile's
  top-left). A street keeps the metaId/era of the city's street at the same
  cell (1x1) or tile anchor (2x2); new ones take the city's most used street
  of that level.
"""
from __future__ import annotations

import copy
from collections import Counter

from foeopt.catalog import Catalog
from foeopt.loader import _OFF_GRID_TYPES, _bundled_catalog, is_v3
from foeopt.model import Layout


class ExportError(ValueError):
    """The result cannot be written as a v3 file (message is user-facing)."""


def can_export(original: dict) -> bool:
    """True for a FULL v3 upload. Caches made before plan X hold a slim copy
    (no mapBuildings, no eras) and cannot be exported."""
    return is_v3(original) and "mapBuildings" in original and "currentEra" in original


def tile_two_lane(cells) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(2x2 tile anchors, cells that cannot be tiled). Greedy in row-major
    order is exact: the first uncovered cell must be its tile's top-left
    (same argument as legality.two_lane_tiles), so the tiling is unique."""
    left = set(cells)
    tiles, bad = [], []
    for (x, y) in sorted(left, key=lambda c: (c[1], c[0])):
        if (x, y) not in left:
            continue
        sq = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
        if sq <= left:
            left -= sq
            tiles.append((x, y))
        else:
            left.discard((x, y))
            bad.append((x, y))
    return tiles, bad


def _entry(meta_id: str, x: int, y: int, era: str, custom: bool) -> dict:
    """A planner entry, key order and zero-omission as in the uploads."""
    e: dict = {"metaId": meta_id}
    if x:
        e["x"] = x
    if y:
        e["y"] = y
    e["era"] = era
    e["custom"] = custom
    return e


def _normalize(result) -> tuple[dict[int, tuple[int, int]], dict[tuple[int, int], int]]:
    """(entity id -> top-left, road cell -> level) from a Layout or a published
    result dict ({"roads": [[x, y, level?], ...], "buildings": {id: [x, y, w, l]}})."""
    if isinstance(result, Layout):
        return ({b.entity_id: (b.footprint.x, b.footprint.y) for b in result.buildings},
                dict(result.roads))
    if not isinstance(result, dict) or "buildings" not in result or "roads" not in result:
        raise ExportError("the layout must have `buildings` and `roads`")
    pos = {int(k): (int(v[0]), int(v[1])) for k, v in result["buildings"].items()}
    roads: dict[tuple[int, int], int] = {}
    for r in result["roads"]:
        lvl = int(r[2]) if len(r) > 2 and r[2] else 1
        roads[(int(r[0]), int(r[1]))] = max(roads.get((int(r[0]), int(r[1])), 0), lvl)
    return pos, roads


class _Streets:
    """Which street metaId/era to write for a road cell or two-lane tile."""

    def __init__(self, city: dict, catalog: Catalog, current_era: str):
        self.at: dict[tuple[int, tuple[int, int]], tuple[str, str]] = {}
        used: dict[int, Counter] = {1: Counter(), 2: Counter()}
        eras: dict[str, Counter] = {}
        for e in city.values():
            if e.get("type") != "street":
                continue
            cid = e.get("cityentity_id", "")
            lvl = 2 if catalog.provided_level(cid) >= 2 else 1
            era = e.get("era") or current_era
            self.at[(lvl, (e.get("x", 0), e.get("y", 0)))] = (cid, era)
            used[lvl][cid] += 1
            eras.setdefault(cid, Counter())[era] += 1
        self.default: dict[int, tuple[str, str]] = {}
        for lvl in (1, 2):
            if used[lvl]:
                cid = used[lvl].most_common(1)[0][0]
                self.default[lvl] = (cid, eras[cid].most_common(1)[0][0])
        for lvl in (1, 2):
            if lvl not in self.default:
                self.default[lvl] = (self._catalog_street(catalog, lvl, current_era), current_era)

    def _catalog_street(self, catalog: Catalog, lvl: int, current_era: str) -> str:
        """A street of `lvl` the city has never used: prefer the age of its
        other street kind (S_X_Street1 -> S_X_CarStreet1), then currentEra."""
        cands = sorted(c for c in catalog.ids() if catalog.entity_type(c) == "street"
                       and catalog.size(c) == ((2, 2) if lvl == 2 else (1, 1))
                       and (catalog.provided_level(c) >= 2) == (lvl == 2))
        if not cands:
            raise ExportError(f"no level-{lvl} street type in the catalog")
        other = self.default.get(3 - lvl)
        tokens = ([other[0].split("_")[1]] if other and other[0].count("_") >= 2 else []) \
            + [current_era]
        for tok in tokens:
            for c in cands:
                if f"_{tok}_" in c:
                    return c
        return cands[0]

    def pick(self, lvl: int, anchor: tuple[int, int]) -> tuple[str, str]:
        return self.at.get((lvl, anchor)) or self.default[lvl]


def to_v3(original: dict, result, to_store=(), added=(), *,
          catalog: Catalog | None = None, warnings: list | None = None) -> dict:
    """The v3 file to import into Forge Hammer: `original` with mapBuildings
    and storedBuildings replaced (see the module docstring). `result` is a
    Layout or a published result dict; `to_store`/`added` are plan E's report
    lists (dicts with `entity_id`, `cityentity_id`). Raises ExportError when the
    file cannot be written faithfully; non-fatal problems go to `warnings`."""
    if not can_export(original):
        raise ExportError("this city was cached before the Forge Hammer export existed "
                          "(only a slim copy is stored); re-upload the city file and "
                          "export again")
    warn = warnings if warnings is not None else []
    if catalog is None:
        catalog = Catalog({**_bundled_catalog(),
                           **((original.get("helper_data") or {}).get("CityEntities") or {})})
    current_era = original.get("currentEra") or ""
    city = original["cityData"]
    pos, roads = _normalize(result)

    stored_ids = {int(s["entity_id"]) for s in to_store}
    added_by_id = {int(a["entity_id"]): a for a in added}

    buildings: list[dict] = []
    stored: list[dict] = []
    seen: set[int] = set()
    for e in city.values():
        if e.get("type") == "street" or e.get("type") in _OFF_GRID_TYPES:
            continue
        eid, cid = e["id"], e.get("cityentity_id", "")
        era = e.get("era") or current_era
        if eid in stored_ids:
            stored.append(_entry(cid, e.get("x", 0), e.get("y", 0), era, False))
        elif eid in pos:
            x, y = pos[eid]
            buildings.append(_entry(cid, x, y, era, False))
        else:
            # The loader drops nothing else on the grid; an entity the result
            # lacks would silently vanish from the plan.
            raise ExportError(f"building {eid} ({cid}) is neither in the layout nor in "
                              "the buildings to store; this layout is not for this city")
        seen.add(eid)

    # Added ids follow the highest BUILDING id (plan E), so they may equal a
    # street's or an off-grid entity's id; those never sit in `pos`.
    for eid, (x, y) in pos.items():
        if eid in seen:
            continue
        a = added_by_id.get(eid)
        if a is None:
            raise ExportError(f"building {eid} is not in the city; this layout is not for "
                              "this city")
        cid = a.get("cityentity_id") or ""
        if cid == "custom" or cid not in catalog.ids():
            warn.append(f"{a.get('name') or cid} ({a.get('width')}x{a.get('length')}) was "
                        "added by size only and has no Forge Hammer building type; it is "
                        "not in the exported plan")
            continue
        buildings.append(_entry(cid, x, y, current_era, True))

    streets = _Streets(city, catalog, current_era)
    lane1 = sorted((c for c, lvl in roads.items() if lvl < 2), key=lambda c: (c[1], c[0]))
    tiles, bad = tile_two_lane(c for c, lvl in roads.items() if lvl >= 2)
    if bad:
        raise ExportError(f"{len(bad)} two-lane road cell(s) cannot be split into 2x2 "
                          f"two-lane streets (first: {bad[:5]}); this layout cannot be "
                          "built in game")
    road_entries = []
    for (x, y) in lane1:
        cid, era = streets.pick(1, (x, y))
        road_entries.append(_entry(cid, x, y, era, False))
    for (x, y) in tiles:
        cid, era = streets.pick(2, (x, y))
        road_entries.append(_entry(cid, x, y, era, False))

    out = copy.deepcopy(original)
    out.pop("helper_data", None)       # webapp-internal; not part of the v3 format
    out["mapBuildings"] = buildings + road_entries
    out["storedBuildings"] = stored
    return out


def plan_as_city(doc: dict, catalog: Catalog | None = None) -> dict:
    """A v3 dict whose cityData IS the file's mapBuildings plan, so the loader
    builds the planned layout (round-trip checks). Entity ids are positional."""
    catalog = catalog or Catalog(_bundled_catalog())
    city = {}
    for i, b in enumerate(doc["mapBuildings"], start=1):
        e = {"id": i, "cityentity_id": b["metaId"],
             "type": catalog.entity_type(b["metaId"]) or "generic_building", "era": b["era"]}
        if b.get("x"):
            e["x"] = b["x"]
        if b.get("y"):
            e["y"] = b["y"]
        city[str(i)] = e
    return {**doc, "cityData": city}
