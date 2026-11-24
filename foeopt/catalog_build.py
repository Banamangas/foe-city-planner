"""Build the slim building catalog from the raw game export.

`trim` slims one raw CityEntity to the fields foeopt.catalog.Catalog reads;
`build` merges a fresh export over the current catalog, `sanity` guards the
result against regressions and `manifest` describes it for the app's updater.
"""
from __future__ import annotations

import datetime
import hashlib
import json

from foeopt.catalog import Catalog

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
        if isinstance(comp.get("chain"), dict):
            keep["chain"] = {k: comp["chain"][k] for k in ("chainId", "linkPositions")
                             if k in comp["chain"]}
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


def _names(new_name: str | None, prev: dict | None, given: dict | None) -> dict:
    if given:
        return {k: given[k] for k in ("en", "fr") if given.get(k)}
    if not prev:
        return {}
    prev_names = prev.get("names") or {}
    fr = prev_names.get("fr") or prev.get("name")
    en = new_name or prev_names.get("en")
    if not fr:
        return {}
    if prev_names.get("fr") or (en and en != fr):
        return {k: v for k, v in (("en", en), ("fr", fr)) if v}
    return {}


def build(lookup: list[dict], previous: dict, names: dict | None = None) -> dict:
    """New data wins; ids only in `previous` are kept; an empty new `type`
    keeps the previous one."""
    names = names or {}
    catalog = dict(previous)
    for raw in lookup:
        cid = raw.get("id")
        if not cid:
            continue
        entry = trim(raw)
        prev = previous.get(cid)
        if prev and not entry.get("type") and prev.get("type"):
            entry["type"] = prev["type"]
        nm = _names(entry.get("name"), prev, names.get(cid))
        if nm:
            entry["names"] = nm
            entry["name"] = nm.get("fr") or nm.get("en") or entry.get("name", cid)
        catalog[cid] = entry
    return catalog


def sanity(new: dict, previous: dict) -> list[str]:
    problems = [f"id missing from new catalog: {cid}" for cid in sorted(previous)
                if cid not in new]
    if len(new) < len(previous):
        problems.append(f"fewer entries than previous ({len(new)} < {len(previous)})")
    cat = Catalog(new)
    for cid in sorted(new):
        size = cat.size(cid)
        if not size or size[0] <= 0 or size[1] <= 0:
            problems.append(f"no positive size: {cid}")
    return problems


def canonical_bytes(catalog: dict) -> bytes:
    return json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()


def manifest(catalog: dict, source_version: str | None) -> dict:
    built = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return {
        "schema": 1,
        "built_at": built.isoformat().replace("+00:00", "Z"),
        "source_version": source_version,
        "count": len(catalog),
        "sha256": hashlib.sha256(canonical_bytes(catalog)).hexdigest(),
    }
