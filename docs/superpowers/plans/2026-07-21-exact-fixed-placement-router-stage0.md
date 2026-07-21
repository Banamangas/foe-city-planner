# Exact fixed-placement router — Stage 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an exact minimum-roads router for a fixed placement and measure `route()`'s slack on the existing best-k layouts (especially the 102-road one) — the go/kill evidence for the lever.

**Architecture:** `foeopt/exact_router.py` solves min connected road-cover via CP-SAT + single-commodity flow (the tractable slice of `minroads` — placement fixed, no rectangle vars). A spike script reconstructs the fixed placement from a `best-k*.json` layout and compares the exact optimum to `route()` on the same placement. Ends in a `lessons.md` verdict.

**Tech Stack:** Python ≥3.12, OR-Tools CP-SAT (lazy import), pytest. Spec: `docs/superpowers/specs/2026-07-21-exact-fixed-placement-router-design.md`.

## Global Constraints

- Python `>=3.12`.
- `ortools` is imported **lazily inside** `exact_route` (same pattern as `foeopt/roads_first.py:probe`) — not at module top. `exact_router.py` is a solver module; `ortools` is already a core dependency.
- Determinism: `num_search_workers = 1`, `random_seed = seed` (default 0). The optimal road *count* is then reproducible.
- `exact_route` returns an `ExactResult(status, count, roads, wall_s, optimal)`. `roads` is a `dict[(x,y), level]` with levels **post-assigned** (any road cell can be any level; level never affects the cell-count objective). Treat `roads` as the proven minimum **only** when `status == "OPTIMAL"`.
- Validity is cover + connect only (`foeopt/validate.py`): every consumer needs one orthogonally-adjacent, TH-connected road cell of level ≥ its `road_level`. No anti-filler-adjacency constraint.
- **Pre-committed Stage-0 gate (spec §5):** exact proven-OPTIMAL `< route()` on ≥1 layout within budget → **advance** (and a sub-102 result on the 102 layout is a re-verified new best). Exact proven-OPTIMAL `== route()` everywhere → **null, documented** (route() is optimal for fixed placement). Timeout (no proven optimum) → the CP-SAT+flow **encoding** is the blocker; record sizes/times, do **not** call it a null.
- **Scope:** this plan is Stage 0 only. Stage 1 (opt-in wiring of `exact_route` into the CLI/webapp/`validate` path + the production A/B) is a separate plan gated on the Stage-0 verdict.

---

## File Structure

- `foeopt/exact_router.py` — **new.** `ExactResult` dataclass + `exact_route(layout, *, time_limit, seed)`. One responsibility: given a fixed layout, return the minimum connected road network.
- `tests/test_exact_router.py` — **new.** Hand-computed toy optima + validity + the `≤ route()` invariant.
- `scripts/exp_exact_router.py` — **new.** Reconstruct a fixed placement from a `best-k*.json` and compare exact vs `route()`; `--selftest`.
- `tests/test_exp_exact_router.py` — **new.** Unit test for `reconstruct_fixed`.
- `tasks/lessons.md` — **modify (append).** The Stage-0 verdict (Task 3).

Cell = `tuple[int, int]`. `best-k*.json` schema: `{"k": int, "achieved": int, "roads": [[x,y],...], "buildings": {"<entity_id>": [x,y,w,l], ...}}` (all 224 buildings).

---

### Task 1: `foeopt/exact_router.py` — the exact model

**Files:**
- Create: `foeopt/exact_router.py`
- Test: `tests/test_exact_router.py`

