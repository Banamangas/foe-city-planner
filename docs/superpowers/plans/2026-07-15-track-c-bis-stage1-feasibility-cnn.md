# Track C-bis Stage 1 — Feasibility CNN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train a small CNN that predicts, for a roads-first probe instance `(region, road skeleton, building set) → P(SAT)`, and use it to rank/prune patterns in the k-walk so the walk reaches a lower `k` (or 106 faster) within the same time budget. Ground truth stays CP-SAT; the model only changes which patterns are probed and in what order.

**Architecture:** All ML lives under `rl/` (torch is an optional extra — `uv sync --extra rl`); `foeopt/` stays torch-free. `rl/kwalk_data.py` reads the Stage-0 corpus (`manifest.json` + `instances.jsonl`) and builds `(grid [C,H,W], globals vector, label)` samples. `rl/kwalk_classifier.py` is a small CNN + trainer + checkpoint. `rl/kwalk_eval.py` computes held-out ROC-AUC (the cheap G1 signal). `rl/kwalk_scorer.py` wraps a trained checkpoint as a `Pattern → P(SAT)` callable. `foeopt/roads_first.py` gains an optional `scorer` callable that reorders/prunes patterns before probing (opt-in; injected, so no torch import in `foeopt/`). A gate runbook compares guided vs baseline k-walk on darkzig.

**Tech Stack:** Python 3.12, `torch>=2` + `numpy>=1.24` (the `rl` extra), stdlib, `pytest`. CP-SAT (`ortools`) unchanged.

## Global Constraints

- **torch is the `rl` extra, not a core dep.** All new torch code is under `rl/`. Run its tests with `uv run --extra rl pytest ...`; every torch-using test starts with `torch = pytest.importorskip("torch")` so the default `uv run pytest` (no extra) skips them cleanly. Like the existing rl suite, these tests are outside the default gate.
- **`foeopt/` must not import torch.** The k-walk's scorer hook takes a plain callable `scorer(pattern) -> float` (or `None`); the torch implementation lives in `rl/kwalk_scorer.py` and is injected by the caller.
- **CP-SAT stays the decider.** The scorer only changes pattern order and may prune patterns below a threshold; it never certifies feasibility. A pruned pattern is one never probed — correctness of any produced layout is unchanged.
- **Corpus format (from Stage 0, do not change):** `manifest.json` = `{city_id, region: [[x,y],...], buildings: [{id, w, l, road_level},...]}`; `instances.jsonl` lines = `{k, status, secs, th: [x,y,w,l], roads: [[x,y],...], pos: {id:[x,y,w,l]}|null}`. Statuses: `SAT, UNSAT, UNKNOWN, ROUTE_FAIL, INVALID, SAT_FILLER_FAIL, SAT_ROTATED`.
- **Labels:** `status == "SAT"` → 1; `status in {UNSAT, ROUTE_FAIL, INVALID, SAT_FILLER_FAIL, SAT_ROTATED}` → 0; `status == "UNKNOWN"` → **excluded from training** (it is the inference target, not a label).
- **Determinism where it matters:** seed torch/numpy in training; the corpus/scorer must not make `route()`/`is_valid` outputs differ (the scorer only affects probe order).
- Corpus + checkpoints live under `output/` (gitignored). Tests use `tmp_path` + synthetic corpora built via `foeopt.corpus.CorpusWriter`.
- No comments in code unless the surrounding source already has them.

## Design decisions (grounded in the spec; flagged for review)

1. **The building set is constant within a city** (`layout.road_needing()` is fixed; every probe places all of them). So within one city only the skeleton/TH vary; the label is `"does this skeleton admit a valid packing of THIS city's buildings"`. Cross-city generalization (the held-out FR city, Stage 3) therefore requires the **region + building set as inputs** — encoded as spatial channels (region, skeleton, TH, skeleton-adjacency) plus a **global feature vector** (building count, total building area, min-side-sum, region free area `|region| − building_area − k`, and a small size histogram). The CNN reads the grid; the globals enter the FC head.
2. **Fixed grid size:** pad each city's bbox-cropped grid, top-left aligned, to a configured `(H, W)` = the max bbox over the training corpus (stored in the checkpoint). Cities larger than that at inference are center-cropped with a logged warning (Stage 3 uses FR16-sized grids; pick `(H, W)` ≥ the largest FR city).
3. **Scheduler policy:** rank `surviving` patterns by descending `P(SAT)` and optionally drop those below `--score-threshold` (default: rank only, no pruning). Opt-in via `RoadsFirstSearch(scorer=…)` / a CLI flag.

