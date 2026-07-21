# Roads-first placement objective — Stage 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Stage-0 proxy correlation study that decides — before any CP-SAT objective code — whether optimizing consumer placement can beat first-feasible, and if so which proxy to use.

**Architecture:** Four pure-Python placement proxies (`foeopt/placement_proxies.py`, unit-tested) computed on finished placements, plus a throwaway study script (`scripts/exp_placement_objective.py`) that: samples comb skeletons, collects N feasible placements each via a CP-SAT solution-pool callback, scores every placement with `route()` and all four proxies, and reports `oracle_gap` + per-proxy Spearman rank-correlation and realized road reduction. The study ends in a `lessons.md` entry with the pre-committed go/kill call.

**Tech Stack:** Python ≥3.12, OR-Tools CP-SAT (study script only), pytest. Design spec: `docs/superpowers/specs/2026-07-21-roads-first-placement-objective-design.md`.

## Global Constraints

- Python `>=3.12` (`pyproject.toml`).
- `foeopt/` core stays **pure-stdlib**: `foeopt/placement_proxies.py` must import only `foeopt.model` + stdlib — no `numpy`, `torch`, or `ortools`.
- `ortools` is allowed in `scripts/` (it is a main dependency); the CP-SAT import stays inside the study script, imported lazily like `foeopt/roads_first.py:probe` does (`from ortools.sat.python import cp_model`).
- Tests that need the gitignored `darkzig.json` must **skip** when it is absent (repo stays green on a fresh clone) — follow the existing `tests/` convention.
- Determinism: all sampling uses a seeded `random.Random`; the CP-SAT collection sets `random_seed` and `num_search_workers = 1`.
- **Pre-committed Stage-0 gate (verbatim from spec §5):** mean `oracle_gap < 1.0` road → KILL the lever. Else advance any proxy that captures `≥ 50%` of `oracle_gap` in mean realized reduction AND has mean rank-corr `≥ 0.4`; prefer the cheapest encoding (P1 cheapest, P4 most expensive). Large `oracle_gap` but no qualifying proxy → document and stop before Stage 1.
- **Scope:** this plan implements Stage 0 only. Stage 1 (opt-in CP-SAT objective for the winning proxy) and Stage 2 (equal-wall-clock A/B) get their own plan **after** the gate, because their code hard-codes the proxy Stage 0 selects — see "Next plan" at the end.

---

## File Structure

- `foeopt/placement_proxies.py` — **new.** Pure-Python proxies over a finished placement: `road_contacts`, `proxy_touched_cells` (P1), `proxy_subtree` (P2), `proxy_double_loaded` (P3), `proxy_same_size_clusters` (P4). One responsibility: turn `(Pattern, positions)` into scalar proxy scores. Reused later as the Stage-1 objective's reference oracle.
- `tests/test_placement_proxies.py` — **new.** Unit tests with hand-computed values on a fixed 6×6 fixture.
- `scripts/exp_placement_objective.py` — **new, throwaway.** The Stage-0 study driver + `spearman` stat + `--selftest`.
- `tasks/lessons.md` — **modify (append).** The Stage-0 result entry and go/kill verdict.

Positions convention (matches `foeopt/roads_first.py:probe`/`validate`): `positions: dict[int, tuple[int, int, int, int]]` mapping `entity_id -> (x, y, w, l)`.

---

### Task 1: P1 proxy — shared/touched road cells

**Files:**
- Create: `foeopt/placement_proxies.py`
- Test: `tests/test_placement_proxies.py`

**Interfaces:**
- Consumes: `foeopt.model.Footprint` (has `.border_cells()`), `foeopt.roads_first.Pattern` (fields `th: Footprint`, `roads: frozenset[tuple[int,int]]`, `params: dict`).
- Produces: `road_contacts(pattern, positions) -> dict[tuple[int,int], set[int]]`; `proxy_touched_cells(pattern, positions) -> int` (lower = better).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_placement_proxies.py
from foeopt.model import Footprint
from foeopt.roads_first import Pattern
from foeopt.placement_proxies import road_contacts, proxy_touched_cells

