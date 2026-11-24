"""Rebuild the slim building catalog from the game's building_entity_lookup export.

Usage: python scripts/update_catalog.py --lookup L.json [--names N.json]
           --previous P.json[.gz] --out DIR [--source-version V]

Writes DIR/catalog.json, DIR/catalog.json.gz and DIR/catalog-manifest.json;
exits 1 and writes nothing when the sanity check reports problems.
"""
from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from foeopt.catalog_build import build, canonical_bytes, manifest, sanity  # noqa: E402


def _read(path: str):
    p = pathlib.Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lookup", required=True)
    ap.add_argument("--names")
    ap.add_argument("--previous", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-version")
    args = ap.parse_args(argv)

    previous = _read(args.previous)
    catalog = build(_read(args.lookup), previous, _read(args.names) if args.names else None)
    problems = sanity(catalog, previous)
    if problems:
        for p in problems[:50]:
            print(f"sanity: {p}", file=sys.stderr)
        print(f"sanity: {len(problems)} problem(s); nothing written", file=sys.stderr)
        return 1

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(catalog)
    (out / "catalog.json").write_bytes(data)
    (out / "catalog.json.gz").write_bytes(gzip.compress(data, mtime=0))
    (out / "catalog-manifest.json").write_text(
        json.dumps(manifest(catalog, args.source_version), indent=2) + "\n")
    print(f"wrote {len(catalog)} entries to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