## Scope

Stage 1 only. Stage 1.5 (UNKNOWN autopsy) and Stage 2 (warm-start) are separate plans, gated on Stage 1's G1 result per `docs/superpowers/specs/2026-07-14-learned-kwalk-acceleration-design.md`. Stage 1's own gate **G1** (ROC-AUC ≥ 0.80 **and** guided walk reaches `k ≤ 104` or 106 in ≤ 50% compute) is evaluated by Task 5's runbook once the real corpus exists.

**Prerequisite:** the Stage-0 corpus for darkzig + FR16 must be generated (via `scripts/exp_roads_first.py --corpus …`) before Tasks 2–5 can train/evaluate on real data. Task 1 and all unit tests use synthetic corpora and need no real data.

---

### Task 1: Corpus → dataset (`rl/kwalk_data.py`)

**Files:**
- Create: `rl/kwalk_data.py`
- Test: `tests/test_kwalk_data.py`

**Interfaces:**
- Consumes: `foeopt.corpus.load_manifest`/`load_instances`, `numpy`.
- Produces:
  - `LABEL_POS = {"SAT"}`, `LABEL_NEG = {"UNSAT", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"}` (UNKNOWN excluded).
  - `encode_instance(manifest, record, H, W) -> tuple[np.ndarray, np.ndarray]` — returns `(grid [4,H,W] float32, globals [G] float32)`.
  - `build_samples(corpus_dirs, H=None, W=None) -> dict` — returns `{"X": np.ndarray[N,4,H,W], "g": np.ndarray[N,G], "y": np.ndarray[N], "H": H, "W": W}`; auto-sizes `(H,W)` to the max bbox across the given corpora when not passed; skips UNKNOWN records.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kwalk_data.py`:

```python
import numpy as np

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.corpus import CorpusWriter
from rl.kwalk_data import build_samples, encode_instance, LABEL_NEG


def _layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


def _corpus(tmp_path):
    w = CorpusWriter(tmp_path, _layout())
    th = Footprint(0, 0, 2, 2)
    w.record(k=5, roads=frozenset({(2, 0), (2, 1)}), th=th, status="SAT", secs=1.0,
             pos={10: (3, 0, 2, 2)})
    w.record(k=5, roads=frozenset({(2, 0)}), th=th, status="UNSAT", secs=0.2, pos=None)
    w.record(k=4, roads=frozenset({(2, 0)}), th=th, status="UNKNOWN", secs=8.0, pos=None)
    w.record(k=5, roads=frozenset({(2, 0), (2, 1)}), th=th, status="SAT_ROTATED", secs=1.0,
             pos={10: (3, 0, 2, 2)})
    w.close()
    return tmp_path


def test_build_samples_labels_and_excludes_unknown(tmp_path):
    ds = build_samples([_corpus(tmp_path)])
    assert ds["y"].tolist() == [1, 0, 0]          # SAT=1, UNSAT=0, SAT_ROTATED=0; UNKNOWN dropped
    assert ds["X"].shape == (3, 4, ds["H"], ds["W"])
    assert ds["g"].shape[0] == 3
    assert "SAT_ROTATED" in LABEL_NEG


def test_encode_channels(tmp_path):
    from foeopt.corpus import load_manifest, load_instances
    d = _corpus(tmp_path)
    man = load_manifest(d)
    rec = next(r for r in load_instances(d) if r["status"] == "SAT")
    grid, glob = encode_instance(man, rec, 6, 6)
    assert grid.shape == (4, 6, 6)
    assert grid[0].sum() == 36                     # region: full 6x6
    assert grid[1, 0, 2] == 1 and grid[1, 1, 2] == 1   # skeleton roads at (2,0),(2,1)
    assert grid[2, 0, 0] == 1 and grid[2, 1, 1] == 1   # TH footprint 2x2 at (0,0)
    assert grid[3, 0, 3] == 1                       # skeleton-adjacency: (3,0) is ortho-adjacent to road (2,0)
    assert glob.ndim == 1 and glob.shape[0] >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kwalk_data.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rl.kwalk_data'`.

