# Road-Target Calibration + Lane/Stub Composition Go/No-Go — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-based road-count target band for darkzig and a go/kill verdict on the Track-A lane/stub decomposition — before any geometry work.

**Architecture:** Durable, stdlib measurement code goes into `foeopt/` (quality sharing metrics, provable bounds) with tests. The CP-SAT composition solver is a throwaway script under `scripts/`, run via `uv run --with ortools`, validated by a built-in tiny-instance self-test against `rl/oracle.py` and calibrated on the user's hand-tuned city (known expert answer: 142 roads). The verdict lands in `tasks/lessons.md` + `tasks/todo.md`.

**Tech Stack:** Python 3.12, pure stdlib in `foeopt/`, pytest; OR-Tools CP-SAT only inside the script via `uv run --with ortools` (never a repo dependency).

Spec: `docs/superpowers/specs/2026-07-02-road-target-calibration-design.md`.

## Global Constraints

- `foeopt/` stays **pure-stdlib**. OR-Tools is used only through `uv run --with ortools scripts/...` and never appears in `pyproject.toml`.
- **Determinism:** CP-SAT runs with `num_search_workers = 1` and `random_seed = 0` (lessons: multi-worker CP-SAT is non-deterministic).
- **Benchmark discipline:** never compare road counts without checking placement status; the 97%-full `city-user-data.json` is a metric fixture here (known 142 roads), never a packer baseline.
- **Targets in play:** darkzig Σ(short-side)/2 = 114 (estimate, not a bound); local-method floor = 158; user's city = 142 roads (expert-real, below its own Σ/2 = 157).
- **Gate (spec §5):** C* = calibrated family-optimum with pessimistic trunk. C* ≥ ~150 → kill Track A; C* ≤ ~130 → go (write the A2/A3 spec); between → user decides.
- TDD for all `foeopt/` code: failing test first, then implement, then green, then commit.

---

## File Structure

| file | role | task |
|---|---|---|
| `tasks/lessons.md` | RL-archival entry (T1) + final verdict entry (T5) | T1, T5 |
| `.gitignore` | ignore `*.log` training logs | T1 |
| `rl/README.md` | archived-status note | T1 |
| `foeopt/quality.py` | add `road_cell_load`, `sharing_histogram`, `road_contribution`; extend `format_quality` | T2 |
| `tests/test_quality.py` | sharing-metric tests + bundled-city regression | T2 |
| `foeopt/bounds.py` | NEW: provable lower bounds | T3 |
| `tests/test_bounds.py` | NEW: bound ≤ known optima / achievable values | T3 |
| `scripts/exp_lane_composition.py` | NEW (throwaway): CP-SAT composition solver + self-test | T4 |
| `tasks/todo.md` | verdict in the Review section | T5 |

---

## Task 1: Archive the RL track

The M4 gate failed by its own fail-fast rule (design spec §2, brainstorm decision). Commit the pending working-tree changes as-is, record the lesson, stop treating `rl/` as active work. Nothing is deleted — env, tests, and checkpoints stay usable.

**Files:**
- Modify: `rl/ppo.py`, `rl/train.py` (already-modified working tree: the `fill=` plumbing), `rl/imitate.py` (untracked), `rl/README.md`, `tasks/lessons.md`, `.gitignore`

**Interfaces:**
- Produces: nothing consumed by later tasks; a clean working tree so T2+ commits are isolated.

- [ ] **Step 1: Append the `*.log` ignore rule**

Append to `.gitignore` (create it if missing):

```
*.log
```

Verify: `git status --short` no longer lists `training*.log`, `bc*.log`.

- [ ] **Step 2: Mark rl/README.md archived**

In `rl/README.md`, replace the line:

```markdown
**Status:** the environment (`foeopt/rlenv.py`) and this training stack are built
and **structurally smoke-tested on CPU** (one PPO update + eval run cleanly). They
have **not been trained to convergence** — that needs a GPU and hours-to-days.
```

with:

```markdown
**Status: ARCHIVED (2026-07-02).** The M4 gate failed per its own fail-fast rule:
0% episode success at darkzig-like 0.9 fill, greedy darkzig eval always
stuck/unroutable, and the imitation warm-start rescue (`rl/imitate.py`, BC acc
45.8%) collapsed to 6–12% success under RL fine-tuning. See the 2026-07-02
entry in `tasks/lessons.md`. The env, tests, and this stack remain usable; no
further GPU training is planned. The road objective moved to the classical
Track-A/B/C1 plan (`tasks/todo.md`).
```

- [ ] **Step 3: Append the lessons entry**

Append to `tasks/lessons.md`:

```markdown
## RL placement (M2-M4) archived: the gate failed by its own rule (2026-07-02)
**Evidence (training logs, ROCm GPU):** curriculum stages learn, but at moderate
fill the policy places 80-86% of episodes with mean_roads ~3x target; at
darkzig-like fill 0.7-0.9 success is 0% everywhere (training_bridge.log,
training_m4.log); every greedy darkzig eval ends stuck/unroutable. The designated
rescue lever - imitation warm-start from repack experts (rl/imitate.py, BC top-1
acc 45.8%) - collapsed to 6-12% success under PPO fine-tuning (training_bc_rl.log),
likely catastrophic forgetting. Per the design's fail-fast rule (spec 2026-06-23
section 9.4), that exhausts the track.
**Root cause (same wall as attempts 1-7):** the policy never observes road
structure during an episode (roads are computed only at the terminal step), so at
90% fill it cannot learn to leave road channels; the -100 trap returns as soon as
the fill rises. Fixing that means changing the formulation (roads in the
observation, routability-preserving action masking, DAgger), not the knobs.
**Rule:** don't resume RL training on this formulation. If RL is ever revisited,
it must include the routability mask (foeopt/reach.py, 2026-07-02 spec) and
road-visible observations, and it competes against the Track-A structured
optimizer, not against random rollouts.
```

- [ ] **Step 4: Commit the archive**

```bash
git add rl/ppo.py rl/train.py rl/imitate.py rl/README.md tasks/lessons.md .gitignore
git commit -m "chore(rl): archive M2-M4 track — gate failed per its own fail-fast rule"
```

Expected: `git status --short` shows a clean tree (logs ignored, no tracked changes).

---

## Task 2: Road-sharing metrics in quality.py

The "avg 2.02 buildings per road cell" analysis of the user's city, generalized into reusable metrics and surfaced in the CLI quality line. These are the structural targets the composition model must reproduce.

**Files:**
- Modify: `foeopt/quality.py` (append functions; extend `format_quality` at `foeopt/quality.py:84-91`)
- Test: `tests/test_quality.py` (append)

**Interfaces:**
- Consumes: `Layout.road_needing()`, `Footprint.border_cells()` (existing).
- Produces:
  - `road_cell_load(layout: Layout) -> dict[tuple[int, int], int]` — per road cell, the number of road-needing buildings orthogonally adjacent.
  - `sharing_histogram(layout: Layout) -> dict[int, int]` — road-cell count by load.
  - `road_contribution(layout: Layout) -> dict[int, float]` — per consumer entity_id, Σ over its adjacent road cells of 1/load. Identity: Σ contributions = number of road cells with load ≥ 1, so `roads_total − Σ` = pure-connectivity overhead = `hist[0]`.
  - `format_quality` gains a sharing segment.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_quality.py`:

```python
from foeopt.quality import road_cell_load, sharing_histogram, road_contribution


def _sharing_layout():
    # TH(0,0); road (1,0),(1,1); consumers A(2,0), B(2,1), C(0,1) all 1x1.
    # (1,0) touches only A (TH is not road-needing) -> load 1.
    # (1,1) touches B and C -> load 2.
    th = _b(1, 0, 0, th=True)
    a = _b(10, 2, 0, needs=True)
    b = _b(11, 2, 1, needs=True)
    c = _b(12, 0, 1, needs=True)
    return Layout(_region(4, 3), [th, a, b, c], th, {(1, 0): 1, (1, 1): 1})


def test_road_cell_load_counts_adjacent_consumers():
    load = road_cell_load(_sharing_layout())
    assert load == {(1, 0): 1, (1, 1): 2}


