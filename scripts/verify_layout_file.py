"""Independently re-verify a saved layout JSON against its city export.

Usage: verify_layout_file.py CITY.json LAYOUT.json [HELPER.json]
Reloads the city, overrides footprints from the file, then checks route(),
exact_route(), road satisfaction, orientation, inventory, overlap, region
containment and that no building sits on a road.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foeopt.exact_router import exact_route
from foeopt.loader import load_layout
from foeopt.model import Footprint, Layout
from foeopt.router import route
from foeopt.validate import canonical_dims, is_valid, rotated_buildings


def main(argv):
    src = load_layout(argv[0], argv[2] if len(argv) > 2 else None)
    rec = json.loads(Path(argv[1]).read_text())
    by_id = {b.entity_id: b for b in src.buildings}
    placed, th = [], None
    for eid, (x, y, w, l) in rec["buildings"].items():
        b = replace(by_id[int(eid)], footprint=Footprint(x, y, w, l))
        placed.append(b)
        th = b if b.is_townhall else th
    lay = Layout(src.region, placed, th, {})
    r = route(lay)
    lay.roads = r
    er = exact_route(lay, time_limit=60)
    cells = [c for b in placed for c in b.footprint.cells()]
    out = {"route": len(r), "exact": er.count, "exact_optimal": er.optimal,
           "valid": is_valid(lay),
           "rotated": len(rotated_buildings(lay, canonical_dims(src))),
           "inventory_ok": sorted(by_id) == sorted(int(e) for e in rec["buildings"]),
           "overlap": len(cells) - len(set(cells)),
           "out_of_region": sum(c not in src.region.cells for c in cells),
           "on_road": sum(c in r for c in cells),
           "level2_consumers": sum(1 for b in placed if b.needs_road and b.road_level > 1)}
    print(json.dumps(out))
    ok = (out["valid"] and out["rotated"] == 0 and out["inventory_ok"] and not out["overlap"]
          and not out["out_of_region"] and not out["on_road"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
