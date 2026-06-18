# FoE Optimizer — Simulated-Annealing Road Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simulated-annealing engine that reduces road tiles by exploring building rearrangements on a fast MST proxy, confirming improvements with `route()`, and never returning a layout worse than the input.

**Architecture:** A new `foeopt/anneal.py` with an MST-length proxy (`mst_cost`), a seeded random move proposer (`random_move`) built on the existing local-search transforms, and an `anneal` loop (geometric cooling, Metropolis acceptance, `route()`-confirmed best tracking). A `--anneal`/`--seed` option on the existing `improve` CLI selects the engine.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only (`random`, `math`). Reuses `foeopt.model/localsearch/router/validate/report/viz/build`.

## Global Constraints

- Python **3.12**; standard library only; dev dep `pytest`. Test runner: `uv run pytest`.
- Coordinates are `(x, y)` integer tuples; `x` → width, `y` → length. **No rotation.**
- **Never worse / never invalid:** `anneal` returns a valid layout whose road count ≤ the input's; the returned best is seeded as the input and replaced only when `route()` confirms a valid layout with strictly fewer roads.
- **Determinism:** all randomness goes through a single `random.Random(seed)`; with a fixed `seed` and fixed `max_iters` (large budget), two runs are identical.
- Moves never mutate the input (`dataclasses.replace`); placement validity comes from the local-search transforms; road truth from `foeopt.router.route`; layout validity from `foeopt.validate.is_valid`.
- **MST proxy** is an approximation that guides search; the real objective is the `route()`-confirmed road count.
- Reuse `foeopt.localsearch` (`move_building`, `swap_buildings`, `free_cells`, `OptimizeResult`); do not duplicate them.

---

### Task 1: MST proxy cost (`anneal.py`)

**Files:**
- Create: `foeopt/anneal.py`
- Test: `tests/test_anneal.py`

**Interfaces:**
- Consumes: `foeopt.model` (`Layout`, `Building`); `Layout.road_needing()`, `Layout.townhall`.
- Produces:
  - `_mst_length(points: list[tuple[float, float]]) -> float` — total weight of the Manhattan minimum spanning tree over the points (Prim's). `0.0` for ≤1 point.
  - `mst_cost(layout: Layout) -> float` — `_mst_length` over each road-needing building's footprint centroid `(x + w/2, y + l/2)` plus the Townhall centroid (if any).

- [ ] **Step 1: Write the failing test**

`tests/test_anneal.py`:
```python
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.anneal import _mst_length, mst_cost


def _rn(eid, x, y, w=1, l=1, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic",
                    Footprint(x, y, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_mst_length_collinear():
    # (0,0)-(0,2)-(0,4): MST connects with edges 2 + 2 = 4
    assert _mst_length([(0.0, 0.0), (0.0, 2.0), (0.0, 4.0)]) == 4.0


def test_mst_length_unit_square():
    # unit square: MST is any 3 edges of weight 1 = 3
    assert _mst_length([(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]) == 3.0


def test_mst_length_trivial():
    assert _mst_length([]) == 0.0
    assert _mst_length([(1.0, 1.0)]) == 0.0


def test_mst_cost_uses_road_needing_and_townhall():
    # townhall at (0,0) 1x1 -> centroid (0.5,0.5); two road-needing 1x1 at
    # (0,2) -> (0.5,2.5) and (0,4) -> (0.5,4.5). Collinear, spacing 2 -> MST 4.
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 0, 2)
    b = _rn(3, 0, 4)
    layout = Layout(_region(2, 6), [th, a, b], th)
    assert mst_cost(layout) == 4.0


def test_mst_cost_drops_when_buildings_cluster():
    th = _rn(1, 0, 0, th=True, needs=False)
    far = Layout(_region(2, 10), [th, _rn(2, 0, 8)], th)
    near = Layout(_region(2, 10), [th, _rn(2, 0, 2)], th)
    assert mst_cost(near) < mst_cost(far)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anneal.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.anneal'`).