**Interfaces:**
- Consumes: `foeopt.model.{Layout,Footprint,Building,Region}`, `foeopt.router.route`, `foeopt.validate.is_valid` (tests only).
- Produces: `ExactResult(status: str, count: int|None, roads: dict[Cell,int]|None, wall_s: float, optimal: bool)`; `exact_route(layout, *, time_limit: float = 300.0, seed: int = 0) -> ExactResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_exact_router.py
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.exact_router import exact_route


def _b(eid, x, y, w, l, *, road=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), road, 1, th, None, None, f"b{eid}")


def _layout_single():
    # 1x3 strip: TH at (0,0), one consumer at (0,2); only free cell (0,1)
    # is both the Townhall root AND the consumer's only cover -> exact min = 1.
    region = Region(frozenset({(0, 0), (0, 1), (0, 2)}))
    th = _b(1, 0, 0, 1, 1, th=True)
    c = _b(2, 0, 2, 1, 1, road=True)
    return Layout(region, [th, c], th, {})


def _layout_shared_cover():
    # 3x3: TH at (1,0); consumers at (0,2) and (2,2). Cell (1,2) borders BOTH
    # consumers; it reaches the TH via (1,1). Exact min = 2 ({(1,1),(1,2)}).
    region = Region(frozenset((x, y) for x in range(3) for y in range(3)))
    th = _b(1, 1, 0, 1, 1, th=True)
    c1 = _b(2, 0, 2, 1, 1, road=True)
    c2 = _b(3, 2, 2, 1, 1, road=True)
    return Layout(region, [th, c1, c2], th, {})


def test_exact_single_cover_root_cell():
    res = exact_route(_layout_single(), time_limit=10)
    assert res.status == "OPTIMAL"
    assert res.count == 1
    assert res.roads == {(0, 1): 1}


def test_exact_finds_shared_cover_optimum():
    res = exact_route(_layout_shared_cover(), time_limit=10)
    assert res.status == "OPTIMAL"
    assert res.count == 2                      # the shared-cover optimum, not 4


def test_exact_result_is_valid_and_not_worse_than_route():
    lay = _layout_shared_cover()
    res = exact_route(lay, time_limit=10)
    chk = Layout(lay.region, lay.buildings, lay.townhall, res.roads)
    assert is_valid(chk)                       # covers + connects every consumer
    assert res.count <= len(route(lay))        # exact is never worse than greedy


def test_exact_uncoverable_consumer():
    # consumer at (1,0) has no free border cell (TH occupies (0,0), rest off-grid),
    # but the TH still has a free root (0,1) -> status UNCOVERABLE, not NO_ROOT.
    region = Region(frozenset({(0, 0), (1, 0), (0, 1)}))
    th = _b(1, 0, 0, 1, 1, th=True)
    c = _b(2, 1, 0, 1, 1, road=True)
    res = exact_route(Layout(region, [th, c], th, {}), time_limit=10)
    assert res.status == "UNCOVERABLE"
    assert res.roads is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_exact_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foeopt.exact_router'`

- [ ] **Step 3: Write the implementation**

