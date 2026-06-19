from __future__ import annotations

import json

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
        return e["needsStreet"] or 1
    return catalog.provided_level(_cid(e))


def _build_combined(data: dict) -> Layout:
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
            name=e.get("name") or catalog.name(cid),
        )
        buildings.append(building)
        if is_th:
            townhall = building

    return Layout(region=region, buildings=buildings, townhall=townhall, roads=roads)


def load_layout(city_path: str, helper_path: str | None = None) -> Layout:
    data = read_json(city_path)
    if "entities" in data:
        if helper_path is None:
            raise ValueError(
                "this city file is the split format; a helper file is required"
            )
        return build_layout(data, read_json(helper_path))
    if "CityMapData" in data:
        return _build_combined(data)
    raise ValueError("unrecognized city file format")
