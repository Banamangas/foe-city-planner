"""End-to-end check of the Forge Hammer export (plan X), through the webapp.

Load a real v3 city, optimize it (BEST preset, short box), export the final
result with /api/export/v3, load the export's PLAN (mapBuildings) as a city and
check: legality valid, road cells and levels equal the result's, every result
building at its result position, storedBuildings = the buildings to store.

    flock output/bench/.lock python scripts/e2e_export_v3.py cities/essay.json --box 60
    ... --remove 2 --add D_HighMiddleAge_Gargoyle   (an edited run)

Runs > 30 s must take the shared bench lock (see tasks/lessons.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("FOEOPT_NO_UPDATE", "1")  # no GitHub check from this script

from foeopt.export_v3 import plan_as_city  # noqa: E402
from foeopt.legality import check  # noqa: E402
from foeopt.loader import load_layout_from_dict, read_json  # noqa: E402
from webapp.app import create_app  # noqa: E402
from webapp.params import BEST_PRESET  # noqa: E402


def _events(raw: str):
    for rec in raw.split("\n\n"):
        ev, data = None, None
        for line in rec.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if ev:
            yield ev, data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--box", type=float, default=60.0)
    ap.add_argument("--remove", type=int, default=0, help="remove the first N plain buildings")
    ap.add_argument("--add", action="append", default=[], help="cityentity_id to add")
    ap.add_argument("--out", help="write the exported file here (stays local)")
    args = ap.parse_args()

    src = read_json(args.city)
    client = create_app(db_path=":memory:").test_client()
    loaded = client.post(f"/api/load?name={os.path.basename(args.city)}", json=src).get_json()
    city_id = loaded["city_id"]
    edits = None
    if args.remove or args.add:
        plain = [b["entity_id"] for b in loaded["buildings"]
                 if not b["is_townhall"] and not b["chain_id"]][:args.remove]
        edits = {"remove": plain, "add": [{"cityentity_id": c, "count": 1} for c in args.add]}
    body = {**BEST_PRESET, "time_box": args.box, "city_id": city_id}
    if edits:
        body["edits"] = edits
    r = client.post("/api/optimize", json=body)
    if r.status_code != 200:
        print("optimize failed:", r.get_json())
        return 2
    job = r.get_json()["job_id"]
    last, final = None, None
    for ev, data in _events(client.get(f"/api/stream/{job}").get_data(as_text=True)):
        if ev == "improvement":
            last = data
        elif ev == "done":
            final = data
    if last is None:
        print("no result; final:", final and final.get("error"))
        return 2
    print(f"result: achieved={last['achieved']} roads={len(last['roads'])} "
          f"two-lane cells={sum(1 for r in last['roads'] if len(r) > 2 and r[2] == 2)} "
          f"legality={last['legality']['status']} to_store={len(last.get('to_store', []))} "
          f"added={len(last.get('added', []))}")

    r = client.post("/api/export/v3", json={"city_id": city_id, "layout": last})
    if r.status_code != 200:
        print("export failed:", r.get_json())
        return 2
    print("file:", r.headers["Content-Disposition"], "warnings:",
          r.headers.get("X-Export-Warnings"))
    doc = json.loads(r.data)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    plan = load_layout_from_dict(plan_as_city(doc))
    rep = check(plan, plan)
    roads = {(r[0], r[1]): (r[2] if len(r) > 2 and r[2] else 1) for r in last["roads"]}
    same_roads = plan.roads == roads
    want = Counter()
    by_id = {str(b["entity_id"]): b for b in loaded["buildings"]}
    added = {str(a["entity_id"]): a for a in last.get("added", [])}
    for eid, (x, y, _w, _l) in last["buildings"].items():
        cid = (by_id.get(eid) or added.get(eid))["cityentity_id"]
        want[(cid, x, y)] += 1
    got = Counter((b.cityentity_id, b.footprint.x, b.footprint.y) for b in plan.buildings)
    stored = Counter(e["metaId"] for e in doc["storedBuildings"])
    want_stored = Counter(s["cityentity_id"] for s in last.get("to_store", []))
    untouched = all(doc[k] == src[k] for k in src if k not in ("mapBuildings", "storedBuildings"))
    street_entities = sum(1 for e in doc["mapBuildings"] if e["metaId"].startswith("S_"))
    print(f"plan: legality={rep.status} {rep.violations[:2]} roads_equal={same_roads} "
          f"road_cells={len(plan.roads)} street_entities={street_entities} "
          f"buildings_equal={got == want} stored_equal={stored == want_stored} "
          f"other_fields_untouched={untouched} custom={sum(e['custom'] for e in doc['mapBuildings'])}")
    ok = rep.status == "valid" and same_roads and got == want and stored == want_stored and untouched
    print("E2E", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