# Fixture: TH 2x1 at origin, a vertical road lane x=2 (y=0..3).
TH = Footprint(0, 0, 2, 1)
ROADS = frozenset({(2, 0), (2, 1), (2, 2), (2, 3)})
PAT = Pattern(th=TH, roads=ROADS, params={})

# Placement A: eid1 & eid2 flank road (2,2); eid3 touches (2,3).
POS_A = {1: (1, 2, 1, 1), 2: (3, 2, 1, 1), 3: (3, 3, 1, 1)}

def test_road_contacts_maps_cells_to_consumers():
    c = road_contacts(PAT, POS_A)
    assert c == {(2, 2): {1, 2}, (2, 3): {3}}

def test_touched_cells_counts_distinct_road_cells():
    assert proxy_touched_cells(PAT, POS_A) == 2

def test_touched_cells_detects_sharing():
    # both consumers flank the same cell (2,2) -> one touched cell
    assert proxy_touched_cells(PAT, {1: (1, 2, 1, 1), 2: (3, 2, 1, 1)}) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_placement_proxies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foeopt.placement_proxies'`

- [ ] **Step 3: Write minimal implementation**

```python
# foeopt/placement_proxies.py
"""Pure-Python placement proxies for the roads-first inner objective (Stage 0).

Each proxy scores a *finished* consumer placement against a road skeleton,
correlating (Stage 0 measures how well) with the post-route() road count. No
ortools/numpy — this stays importable in the pure-stdlib core and doubles as the
reference oracle for the later CP-SAT objective.

positions: dict[entity_id, (x, y, w, l)] — same shape probe()/validate() emit.
"""
from __future__ import annotations

from foeopt.model import Footprint

Cell = tuple[int, int]
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def road_contacts(pattern, positions) -> dict[Cell, set[int]]:
    """Skeleton road cell -> set of entity_ids orthogonally adjacent to it."""
    roads = pattern.roads
    out: dict[Cell, set[int]] = {}
    for eid, (x, y, w, l) in positions.items():
        for c in Footprint(x, y, w, l).border_cells():
            if c in roads:
                out.setdefault(c, set()).add(eid)
    return out


def proxy_touched_cells(pattern, positions) -> int:
    """P1: number of distinct skeleton cells that carry >=1 consumer. Lower better."""
    return len(road_contacts(pattern, positions))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_placement_proxies.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/placement_proxies.py tests/test_placement_proxies.py
git commit -m "feat: P1 placement proxy (shared road cells) for roads-first Stage 0"
```

---

### Task 2: P2 proxy — TH-rooted subtree size

**Files:**
- Modify: `foeopt/placement_proxies.py`
- Test: `tests/test_placement_proxies.py`

**Interfaces:**
- Consumes: `road_contacts` (Task 1), `pattern.th.cells()`, `pattern.roads`.
- Produces: `proxy_subtree(pattern, positions) -> int` (lower = better) — counts touched cells **plus** the connectors linking them back to the Townhall along the skeleton's BFS tree.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_placement_proxies.py
from foeopt.placement_proxies import proxy_subtree

def test_subtree_adds_connectors_to_townhall():
    # touched cells are (2,2) and (2,3); the only TH-root is (2,0) (adj to (1,0)),
    # so the subtree must include connectors (2,1)+(2,0): {(2,0),(2,1),(2,2),(2,3)} = 4.
    assert proxy_subtree(PAT, POS_A) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_placement_proxies.py::test_subtree_adds_connectors_to_townhall -v`
Expected: FAIL — `ImportError: cannot import name 'proxy_subtree'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to foeopt/placement_proxies.py
from collections import deque


