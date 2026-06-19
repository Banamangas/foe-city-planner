# FoE Optimizer — True-Objective Annealing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `anneal()` optimize the real road count (`len(route(candidate))`) instead of the MST proxy, now that `route()` is ~60ms — and delete the obsolete proxy.

**Architecture:** Rewrite `foeopt/anneal.py`'s `anneal()` to Metropolis-accept on `len(route(candidate))` (route per move), routing the input placement once to seed the cost and anchoring the returned best at the input. Remove `mst_cost`/`_mst_length`/`_centroid` and their tests. `random_move`, `OptimizeResult`, and the `improve --anneal` CLI are unchanged.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Reuses `foeopt.router.route`, `foeopt.validate.is_valid`, `foeopt.localsearch` (`random_move` deps, `OptimizeResult`).

## Global Constraints

- Python **3.12**; standard library only; dev dep `pytest`. Test runner: `uv run pytest`.
- **Objective:** the SA cost is `len(route(candidate))`; `route()` is called on every evaluated move (no proxy, no new-low gating).
- **Never worse / never invalid:** `best` is anchored at the input layout and replaced only when a candidate is `is_valid` AND has strictly fewer roads. Worsening moves may be *accepted for exploration* but are never returned unless a better validated layout is found.
- **Deterministic:** all randomness flows through a single `random.Random(seed)`; fixed `seed` + fixed `max_iters` (budget not binding) → identical result.
- Input is never mutated; candidate layouts are produced by the existing `random_move`/local-search transforms.
- **Delete the proxy:** remove `mst_cost`, `_mst_length`, `_centroid` and their tests (no remaining caller; strictly inferior). Keep `random_move`, `OptimizeResult`, `_T_FLOOR`, `_COOLING`.

---

### Task 1: Rewrite `anneal()` to the true objective; remove the MST proxy

**Files:**
- Modify: `foeopt/anneal.py`
- Modify: `tests/test_anneal.py`

**Interfaces:**
- Consumes: `random_move(layout, rng)` (unchanged, same file), `foeopt.router.route`/`RouteError`, `foeopt.validate.is_valid`, `OptimizeResult`.
- Produces: `anneal(layout, *, seed=0, budget_seconds=30.0, max_iters=1_000_000) -> OptimizeResult` — unchanged signature, new internals (true objective). `mst_cost`, `_mst_length`, `_centroid` are **removed**.

- [ ] **Step 1: Update the tests (remove proxy tests, keep behavioral tests)**

In `tests/test_anneal.py`:
1. Change the import on line 4 from
   `from foeopt.anneal import _mst_length, mst_cost, random_move, anneal`
   to:
   ```python
   from foeopt.anneal import random_move, anneal
   ```
2. **Delete** these five now-obsolete tests entirely: `test_mst_length_collinear`, `test_mst_length_unit_square`, `test_mst_length_trivial`, `test_mst_cost_uses_road_needing_and_townhall`, `test_mst_cost_drops_when_buildings_cluster`.
3. **Keep** everything else unchanged: `_rn`, `_region`, the two `test_random_move_*` tests, and the five `test_anneal_*` behavioral tests (`never_worse_and_valid`, `deterministic_for_seed`, `can_beat_inflated_start`, `moves_applied_on_improvement`, `moves_applied_zero_on_tight_layout`). These assert roads/validity/determinism/moves — all preserved by the rewrite.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_anneal.py -q`
Expected: collection error / FAIL — the import of `_mst_length`/`mst_cost` is gone from the test, but `anneal.py` still defines them and the rewrite hasn't happened; specifically the import line change passes, but until Step 3 the behavioral tests still run against the old proxy `anneal` (they should still pass) — the real RED signal is that we have removed the proxy tests and must now rewrite the implementation. To get a clean RED, first do Step 3's test edit by also asserting the new behavior; simplest: proceed to Step 3 and rely on the full-suite run there. (If `pytest` reports an ImportError for `_mst_length` anywhere, that confirms the proxy removal is needed.)

- [ ] **Step 3: Rewrite `foeopt/anneal.py`**

Replace the entire file with:
```python
from __future__ import annotations

import math
import random
import time

from foeopt.model import Building, Layout
from foeopt.localsearch import OptimizeResult, free_cells, move_building, swap_buildings

_T_FLOOR = 1e-9
_COOLING = 0.9995
_WARMUP_SAMPLES = 12


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


