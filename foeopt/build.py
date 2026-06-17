from __future__ import annotations

from foeopt.catalog import Catalog
from foeopt.model import Building, Footprint, Layout
from foeopt.region import build_region

EXCLUDED_TYPES = {"off_grid", "outpost_ship", "friends_tavern"}


def _on_main_grid(e: dict) -> bool:
    if "x" not in e or "y" not in e:
        return False
    return 0 <= e["x"] < 200 and 0 <= e["y"] < 200


def build_layout(city_data: dict, helper_data: dict) -> Layout:
    catalog = Catalog(helper_data["CityEntities"])
    region = build_region(city_data["unlocked_areas"])

    buildings: list[Building] = []
    roads: dict[tuple[int, int], int] = {}
    townhall: Building | None = None

    for e in city_data["entities"]:
        if not _on_main_grid(e):
            continue
        etype = e["type"]
        if etype in EXCLUDED_TYPES:
            continue

        cid = e["cityentity_id"]
        x, y = e["x"], e["y"]

        if etype == "street":
            roads[(x, y)] = catalog.provided_level(cid)
            continue

        size = catalog.size(cid)
        if size is None:
            raise ValueError(f"Cannot resolve size for {cid}")
        w, length = size

        is_th = etype == "main_building"
        building = Building(
            entity_id=e["id"],
            cityentity_id=cid,
            type=etype,
            footprint=Footprint(x, y, w, length),
            needs_road="connected" in e,
            road_level=catalog.required_level(cid),
            is_townhall=is_th,
            set_id=catalog.set_id(cid),
            chain_id=catalog.chain_id(cid),
            name=catalog.name(cid),
        )
        buildings.append(building)
        if is_th:
            townhall = building

    return Layout(region=region, buildings=buildings, townhall=townhall, roads=roads)
