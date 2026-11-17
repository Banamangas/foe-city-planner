"""Build foeopt/data/catalog.json: the building catalog the v3 city format lacks.

FoE Helper v3 exports (`{version, cityData, mapData, ...}`) carry no CityEntities,
so sizes, road requirements and chain metadata come from this bundled catalog.
It is the union of the CityEntities of the given exports (later files win),
trimmed to the fields foeopt.catalog.Catalog reads.

Usage: python scripts/build_catalog.py EXPORT.json [EXPORT.json ...]
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from foeopt.loader import read_json  # noqa: E402

OUT = ROOT / "foeopt" / "data" / "catalog.json"
ABILITY_KEYS = ("setId", "chainId", "linkPositions")


def trim(defn: dict) -> dict:
    out = {k: defn[k] for k in ("id", "name", "type", "width", "length") if k in defn}
    lvl = (defn.get("requirements") or {}).get("street_connection_level")
    if lvl:
        out["requirements"] = {"street_connection_level": lvl}
    comps = {}
    for key, comp in (defn.get("components") or {}).items():
        if not isinstance(comp, dict):
            continue
        keep = {k: comp[k] for k in ("placement", "streetConnectionRequirement") if k in comp}
        if "placement" in keep:
            keep["placement"] = {"size": (keep["placement"] or {}).get("size")}
        if keep:
            comps[key] = keep
    if comps:
        out["components"] = comps
    abilities = [{k: a[k] for k in ABILITY_KEYS if k in a}
                 for a in defn.get("abilities", []) if isinstance(a, dict)]
    abilities = [a for a in abilities if a]
    if abilities:
        out["abilities"] = abilities
    return out


def main(paths: list[str]) -> None:
    catalog: dict[str, dict] = {}
    for p in paths:
        defs = read_json(p).get("CityEntities") or {}
        catalog.update({cid: trim(d) for cid, d in defs.items()})
        print(f"{p}: {len(defs)} definitions")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, sort_keys=True, separators=(",", ":")))
    print(f"wrote {OUT} ({len(catalog)} definitions, {OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