- [ ] **Step 3: Implement `rl/kwalk_data.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kwalk_data.py -q`
Expected: PASS (2 tests). Note: this task uses only numpy + stdlib, so it runs under the default env (no torch needed).

- [ ] **Step 5: Commit**

```bash
git add rl/kwalk_data.py tests/test_kwalk_data.py
git commit -m "feat: corpus->dataset builder for the feasibility CNN (Track C-bis Stage 1)"
```

---

### Task 2: Small CNN + trainer (`rl/kwalk_classifier.py`)

**Files:**
- Create: `rl/kwalk_classifier.py`
- Test: `tests/test_kwalk_classifier.py`

**Interfaces:**
- Consumes: `torch`, `numpy`, `rl.kwalk_data`.
- Produces:
  - `FeasibilityCNN(in_ch=4, n_glob=9)` — conv stack → global avg pool → concat globals → FC → 1 logit.
  - `train(samples, *, epochs=30, lr=1e-3, batch=64, seed=0, device="cpu") -> FeasibilityCNN`.
  - `save(model, path, H, W)` / `load(path) -> tuple[FeasibilityCNN, int, int]` (model + H + W).
  - `predict_proba(model, X, g, device="cpu") -> np.ndarray` (sigmoid probabilities).

- [ ] **Step 1: Write the failing test**

Create `tests/test_kwalk_classifier.py`:

```python
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from rl.kwalk_classifier import FeasibilityCNN, train, predict_proba, save, load


def _separable(n=120, H=8, W=8, seed=0):
    rng = np.random.default_rng(seed)
    X = np.zeros((n, 4, H, W), dtype=np.float32)
    g = rng.standard_normal((n, 9)).astype(np.float32)
    y = np.zeros(n, dtype=np.float32)
    for i in range(n):
        pos = i % 2
        y[i] = pos
        # class signal: positives have a dense skeleton channel, negatives sparse
        X[i, 1] = (rng.random((H, W)) < (0.5 if pos else 0.05)).astype(np.float32)
        g[i, 0] = pos * 5.0
    return {"X": X, "g": g, "y": y, "H": H, "W": W}


def test_train_separates_classes():
    ds = _separable()
    model = train(ds, epochs=40, seed=0)
    p = predict_proba(model, ds["X"], ds["g"])
    acc = ((p > 0.5).astype(np.float32) == ds["y"]).mean()
    assert acc >= 0.9


def test_save_load_roundtrip(tmp_path):
    ds = _separable(n=20)
    model = train(ds, epochs=2, seed=0)
    save(model, tmp_path / "m.pt", ds["H"], ds["W"])
    m2, H, W = load(tmp_path / "m.pt")
    assert (H, W) == (ds["H"], ds["W"])
    p1 = predict_proba(model, ds["X"], ds["g"])
    p2 = predict_proba(m2, ds["X"], ds["g"])
    assert np.allclose(p1, p2, atol=1e-5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra rl pytest tests/test_kwalk_classifier.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rl.kwalk_classifier'`.

- [ ] **Step 3: Implement `rl/kwalk_classifier.py`**