def _road_parents(pattern) -> dict[Cell, Cell | None]:
    """BFS parent map over skeleton road cells, rooted at road cells that touch
    the Townhall footprint. A cell's chain of parents is its path to the TH."""
    roads = set(pattern.roads)
    th_cells = set(pattern.th.cells())
    roots = [c for c in roads
             if any((c[0] + dx, c[1] + dy) in th_cells for dx, dy in _ORTHO)]
    parent: dict[Cell, Cell | None] = {r: None for r in roots}
    q = deque(roots)
    while q:
        c = q.popleft()
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in roads and nb not in parent:
                parent[nb] = c
                q.append(nb)
    return parent


def proxy_subtree(pattern, positions) -> int:
    """P2: size of the connected skeleton subtree (touched cells + their
    connectors to the TH). Lower better. route() may still beat this, so it is an
    upper proxy the real router can only improve on."""
    parent = _road_parents(pattern)
    keep: set[Cell] = set()
    for c in road_contacts(pattern, positions):
        cur: Cell | None = c
        while cur is not None and cur not in keep:
            keep.add(cur)
            cur = parent.get(cur)
    return len(keep)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_placement_proxies.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/placement_proxies.py tests/test_placement_proxies.py
git commit -m "feat: P2 placement proxy (TH-rooted subtree) for roads-first Stage 0"
```

---

### Task 3: P3 proxy — double-loaded contiguity

**Files:**
- Modify: `foeopt/placement_proxies.py`
- Test: `tests/test_placement_proxies.py`

**Interfaces:**
- Consumes: `road_contacts` (Task 1).
- Produces: `proxy_double_loaded(pattern, positions) -> int` (higher = better) — rewards road cells serving ≥2 consumers, plus straight adjacent runs of them.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_placement_proxies.py
from foeopt.placement_proxies import proxy_double_loaded

def test_double_loaded_rewards_shared_cells_and_runs():
    # Only (2,2) serves >=2 consumers; no adjacent load>=2 cell -> 1 + 0 = 1.
    assert proxy_double_loaded(PAT, POS_A) == 1

def test_double_loaded_counts_a_run():
    # Two vertically-adjacent double-loaded cells (2,1)&(2,2): 2 cells + 1 run = 3.
    pos = {1: (1, 1, 1, 1), 2: (3, 1, 1, 1),   # flank (2,1)
           3: (1, 2, 1, 1), 4: (3, 2, 1, 1)}   # flank (2,2)
    assert proxy_double_loaded(PAT, pos) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_placement_proxies.py -k double_loaded -v`
Expected: FAIL — `ImportError: cannot import name 'proxy_double_loaded'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to foeopt/placement_proxies.py
def proxy_double_loaded(pattern, positions) -> int:
    """P3: reward straight double-loaded rows. Count road cells serving >=2
    consumers, plus each collinear-adjacent pair of such cells (a run). Higher
    better."""
    contacts = road_contacts(pattern, positions)
    load2 = {c for c, ids in contacts.items() if len(ids) >= 2}
    runs = 0
    for (cx, cy) in load2:
        for dx, dy in ((1, 0), (0, 1)):  # forward-only so each pair counts once
            if (cx + dx, cy + dy) in load2:
                runs += 1
    return len(load2) + runs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_placement_proxies.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/placement_proxies.py tests/test_placement_proxies.py
git commit -m "feat: P3 placement proxy (double-loaded contiguity) for roads-first Stage 0"
```

---

### Task 4: P4 proxy — same-size lane clustering

**Files:**
- Modify: `foeopt/placement_proxies.py`
- Test: `tests/test_placement_proxies.py`

**Interfaces:**
- Consumes: `positions` only.
- Produces: `proxy_same_size_clusters(pattern, positions) -> int` (higher = better) — rewards same-footprint consumers that share a column-span or row-span (a lane).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_placement_proxies.py
from foeopt.placement_proxies import proxy_same_size_clusters

def test_same_size_clusters_rewards_aligned_same_size_pairs():
    # POS_A: three 1x1s. (1,2)&(3,2) share row y=2 -> +1; (3,2)&(3,3) share col x=3
    # -> +1; (1,2)&(3,3) neither -> 0. Total 2.
    assert proxy_same_size_clusters(PAT, POS_A) == 2