```python
# foeopt/exact_router.py
"""Exact minimum-roads router for a FIXED placement.

route() (foeopt/router.py) is a greedy SPH-Steiner heuristic with no optimality
guarantee. For a fixed placement the minimum connected set of road cells that
covers every consumer and reaches the Townhall is an exact optimization: pick road
cells from the free set, cover each consumer, keep the picked cells connected to the
TH via single-commodity flow, minimize the count. This is the tractable slice of
foeopt/minroads.py (placement fixed -> no rectangle-placement variables). ortools is
imported lazily, as in roads_first.probe.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from foeopt.model import Layout

Cell = tuple[int, int]
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class ExactResult:
    status: str                    # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN | NO_ROOT | UNCOVERABLE
    count: int | None              # road cells in the best solution found
    roads: dict[Cell, int] | None  # best network found, levels post-assigned
    wall_s: float
    optimal: bool                  # status == OPTIMAL (roads is the proven minimum)


def exact_route(layout: Layout, *, time_limit: float = 300.0, seed: int = 0) -> ExactResult:
    from ortools.sat.python import cp_model

    t0 = time.monotonic()
    region = set(layout.region.cells)
    th = layout.townhall
    if th is None:
        return ExactResult("NO_ROOT", None, None, 0.0, False)

    occupied: set[Cell] = set()
    for b in layout.buildings:
        occupied |= b.footprint.cells()
    free = region - occupied

    th_roots = set(th.footprint.border_cells()) & free
    if not th_roots:
        return ExactResult("NO_ROOT", None, None, round(time.monotonic() - t0, 2), False)

    consumers = layout.road_needing()
    cover: list[list[Cell]] = []
    for b in consumers:
        opts = [c for c in b.footprint.border_cells() if c in free]
        if not opts:
            return ExactResult("UNCOVERABLE", None, None, round(time.monotonic() - t0, 2), False)
        cover.append(opts)

    free_list = sorted(free)
    n = len(free_list)
    m = cp_model.CpModel()
    r = {c: m.NewBoolVar(f"r_{c[0]}_{c[1]}") for c in free_list}

    for opts in cover:
        m.AddBoolOr([r[c] for c in opts])          # each consumer covered by >=1 road

    # single-commodity flow: every selected cell must receive 1 unit routed from a
    # selected Townhall-root through selected cells -> one component reaching the TH.
    in_edges: dict[Cell, list] = {c: [] for c in free_list}
    out_edges: dict[Cell, list] = {c: [] for c in free_list}
    for c in free_list:
        for dx, dy in _ORTHO:
            nb = (c[0] + dx, c[1] + dy)
            if nb in free:
                fv = m.NewIntVar(0, n, f"f_{c[0]}_{c[1]}__{nb[0]}_{nb[1]}")
                out_edges[c].append(fv)
                in_edges[nb].append(fv)
                m.Add(fv <= n * r[c])
                m.Add(fv <= n * r[nb])
    for c in th_roots:
        sv = m.NewIntVar(0, n, f"s_{c[0]}_{c[1]}")
        in_edges[c].append(sv)
        m.Add(sv <= n * r[c])
    for c in free_list:
        m.Add(sum(in_edges[c]) - sum(out_edges[c]) == r[c])

    m.Minimize(sum(r.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = time_limit
    st = solver.Solve(m)
    wall = round(time.monotonic() - t0, 2)

    name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE"}.get(st, "UNKNOWN")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ExactResult(name, None, None, wall, False)

    roads: dict[Cell, int] = {c: 1 for c in free_list if solver.Value(r[c]) == 1}
    for b, opts in zip(consumers, cover):        # post-assign levels for validity
        for c in opts:
            if c in roads:
                roads[c] = max(roads[c], b.road_level)
    return ExactResult(name, len(roads), roads, wall, st == cp_model.OPTIMAL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_exact_router.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/exact_router.py tests/test_exact_router.py
git commit -m "feat: exact fixed-placement router (min connected road-cover, CP-SAT+flow)"
```

---

### Task 2: `scripts/exp_exact_router.py` — the gate spike

**Files:**
- Create: `scripts/exp_exact_router.py`
- Test: `tests/test_exp_exact_router.py`

**Interfaces:**
- Consumes: `foeopt.loader.load_layout`, `foeopt.model.{Layout,Footprint}`, `foeopt.router.route`, `foeopt.validate.is_valid`, `foeopt.exact_router.exact_route`.
- Produces: `reconstruct_fixed(layout, best) -> Layout`; `run_layout(layout, best, time_limit) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exp_exact_router.py
import importlib.util, pathlib
from foeopt.model import Building, Footprint, Layout, Region

_spec = importlib.util.spec_from_file_location(
    "exp_exact_router",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_exact_router.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _b(eid, x, y, w, l, *, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), False, 1, th, None, None, f"b{eid}")


def test_reconstruct_fixed_overrides_footprints_from_best():
    # loaded layout has canonical positions; `best` moves them.
    region = Region(frozenset((x, y) for x in range(5) for y in range(5)))
    loaded = Layout(region, [_b(1, 0, 0, 2, 2, th=True), _b(2, 0, 0, 1, 1)], None, {})
    best = {"buildings": {"1": [0, 0, 2, 2], "2": [3, 4, 1, 1]}}
    fixed = mod.reconstruct_fixed(loaded, best)
    by_id = {b.entity_id: b for b in fixed.buildings}
    assert (by_id[2].footprint.x, by_id[2].footprint.y) == (3, 4)   # moved
    assert fixed.townhall is not None and fixed.townhall.entity_id == 1  # TH re-found
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_exp_exact_router.py -v`
Expected: FAIL — module file does not exist yet