def test_sharing_histogram_buckets_by_load():
    assert sharing_histogram(_sharing_layout()) == {1: 1, 2: 1}


def test_road_contribution_splits_shared_cells():
    contrib = road_contribution(_sharing_layout())
    assert contrib[10] == 1.0            # A owns (1,0)
    assert contrib[11] == 0.5            # B shares (1,1)
    assert contrib[12] == 0.5            # C shares (1,1)
    assert sum(contrib.values()) == 2.0  # == number of load>=1 road cells


def test_format_quality_includes_sharing():
    line = format_quality(_sharing_layout())
    assert "road sharing avg 1.50" in line
    assert "overhead cells 0" in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quality.py -k "sharing or load or contribution" -v`
Expected: FAIL with `ImportError: cannot import name 'road_cell_load'`.

- [ ] **Step 3: Implement the metrics**

Append to `foeopt/quality.py` (before `quality_report`):

```python
def road_cell_load(layout: Layout) -> dict[tuple[int, int], int]:
    """Per road cell: how many road-needing buildings it is orthogonally
    adjacent to. Load 2 is the double-row ideal; 3 happens at junctions/stubs;
    0 is pure connectivity overhead. The Townhall and fillers don't count."""
    load = {c: 0 for c in layout.roads}
    for b in layout.road_needing():
        for c in b.footprint.border_cells():
            if c in load:
                load[c] += 1
    return load


def sharing_histogram(layout: Layout) -> dict[int, int]:
    """Road-cell count by load — the shape of road sharing in one dict."""
    hist: dict[int, int] = {}
    for v in road_cell_load(layout).values():
        hist[v] = hist.get(v, 0) + 1
    return hist


def road_contribution(layout: Layout) -> dict[int, float]:
    """Per consumer: sum over its adjacent road cells of 1/load. Splits each
    shared cell's cost among the buildings it serves; the total equals the
    number of load>=1 road cells, so roads_total - total = overhead cells."""
    load = road_cell_load(layout)
    return {
        b.entity_id: sum(1.0 / load[c] for c in b.footprint.border_cells()
                         if load.get(c, 0) > 0)
        for b in layout.road_needing()
    }
```

Then replace `format_quality` (`foeopt/quality.py:84-91`) with:

```python
def format_quality(layout: Layout) -> str:
    """One-line human summary for the CLI."""
    q = quality_report(layout)
    line = (
        f"placement quality: fillers touching a road {q['filler_road_adjacent']}"
        f"/{q['fillers_total']} (rule 1) | "
        f"under-used roads {q['underused_roads']}/{q['roads_total']} (rule 2)"
    )
    load = road_cell_load(layout)
    if load:
        hist = sharing_histogram(layout)
        avg = sum(load.values()) / len(load)
        buckets = " ".join(f"{k}:{hist[k]}" for k in sorted(hist, reverse=True))
        line += (f" | road sharing avg {avg:.2f} ({buckets})"
                 f" | overhead cells {hist.get(0, 0)}")
    return line
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quality.py -v`
Expected: all pass (new + the existing rule-1/rule-2 tests, whose `format_quality` assertions only check the prefix).

- [ ] **Step 5: Measure the bundled city, then pin it as a regression test**

Run the measurement:

```bash
uv run python -c "
from foeopt.loader import load_layout
from foeopt.quality import sharing_histogram, road_cell_load
lay = load_layout('city-user-data.json', 'city-user-data-foe-helper.json')
load = road_cell_load(lay)
print('roads', len(load), 'hist', sharing_histogram(lay),
      'avg', round(sum(load.values())/len(load), 2))
"
```

Expected (from the 2026-06 analysis): 142 roads, avg ≈ 2.02, ~137 cells at load 2, ~4 at load 3. **Pin whatever this prints** (the metric definition is authoritative, the remembered numbers are the sanity check — investigate before pinning if avg is outside 1.9–2.1). Append to `tests/test_quality.py`, substituting the measured values:

```python
def test_bundled_city_sharing_regression(repo_root):
    from foeopt.loader import load_layout
    lay = load_layout(str(repo_root / "city-user-data.json"),
                      str(repo_root / "city-user-data-foe-helper.json"))
    load = road_cell_load(lay)
    hist = sharing_histogram(lay)
    assert len(load) == 142
    assert round(sum(load.values()) / len(load), 2) == 2.02   # measured
    assert hist[2] == 137 and hist[3] == 4                    # measured