def anneal(
    layout: Layout,
    *,
    seed: int = 0,
    budget_seconds: float = 30.0,
    max_iters: int = 1_000_000,
) -> OptimizeResult:
    """Simulated annealing on the true road count (len(route(candidate))).

    Starts from the input layout, routes it once to seed the cost (capturing any
    free roads-only improvement), and accepts worsening moves probabilistically to
    escape the plateau where hill-climbing stops. The returned `best` is anchored
    at the input and only replaced by a valid layout with strictly fewer roads, so
    the result is never worse than the input. Deterministic for a fixed seed.
    """
    from foeopt.router import RouteError, route
    from foeopt.validate import is_valid

    rng = random.Random(seed)

    best = layout
    best_roads = len(layout.roads)

    # Route the input placement to seed the SA's current cost (also captures the
    # roads-only "Phase 1" win when the input network is not minimal).
    try:
        roads0 = route(layout)
        state = Layout(layout.region, layout.buildings, layout.townhall, roads0)
        cur = len(roads0)
        if is_valid(state) and cur < best_roads:
            best, best_roads = state, cur
    except RouteError:
        state, cur = layout, len(layout.roads)

    # Initial temperature: mean of positive |Δroads| over a few sampled routed
    # moves (small integer deltas); fallback 1.0.
    deltas: list[int] = []
    for _ in range(_WARMUP_SAMPLES):
        cand = random_move(state, rng)
        if cand is None:
            continue
        try:
            d = abs(len(route(cand)) - cur)
        except RouteError:
            continue
        if d > 0:
            deltas.append(d)
    temperature = (sum(deltas) / len(deltas)) if deltas else 1.0

    moves_applied = 0
    deadline = time.monotonic() + budget_seconds
    for _ in range(max_iters):
        if time.monotonic() >= deadline:
            break
        cand = random_move(state, rng)
        if cand is None:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        try:
            roads = route(cand)
        except RouteError:
            temperature = max(temperature * _COOLING, _T_FLOOR)
            continue
        delta = len(roads) - cur
        if delta < 0 or rng.random() < math.exp(-delta / max(temperature, _T_FLOOR)):
            state = Layout(cand.region, cand.buildings, cand.townhall, roads)
            cur = len(roads)
            if is_valid(state) and cur < best_roads:
                best, best_roads = state, cur
                moves_applied += 1
        temperature = max(temperature * _COOLING, _T_FLOOR)

    return OptimizeResult(layout=best, moves_applied=moves_applied)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_anneal.py -v`
Expected: PASS — `random_move` tests, the five `test_anneal_*` behavioral tests (never-worse, determinism, inflated-start improvement, moves_applied) all pass against the true-objective implementation; the proxy tests are gone.

Then the full suite: `uv run pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add foeopt/anneal.py tests/test_anneal.py
git commit -m "feat(anneal): optimize true route() count, remove MST proxy"
```

---

### Task 2: Real-city annealing test (`darkzig.json`)

**Files:**
- Modify: `tests/test_anneal_cli.py`

**Interfaces:**
- Consumes: `foeopt.loader.load_layout`, `foeopt.anneal.anneal`, `foeopt.validate.is_valid`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_anneal_cli.py`:
```python
def test_anneal_darkzig_valid_and_not_worse():
    from foeopt.loader import load_layout
    from foeopt.anneal import anneal
    from foeopt.validate import is_valid
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent
    current = load_layout(str(repo / "darkzig.json"))
    res = anneal(current, seed=0, budget_seconds=3.0, max_iters=10_000)
    assert is_valid(res.layout)
    assert len(res.layout.roads) <= len(current.roads)   # never worse than the player's 250
    # buildings conserved, non-overlapping, in-region
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    assert len(res.layout.buildings) == len(current.buildings)
```

- [ ] **Step 2: Run test to verify it passes (small budget)**

Run: `uv run pytest tests/test_anneal_cli.py::test_anneal_darkzig_valid_and_not_worse -v -s`
Expected: PASS — within a 3s budget the input is routed (250 → ~236 baseline) so `roads ≤ 250` holds and the layout is valid. Record the achieved road count in the report. (It should be ≤ 236; the full 600s run reaches ~211, demonstrated outside the suite.)

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_anneal_cli.py
git commit -m "test: real-city true-objective annealing (darkzig, never-worse)"
```

---

### Task 3: README — update the annealing description

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Fix the stale proxy wording**

In `README.md`, the `--anneal` section currently describes "simulated annealing on a fast spanning-tree proxy, confirmed with the real router". Replace that description so it reflects the true objective. Find the line:
```markdown
For a deeper search that can escape the plateau where hill-climbing stalls, add `--anneal`
(simulated annealing on a fast spanning-tree proxy, confirmed with the real router):
```
and replace the parenthetical:
```markdown
For a deeper search that can escape the plateau where hill-climbing stalls, add `--anneal`
(simulated annealing on the real road count — accepts some worse moves to find a better one):
```

- [ ] **Step 2: Verify the full suite is green**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: describe --anneal as true-objective (not proxy)"
```

---

## Self-Review

**Spec coverage:**
- True objective `len(route(candidate))`, route per move (spec §4) → Task 1 `anneal` loop. ✓
- Delete proxy `mst_cost`/`_mst_length`/`_centroid` + tests (spec §3) → Task 1 (file rewrite omits them; tests removed). ✓
- Initial routing seeds cost + captures Phase-1 win; best anchored at input (spec §4/§5) → Task 1 (route(layout) block). ✓
- Metropolis acceptance, geometric cooling, sampled T0 (spec §4) → Task 1. ✓
- Never-worse / never-invalid (spec §5) → Task 1 best-update gate; tests `never_worse_and_valid`, darkzig test (Task 2). ✓
- Deterministic (spec §5) → single seeded RNG; `deterministic_for_seed` test retained. ✓
- CLI/`random_move`/`OptimizeResult` unchanged (spec §3) → not modified. ✓
- Testing: drop proxy tests; never-worse, determinism, improvement, real-city (spec §6) → Tasks 1–2. ✓
- README stale wording (proxy → true objective) → Task 3. ✓

**Placeholder scan:** No placeholders; Task 1 Step 3 gives the complete file. Note: Task 1 Step 2's RED is soft (the behavioral tests pass against both old and new code since they're behavior-level); the genuine gate is the proxy-test removal + import change forcing the rewrite, and the full-suite green in Step 4. This is called out explicitly rather than faked.

**Type consistency:** `anneal(layout, *, seed, budget_seconds, max_iters) -> OptimizeResult` and `random_move(layout, rng) -> Layout | None` unchanged across the file; `OptimizeResult(layout, moves_applied)` imported from `localsearch`; `route(layout) -> dict[(x,y)->level]` and `is_valid(layout) -> bool` consumed as elsewhere. No references to the removed `mst_cost`/`_mst_length`/`_centroid` remain (Task 1 removes the only callers — the old `anneal`/`_initial_temperature` — and the import line in the test).