```python
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


class FeasibilityCNN(nn.Module):
    def __init__(self, in_ch: int = 4, n_glob: int = 9):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, 16, 3, padding=1), nn.ReLU(),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
            nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.head = nn.Sequential(
            nn.Linear(32 + n_glob, 64), nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, x, g):
        h = self.conv(x).flatten(1)
        return self.head(torch.cat([h, g], dim=1)).squeeze(1)


def _loaders(samples, batch, seed):
    g = torch.from_numpy(samples["g"])
    gmean, gstd = g.mean(0, keepdim=True), g.std(0, keepdim=True) + 1e-6
    g = (g - gmean) / gstd
    ds = torch.utils.data.TensorDataset(
        torch.from_numpy(samples["X"]), g, torch.from_numpy(samples["y"]))
    gen = torch.Generator().manual_seed(seed)
    return torch.utils.data.DataLoader(ds, batch_size=batch, shuffle=True, generator=gen), gmean, gstd


def train(samples, *, epochs=30, lr=1e-3, batch=64, seed=0, device="cpu"):
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = FeasibilityCNN(in_ch=samples["X"].shape[1], n_glob=samples["g"].shape[1]).to(device)
    loader, gmean, gstd = _loaders(samples, batch, seed)
    model._gmean = gmean.to(device)
    model._gstd = gstd.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    pos = float(samples["y"].sum())
    neg = float(len(samples["y"]) - pos)
    pw = torch.tensor([neg / max(pos, 1.0)], device=device)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    model.train()
    for _ in range(epochs):
        for xb, gb, yb in loader:
            xb, gb, yb = xb.to(device), gb.to(device), yb.to(device)
            opt.zero_grad()
            lossf(model(xb, gb), yb).backward()
            opt.step()
    model.eval()
    return model


def predict_proba(model, X, g, device="cpu"):
    model.eval()
    with torch.no_grad():
        xb = torch.from_numpy(np.asarray(X, dtype=np.float32)).to(device)
        gb = (torch.from_numpy(np.asarray(g, dtype=np.float32)).to(device) - model._gmean) / model._gstd
        return torch.sigmoid(model(xb, gb)).cpu().numpy()


def save(model, path, H, W):
    torch.save({"state": model.state_dict(), "H": int(H), "W": int(W),
                "in_ch": model.conv[0].in_channels, "n_glob": model.head[0].in_features - 32,
                "gmean": model._gmean.cpu(), "gstd": model._gstd.cpu()}, str(path))


def load(path):
    ck = torch.load(str(path), map_location="cpu")
    model = FeasibilityCNN(in_ch=ck["in_ch"], n_glob=ck["n_glob"])
    model.load_state_dict(ck["state"])
    model._gmean = ck["gmean"]
    model._gstd = ck["gstd"]
    model.eval()
    return model, ck["H"], ck["W"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra rl pytest tests/test_kwalk_classifier.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add rl/kwalk_classifier.py tests/test_kwalk_classifier.py
git commit -m "feat: small feasibility CNN + trainer (Track C-bis Stage 1)"
```

---

### Task 3: Held-out ROC-AUC eval (`rl/kwalk_eval.py`)

**Files:**
- Create: `rl/kwalk_eval.py`
- Test: `tests/test_kwalk_eval.py`

**Interfaces:**
- Consumes: `numpy`, `rl.kwalk_data`, `rl.kwalk_classifier`.
- Produces:
  - `roc_auc(y_true, scores) -> float` — rank-based AUC (no sklearn).
  - `split(samples, frac=0.2, seed=0) -> tuple[dict, dict]` — stratified train/val split.
  - `evaluate(corpus_dirs, *, epochs=30, seed=0) -> dict` — build → split → train → `{"auc": float, "n_train": int, "n_val": int, "H": int, "W": int}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kwalk_eval.py`:

```python
import numpy as np
import pytest

from rl.kwalk_eval import roc_auc, split


def test_roc_auc_perfect_and_random():
    y = np.array([0, 0, 1, 1])
    assert roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    mid = roc_auc(np.array([0, 1, 0, 1]), np.array([0.5, 0.5, 0.5, 0.5]))
    assert abs(mid - 0.5) < 1e-9


def test_split_is_stratified():
    s = {"X": np.zeros((100, 4, 4, 4), np.float32), "g": np.zeros((100, 9), np.float32),
         "y": np.array([0, 1] * 50, dtype=np.float32), "H": 4, "W": 4}
    tr, va = split(s, frac=0.2, seed=0)
    assert va["y"].shape[0] == 20 and tr["y"].shape[0] == 80
    assert abs(va["y"].mean() - 0.5) < 0.2       # both classes present in val
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kwalk_eval.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rl.kwalk_eval'`.

- [ ] **Step 3: Implement `rl/kwalk_eval.py`**

