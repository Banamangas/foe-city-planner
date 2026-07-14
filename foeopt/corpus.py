from __future__ import annotations

import hashlib
import json
import pathlib
from collections.abc import Iterator


def _city_id(region: list, buildings: list) -> str:
    h = hashlib.sha256()
    h.update(repr(region).encode())
    h.update(repr([(b["id"], b["w"], b["l"], b["road_level"]) for b in buildings]).encode())
    return h.hexdigest()[:16]


class CorpusWriter:
    """Append-only writer for one city's roads-first probe corpus.

    Writes a manifest (region + road-needing building set, constant per city)
    once, then one JSON line per probe (skeleton + status + optional CP-SAT
    placement) to instances.jsonl. The manifest keeps the large constant data
    out of every record.
    """

    def __init__(self, corpus_dir, layout):
        self.dir = pathlib.Path(corpus_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        buildings = [{"id": str(b.entity_id), "w": b.footprint.width,
                      "l": b.footprint.length, "road_level": b.road_level}
                     for b in layout.road_needing()]
        region = sorted([x, y] for (x, y) in layout.region.cells)
        self.city_id = _city_id(region, buildings)
        (self.dir / "manifest.json").write_text(
            json.dumps({"city_id": self.city_id, "region": region,
                        "buildings": buildings}),
            encoding="utf-8")
        self._fh = open(self.dir / "instances.jsonl", "a", encoding="utf-8")

    def record(self, *, k, roads, th, status, secs, pos):
        rec = {
            "k": k,
            "status": status,
            "secs": secs,
            "th": [th.x, th.y, th.width, th.length],
            "roads": sorted([x, y] for (x, y) in roads),
            "pos": ({str(bid): list(v) for bid, v in pos.items()} if pos else None),
        }
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()


def load_manifest(corpus_dir) -> dict:
    return json.loads((pathlib.Path(corpus_dir) / "manifest.json").read_text(encoding="utf-8"))


def load_instances(corpus_dir) -> Iterator[dict]:
    p = pathlib.Path(corpus_dir) / "instances.jsonl"
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def reconstruct(manifest: dict, record: dict) -> dict:
    return {
        "region": {(x, y) for x, y in manifest["region"]},
        "skeleton": {(x, y) for x, y in record["roads"]},
        "buildings": manifest["buildings"],
        "th": tuple(record["th"]),
        "status": record["status"],
        "pos": record.get("pos"),
    }