- [ ] **Step 3: Write the implementation**

```python
# scripts/exp_exact_router.py
"""Stage-0 spike: does an exact router beat greedy route() on a fixed placement?

Reconstructs the fixed placement from a roads-first best-k*.json layout, runs the
exact router, and compares its optimum to route() on the same placement.

  uv run python scripts/exp_exact_router.py --selftest
  uv run python scripts/exp_exact_router.py darkzig.json \
      output/roads-first/best-k110-a102.json --time-limit 300
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dataclasses import replace

from foeopt.loader import load_layout
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.exact_router import exact_route


def reconstruct_fixed(layout: Layout, best: dict) -> Layout:
    """Fixed placement = loaded building metadata with footprints overridden by `best`."""
    by_id = {b.entity_id: b for b in layout.buildings}
    placed, th = [], None
    for eid_str, (x, y, w, l) in best["buildings"].items():
        b = by_id[int(eid_str)]
        nb = replace(b, footprint=Footprint(x, y, w, l))
        placed.append(nb)
        if nb.is_townhall:
            th = nb
    return Layout(layout.region, placed, th, {})


def run_layout(layout: Layout, best: dict, time_limit: float) -> dict:
    fixed = reconstruct_fixed(layout, best)
    route_roads = len(route(fixed))
    res = exact_route(fixed, time_limit=time_limit)
    valid = None
    if res.roads is not None:
        chk = Layout(fixed.region, fixed.buildings, fixed.townhall, res.roads)
        valid = is_valid(chk) and len(res.roads) == res.count
    return {"achieved_json": best.get("achieved"), "route_roads": route_roads,
            "exact_status": res.status, "exact_count": res.count,
            "optimal": res.optimal, "wall_s": res.wall_s, "exact_valid": valid,
            "slack": (route_roads - res.count) if res.count is not None else None}


def _selftest() -> int:
    region = Region(frozenset((x, y) for x in range(3) for y in range(3)))
    th = Building(1, "c1", "main_building", Footprint(1, 0, 1, 1), False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 2, 1, 1), True, 1, False, None, None, "a")
    c2 = Building(3, "c3", "g", Footprint(2, 2, 1, 1), True, 1, False, None, None, "b")
    layout = Layout(region, [th, c1, c2], th, {})
    best = {"achieved": len(route(layout)),
            "buildings": {"1": [1, 0, 1, 1], "2": [0, 2, 1, 1], "3": [2, 2, 1, 1]}}
    row = run_layout(layout, best, time_limit=10)
    assert row["exact_status"] == "OPTIMAL" and row["exact_valid"] is True
    assert row["exact_count"] == 2 and row["slack"] == row["route_roads"] - 2
    print("SELFTEST OK:", json.dumps(row))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("best", nargs="*", help="best-k*.json layout file(s)")
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city or not args.best:
        ap.error("city file and at least one best-k*.json required (or --selftest)")
    layout = load_layout(args.city)
    rows = []
    for p in args.best:
        best = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        row = run_layout(layout, best, args.time_limit)
        row["file"] = pathlib.Path(p).name
        rows.append(row)
        print(json.dumps(row))
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test and the selftest**

Run: `uv run pytest tests/test_exp_exact_router.py -v`
Expected: PASS (1 test)

Run: `uv run python scripts/exp_exact_router.py --selftest`
Expected: prints `SELFTEST OK: {...}` with `"exact_count": 2`, exits 0

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_exact_router.py tests/test_exp_exact_router.py
git commit -m "feat: Stage-0 spike comparing exact router vs route() on best-k layouts"
```

---

### Task 3: Run the gate on the best-k layouts and record the verdict

**Files:**
- Modify: `tasks/lessons.md` (append a dated entry)

No unit test — runs the spike and applies the pre-committed gate. Requires the gitignored `darkzig.json` and the `output/roads-first/best-k*.json` layouts (present locally). If absent, stop and tell the user.

- [ ] **Step 1: Cheapest, highest-value probe first — the 102 layout**