```python
from __future__ import annotations

import numpy as np


def roc_auc(y_true, scores) -> float:
    y = np.asarray(y_true)
    s = np.asarray(scores, dtype=np.float64)
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=np.float64)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    _, inv, counts = np.unique(s, return_inverse=True, return_counts=True)
    sum_ranks = np.zeros(len(counts))
    np.add.at(sum_ranks, inv, ranks)
    ranks = (sum_ranks / counts)[inv]
    rank_pos = ranks[y == 1].sum()
    n_pos, n_neg = len(pos), len(neg)
    return float((rank_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def split(samples, frac=0.2, seed=0):
    rng = np.random.default_rng(seed)
    y = samples["y"]
    val_idx = []
    for cls in (0, 1):
        idx = np.where(y == cls)[0]
        rng.shuffle(idx)
        val_idx.extend(idx[: int(round(len(idx) * frac))].tolist())
    val_mask = np.zeros(len(y), dtype=bool)
    val_mask[val_idx] = True

    def take(mask):
        return {"X": samples["X"][mask], "g": samples["g"][mask], "y": samples["y"][mask],
                "H": samples["H"], "W": samples["W"]}
    return take(~val_mask), take(val_mask)


def evaluate(corpus_dirs, *, epochs=30, seed=0):
    from rl.kwalk_data import build_samples
    from rl.kwalk_classifier import train, predict_proba
    s = build_samples(corpus_dirs)
    tr, va = split(s, seed=seed)
    model = train(tr, epochs=epochs, seed=seed)
    p = predict_proba(model, va["X"], va["g"])
    return {"auc": roc_auc(va["y"], p), "n_train": len(tr["y"]),
            "n_val": len(va["y"]), "H": s["H"], "W": s["W"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kwalk_eval.py -q`