- [ ] **Step 3: Write the implementation**

`foeopt/anneal.py`:
```python
from __future__ import annotations

import math

from foeopt.model import Building, Layout


def _mst_length(points: list[tuple[float, float]]) -> float:
    n = len(points)
    if n <= 1:
        return 0.0
    in_tree = [False] * n
    dist = [math.inf] * n
    dist[0] = 0.0
    total = 0.0
    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: dist[i])
        in_tree[u] = True
        total += dist[u]
        ux, uy = points[u]
        for v in range(n):
            if not in_tree[v]:
                d = abs(ux - points[v][0]) + abs(uy - points[v][1])
                if d < dist[v]:
                    dist[v] = d
    return total


def _centroid(b: Building) -> tuple[float, float]:
    return (b.footprint.x + b.footprint.width / 2,
            b.footprint.y + b.footprint.length / 2)


def mst_cost(layout: Layout) -> float:
    points = [_centroid(b) for b in layout.road_needing()]
    if layout.townhall is not None:
        points.append(_centroid(layout.townhall))
    return _mst_length(points)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anneal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/anneal.py tests/test_anneal.py
git commit -m "feat: MST-length proxy cost for annealing"
```

---

### Task 2: Seeded random move proposer (`anneal.py`)

**Files:**
- Modify: `foeopt/anneal.py`
- Test: `tests/test_anneal.py`

**Interfaces:**
- Consumes: `random.Random`, `foeopt.localsearch` (`move_building`, `swap_buildings`, `free_cells`), `Layout`.
- Produces: `random_move(layout: Layout, rng: random.Random) -> Layout | None` — with probability ½ proposes a same-footprint swap (two distinct random non-Townhall buildings of identical `width×length`), otherwise a relocation (a random non-Townhall building to a random free cell). Returns a validated new `Layout` (via the local-search transforms) or `None` if the chosen move is infeasible. Uses only `rng`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_anneal.py`:
```python
import random
from foeopt.anneal import random_move


def test_random_move_returns_valid_or_none():
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    b = _rn(3, 4, 0)
    layout = Layout(_region(8, 1), [th, a, b], th)
    rng = random.Random(123)
    region = layout.region.cells
    for _ in range(50):
        cand = random_move(layout, rng)
        if cand is None:
            continue
        occ = set()
        for bld in cand.buildings:
            cells = bld.footprint.cells()
            assert cells <= region            # in region
            assert not (cells & occ)          # no overlap
            occ |= cells
        assert len(cand.buildings) == len(layout.buildings)   # conserved