Run: `uv run python scripts/exp_exact_router.py darkzig.json output/roads-first/best-k110-a102.json --time-limit 300`
Expected: one JSON row. Read `exact_status`, `exact_count` vs `route_roads` (should be 102), `slack`, `wall_s`, `exact_valid` (must be `true`). A sub-102 `OPTIMAL` here is a new all-time best.

- [ ] **Step 2: A few more low-achieved layouts**

Run: `uv run python scripts/exp_exact_router.py darkzig.json output/roads-first/best-k112-a105.json output/roads-first/best-k119-a108.json --time-limit 300 --out output/stage0-exact.json`
Expected: rows for each; note statuses, slack, and wall times (tractability).

- [ ] **Step 3: Apply the pre-committed gate and write the lessons entry**

- Any `OPTIMAL` with `slack >= 1` (and `exact_valid == true`) → **advance to Stage 1** (wiring). If the 102 layout produced `exact_count < 102`, independently re-verify and record it as a new best.
- All probed layouts `OPTIMAL` with `slack == 0` → **null:** `route()` is optimal for fixed placement — do not productionize; document the assumption as now-measured.
- Any `UNKNOWN`/`FEASIBLE` (timeout, no proven optimum) within budget → the CP-SAT+flow **encoding** is the blocker: record `wall_s` and free-cell sizes, and note escalation (lazy cuts / HiGHS) per spec §6 — **not** a null.

Append to `tasks/lessons.md` an entry `## Exact fixed-placement router — Stage 0 (2026-07-21)` with: the exact commands, the per-layout rows (route vs exact, slack, status, wall_s, valid), the gate arithmetic, and the verdict. Match the voice of the existing "TESTED … closed / WIN" entries.

- [ ] **Step 4: Commit**

```bash
git add tasks/lessons.md
git commit -m "docs: exact fixed-placement router Stage 0 result + gate verdict"
```

*(If a run wrote `output/stage0-exact.json` and `output/` is gitignored, don't add it — commit only `tasks/lessons.md`.)*

---

## Next plan (post-gate, out of scope here)

Only if Task 3 advances: **Stage 1** — wire `exact_route` as an opt-in polish: return `roads if res.optimal else route(...)` so the pipeline never regresses; add a CLI/webapp "polish to minimum roads" entry and an optional flag replacing `route()`'s final call in `validate()`. Gate: beats `route()` by ≥1 road on the darkzig best layouts AND solves within a production-acceptable budget; fall back to `route()` on timeout. If Stage 0 hit timeouts, Stage 1 first swaps the connectivity encoding (spec §6 B/C) before wiring.

---

## Self-Review

**1. Spec coverage.** Spec §3 model (cover + single-commodity flow + minimize) → Task 1 `exact_route`. §2 grounding (level post-assign, cover+connect validity) → Task 1 level loop + cover constraints. §4/§5 Stage-0 spike + gate → Tasks 2–3 (`run_layout` compares exact vs route() on the reconstructed fixed placement; gate arithmetic in Task 3 Step 3 + Global Constraints). §6 encoding A (CP-SAT+flow) → Task 1; B/C escalation noted in Task 3 and the next-plan section. §7 non-goals (no placement change, no wiring) honored — Stage 1 deferred. §9 deliverables → the three code files + the lessons entry.

**2. Placeholder scan.** No TBD/TODO/"handle edge cases". Every code step is complete. Task 3 is analysis with exact commands + the verbatim gate rule.

**3. Type consistency.** `ExactResult(status, count, roads, wall_s, optimal)` fields match between `exact_router.py`, the tests, and `run_layout`'s reads (`res.status`/`.count`/`.roads`/`.optimal`/`.wall_s`). `exact_route(layout, *, time_limit, seed)` signature consistent across Task 1 tests and Task 2's call (positional `layout` + `time_limit=`). `reconstruct_fixed(layout, best)`/`run_layout(layout, best, time_limit)` consistent between Task 2's script and its test. `roads` is `dict[Cell,int]` everywhere; `route()` returns the same shape so `Layout(..., res.roads)` type-checks for `is_valid`.