Expected: PASS (2 tests; `roc_auc`/`split` are numpy-only. `evaluate` needs `--extra rl` but isn't exercised by these unit tests.)

- [ ] **Step 5: Commit**

```bash
git add rl/kwalk_eval.py tests/test_kwalk_eval.py
git commit -m "feat: ROC-AUC + stratified split + evaluate() for the feasibility CNN"
```

---

### Task 4: Scorer + opt-in k-walk pattern scheduling

**Files:**
- Create: `rl/kwalk_scorer.py`
- Modify: `foeopt/roads_first.py` (`_probe_level` gains `scorer=None`; rank/prune `surviving`; `RoadsFirstSearch` gains `scorer=None`)
- Test: `tests/test_kwalk_schedule.py`

**Interfaces:**
- Consumes: `rl.kwalk_classifier.load`, `rl.kwalk_data.encode_instance`, `foeopt.model`.
- Produces:
  - `foeopt/roads_first.py`: `_probe_level(..., scorer=None, score_threshold=None)` — when `scorer` is set, sort `surviving` by descending `scorer(pat)` and drop patterns scoring below `score_threshold` (if not None). `RoadsFirstSearch(..., scorer=None, score_threshold=None)` threads it in.
  - `rl/kwalk_scorer.py`: `PatternScorer(checkpoint_path, layout)` with `__call__(pattern) -> float` — builds the instance grid+globals for `pattern` (from `layout`'s region/buildings and the pattern's roads/th) and returns `P(SAT)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kwalk_schedule.py`:

```python
import random
import time
from types import SimpleNamespace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as rf


def _tiny():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "hut")
    region = {(x, y) for x in range(5) for y in range(5)}
    return Layout(Region(frozenset(region)), [th, c1], th, {}), region


def test_scorer_orders_and_prunes_patterns(monkeypatch):
    layout, region = _tiny()
    th = Footprint(0, 0, 2, 2)
    pa = rf.Pattern(th=th, roads=frozenset({(2, 0), (2, 1)}), params={"id": "a"})
    pb = rf.Pattern(th=th, roads=frozenset({(2, 0)}), params={"id": "b"})
    pc = rf.Pattern(th=th, roads=frozenset({(3, 0)}), params={"id": "c"})
    monkeypatch.setattr(rf, "generate_patterns", lambda *a, **k: [pa, pb, pc])
    monkeypatch.setattr(rf, "prefilter", lambda *a, **k: None)
    scores = {"a": 0.9, "b": 0.1, "c": 0.5}
    probed = []
    def fake_run_probe_seq(payload):
        pat = payload[0]
        probed.append(pat.params["id"])
        return {"k": payload[1], "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.0, "layout": None, "pat_index": 0, "pos": None}
    monkeypatch.setattr(rf, "_run_probe_seq", fake_run_probe_seq)
    params = SimpleNamespace(patterns=3, probe_limit=1.0, probe_workers=1,
                             deadline=time.monotonic() + 30, th_anchors="coarse")
    rf._probe_level(layout, set(region), layout.road_needing(), 5, random.Random(0),
                    params, lambda r: None, pool=None,
                    scorer=lambda p: scores[p.params["id"]], score_threshold=0.3)
    assert probed == ["a", "c"]        # ranked desc by score; "b" (0.1<0.3) pruned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kwalk_schedule.py -q`
Expected: FAIL — `_probe_level` has no `scorer` kwarg (`TypeError`).

- [ ] **Step 3: Add scorer scheduling to `_probe_level` and `RoadsFirstSearch`**

In `foeopt/roads_first.py`, change the `_probe_level` signature to add trailing `scorer=None, score_threshold=None`:

```python
def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None, corpus=None, scorer=None, score_threshold=None) -> tuple[str, int | None]:
```

After the prefilter loop builds `surviving` (right before the `if pool is None:` dispatch), insert the ranking/pruning:

```python
    if scorer is not None and surviving:
        scored = [(scorer(pat), pat) for pat in surviving]
        if score_threshold is not None:
            scored = [sp for sp in scored if sp[0] >= score_threshold]
        scored.sort(key=lambda sp: sp[0], reverse=True)
        surviving = [pat for _, pat in scored]
```

In `RoadsFirstSearch.__init__`, add `scorer=None, score_threshold=None` (trailing) and store them. In `run()`'s `level(k)`, pass them into the `_probe_level` call:

```python
                results[k] = _probe_level(layout, region, consumers, k, rng,
                                          params, lambda r: None, pool=pool,
                                          on_improvement=on_improvement, corpus=corpus,
                                          scorer=self.scorer, score_threshold=self.score_threshold)
```

Because `_probe_level` gains trailing kwargs and the k-start spies in `tests/test_roads_first_parallel.py` and `tests/roads_first/test_search.py` replace it, add `scorer=None, score_threshold=None` to every `spy_probe_level`/`fake_probe_level` signature in those two files (they already carry `corpus=None`).

- [ ] **Step 4: Implement `rl/kwalk_scorer.py`**

```python
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
```

- [ ] **Step 5: Run tests + regressions**

Run: `uv run pytest tests/test_kwalk_schedule.py tests/test_roads_first_parallel.py tests/roads_first/test_search.py -q`
Expected: PASS. Then `uv run python scripts/exp_roads_first.py --selftest` → `selftest: PASS`.

- [ ] **Step 6: Commit**

```bash
git add foeopt/roads_first.py rl/kwalk_scorer.py tests/test_kwalk_schedule.py tests/test_roads_first_parallel.py tests/roads_first/test_search.py
git commit -m "feat: opt-in CNN pattern scheduling in the k-walk (Track C-bis Stage 1)"
```

---

### Task 5: G1 gate — offline AUC + guided-vs-baseline runbook

**Files:**
- Create: `scripts/kwalk_gate.py` (train + offline AUC + guided-vs-baseline driver)
- Test: `tests/test_kwalk_gate_smoke.py`

**Interfaces:**
- Consumes: `rl.kwalk_eval.evaluate`, `rl.kwalk_classifier`, `rl.kwalk_scorer.PatternScorer`, `foeopt.roads_first.RoadsFirstSearch`, `foeopt.loader.load_layout`.
- Produces: `scripts/kwalk_gate.py` with subcommands `train` (build corpus → train → save checkpoint + report AUC), `walk` (run a k-walk with/without `--scorer`), so a human can run the equal-wall-clock guided-vs-baseline comparison.

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_kwalk_gate_smoke.py`:

```python
import subprocess
import sys


def test_gate_cli_help_lists_subcommands():
    out = subprocess.run([sys.executable, "scripts/kwalk_gate.py", "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "train" in out.stdout and "walk" in out.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kwalk_gate_smoke.py -q`
Expected: FAIL — `scripts/kwalk_gate.py` does not exist.

- [ ] **Step 3: Implement `scripts/kwalk_gate.py`**

```python
"""Track C-bis Stage 1 G1 gate driver.

Usage:
  # train on the Stage-0 corpora, save a checkpoint, print held-out ROC-AUC:
  uv run --extra rl python scripts/kwalk_gate.py train \
      --corpus output/corpus/darkzig output/corpus/FR16 --out output/kwalk/cnn.pt

  # baseline k-walk (no model) vs guided (with model), equal wall-clock:
  uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 3600
  uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 3600 \
      --scorer output/kwalk/cnn.pt

G1 passes iff held-out AUC >= 0.80 AND the guided walk reaches k <= 104
(or 106 in <= 50% of the baseline's wall-clock).
"""
import argparse
import json
import pathlib
import sys


def _train(args):
    from rl.kwalk_eval import evaluate
    from rl.kwalk_data import build_samples
    from rl.kwalk_classifier import train, save
    res = evaluate(args.corpus, epochs=args.epochs, seed=args.seed)
    samples = build_samples(args.corpus)
    model = train(samples, epochs=args.epochs, seed=args.seed)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save(model, out, samples["H"], samples["W"])
    print(json.dumps({**res, "checkpoint": str(out),
                      "G1_auc_pass": res["auc"] >= 0.80}, indent=1))
    return 0


def _walk(args):
    from foeopt.loader import load_layout
    from foeopt.roads_first import RoadsFirstSearch
    layout = load_layout(args.city)
    scorer = None
    if args.scorer:
        from rl.kwalk_scorer import PatternScorer
        scorer = PatternScorer(args.scorer, layout)
    res = RoadsFirstSearch(
        layout, time_box=args.time_box, patterns=args.patterns,
        probe_limit=args.probe_limit, workers=args.workers,
        probe_workers=args.probe_workers, th_anchors=args.th_anchors,
        scorer=scorer, score_threshold=args.score_threshold,
    ).run(on_status=lambda k, s, *_: print(f"  k={k}: {s}", flush=True))
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, indent=1))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Track C-bis Stage 1 G1 gate driver")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--corpus", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--seed", type=int, default=0)
    t.set_defaults(fn=_train)
    w = sub.add_parser("walk")
    w.add_argument("city")
    w.add_argument("--scorer", default=None)
    w.add_argument("--score-threshold", type=float, default=None)
    w.add_argument("--time-box", type=float, default=3600.0)
    w.add_argument("--patterns", type=int, default=200)
    w.add_argument("--probe-limit", type=float, default=30.0)
    w.add_argument("--workers", type=int, default=6)
    w.add_argument("--probe-workers", type=int, default=2)
    w.add_argument("--th-anchors", choices=("coarse", "full"), default="full")
    w.set_defaults(fn=_walk)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the smoke test**

Run: `uv run pytest tests/test_kwalk_gate_smoke.py -q`
Expected: PASS (the CLI parses and lists subcommands; no torch import happens at `--help` time).

- [ ] **Step 5: Commit**

```bash
git add scripts/kwalk_gate.py tests/test_kwalk_gate_smoke.py
git commit -m "feat: G1 gate driver (train/AUC + guided-vs-baseline walk) for Track C-bis Stage 1"
```

- [ ] **Step 6: G1 gate run (human, real compute — not a repo test)**

Once the darkzig + FR16 corpora exist:

```bash
uv run --extra rl python scripts/kwalk_gate.py train \
    --corpus output/corpus/darkzig output/corpus/FR16 --out output/kwalk/cnn.pt
```

Record held-out **AUC**. If AUC ≥ 0.80, run the equal-wall-clock comparison (pick a budget both share, e.g. 1h):

```bash
uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 3600            # baseline
uv run --extra rl python scripts/kwalk_gate.py walk darkzig.json --time-box 3600 --scorer output/kwalk/cnn.pt  # guided
```

**G1 verdict:** PASS iff AUC ≥ 0.80 **and** the guided walk reaches `k ≤ 104` (below the current 106) **or** reaches 106 in ≤ 50% of the baseline's wall-clock. On PASS → proceed to Stage 1.5 (UNKNOWN autopsy). On FAIL → archive the track per the spec, keeping the corpus + encoder + trained model as paid-for assets. Record the numbers in `tasks/lessons.md`.

---

### Task 6: Full-suite regression

**Files:** none (verification only)

- [ ] **Step 1: Default suite (no torch) stays green**

Run: `uv run pytest -q --ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`
Expected: all pass. The numpy-only tests (`test_kwalk_data`, `test_kwalk_eval`, `test_kwalk_schedule`, `test_kwalk_gate_smoke`) run; the torch-only `test_kwalk_classifier` skips (no `--extra rl`). Roads-first + selftest unaffected.

- [ ] **Step 2: rl-extra suite passes**

Run: `uv run --extra rl pytest tests/test_kwalk_data.py tests/test_kwalk_classifier.py tests/test_kwalk_eval.py tests/test_kwalk_schedule.py -q`
Expected: all pass (including the CNN training/roundtrip tests).

- [ ] **Step 3: selftest**

Run: `uv run python scripts/exp_roads_first.py --selftest`
Expected: `selftest: PASS` (the scorer is off by default; the k-walk path is unchanged when `scorer=None`).
