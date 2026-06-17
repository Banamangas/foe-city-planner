from __future__ import annotations

from foeopt.catalog import Catalog
from foeopt.model import Building, Footprint, Layout
from foeopt.region import build_region


def build_layout(city_data: dict, helper_data: dict) -> Layout:
    catalog = Catalog(helper_data["CityEntities"])
    region = build_region(city_data["unlocked_areas"])

    # Pass 1: collect roads and candidate (entity, footprint) pairs on the grid.
    roads: dict[tuple[int, int], int] = {}
    candidates: list[tuple[dict, Footprint]] = []
    for e in city_data["entities"]:
        if "x" not in e or "y" not in e:
            continue
        if (e["x"], e["y"]) not in region.cells:  # off-grid: anchor outside region
            continue
        cid = e["cityentity_id"]
        if e["type"] == "street":
            roads[(e["x"], e["y"])] = catalog.provided_level(cid)
            continue
        size = catalog.size(cid)
        if size is None:
            raise ValueError(f"Cannot resolve size for {cid}")
        w, length = size
        candidates.append((e, Footprint(e["x"], e["y"], w, length)))

    # Pass 2: a building needs a road iff it has the `connected` key AND is road-adjacent.
    road_cells = set(roads)
    buildings: list[Building] = []
    townhall: Building | None = None
    for e, fp in candidates:
        cid = e["cityentity_id"]
        is_th = e["type"] == "main_building"
        needs_road = ("connected" in e) and bool(fp.border_cells() & road_cells)
        building = Building(
            entity_id=e["id"],
            cityentity_id=cid,
            type=e["type"],
            footprint=fp,
            needs_road=needs_road,
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
