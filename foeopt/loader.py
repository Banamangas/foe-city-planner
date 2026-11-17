from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from foeopt.build import build_layout
from foeopt.catalog import Catalog
from foeopt.model import Building, Footprint, Layout
from foeopt.region import build_region


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _cid(e: dict) -> str:
    return e.get("cityentity_id") or e.get("entityId") or ""


def _entity_coords(e: dict) -> tuple[int, int]:
    coords = e.get("coords")
    if isinstance(coords, dict):
        return (coords.get("x", 0), coords.get("y", 0))
    return (e.get("x", 0), e.get("y", 0))


def _entity_size(e: dict, catalog: Catalog) -> tuple[int, int] | None:
    size = e.get("size")
    if isinstance(size, dict) and size.get("width") and size.get("length"):
        return (size["width"], size["length"])
    return catalog.size(_cid(e))


def _street_level(e: dict, catalog: Catalog) -> int:
    if "needsStreet" in e:
        return e["needsStreet"] or 1  # FOE streets always provide level ≥ 1; fallback for 0/absent
    return catalog.provided_level(_cid(e))


CATALOG_PATH = Path(__file__).with_name("data") / "catalog.json"


@lru_cache(maxsize=1)
def _bundled_catalog() -> dict:
    """Catalog for exports that carry none (v3); built by scripts/build_catalog.py."""
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def is_v3(data: dict) -> bool:
    """FoE Helper city export, version 3: `cityData` (entities) + `mapData`
    (unlocked areas), and no building catalog."""
    return "cityData" in data and "mapData" in data


def _build_v3(data: dict, helper_data: dict | None = None) -> Layout:
    """v3 has no CityEntities and no per-entity `connected` flag. The catalog is
    the bundled one, extended by an optional helper export's CityEntities. A
    building needs a road iff its definition requires one AND it touches a road
    in the upload -- the same "keep the player's connectivity" rule the
    `connected`-key path applies (a building the player left unconnected stays
    unconnected)."""
    defs = {**_bundled_catalog(), **((helper_data or {}).get("CityEntities") or {})}
    entities = data["cityData"]
    missing = sorted({_cid(e) for e in entities.values() if e.get("type") not in _OFF_GRID_TYPES
                      and _cid(e) not in defs})
    if missing:
        raise ValueError(
            f"{len(missing)} building types are not in the catalog "
            f"({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}); "
            "pass a FoE Helper CityMap export as the helper file, or rebuild "
            "foeopt/data/catalog.json with scripts/build_catalog.py")
    return _build_combined({"CityMapData": entities, "UnlockedAreas": data["mapData"],
                            "CityEntities": defs}, needs_from_catalog=True)


# Never on the buildable grid; skipped before the catalog check so an unknown
# expansion/ship id cannot block a load (the region test drops them anyway).
_OFF_GRID_TYPES = {"off_grid", "outpost_ship", "friends_tavern", "hub_main", "hub_part"}


def _build_combined(data: dict, needs_from_catalog: bool = False) -> Layout:
    # needs_road: the catalog's street requirement AND road-adjacent in the upload.
    # The per-entity `connected` key is only the fallback for catalog-less files:
    # the game sets it on buildings that need no road (e.g. GR25 "Niv. 2", user-
    # confirmed 2026-11-17), which made FR17/FR24 over-constrained.
    catalog = Catalog(data.get("CityEntities", {}))
    region = build_region(data["UnlockedAreas"])

    roads: dict[tuple[int, int], int] = {}
    candidates: list[tuple[dict, Footprint]] = []
    for e in data["CityMapData"].values():
        if e.get("isInInventory"):
            continue
        x, y = _entity_coords(e)
        if (x, y) not in region.cells:
            continue
        size = _entity_size(e, catalog)
        if size is None:
            continue
        w, length = size
        fp = Footprint(x, y, w, length)
        if e.get("type") == "street":
            level = _street_level(e, catalog)
            for cell in fp.cells():
                roads[cell] = max(roads.get(cell, 0), level)
            continue
        candidates.append((e, fp))

    road_cells = set(roads)
    buildings: list[Building] = []
    townhall: Building | None = None
    for e, fp in candidates:
        cid = _cid(e)
        if "needsStreet" in e:
            lvl = e["needsStreet"] or 0
            needs_road, road_level = (lvl > 0, lvl if lvl > 0 else 1)
        elif needs_from_catalog or catalog.known:
            needs_road = (catalog.street_requirement(cid) > 0
                          and bool(fp.border_cells() & road_cells))
            road_level = catalog.required_level(cid)
        else:
            needs_road = ("connected" in e) and bool(fp.border_cells() & road_cells)
            road_level = catalog.required_level(cid)
        is_th = e.get("type") == "main_building"
        building = Building(
            entity_id=e["id"],
            cityentity_id=cid,
            type=e.get("type", ""),
            footprint=fp,
            needs_road=needs_road,
            road_level=road_level,
            is_townhall=is_th,
            set_id=catalog.set_id(cid),
            chain_id=catalog.chain_id(cid),
            link_positions=catalog.link_positions(cid),
            name=e.get("name") or catalog.name(cid),
        )
        buildings.append(building)
        if is_th:
            townhall = building

    layout = Layout(region=region, buildings=buildings, townhall=townhall, roads=roads)
    layout.catalog_known = catalog.known
    return layout


def load_layout_from_dict(data: dict, helper_data: dict | None = None) -> Layout:
    """Build a Layout from an in-memory dict (slim or full combined format).

    Same logic as load_layout but avoids a filesystem round-trip — the API
    receives the slim payload as JSON in the request body, not as a file path.
    """
    if "entities" in data:
        # A cached split city carries its helper's catalog inline (webapp).
        helper_data = helper_data or data.get("helper_data")
        if helper_data is None:
            raise ValueError(
                "this city file is the split format; a helper file is required"
            )
        return build_layout(data, helper_data)
    if is_v3(data):
        return _build_v3(data, helper_data or data.get("helper_data"))
    if "CityMapData" in data:
        return _build_combined(data)
    raise ValueError("unrecognized city file format")


def load_layout(city_path: str, helper_path: str | None = None) -> Layout:
    data = read_json(city_path)
    if "entities" in data:
        if helper_path is None:
            raise ValueError(
                "this city file is the split format; a helper file is required"
            )
        return build_layout(data, read_json(helper_path))
    if is_v3(data):
        return _build_v3(data, read_json(helper_path) if helper_path else None)
    if "CityMapData" in data:
        return _build_combined(data)
    raise ValueError("unrecognized city file format")


def city_catalog_defs(data: dict) -> dict:
    """The building definitions a cached city resolves against: the bundled
    catalog, overridden by the city's own CityEntities (combined exports) or
    its embedded helper's (split and v3 uploads)."""
    own = data.get("CityEntities") or (data.get("helper_data") or {}).get("CityEntities") or {}
    return {**_bundled_catalog(), **own}