def test_same_size_clusters_ignores_different_sizes():
    # a 1x1 and a 2x1 sharing a row are NOT the same footprint -> 0.
    assert proxy_same_size_clusters(PAT, {1: (1, 2, 1, 1), 2: (3, 2, 2, 1)}) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_placement_proxies.py -k same_size -v`
Expected: FAIL — `ImportError: cannot import name 'proxy_same_size_clusters'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to foeopt/placement_proxies.py
def _lane_aligned(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, al = a
    bx, by, bw, bl = b
    same_col = ax == bx and aw == bw   # stacked in a vertical lane
    same_row = ay == by and al == bl   # in a row of a horizontal lane
    return same_col or same_row


def proxy_same_size_clusters(pattern, positions) -> int:
    """P4: reward same-footprint consumers aligned into a lane (shared column- or
    row-span). Clean double-loading needs equal-depth neighbours. Higher better."""
    by_size: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for (x, y, w, l) in positions.values():
        by_size.setdefault((w, l), []).append((x, y, w, l))
    score = 0
    for items in by_size.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if _lane_aligned(items[i], items[j]):
                    score += 1
    return score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_placement_proxies.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/placement_proxies.py tests/test_placement_proxies.py
git commit -m "feat: P4 placement proxy (same-size lane clustering) for roads-first Stage 0"
```

---

### Task 5: Stage-0 study script + Spearman stat

**Files:**
- Create: `scripts/exp_placement_objective.py`
- Test: `tests/test_placement_objective.py`

**Interfaces:**
- Consumes: `foeopt.loader.load_layout`, `foeopt.model.{Layout,Footprint}`, `foeopt.router.{route,RouteError}`, `foeopt.roads_first.{generate_patterns,probe,_anchor_candidates,_bbox}`, all four proxies from Task 1-4.
- Produces: `spearman(xs, ys) -> float`; `feasible_placements(layout, pattern, n, probe_limit) -> list[dict]`; `roads_for_placement(layout, pattern, positions) -> int | None`; `score_skeleton(layout, pattern, n, probe_limit) -> dict`; `run_study(layout, k_levels, skeletons, placements, probe_limit, seed) -> dict`.

- [ ] **Step 1: Write the failing test** (Spearman is the one piece worth a unit test; the rest is exercised by `--selftest`)

```python
# tests/test_placement_objective.py
import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "exp_placement_objective",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_placement_objective.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

def test_spearman_perfect_monotonic():
    assert mod.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0

def test_spearman_perfect_inverse():
    assert mod.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0

def test_spearman_handles_ties_without_crashing():
    r = mod.spearman([1, 1, 2, 2], [5, 5, 9, 9])
    assert 0.0 <= r <= 1.0

def test_spearman_too_short_is_zero():
    assert mod.spearman([1], [2]) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_placement_objective.py -v`
Expected: FAIL — `FileNotFoundError` / module load error (script does not exist yet)

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/exp_placement_objective.py
"""Stage-0 proxy correlation study for the roads-first placement objective.

Throwaway R&D driver (spec: docs/superpowers/specs/2026-07-21-roads-first-placement-objective-design.md).
For a sample of comb skeletons it collects N feasible consumer placements, scores
each with route() and all four proxies, and reports oracle_gap plus per-proxy
Spearman rank-correlation and realized road reduction — the go/kill evidence.

  uv run python scripts/exp_placement_objective.py --selftest
  uv run python scripts/exp_placement_objective.py darkzig.json --skeletons 30 \
      --placements 20 --k-levels 112,118,125 --probe-limit 20 --out output/stage0.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dataclasses import replace

from foeopt.loader import load_layout
from foeopt.model import Footprint, Layout, Region
from foeopt.router import route, RouteError
from foeopt.roads_first import (
    generate_patterns, probe, _anchor_candidates, _bbox,
)
from foeopt.placement_proxies import (
    proxy_touched_cells, proxy_subtree, proxy_double_loaded, proxy_same_size_clusters,
)

# (name, fn, sign): sign folds each proxy into a "minimize" orientation so that
# argmin(sign*raw) is the placement the proxy would pick and a POSITIVE
# spearman(sign*raw, roads) means the proxy tracks the real road count.
PROXIES = [
    ("P1_touched", proxy_touched_cells, +1),
    ("P2_subtree", proxy_subtree, +1),
    ("P3_double_loaded", proxy_double_loaded, -1),
    ("P4_same_size", proxy_same_size_clusters, -1),
]


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    if len(xs) < 2:
        return 0.0
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def roads_for_placement(layout: Layout, pattern, positions) -> int | None:
    """route() road count for a consumer placement (fillers ignored — they do not
    affect the road count, which route() derives from the consumers before fill)."""
    placed = [replace(b, footprint=Footprint(*positions[b.entity_id]))
              for b in layout.road_needing()]
    th = replace(layout.townhall, footprint=pattern.th)
    cand = Layout(layout.region, [th, *placed], th, {})
    try:
        return len(route(cand))
    except RouteError:
        return None


def feasible_placements(layout: Layout, pattern, n: int, probe_limit: float) -> list[dict]:
    """Up to n distinct feasible consumer placements on a fixed skeleton, via the
    CP-SAT solution pool. Same model as roads_first.probe(), no objective."""
    from ortools.sat.python import cp_model

    region = set(layout.region.cells)
    consumers = layout.road_needing()
    blocked = set(pattern.roads) | set(pattern.th.cells())
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            return []
        cand.append((b, opts))

    m = cp_model.CpModel()
    x0b, y0b, x1b, y1b = _bbox(region)
    xs, ys, xiv, yiv = [], [], [], []
    for i, (b, opts) in enumerate(cand):
        x = m.NewIntVar(x0b, x1b, f"x{i}")
        y = m.NewIntVar(y0b, y1b, f"y{i}")
        m.AddAllowedAssignments([x, y], opts)
        xiv.append(m.NewFixedSizeIntervalVar(x, b.footprint.width, f"xi{i}"))
        yiv.append(m.NewFixedSizeIntervalVar(y, b.footprint.length, f"yi{i}"))
        xs.append(x); ys.append(y)
    m.AddNoOverlap2D(xiv, yiv)

    collected: list[dict] = []

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()  # required: SWIG-wrapped base

        def on_solution_callback(self):
            pos = {}
            for i, (b, _) in enumerate(cand):
                pos[b.entity_id] = (self.Value(xs[i]), self.Value(ys[i]),
                                    b.footprint.width, b.footprint.length)
            collected.append(pos)
            if len(collected) >= n:
                self.StopSearch()

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = probe_limit
    solver.parameters.enumerate_all_solutions = True
    solver.Solve(m, _Collector())
    return collected


def score_skeleton(layout: Layout, pattern, n: int, probe_limit: float) -> dict | None:
    """Collect placements, score each; return per-skeleton oracle_gap + proxy stats.
    None if <2 usable placements (nothing to correlate)."""
    placements = feasible_placements(layout, pattern, n, probe_limit)
    rows = []
    for pos in placements:
        r = roads_for_placement(layout, pattern, pos)
        if r is None:
            continue
        vals = {name: sign * fn(pattern, pos) for name, fn, sign in PROXIES}
        rows.append((r, vals))
    if len(rows) < 2:
        return None
    roads = [r for r, _ in rows]
    first_roads = roads[0]  # first solution found == today's first-feasible probe result
    oracle_gap = first_roads - min(roads)
    out = {"n_placements": len(rows), "first_roads": first_roads,
           "min_roads": min(roads), "oracle_gap": oracle_gap, "proxies": {}}
    for name, _, _ in PROXIES:
        col = [vals[name] for _, vals in rows]
        best_idx = min(range(len(rows)), key=lambda i: col[i])
        out["proxies"][name] = {
            "spearman": round(spearman(col, roads), 3),
            "realized_reduction": first_roads - roads[best_idx],
        }
    return out


def run_study(layout: Layout, k_levels, skeletons: int, placements: int,
              probe_limit: float, seed: int) -> dict:
    rng = random.Random(seed)
    region = set(layout.region.cells)
    tw, tl = layout.townhall.footprint.width, layout.townhall.footprint.length
    per_level = max(1, skeletons // len(k_levels))
    results = []
    for k in k_levels:
        pats = generate_patterns(region, tw, tl, k, rng, per_level, th_mode="full")
        for pat in pats:
            s = score_skeleton(layout, pat, placements, probe_limit)
            if s is not None:
                s["k"] = k
                results.append(s)
    return summarize(results)


def summarize(results: list[dict]) -> dict:
    if not results:
        return {"skeletons_scored": 0, "note": "no skeleton yielded >=2 placements"}
    gaps = [r["oracle_gap"] for r in results]
    summary = {"skeletons_scored": len(results),
               "mean_oracle_gap": round(sum(gaps) / len(gaps), 3),
               "max_oracle_gap": max(gaps), "proxies": {}}
    for name, _, _ in PROXIES:
        corrs = [r["proxies"][name]["spearman"] for r in results]
        reds = [r["proxies"][name]["realized_reduction"] for r in results]
        summary["proxies"][name] = {
            "mean_spearman": round(sum(corrs) / len(corrs), 3),
            "mean_realized_reduction": round(sum(reds) / len(reds), 3),
        }
    return summary


def _selftest() -> int:
    # Tiny synthetic instance: TH + 2 same-size consumers in a 6x6 region.
    from foeopt.model import Building
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "b")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1, c2], th, {})
    out = run_study(layout, [6], skeletons=4, placements=6, probe_limit=5.0, seed=0)
    assert spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert "skeletons_scored" in out
    print("SELFTEST OK:", json.dumps(out))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("helper", nargs="?")
    ap.add_argument("--k-levels", default="112,118,125")
    ap.add_argument("--skeletons", type=int, default=30)
    ap.add_argument("--placements", type=int, default=20)
    ap.add_argument("--probe-limit", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    layout = load_layout(args.city, args.helper)
    k_levels = [int(x) for x in args.k_levels.split(",")]
    out = run_study(layout, k_levels, args.skeletons, args.placements,
                    args.probe_limit, args.seed)
    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the unit test and the selftest**

Run: `uv run pytest tests/test_placement_objective.py -v`
Expected: PASS (4 tests)

Run: `uv run python scripts/exp_placement_objective.py --selftest`
Expected: prints `SELFTEST OK: {...}` and exits 0

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_placement_objective.py tests/test_placement_objective.py
git commit -m "feat: Stage-0 placement-objective correlation study (script + spearman)"
```

---

### Task 6: Run Stage 0 on darkzig and record the gate verdict

**Files:**
- Modify: `tasks/lessons.md` (append a dated entry)

This task has no unit test — it runs the experiment and applies the pre-committed gate. Requires the gitignored `darkzig.json` in the project root (user-supplied). If absent, stop and tell the user it is needed.

- [ ] **Step 1: Smoke the pipeline cheaply first**

Run: `uv run python scripts/exp_placement_objective.py darkzig.json --skeletons 6 --placements 8 --probe-limit 10 --k-levels 118`
Expected: JSON with `skeletons_scored >= 1` and a `proxies` block. If `skeletons_scored == 0`, raise the `--probe-limit` (skeletons need ≥2 feasible placements) before the full run.

- [ ] **Step 2: Full study run**

Run: `uv run python scripts/exp_placement_objective.py darkzig.json --skeletons 30 --placements 20 --k-levels 112,118,125 --probe-limit 20 --out output/stage0-placement.json`
Expected: JSON summary with `mean_oracle_gap`, `max_oracle_gap`, and per-proxy `mean_spearman` + `mean_realized_reduction`.

- [ ] **Step 3: Apply the pre-committed gate and write the lessons entry**

Apply the Global-Constraints gate to the numbers:
- `mean_oracle_gap < 1.0` → **KILL** (first-feasible already ~best; 102 is placement-optimal for the comb family — a real answer to the headroom question).
- Else advance each proxy with `mean_realized_reduction >= 0.5 * mean_oracle_gap` AND `mean_spearman >= 0.4`; among those, name the cheapest-encoding winner (P1 < P2 < P3 < P4 by model cost).
- Large `mean_oracle_gap` but no qualifying proxy → document; do NOT start Stage 1.

Append to `tasks/lessons.md` an entry titled `## Roads-first placement objective — Stage 0 correlation study (2026-07-21)` containing: the exact command, the summary JSON, the gate arithmetic, and the verdict (KILL / advance `<proxy>` / signal-without-proxy). Follow the voice of the existing "TESTED … closed" entries.

- [ ] **Step 4: Commit**

```bash
git add tasks/lessons.md output/stage0-placement.json
git commit -m "docs: roads-first placement objective Stage 0 result + gate verdict"
```

*(If `output/` is gitignored, drop it from the `git add` — commit only `tasks/lessons.md`.)*

---

## Next plan (post-gate, out of scope here)

Written only if Task 6 advances a proxy (`mean_oracle_gap >= 1.0` and a proxy qualifies):

- **Stage 1** — add the winning proxy as an **opt-in** `Minimize`/`Maximize` on `foeopt/roads_first.py:probe` (default off, byte-identical when off). Introduce the per-option one-hot adjacency channelling the proxy needs; require the objective probe to seed from a fast first-feasible incumbent (`AddHint`) so feasibility never regresses. Unit tests: off == byte-identical; on == the proxy's Python value matches `foeopt.placement_proxies`; feasibility not lost on a fixture.
- **Stage 2** — the equal-wall-clock A/B (objective on vs off) on darkzig, ≥3 seeds, 0-unplaced, with the pre-committed win/kill from spec §5. Wire it through `scripts/kwalk_gate.py`.

The exact CP-SAT objective code is deliberately not written here — it hard-codes a proxy the experiment has not yet chosen.

---

## Self-Review

**1. Spec coverage.** Spec §5 Stage 0 (correlation study) → Tasks 1-6. The four proxies §4 (P1-P4) → Tasks 1-4. `oracle_gap`, rank-corr, realized reduction → Task 5 `score_skeleton`/`summarize`. Pre-committed gate → Task 6 Step 3 + Global Constraints. Stage 1/2 (§5) → explicitly deferred to the post-gate plan with rationale (spec's own "only if Stage 0 advances"). Non-goals §6 → nothing in this plan touches the filler packer, pattern-gen spacing, swap moves, or probe latency. No gaps for Stage 0.

**2. Placeholder scan.** No "TBD"/"TODO"/"handle edge cases". Every code step is complete. Task 6 is analysis, not code — its steps are exact commands + the verbatim gate rule, not placeholders.

**3. Type consistency.** `positions` is `dict[int, tuple[int,int,int,int]]` everywhere (proxies, `roads_for_placement`, `feasible_placements`, `score_skeleton`). Proxy names `proxy_touched_cells`/`proxy_subtree`/`proxy_double_loaded`/`proxy_same_size_clusters` match between `placement_proxies.py`, tests, and the script's `PROXIES` table. `road_contacts` returns `dict[Cell,set[int]]`, consumed by P1/P2/P3. `spearman(xs,ys)->float` consistent between test and script. `Pattern(th=,roads=,params=)` matches `foeopt/roads_first.py:generate_patterns` usage. `_anchor_candidates(b, region, blocked, roads)` and `_bbox(region)` signatures match `foeopt/roads_first.py`.