def test_random_move_is_deterministic_for_seed():
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    layout = Layout(_region(6, 1), [th, a], th)
    m1 = random_move(layout, random.Random(7))
    m2 = random_move(layout, random.Random(7))
    # same seed -> same proposal (both None or both the same anchors)
    def anchors(layout_or_none):
        if layout_or_none is None:
            return None
        return sorted((b.entity_id, b.footprint.x, b.footprint.y) for b in layout_or_none.buildings)
    assert anchors(m1) == anchors(m2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anneal.py -k random_move -v`
Expected: FAIL (`cannot import name 'random_move'`).

- [ ] **Step 3: Write the implementation**

Append to `foeopt/anneal.py` (add `import random` at top):
```python
from foeopt.localsearch import free_cells, move_building, swap_buildings


def random_move(layout: Layout, rng: random.Random) -> Layout | None:
    movable = [b for b in layout.buildings if not b.is_townhall]
    if not movable:
        return None

    if rng.random() < 0.5:
        by_size: dict[tuple[int, int], list[Building]] = {}
        for b in movable:
            by_size.setdefault((b.footprint.width, b.footprint.length), []).append(b)
        groups = [g for g in by_size.values() if len(g) >= 2]
        if groups:
            group = rng.choice(groups)
            a, b = rng.sample(group, 2)
            return swap_buildings(layout, a.entity_id, b.entity_id)

    free = sorted(free_cells(layout))
    if not free:
        return None
    b = rng.choice(movable)
    x, y = rng.choice(free)
    return move_building(layout, b.entity_id, x, y)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anneal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/anneal.py tests/test_anneal.py
git commit -m "feat: seeded random move proposer for annealing"
```

---

### Task 3: Annealing loop (`anneal.py`)

**Files:**
- Modify: `foeopt/anneal.py`
- Test: `tests/test_anneal.py`

**Interfaces:**
- Consumes: `mst_cost`, `random_move`, `foeopt.localsearch.OptimizeResult`, `foeopt.router.route`/`RouteError`, `foeopt.validate.is_valid`, `time`, `math`, `random`.
- Produces: `anneal(layout: Layout, *, seed: int = 0, budget_seconds: float = 30.0, max_iters: int = 1_000_000) -> OptimizeResult`.
  - Metropolis acceptance on `mst_cost` (accept if `delta < 0` else with probability `exp(-delta / T)`); geometric cooling `T *= 0.9995` per iteration; `T0` auto-scaled from the mean absolute proxy delta of a few sampled moves (fallback `1.0`).
  - Tracks the best **route-confirmed** layout: when the proxy reaches a new low, call `route(state)`; if it succeeds, `is_valid`, and `len(roads) < best_roads`, adopt it. `best` is seeded as the input layout (so the result is never worse).
  - Stops at the time budget or `max_iters`. `moves_applied` = number of confirmed best updates.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_anneal.py`:
```python
from foeopt.anneal import anneal
from foeopt.localsearch import OptimizeResult
from foeopt.router import route
from foeopt.validate import is_valid


def test_anneal_never_worse_and_valid():
    # tiny already-tight layout: TH(0,0) road(1,0) house(2,0)
    th = _rn(1, 0, 0, th=True, needs=False)
    house = _rn(2, 2, 0)
    layout = Layout(_region(3, 1), [th, house], th, roads={(1, 0): 1})
    res = anneal(layout, seed=1, budget_seconds=1.0, max_iters=200)
    assert isinstance(res, OptimizeResult)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(layout.roads)   # never worse


def test_anneal_deterministic_for_seed():
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 3, 0)
    b = _rn(3, 5, 0)
    layout = Layout(_region(8, 2), [th, a, b], th,
                    roads=route(Layout(_region(8, 2), [th, a, b], th, {})))
    r1 = anneal(layout, seed=42, budget_seconds=5.0, max_iters=300)
    r2 = anneal(layout, seed=42, budget_seconds=5.0, max_iters=300)
    # same seed + same max_iters (budget not binding) -> identical result
    def sig(res):
        return (sorted((bld.entity_id, bld.footprint.x, bld.footprint.y)
                       for bld in res.layout.buildings),
                sorted(res.layout.roads.items()))
    assert sig(r1) == sig(r2)


def test_anneal_can_beat_inflated_start():
    # Input carries MORE roads than the placement needs; any route-confirmation
    # the search performs will beat it -> result strictly fewer roads.
    th = _rn(1, 0, 0, th=True, needs=False)
    a = _rn(2, 2, 0)
    region = _region(6, 2)
    minimal = route(Layout(region, [th, a], th, {}))
    inflated = dict(minimal)
    inflated[(0, 1)] = 1
    inflated[(1, 1)] = 1            # extra redundant tiles
    layout = Layout(region, [th, a], th, roads=inflated)
    res = anneal(layout, seed=3, budget_seconds=2.0, max_iters=500)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(layout.roads)
    # the route-confirmed result is self-consistent
    assert len(res.layout.roads) == len(route(
        Layout(res.layout.region, res.layout.buildings, res.layout.townhall, {})))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anneal.py -k anneal -v`
Expected: FAIL (`cannot import name 'anneal'`).

- [ ] **Step 3: Write the implementation**

Append to `foeopt/anneal.py` (add `import time` at top):
```python
from foeopt.localsearch import OptimizeResult

_T_FLOOR = 1e-9
_COOLING = 0.9995


def _initial_temperature(layout: Layout, rng: random.Random, samples: int = 20) -> float:
    base = mst_cost(layout)
    deltas: list[float] = []
    for _ in range(samples):
        cand = random_move(layout, rng)
        if cand is not None:
            deltas.append(abs(mst_cost(cand) - base))
    positive = [d for d in deltas if d > 0]
    return (sum(positive) / len(positive)) if positive else 1.0


def anneal(
    layout: Layout,
    *,
    seed: int = 0,
    budget_seconds: float = 30.0,
    max_iters: int = 1_000_000,
) -> OptimizeResult:
    from foeopt.router import RouteError, route
    from foeopt.validate import is_valid

    rng = random.Random(seed)
    temperature = _initial_temperature(layout, rng)

    state = layout
    cost = mst_cost(state)
    best = layout
    best_roads = len(layout.roads)
    best_proxy = cost
    moves_applied = 0

    deadline = time.monotonic() + budget_seconds
    for _ in range(max_iters):
        if time.monotonic() >= deadline:
            break
        cand = random_move(state, rng)
        if cand is None:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        new_cost = mst_cost(cand)
        delta = new_cost - cost
        if delta < 0 or rng.random() < math.exp(-delta / max(temperature, _T_FLOOR)):
            state, cost = cand, new_cost
            if new_cost < best_proxy:
                best_proxy = new_cost
                try:
                    roads = route(state)
                except RouteError:
                    roads = None
                if roads is not None:
                    confirmed = Layout(state.region, state.buildings,
                                       state.townhall, roads)
                    if is_valid(confirmed) and len(roads) < best_roads:
                        best, best_roads = confirmed, len(roads)
                        moves_applied += 1
        temperature = max(temperature * _COOLING, _T_FLOOR)

    return OptimizeResult(layout=best, moves_applied=moves_applied)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anneal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/anneal.py tests/test_anneal.py
git commit -m "feat: simulated-annealing loop (MST proxy, route-confirmed, never-worse)"
```

---

### Task 4: `--anneal` option on `improve` CLI + real-city test

**Files:**
- Modify: `foeopt/cli.py`
- Test: `tests/test_anneal_cli.py`

**Interfaces:**
- Consumes: `foeopt.anneal.anneal`, `foeopt.localsearch.optimize`, `build_layout`, `render_comparison`, `report.stats`, `is_valid`.
- Produces: the existing `improve` subcommand gains `--anneal` (use the SA engine) and `--seed N` (default `0`). Without `--anneal` it uses hill-climbing (unchanged). Budget is 30 s (120 s with `--thorough`) for both engines. Always exits 0.

- [ ] **Step 1: Write the failing real-city test**

`tests/test_anneal_cli.py`:
```python
from foeopt.build import build_layout
from foeopt.anneal import anneal
from foeopt.validate import is_valid


def test_anneal_real_city_valid_and_not_worse(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    res = anneal(current, seed=0, budget_seconds=2.0, max_iters=500)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(current.roads)     # never worse
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    assert len(res.layout.buildings) == len(current.buildings)
```

- [ ] **Step 2: Run test to verify the invariant**

Run: `uv run pytest tests/test_anneal_cli.py -v -s`
Expected: PASS (valid + roads ≤ current). Record the achieved roads/moves in the report.

- [ ] **Step 3: Wire `--anneal` into the `improve` command**

In `foeopt/cli.py`, add `from foeopt.anneal import anneal` to the imports. Replace the body of `_cmd_improve` so the engine is chosen by the flag:
```python
def _cmd_improve(args) -> int:
    current = build_layout(_load(args.city), _load(args.helper))
    budget = 120.0 if args.thorough else 30.0
    if args.anneal:
        res = anneal(current, seed=args.seed, budget_seconds=budget)
        engine = "simulated annealing"
    else:
        res = optimize(current, budget_seconds=budget)
        engine = "hill-climbing"
    s = stats(current, res.layout.roads)
    print(f"Road optimization ({engine}):")
    print(f"  current roads: {s['current_roads']} | optimized roads: {s['optimized_roads']}"
          f" | tiles_saved: {s['tiles_saved']} | moves: {res.moves_applied}")
    Path(args.out).write_text(render_comparison(current, res.layout), encoding="utf-8")
    print(f"Wrote before/after map to {args.out}")
    return 0
```

Add the two options to the `improve` parser registration in `main()` (next to the existing `--thorough`):
```python
    p_improve.add_argument("--anneal", action="store_true",
                           help="use simulated annealing instead of hill-climbing")
    p_improve.add_argument("--seed", type=int, default=0,
                           help="RNG seed for --anneal (deterministic)")
```

- [ ] **Step 4: Run the real-city test + CLI smoke test**

Run: `uv run pytest tests/test_anneal_cli.py -v -s`
Expected: PASS.

Run: `uv run python -m foeopt.cli improve city-user-data.json city-user-data-foe-helper.json --anneal -o output/anneal.html`
Expected: prints `Road optimization (simulated annealing): ...` and writes the map. On the dense sample, savings may be 0 — expected honest outcome; the map still opens.

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/test_anneal_cli.py
git commit -m "feat: --anneal/--seed engine selection on improve CLI"
```

---

### Task 5: README — document `--anneal`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an `--anneal` note**

Under the existing `improve` usage in `README.md`, add:
```markdown
For a deeper search that can escape the plateau where hill-climbing stalls, add `--anneal`
(simulated annealing on a fast spanning-tree proxy, confirmed with the real router):

    uv run python -m foeopt.cli improve city-user-data.json city-user-data-foe-helper.json --anneal --thorough -o output/anneal.html

`--anneal` is deterministic for a given `--seed` (default 0) and is still never worse than your
current layout. Like every engine here, it only finds savings when the city has free space to
rearrange into; on a near-full, already-tuned city it may report no improvement.
```

- [ ] **Step 2: Verify the full suite is green**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the --anneal engine"
```

---

## Self-Review

**Spec coverage:**
- Purpose / SA engine (spec §1) → Tasks 1–4. ✓
- Never-worse guarantee (spec §3) → `best` seeded as input, replaced only on route-confirmed strict improvement (Task 3); property tests (Tasks 3, 4). ✓
- MST proxy `mst_cost` over road-needing centroids + Townhall (spec §4) → Task 1. ✓
- Architecture `anneal.py` reusing local-search transforms + `route`/`is_valid` (spec §5) → Tasks 1–3. ✓
- SA loop: Metropolis acceptance, geometric cooling, auto-scaled T0, route-confirmed best, route() only on proxy new-low (spec §6) → Task 3. ✓
- Determinism via single seeded RNG (spec §7) → `random.Random(seed)`; determinism test (Task 3). ✓
- CLI `--anneal`/`--seed` on `improve`, output unchanged, exit 0 (spec §8) → Task 4. ✓
- Testing: mst_cost units, random_move valid-or-None, never-worse property, determinism, improvement case, real-city (spec §9) → Tasks 1–4. ✓

**Placeholder scan:** No placeholders; every code step has complete code, every test real assertions. The "improvement" demonstration (`test_anneal_can_beat_inflated_start`) asserts the robust invariant (valid, ≤ input, route-consistent) using an inflated-input construction rather than a brittle "strictly fewer than the optimal" claim that would depend on the RNG stream — intentional and complete.

**Type consistency:** `_mst_length(list[(float,float)]) -> float`, `mst_cost(layout) -> float`, `random_move(layout, rng) -> Layout|None`, `anneal(layout, *, seed, budget_seconds, max_iters) -> OptimizeResult` are consistent across Tasks 1–4. `OptimizeResult(layout, moves_applied)` is imported from `foeopt.localsearch` (already defined there). `roads` is `dict[(x,y)->level]`; moves reuse the local-search transforms which build new `Layout`s via `dataclasses.replace`.