```

Run: `uv run pytest tests/test_quality.py::test_bundled_city_sharing_regression -v`
Expected: PASS with the pinned values.

- [ ] **Step 6: Commit**

```bash
git add foeopt/quality.py tests/test_quality.py
git commit -m "feat(quality): road-sharing metrics — per-cell load, histogram, contribution"
```

---

## Task 3: Provable lower bounds (foeopt/bounds.py)

Only bounds with airtight arguments (spec §3.2). Right now that is one bound; the module exists so future provable refinements have a home and a test harness.

**Files:**
- Create: `foeopt/bounds.py`
- Test: `tests/test_bounds.py`

**Interfaces:**
- Consumes: `Layout.road_needing()`; `rl.oracle.optimal_roads(layout, *, budget_s)` (tests only — it is stdlib).
- Produces:
  - `bound_adjacency(layout: Layout) -> int`
  - `report_bounds(layout: Layout) -> dict[str, int]` with per-bound values + `"max"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bounds.py`:

```python
from pathlib import Path

import pytest

from foeopt.bounds import bound_adjacency, report_bounds
from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from rl.oracle import optimal_roads


def _b(eid, w, l, *, needs=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(0, 0, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_adjacency_bound_is_ceil_n_over_3():
    th = _b(1, 2, 2, th=True)
    cons = [_b(10 + i, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_region(10, 10), [th, *cons], th, {})
    assert bound_adjacency(layout) == 2          # ceil(4/3)


def test_bound_le_true_optimum_on_tiny_instance():
    th = _b(1, 2, 2, th=True)
    c1 = _b(10, 2, 2, needs=True)
    c2 = _b(11, 2, 1, needs=True)
    layout = Layout(_region(6, 6), [th, c1, c2], th, {})
    opt = optimal_roads(layout, budget_s=30.0)
    assert opt is not None
    assert bound_adjacency(layout) <= opt


def test_bounds_below_known_achievable_on_user_city(repo_root):
    lay = load_layout(str(repo_root / "city-user-data.json"),
                      str(repo_root / "city-user-data-foe-helper.json"))
    assert report_bounds(lay)["max"] <= 142      # expert-real road count


def test_bounds_below_known_achievable_on_darkzig(repo_root):
    path = repo_root / "darkzig.json"
    if not path.exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout(str(path))
    assert report_bounds(lay)["max"] <= 158      # polish-achieved road count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bounds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foeopt.bounds'`.

- [ ] **Step 3: Implement**

Create `foeopt/bounds.py`:

```python
"""Provable, placement-independent lower bounds on the road count.

Buildings are movable, so any bound here must hold over ALL feasible
placements — border-based arguments from a specific layout do not qualify.
That makes honest bounds weak (see the 2026-07-02 calibration spec): their
role is to anchor the bottom of the target band, not to be tight. Anything
added here needs an airtight argument in its docstring and a test proving
bound <= a known optimum/achievable value.
"""
from __future__ import annotations

import math

from foeopt.model import Layout


def bound_adjacency(layout: Layout) -> int:
    """roads >= ceil(n_consumers / 3): a road cell has 4 orthogonal
    neighbours, and in any connected network of >= 2 cells (or a 1-cell
    network, which must touch the Townhall border) at least one neighbour is
    a road or the Townhall — so a single road cell serves at most 3
    road-needing buildings."""
    return math.ceil(len(layout.road_needing()) / 3)


def report_bounds(layout: Layout) -> dict[str, int]:
    """All provable bounds plus their max (the usable combined bound)."""
    bounds = {"adjacency": bound_adjacency(layout)}
    bounds["max"] = max(bounds.values())
    return bounds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bounds.py -v`
Expected: all pass (the oracle test takes seconds — it enumerates a 6×6 with 2 movable buildings).

- [ ] **Step 5: Commit**

```bash
git add foeopt/bounds.py tests/test_bounds.py
git commit -m "feat(bounds): provable road lower bounds — adjacency capacity"
```

---

## Task 4: Lane/stub composition solver (throwaway CP-SAT script)

The optimal road cost within the expert layout family (double-loaded uniform-depth lanes stacked on a trunk, optional end-stubs), for a city's exact road-needing inventory. This number — calibrated in T5 — is the go/no-go gate. Throwaway per the spec: full code lives in one script, validated by its built-in self-test, never imported by `foeopt/`.

**Files:**
- Create: `scripts/exp_lane_composition.py`

**Interfaces:**
- Consumes: `foeopt.loader.load_layout`, `foeopt.packer.bbox`, `rl.oracle.optimal_roads` (self-test only).
- Produces: a JSON report on stdout / `-o` — keys `city, n_consumers, status, model_optimum, proven_bound, gap, trunk_pessimistic, optimistic_total, lanes, stub_cells`. T5 consumes these numbers manually.

- [ ] **Step 1: Write the script**

Create `scripts/exp_lane_composition.py`:

```python
"""THROWAWAY EXPERIMENT (2026-07-02 calibration spec, Task A1).

Optimal road cost within the expert layout family: buildings are assigned to
double-loaded straight lanes (uniform depth per side, orientation free), lanes
stack along a perpendicular trunk, optional dead-end stubs at lane ends serve
up to 3 buildings each. Costs: lane = max(side loads); trunk pessimistic =
sum(depthA + 1 + depthB) over used lanes; stub = 1 cell each. The model is a
RESTRICTION of the real problem, so family-optimum >= true optimum wherever
both are computable (checked by --selftest against rl.oracle).

Run (never a repo dep):
  uv run --with ortools python scripts/exp_lane_composition.py --selftest
  uv run --with ortools python scripts/exp_lane_composition.py \
      city-user-data.json city-user-data-foe-helper.json -o output/comp-user.json
  uv run --with ortools python scripts/exp_lane_composition.py darkzig.json \
      -o output/comp-darkzig.json
"""
from __future__ import annotations

import argparse
import json
import sys

from ortools.sat.python import cp_model

from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import bbox


def solve_composition(items, *, k_max, len_max, stack_max, area_budget,
                      stubs=False, time_limit=120.0):
    """items: list of (entity_id, w, l) road-needing buildings.
    Returns a result dict (see report keys)."""
    m = cp_model.CpModel()
    n = len(items)
    depths = sorted({d for (_, w, l) in items for d in (w, l)})

    x = {}                       # x[i,k,s,o]=1: item i on lane k side s orient o
    stub_y = {}                  # stub_y[i]=1: item i served by a stub
    for i, (_, w, l) in enumerate(items):
        opts = []
        for k in range(k_max):
            for s in (0, 1):
                for o in (0, 1):
                    v = m.NewBoolVar(f"x_{i}_{k}_{s}_{o}")
                    x[i, k, s, o] = v
                    opts.append(v)
        if stubs:
            stub_y[i] = m.NewBoolVar(f"stub_{i}")
            opts.append(stub_y[i])
        m.AddExactlyOne(opts)

    d = {}                       # d[k,s,dep]=1: lane k side s has depth class dep
    for k in range(k_max):
        for s in (0, 1):
            for dep in depths:
                d[k, s, dep] = m.NewBoolVar(f"d_{k}_{s}_{dep}")
            m.AddAtMostOne(d[k, s, dep] for dep in depths)
    for i, (_, w, l) in enumerate(items):
        for k in range(k_max):
            for s in (0, 1):
                # orientation o=0: extent w, depth l; o=1: extent l, depth w
                m.AddImplication(x[i, k, s, 0], d[k, s, l])
                m.AddImplication(x[i, k, s, 1], d[k, s, w])

    lane_len, thick, used = [], [], []
    for k in range(k_max):
        loads = []
        for s in (0, 1):
            load = m.NewIntVar(0, len_max, f"L_{k}_{s}")
            m.Add(load == sum(
                x[i, k, s, 0] * w + x[i, k, s, 1] * l
                for i, (_, w, l) in enumerate(items)))
            loads.append(load)
        ll = m.NewIntVar(0, len_max, f"len_{k}")
        m.AddMaxEquality(ll, loads)
        lane_len.append(ll)
        u = m.NewBoolVar(f"u_{k}")
        m.Add(ll >= 1).OnlyEnforceIf(u)
        m.Add(ll == 0).OnlyEnforceIf(u.Not())
        used.append(u)
        for s in (0, 1):
            for dep in depths:
                m.AddImplication(u.Not(), d[k, s, dep].Not())
        tk = m.NewIntVar(0, 2 * max(depths) + 1, f"t_{k}")
        m.Add(tk == sum(dep * d[k, 0, dep] for dep in depths)
                  + sum(dep * d[k, 1, dep] for dep in depths) + u)
        thick.append(tk)
    for k in range(k_max - 1):                    # symmetry breaking
        m.Add(lane_len[k] >= lane_len[k + 1])

    stub_cells = m.NewIntVar(0, n, "stub_cells")
    if stubs:
        m.Add(3 * stub_cells >= sum(stub_y.values()))
        m.Add(stub_cells <= 2 * sum(used))        # <=1 stub per lane end
    else:
        m.Add(stub_cells == 0)

    trunk_pess = m.NewIntVar(0, 10000, "trunk")
    m.Add(trunk_pess == sum(thick))
    m.Add(trunk_pess <= stack_max)                # lanes must stack in-region
    total = m.NewIntVar(0, 100000, "total")
    m.Add(total == sum(lane_len) + trunk_pess + stub_cells)
    m.Add(total <= area_budget)                   # buildings + roads fit region
    m.Minimize(total)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": solver.StatusName(status)}
    lanes = []
    for k in range(k_max):
        if not solver.Value(used[k]):
            continue
        members = [[], []]
        for i, (eid, w, l) in enumerate(items):
            for s in (0, 1):
                if solver.Value(x[i, k, s, 0]) or solver.Value(x[i, k, s, 1]):
                    members[s].append(eid)
        lanes.append({"len": solver.Value(lane_len[k]),
                      "thickness": solver.Value(thick[k]),
                      "side_a": members[0], "side_b": members[1]})
    n_used = sum(solver.Value(u) for u in used)
    lane_total = sum(la["len"] for la in lanes)
    return {
        "status": solver.StatusName(status),
        "model_optimum": solver.Value(total),
        "proven_bound": int(solver.BestObjectiveBound()),
        "gap": solver.Value(total) - int(solver.BestObjectiveBound()),
        "trunk_pessimistic": solver.Value(trunk_pess),
        "optimistic_total": lane_total + n_used + solver.Value(stub_cells),
        "stub_cells": solver.Value(stub_cells),
        "lanes": lanes,
    }


def _selftest():
    """Family-optimum must be >= the true joint optimum (the family is a
    restriction). Tiny instance sized for rl.oracle's exhaustive search."""
    from rl.oracle import optimal_roads
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2),
                  True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1),
                  True, 1, False, None, None, "b")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1, c2], th, {})
    opt = optimal_roads(layout, budget_s=60.0)
    items = [(b.entity_id, b.footprint.width, b.footprint.length)
             for b in layout.road_needing()]
    res = solve_composition(items, k_max=2, len_max=6, stack_max=6,
                            area_budget=36, time_limit=30.0)
    ok = (opt is not None and res.get("model_optimum") is not None
          and res["model_optimum"] >= opt)
    print(f"selftest: oracle={opt} family={res.get('model_optimum')} "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("helper", nargs="?", default=None)
    p.add_argument("--lanes", type=int, default=12)
    p.add_argument("--stack-max", type=int, default=None,
                   help="cap on summed lane thicknesses (default 2x the bbox max "
                        "dim - real layouts stack lanes in more than one column; "
                        "a single-stack cap can spuriously report INFEASIBLE)")
    p.add_argument("--stubs", action="store_true")
    p.add_argument("--time-limit", type=float, default=120.0)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("-o", "--out", default=None)
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.city:
        p.error("city required unless --selftest")
    layout = load_layout(args.city, args.helper)
    items = [(b.entity_id, b.footprint.width, b.footprint.length)
             for b in layout.road_needing()]
    w, h = bbox(layout.region)
    building_area = sum(b.footprint.width * b.footprint.length
                        for b in layout.buildings)
    res = solve_composition(
        items, k_max=args.lanes, len_max=max(w, h) - 1,
        stack_max=args.stack_max or 2 * max(w, h),
        area_budget=len(layout.region.cells) - building_area,
        stubs=args.stubs, time_limit=args.time_limit)
    res.update({"city": args.city, "n_consumers": len(items)})
    out = json.dumps(res, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(out + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the self-test**

```bash
uv run --with ortools python scripts/exp_lane_composition.py --selftest
```

Expected: `selftest: oracle=<n> family=<m> PASS` with `m >= n`. If FAIL, the model under-counts road cells — fix the model before touching any real city (most likely suspects: a load sum missing an orientation term, or the `+ u` road-row term in thickness).

- [ ] **Step 3: Commit**

```bash
git add scripts/exp_lane_composition.py
git commit -m "feat(scripts): throwaway CP-SAT lane/stub composition solver (A1 go/no-go)"
```

---

## Task 5: Calibrate, run the gate, record the verdict

**Files:**
- Modify: `tasks/lessons.md`, `tasks/todo.md`

**Interfaces:**
- Consumes: T2 metrics (CLI/city analysis), T3 bounds, T4 report JSONs.
- Produces: the written verdict + gate decision that unblocks (or kills) the Track-A A2/A3 spec.

- [ ] **Step 1: Run the calibration pair**

```bash
mkdir -p output
uv run --with ortools python scripts/exp_lane_composition.py \
    city-user-data.json city-user-data-foe-helper.json \
    --time-limit 300 -o output/comp-user.json
uv run --with ortools python scripts/exp_lane_composition.py darkzig.json \
    --time-limit 300 -o output/comp-darkzig.json
uv run --with ortools python scripts/exp_lane_composition.py darkzig.json \
    --stubs --time-limit 300 -o output/comp-darkzig-stubs.json
```

Expected: three JSON reports with `status` OPTIMAL (or FEASIBLE with a small `gap`). If `gap` straddles a gate threshold, re-run with `--time-limit 900` before calling it inconclusive.

- [ ] **Step 2: Compute the calibrated verdict**

- Calibration factor `f = 142 / model_optimum(user city)`. Sanity check from the spec §3.4: if `f` is outside [0.75, 1.33] the family model itself is wrong — stop, diagnose the model against the T2 sharing metrics of the user's city (its histogram says which sharing levels the model must be able to express), and do not read the darkzig number.
- `C* = f × model_optimum(darkzig, pessimistic trunk)`.
- Apply the gate: `C* >= ~150` → **kill Track A**; `C* <= ~130` → **go** (A2/A3 spec next); between → present both JSONs to the user for the call.
- Also record: `report_bounds(darkzig)["max"]` (band bottom), the optimistic totals, and the stub-scenario delta.

- [ ] **Step 3: Record the verdict**

Append to `tasks/lessons.md` an entry titled `## Road-target calibration + A1 composition verdict (2026-07-XX)` containing: the user-city model optimum + calibration factor, darkzig C* (pessimistic + optimistic + stub scenario), the proven bounds, the target band `[bounds_max, C*]`, and the gate decision with one sentence of reasoning. Fill the `## Review` section of `tasks/todo.md` with the Track-0/A1 outcome and check off the completed track-0/A1 items.

- [ ] **Step 4: Commit**

```bash
git add tasks/lessons.md tasks/todo.md
git commit -m "docs: road-target calibration verdict — A1 gate decision"
```

---

## Self-review notes

- Spec §3.1 (metrics) → T2; §3.2 (bounds) → T3; §3.3 (solver, determinism, feasibility guards, stub caps) → T4; §3.4 (calibration + tiny cross-check) → T4 self-test + T5 Step 2; §5 (gate) → T5; §2 (RL archival decision) → T1. No spec requirement is untasked.
- The bundled-city regression test pins measured values (measure-first step included) rather than trusting remembered numbers.
- `optimal_roads` is imported from `rl.oracle` in tests and the self-test only — it is stdlib, so no torch dependency leaks into the default test run.
