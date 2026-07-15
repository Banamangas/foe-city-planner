from __future__ import annotations

import numpy as np

from foeopt.corpus import load_manifest, load_instances

LABEL_POS = {"SAT"}
LABEL_NEG = {"UNSAT", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"}

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
_SIZE_BUCKETS = ((1, 2), (3, 3), (4, 5), (6, 99))   # min-side bucket upper bounds


def _bbox(cells):
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return min(xs), min(ys), max(xs), max(ys)


def _globals(manifest, k) -> np.ndarray:
    b = manifest["buildings"]
    area = sum(x["w"] * x["l"] for x in b)
    minside = sum(min(x["w"], x["l"]) for x in b)
    region_n = len(manifest["region"])
    hist = [0.0] * len(_SIZE_BUCKETS)
    for x in b:
        ms = min(x["w"], x["l"])
        for i, hi in enumerate(_SIZE_BUCKETS):
            if ms <= hi[1]:
                hist[i] += 1.0
                break
    return np.asarray([len(b), area, minside, region_n - area - k, float(k)] + hist,
                      dtype=np.float32)


def encode_instance(manifest, record, H, W):
    region = [(x, y) for x, y in manifest["region"]]
    ox, oy, _, _ = _bbox(region)
    grid = np.zeros((4, H, W), dtype=np.float32)

    def put(ch, x, y):
        gx, gy = x - ox, y - oy
        if 0 <= gy < H and 0 <= gx < W:
            grid[ch, gy, gx] = 1.0

    for (x, y) in region:
        put(0, x, y)
    roads = {(x, y) for x, y in record["roads"]}
    for (x, y) in roads:
        put(1, x, y)
    tx, ty, tw, tl = record["th"]
    for x in range(tx, tx + tw):
        for y in range(ty, ty + tl):
            put(2, x, y)
    for (x, y) in region:
        if (x, y) not in roads and any((x + dx, y + dy) in roads for dx, dy in _ORTHO):
            put(3, x, y)
    return grid, _globals(manifest, record["k"])


def build_samples(corpus_dirs, H=None, W=None):
    loaded = []
    max_h, max_w = 0, 0
    for d in corpus_dirs:
        man = load_manifest(d)
        x0, y0, x1, y1 = _bbox([(x, y) for x, y in man["region"]])
        max_h = max(max_h, y1 - y0 + 1)
        max_w = max(max_w, x1 - x0 + 1)
        for rec in load_instances(d):
            if rec["status"] in LABEL_POS:
                y = 1
            elif rec["status"] in LABEL_NEG:
                y = 0
            else:
                continue
            loaded.append((man, rec, y))
    H = H or max_h
    W = W or max_w
    X = np.zeros((len(loaded), 4, H, W), dtype=np.float32)
    g_list, y_list = [], []
    for i, (man, rec, y) in enumerate(loaded):
        grid, glob = encode_instance(man, rec, H, W)
        X[i] = grid
        g_list.append(glob)
        y_list.append(y)
    g = np.stack(g_list) if g_list else np.zeros((0, 9), dtype=np.float32)
    return {"X": X, "g": g, "y": np.asarray(y_list, dtype=np.float32), "H": H, "W": W}
