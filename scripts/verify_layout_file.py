"""Independently verify a saved layout JSON against its city export.

Usage: verify_layout_file.py CITY.json LAYOUT.json [HELPER.json] [--military connect|unconnected]
       [--reroute]

Checks the DELIVERED artifact: the saved road network (cells with levels when
the file has them, as [x, y, level]; bare [x, y] means level 1) and the saved
building positions, using the full legality gate (`foeopt.legality.check`).
The claimed `achieved` count must equal the number of saved road cells.
`--reroute` also reports greedy route() and exact_route() counts on the same
positions, for comparison only. They never replace the saved network.
Exit 0 only when the status is "valid" and the count matches.
"""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foeopt.legality import MILITARY_POLICIES, check
from foeopt.loader import load_layout
from foeopt.model import Footprint, Layout


def load_saved(src: Layout, rec: dict) -> Layout:
    by_id = {b.entity_id: b for b in src.buildings}
    placed, th = [], None
    for eid, (x, y, w, l) in rec["buildings"].items():
        b = replace(by_id[int(eid)], footprint=Footprint(x, y, w, l))
        placed.append(b)
        th = b if b.is_townhall else th
    roads = {}
    for cell in rec["roads"]:
        roads[(cell[0], cell[1])] = cell[2] if len(cell) > 2 else 1
    return Layout(src.region, placed, th, roads)


def verify(src: Layout, rec: dict, military: str = "connect", reroute: bool = False) -> dict:
    lay = load_saved(src, rec)
    rep = check(lay, src, military=military)
    out = {"legality": rep.as_dict(), "military": military,
           "roads_saved": len(lay.roads), "achieved_claimed": rec.get("achieved"),
           "count_matches": rec.get("achieved") == len(lay.roads)}
    if reroute:
        from foeopt.exact_router import exact_route
        from foeopt.router import route
        bare = Layout(lay.region, lay.buildings, lay.townhall, {})
        out["reroute_greedy"] = len(route(bare))
        bare.roads = route(bare)
        er = exact_route(bare, time_limit=60)
        out["reroute_exact"], out["reroute_exact_optimal"] = er.count, er.optimal
    out["ok"] = rep.status == "valid" and out["count_matches"]
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city")
    p.add_argument("layout")
    p.add_argument("helper", nargs="?")
    p.add_argument("--military", choices=MILITARY_POLICIES, default="connect")
    p.add_argument("--reroute", action="store_true")
    a = p.parse_args(argv)
    src = load_layout(a.city, a.helper)
    out = verify(src, json.loads(Path(a.layout).read_text()), a.military, a.reroute)
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
