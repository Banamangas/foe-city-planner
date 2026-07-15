from __future__ import annotations

import numpy as np

from rl.kwalk_classifier import load, predict_proba
from rl.kwalk_data import encode_instance


class PatternScorer:
    def __init__(self, checkpoint_path, layout):
        self.model, self.H, self.W = load(checkpoint_path)
        self.manifest = {
            "region": [[x, y] for (x, y) in layout.region.cells],
            "buildings": [{"id": str(b.entity_id), "w": b.footprint.width,
                           "l": b.footprint.length, "road_level": b.road_level}
                          for b in layout.road_needing()],
        }

    def __call__(self, pattern) -> float:
        record = {"k": len(pattern.roads),
                  "th": [pattern.th.x, pattern.th.y, pattern.th.width, pattern.th.length],
                  "roads": [[x, y] for (x, y) in pattern.roads]}
        grid, glob = encode_instance(self.manifest, record, self.H, self.W)
        p = predict_proba(self.model, grid[None, ...], glob[None, ...])
        return float(p[0])
