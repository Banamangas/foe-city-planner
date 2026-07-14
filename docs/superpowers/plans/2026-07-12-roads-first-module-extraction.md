# Phase 1: roads_first Module Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the roads-first CP-SAT search from `scripts/exp_roads_first.py` into a clean importable `foeopt/roads_first.py` module with a `RoadsFirstSearch` class that supports `on_improvement`, `on_status`, and `should_stop` callbacks for the webapp's any-time-best SSE integration.

**Architecture:** The experiment script's pure functions (pattern generation, prefilter, probe, validate, worker infrastructure) move verbatim into `foeopt/roads_first.py`. A new `RoadsFirstSearch` class wraps the `run_search` orchestration, replacing disk-writing and `print()` with callback injection. `scripts/exp_roads_first.py` becomes a thin CLI wrapper that imports from the new module and stays functionally identical (including `--selftest`).

**Tech Stack:** Python 3.12+, `ortools>=9` (CP-SAT), `multiprocessing` (parallel probes), `pytest`.

## Global Constraints

- `ortools>=9` becomes a hard dependency: add to `pyproject.toml` `dependencies`.
- Python 3.12+ required (already set in `requires-python`).
- `exp_roads_first.py --selftest` must still pass after refactor (regression gate).
- All existing tests in `tests/test_roads_first_parallel.py` must pass unchanged after the module extraction (import-passthrough strategy).
- FoE buildings cannot rotate — `validate()` must continue calling `rotated_buildings()` as defence-in-depth.
- No comments added to code unless the original source had them at that location.

---

### Task 1: Add ortools hard dependency to pyproject.toml

**Files:**
- Modify: `pyproject.toml:6`

**Interfaces:**
- Consumes: nothing
- Produces: `ortools>=9` available to all `uv run` commands without `--with ortools`

- [ ] **Step 1: Edit pyproject.toml**

Change line 6 from:
```toml
dependencies = ["flask>=3"]
```
to:
```toml
dependencies = ["flask>=3", "ortools>=9"]
```

- [ ] **Step 2: Verify ortools installs via uv sync**

Run: `uv sync`
Expected: succeeds, installs `ortools>=9`

- [ ] **Step 3: Verify existing tests still work with new dep**

Run: `uv run pytest tests/test_roads_first_parallel.py -x -q`
Expected: All tests pass (or skip if city files absent)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add ortools>=9 as hard dependency for roads-first"
```

---

### Task 2: Create foeopt/roads_first.py with pattern generation functions

**Files:**
- Create: `foeopt/roads_first.py`
- Test: `tests/roads_first/__init__.py`, `tests/roads_first/test_pattern_gen.py`

**Interfaces:**
- Consumes: `foeopt.model.{Building, Footprint, Layout, Region}`, `foeopt.bounds.pick_k_start`, `foeopt.packing.{Grid, first_fit}`, `foeopt.router.{route, RouteError}`, `foeopt.validate.{canonical_dims, is_valid, rotated_buildings}`, `foeopt.viz.render_html`
- Produces: `Pattern` dataclass, `th_anchor_candidates(region, tw, tl, mode) -> list[Footprint]`, `generate_patterns(region, tw, tl, k, rng, max_patterns, th_mode) -> list[Pattern]`, `prefilter(pattern, region, consumers) -> str|None`

- [ ] **Step 1: Create test directory + init**

```bash
mkdir -p tests/roads_first
touch tests/roads_first/__init__.py
```

- [ ] **Step 2: Write failing test for Pattern + generate_patterns**

Create `tests/roads_first/test_pattern_gen.py`:

```python
import random
from foeopt.roads_first import Pattern, generate_patterns, prefilter, th_anchor_candidates


def test_pattern_is_frozen_dataclass():
    p = Pattern(th=__import__("foeopt.model", fromlist=["Footprint"]).Footprint(0, 0, 2, 2),
                roads=frozenset({(0, 2)}), params={"k": 1})
    assert p.params == {"k": 1}
    assert isinstance(p.roads, frozenset)


def test_generate_patterns_k0_returns_empty():
    region = set((x, y) for x in range(6) for y in range(6))
    pats = generate_patterns(region, 2, 2, 0, random.Random(0), 50)
    assert pats == []


def test_generate_patterns_k1_yields_patterns():
    region = set((x, y) for x in range(6) for y in range(6))
    pats = generate_patterns(region, 2, 2, 1, random.Random(0), 50)
    assert len(pats) > 0
    for p in pats:
        assert len(p.roads) == 1
        assert p.roads <= region


def test_th_anchor_candidates_full_mode_yields_many():
    region = set((x, y) for x in range(10) for y in range(10))
    cands = th_anchor_candidates(region, 2, 2, mode="full")
    assert len(cands) > 10
    for fp in cands:
        assert fp.cells() <= frozenset(region)


def test_th_anchor_candidates_coarse_mode_yields_few():
    region = set((x, y) for x in range(10) for y in range(10))
    cands = th_anchor_candidates(region, 2, 2, mode="coarse")
    assert len(cands) >= 1
    assert len(cands) < 20


def test_prefilter_area_rejects_impossible():
    from foeopt.model import Building, Footprint
    th_fp = Footprint(0, 0, 2, 2)
    pat = Pattern(th=th_fp, roads=frozenset({(2, 0), (2, 1)}), params={"k": 2})
    region = set((x, y) for x in range(4) for y in range(4))
    big = Building(1, "c", "g", Footprint(0, 0, 3, 3), True, 1, False, None, None, "big")
    reason = prefilter(pat, region, [big])
    assert reason == "area"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/roads_first/test_pattern_gen.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'foeopt.roads_first'"

- [ ] **Step 4: Create foeopt/roads_first.py with pattern generation**

Create `foeopt/roads_first.py`:

```python
from __future__ import annotations

import random
from dataclasses import dataclass

from foeopt.model import Building, Footprint, Layout, Region

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


@dataclass(frozen=True)
class Pattern:
    th: Footprint
    roads: frozenset[Cell]
    params: dict


def _bbox(region: set[Cell]) -> tuple[int, int, int, int]:
    xs = [c[0] for c in region]
    ys = [c[1] for c in region]
    return min(xs), min(ys), max(xs), max(ys)


def _fits(region: set[Cell], fp: Footprint) -> bool:
    return fp.cells() <= region


def th_anchor_candidates(region: set[Cell], tw: int, tl: int,
                         mode: str = "coarse") -> list[Footprint]:
    if mode == "full":
        x0, y0, x1, y1 = _bbox(region)
        out: dict[tuple[int, int], Footprint] = {}
        for x in range(x0, x1 - tw + 2):
            for y in range(y0, y1 - tl + 2):
                fp = Footprint(x, y, tw, tl)
                if _fits(region, fp):
                    out[(x, y)] = fp
        return [out[k] for k in sorted(out)]
    x0, y0, x1, y1 = _bbox(region)
    corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    out: dict[tuple[int, int], Footprint] = {}

    def scan(keyfn, accept):
        for (x, y) in sorted(region, key=keyfn):
            fp = Footprint(x, y, tw, tl)
            if _fits(region, fp) and accept(x, y):
                return fp
        return None

    for (cx, cy) in corners:
        for d in (0, 2, 4, 6):
            fp = scan(lambda c: (abs(c[0] - cx) + abs(c[1] - cy)),
                      lambda x, y, cx=cx, cy=cy, d=d: max(abs(x - cx), abs(y - cy)) >= d)
            if fp is not None:
                out[(fp.x, fp.y)] = fp
    midx, midy = (x0 + x1) // 2, (y0 + y1) // 2
    for target in ((midx, y0), (x0, midy)):
        fp = scan(lambda c, t=target: (abs(c[0] - t[0]) + abs(c[1] - t[1])), lambda x, y: True)
        if fp is not None:
            out[(fp.x, fp.y)] = fp
    return [out[k] for k in sorted(out)]


def _trunk(region: set[Cell], th: Footprint, side: str) -> list[Cell]:
    if side == "top":
        line = [(x, th.y - 1) for x in range(-1000, 1000)]
        anchor = (th.x, th.y - 1)
    elif side == "bottom":
        line = [(x, th.y + th.length) for x in range(-1000, 1000)]
        anchor = (th.x, th.y + th.length)
    elif side == "left":
        line = [(th.x - 1, y) for y in range(-1000, 1000)]
        anchor = (th.x - 1, th.y)
    else:
        line = [(th.x + th.width, y) for y in range(-1000, 1000)]
        anchor = (th.x + th.width, th.y)
    if anchor not in region:
        return []
    idx = line.index(anchor)
    run = [anchor]
    for i in range(idx - 1, -1, -1):
        if line[i] in region:
            run.insert(0, line[i])
        else:
            break
    for i in range(idx + 1, len(line)):
        if line[i] in region:
            run.append(line[i])
        else:
            break
    return run


def _stub_cells(region: set[Cell], th: Footprint, roads: set[Cell]) -> list[Cell]:
    for row in (th.y + th.length - 1, th.y):
        pair = [(th.x - 1, row), (th.x + th.width, row)]
        if all(c in region and c not in roads for c in pair):
            return pair
    return []


def generate_patterns(region: set[Cell], tw: int, tl: int, k: int,
                      rng: random.Random, max_patterns: int,
                      th_mode: str = "coarse") -> list[Pattern]:
    out: list[Pattern] = []
    seen: set[frozenset[Cell]] = set()
    for th in th_anchor_candidates(region, tw, tl, mode=th_mode):
        th_cells = th.cells()
        reg = region
        for side in ("top", "bottom", "left", "right"):
            trunk = [c for c in _trunk(reg, th, side) if c not in th_cells]
            if not trunk:
                continue
            horiz = trunk[0][1] == trunk[-1][1]
            for spacing in (3, 4, 5, 6, 7):
                for mode in ("both", "alternate"):
                    for use_stubs in (False, True):
                        roads: set[Cell] = set()
                        stubs = _stub_cells(reg, th, roads) if use_stubs else []
                        budget = k - len(stubs)
                        if budget < 1:
                            continue
                        trunk_len = 1 if budget == 1 else max(2, budget // 2)
                        trunk_used = trunk[:min(len(trunk), trunk_len)]
                        roads |= set(trunk_used)
                        remaining = budget - len(trunk_used)
                        if remaining < 0:
                            continue
                        seeds = trunk_used[spacing - 1::spacing]
                        dirs = []
                        for i, s in enumerate(seeds):
                            if horiz:
                                cand_dirs = [(0, -1), (0, 1)]
                            else:
                                cand_dirs = [(-1, 0), (1, 0)]
                            if mode == "both":
                                dirs += [(s, d) for d in cand_dirs]
                            else:
                                dirs.append((s, cand_dirs[i % 2]))
                        fronts = [(s, d, 1) for (s, d) in dirs]
                        grown = True
                        while remaining > 0 and grown:
                            grown = False
                            for j, (s, d, dist) in enumerate(fronts):
                                if remaining == 0:
                                    break
                                c = (s[0] + d[0] * dist, s[1] + d[1] * dist)
                                if c in reg and c not in roads and c not in th_cells:
                                    roads.add(c)
                                    fronts[j] = (s, d, dist + 1)
                                    remaining -= 1
                                    grown = True
                        if remaining != 0:
                            continue
                        roads |= set(stubs)
                        key = frozenset(roads)
                        if len(key) != k or key in seen:
                            continue
                        seen.add(key)
                        out.append(Pattern(th=th, roads=key, params={
                            "th": (th.x, th.y), "side": side, "spacing": spacing,
                            "mode": mode, "stubs": use_stubs,
                            "trunk_len": len(trunk_used), "k": k}))
    rng.shuffle(out)
    return out[:max_patterns]


def prefilter(pattern: Pattern, region: set[Cell],
              consumers: list[Building]) -> str | None:
    th_cells = pattern.th.cells()
    area_needed = sum(b.footprint.width * b.footprint.length for b in consumers)
    if area_needed + len(pattern.roads) > len(region) - len(th_cells):
        return "area"
    free = region - pattern.roads - th_cells
    capacity = sum(3 for c in pattern.roads
                   if any((c[0] + dx, c[1] + dy) in free for dx, dy in _ORTHO))
    if capacity < len(consumers):
        return "adjacency-capacity"
    return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/roads_first/test_pattern_gen.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add foeopt/roads_first.py tests/roads_first/__init__.py tests/roads_first/test_pattern_gen.py
git commit -m "feat: extract Pattern + pattern generation into foeopt/roads_first"
```

---

### Task 3: Add probe + validate functions to roads_first.py

**Files:**
- Modify: `foeopt/roads_first.py`
- Test: `tests/roads_first/test_probe.py`

**Interfaces:**
- Consumes: `foeopt.packing.{Grid, first_fit}`, `foeopt.router.{route, RouteError}`, `foeopt.validate.{canonical_dims, is_valid, rotated_buildings}`
- Produces: `probe(pattern, region, consumers, *, probe_limit, probe_workers=1) -> tuple[str, dict|None]`, `validate(layout_src, pattern, positions) -> tuple[str, Layout|None, int]`

- [ ] **Step 1: Write failing test for probe (mocked, no ortools needed for UNSAT path)**

Create `tests/roads_first/test_probe.py`:

```python
import random
import pytest
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.roads_first import probe, validate, generate_patterns, prefilter, Pattern


def test_probe_returns_unsat_when_no_anchors():
    """A consumer too big for the region after roads+TH occupy space -> UNSAT."""
    th = Building(1, "c1", "main_building", Footprint(0, 0, 1, 1),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(2) for y in range(2)))
    lay = Layout(region, [th, consumer], th, {})
    pats = list(generate_patterns(set(region.cells), 1, 1, 1, random.Random(0), 5))
    assert pats
    pat = pats[0]
    st, pos = probe(pat, set(region.cells), [consumer], probe_limit=5.0)
    assert st == "UNSAT"
    assert pos is None


def test_validate_returns_ok_on_simple_satisfiable():
    """End-to-end: a 6x6 region with TH + 1 consumer at k=1 should validate OK
    when probe finds a SAT placement. Requires ortools."""
    pytest.importorskip("ortools")
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})
    region_set = set(region.cells)
    rng = random.Random(0)
    found_ok = False
    for pat in generate_patterns(region_set, 2, 2, 1, rng, 50):
        if prefilter(pat, region_set, [c1]) is not None:
            continue
        st, pos = probe(pat, region_set, [c1], probe_limit=30.0)
        if st != "SAT":
            continue
        vstat, vlay, achieved = validate(lay, pat, pos)
        if vstat == "OK":
            found_ok = True
            assert achieved == 1
            assert len(vlay.buildings) >= 2
            break
    assert found_ok, "expected at least one OK validation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/roads_first/test_probe.py -v`
Expected: FAIL with "ImportError: cannot import name 'probe' from 'foeopt.roads_first'"

- [ ] **Step 3: Add _check_pattern, probe + validate + _anchor_candidates to roads_first.py**

Append to `foeopt/roads_first.py` (after `prefilter`):

```python
from foeopt.packing import Grid, first_fit
from foeopt.router import RouteError, route
from foeopt.validate import canonical_dims, is_valid, rotated_buildings


def _check_pattern(p: Pattern, region: set[Cell], k: int) -> None:
    assert len(p.roads) == k, f"{len(p.roads)} != {k}"
    assert p.roads <= region and not (p.roads & p.th.cells())
    th_border = p.th.border_cells()
    seeds = [c for c in p.roads if c in th_border]
    assert seeds, "no road cell touches the TH border"
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        cx, cy = stack.pop()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in p.roads and n not in seen:
                seen.add(n)
                stack.append(n)
    assert seen == set(p.roads), "pattern not connected to the TH"


def _anchor_candidates(b: Building, region: set[Cell], blocked: set[Cell],
                       roads: frozenset[Cell]) -> list[tuple[int, int]]:
    out = []
    w, l = b.footprint.width, b.footprint.length
    x0, y0, x1, y1 = _bbox(region)
    for y in range(y0, y1 - l + 2):
        for x in range(x0, x1 - w + 2):
            fp = Footprint(x, y, w, l)
            cells = fp.cells()
            if not (cells <= region) or (cells & blocked):
                continue
            if any(c in roads for c in fp.border_cells()):
                out.append((x, y))
    return out


def probe(pattern: Pattern, region: set[Cell], consumers: list[Building],
          *, probe_limit: float, probe_workers: int = 1) -> tuple[str, dict | None]:
    from ortools.sat.python import cp_model

    th_cells = set(pattern.th.cells())
    blocked = set(pattern.roads) | th_cells
    cand = []
    for b in consumers:
        opts = _anchor_candidates(b, region, blocked, pattern.roads)
        if not opts:
            return ("UNSAT", None)
        cand.append((b, opts))

    m = cp_model.CpModel()
    x0b, y0b, x1b, y1b = _bbox(region)
    xs, ys, xiv, yiv = [], [], [], []
    for i, (b, opts) in enumerate(cand):
        w0, l0 = b.footprint.width, b.footprint.length
        x = m.NewIntVar(x0b, x1b, f"x{i}")
        y = m.NewIntVar(y0b, y1b, f"y{i}")
        m.AddAllowedAssignments([x, y], opts)
        xiv.append(m.NewFixedSizeIntervalVar(x, w0, f"xi{i}"))
        yiv.append(m.NewFixedSizeIntervalVar(y, l0, f"yi{i}"))
        xs.append(x); ys.append(y)
    m.AddNoOverlap2D(xiv, yiv)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = probe_workers
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = probe_limit
    st = solver.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        pos = {}
        for i, (b, _) in enumerate(cand):
            w, l = b.footprint.width, b.footprint.length
            pos[b.entity_id] = (solver.Value(xs[i]), solver.Value(ys[i]), w, l)
        return ("SAT", pos)
    if st == cp_model.INFEASIBLE:
        return ("UNSAT", None)
    return ("UNKNOWN", None)


def validate(layout_src: Layout, pattern: Pattern,
             positions: dict) -> tuple[str, Layout | None, int]:
    from dataclasses import replace
    consumers = layout_src.road_needing()
    fillers = [b for b in layout_src.buildings
               if not b.needs_road and not b.is_townhall]
    placed = []
    for b in consumers:
        x, y, w, l = positions[b.entity_id]
        placed.append(replace(b, footprint=Footprint(x, y, w, l)))
    th = replace(layout_src.townhall, footprint=pattern.th)
    cand = Layout(layout_src.region, [th, *placed], th, {})
    try:
        roads = route(cand)
    except RouteError:
        return ("ROUTE_FAIL", None, 0)
    cand.roads = roads
    if not is_valid(cand):
        return ("INVALID", None, 0)
    region = set(layout_src.region.cells)
    x0, y0, x1, y1 = _bbox(region)
    w, h = x1 + 1, y1 + 1
    occupied = set(roads) | set(th.footprint.cells())
    for b in placed:
        occupied |= b.footprint.cells()
    free = region - occupied
    grid = Grid(w, h, {(x, y) for x in range(w) for y in range(h)} - free)
    for b in sorted(fillers, key=lambda b: -(b.footprint.width * b.footprint.length)):
        bw, bl = b.footprint.width, b.footprint.length
        spot = first_fit(grid, bw, bl)
        if spot is None:
            return ("SAT_FILLER_FAIL", None, len(roads))
        grid.occupy(spot[0], spot[1], bw, bl)
        from dataclasses import replace as _r
        cand.buildings.append(_r(b, footprint=Footprint(spot[0], spot[1], bw, bl)))
    bad = rotated_buildings(cand, canonical_dims(layout_src))
    if bad:
        return ("SAT_ROTATED", None, len(roads))
    return ("OK", cand, len(roads))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/roads_first/test_probe.py -v`
Expected: PASS (2 tests; the validate test requires ortools and may take a few seconds)

- [ ] **Step 5: Commit**

```bash
git add foeopt/roads_first.py tests/roads_first/test_probe.py
git commit -m "feat: add probe + validate to roads_first module"
```

---

### Task 4: Add worker infrastructure (_worker_init, _run_probe, _run_probe_seq)

**Files:**
- Modify: `foeopt/roads_first.py`
- Test: `tests/roads_first/test_worker.py`

**Interfaces:**
- Consumes: `multiprocessing`, `time`
- Produces: `_worker_init(layout, probe_limit, probe_workers)`, `_run_probe(payload) -> dict`, `_run_probe_seq(payload) -> dict`, module globals `_WORKER_LAYOUT`, `_WORKER_PROBE_LIMIT`, `_WORKER_PROBE_WORKERS`

- [ ] **Step 1: Write failing test for _run_probe with mocked probe**

Create `tests/roads_first/test_worker.py`:

```python
import pytest
from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as mod


def test_run_probe_unsat_returns_status_no_layout(monkeypatch):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 1, 1),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(2) for y in range(2)))
    lay = Layout(region, [th, consumer], th, {})

    import random
    pats = list(mod.generate_patterns(set(region.cells), 1, 1, 1, random.Random(0), 5))
    assert pats
    pat = pats[0]

    def fake_probe(pattern, region, consumers, *, probe_limit, **kwargs):
        return ("UNSAT", None)

    monkeypatch.setattr(mod, "probe", fake_probe)
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        result = mod._run_probe((pat, 1, 0))
    finally:
        mod._WORKER_LAYOUT = None
    assert set(result.keys()) >= {"k", "params", "status", "achieved", "secs", "layout"}
    assert result["status"] == "UNSAT"
    assert result["achieved"] is None
    assert result["layout"] is None
    assert isinstance(result["secs"], float)
    assert result["secs"] >= 0.0
    assert result["k"] == 1
    assert result["params"] == pat.params


def test_run_probe_payload_uses_worker_global_not_embedded_layout(monkeypatch):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    import random
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        pats = list(mod.generate_patterns(set(region.cells), 2, 2, 1, random.Random(0), 5))
        pat = next(p for p in pats if mod.prefilter(p, set(region.cells), [c1]) is None)
        monkeypatch.setattr(mod, "probe",
                            lambda pattern, region, consumers, *, probe_limit, probe_workers=1:
                            ("UNSAT", None))
        result = mod._run_probe((pat, 1, 0))
        assert result["pat_index"] == 0
        assert result["k"] == 1
    finally:
        mod._WORKER_LAYOUT = None
        del mod._WORKER_PROBE_LIMIT
        del mod._WORKER_PROBE_WORKERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/roads_first/test_worker.py -v`
Expected: FAIL with "AttributeError: module 'foeopt.roads_first' has no attribute '_run_probe'"

- [ ] **Step 3: Add worker infrastructure to roads_first.py**

Add these imports at the top of `foeopt/roads_first.py` (after existing imports):

```python
import json
import multiprocessing
import time
from dataclasses import replace
```

Append to `foeopt/roads_first.py` (after `validate`):

```python
_WORKER_LAYOUT: Layout | None = None
_WORKER_PROBE_LIMIT: float = 30.0
_WORKER_PROBE_WORKERS: int = 1


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int) -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers


def _run_probe(payload: tuple) -> dict:
    pat, k, pat_index = payload
    layout = _WORKER_LAYOUT
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers,
                   probe_limit=_WORKER_PROBE_LIMIT,
                   probe_workers=_WORKER_PROBE_WORKERS)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay, "pat_index": pat_index}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}


def _run_probe_seq(payload: tuple) -> dict:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    pat, k, layout, probe_limit, probe_workers = payload
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    try:
        return _run_probe((pat, k, 0))
    finally:
        _WORKER_LAYOUT = None
```

Also update `validate` to use the module-level `replace` import instead of inline import — change the two `from dataclasses import replace as _r` lines to use `replace` directly. The `validate` function already has `from dataclasses import replace` at the top of the file now, so remove the inline import:

In the `validate` function, replace:
```python
        from dataclasses import replace as _r
        cand.buildings.append(_r(b, footprint=Footprint(spot[0], spot[1], bw, bl)))
```
with:
```python
        cand.buildings.append(replace(b, footprint=Footprint(spot[0], spot[1], bw, bl)))
```

And remove the earlier inline `from dataclasses import replace` inside `validate` (it's now at module level).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/roads_first/test_worker.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/roads_first.py tests/roads_first/test_worker.py
git commit -m "feat: add worker infrastructure (_worker_init, _run_probe) to roads_first"
```

---

### Task 5: Add _probe_level to roads_first.py

**Files:**
- Modify: `foeopt/roads_first.py`
- Test: `tests/roads_first/test_probe_level.py`

**Interfaces:**
- Consumes: `_run_probe`, `_run_probe_seq`, `generate_patterns`, `prefilter`, `multiprocessing.Pool|None`
- Produces: `_probe_level(layout, region, consumers, k, rng, params, log, pool=None, on_improvement=None) -> tuple[str, int|None]` where `params` is a namespace with `.patterns`, `.probe_limit`, `.probe_workers`, `.deadline`, `.th_anchors`, and `on_improvement` is an optional callback `(layout, k, achieved)` fired when a better validated layout is found inside `handle_result`

- [ ] **Step 1: Write failing test for _probe_level sequential**

Create `tests/roads_first/test_probe_level.py`:

```python
import random
import time
import pytest
from types import SimpleNamespace
from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as mod


def test_probe_level_sequential_fallback_matches_today():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    call_order = []
    fake_layout = SimpleNamespace(roads=set(), buildings=[])

    def fake_run_probe(payload):
        pat, k, pat_index = payload
        call_order.append(pat.params)
        if len(call_order) == 1:
            return {"k": k, "params": pat.params, "status": "SAT",
                    "achieved": k, "secs": 0.1,
                    "layout": fake_layout, "pat_index": pat_index}
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None,
                "pat_index": pat_index}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "_run_probe", fake_run_probe)

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    log_rows = []

    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=None)
    finally:
        monkeypatch.undo()

    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    expected_order = [p.params for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    assert call_order == expected_order
    assert status == "FEASIBLE"
    assert best == 1
    assert any(r.get("status") == "SAT" for r in log_rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/roads_first/test_probe_level.py -v`
Expected: FAIL with "AttributeError: module 'foeopt.roads_first' has no attribute '_probe_level'"

- [ ] **Step 3: Add _probe_level to roads_first.py**

Append to `foeopt/roads_first.py` (after `_run_probe_seq`):

```python
def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None) -> tuple[str, int | None]:
    th = layout.townhall.footprint
    th_mode = getattr(params, "th_anchors", "coarse")
    pats = generate_patterns(region, th.width, th.length, k, rng, params.patterns,
                             th_mode=th_mode)
    best_achieved = None
    saw_nonproof_failure = False
    order = 0

    def handle_result(result, pat):
        nonlocal best_achieved, order, saw_nonproof_failure
        order += 1
        status = result["status"]
        achieved = result["achieved"]
        log({"k": k, "params": pat.params, "status": status,
             "achieved": achieved, "secs": result["secs"], "order": order})
        if status == "SAT":
            vlay = result["layout"]
            if best_achieved is None or achieved < best_achieved:
                best_achieved = achieved
                if on_improvement is not None:
                    on_improvement(vlay, k, achieved)
        elif status in ("UNKNOWN", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"):
            saw_nonproof_failure = True
        if time.monotonic() > params.deadline:
            return True
        return False

    surviving = []
    for pat in pats:
        reason = prefilter(pat, region, consumers)
        if reason is not None:
            log({"k": k, "params": pat.params, "status": "PREFILTERED",
                 "reason": reason, "secs": 0.0, "order": 0})
            continue
        surviving.append(pat)

    if pool is None:
        for pat in surviving:
            result = _run_probe_seq((pat, k, layout, params.probe_limit, params.probe_workers))
            if handle_result(result, pat):
                return ("INCONCLUSIVE" if best_achieved is None else "FEASIBLE", best_achieved)
    else:
        payloads = [(pat, k, idx) for idx, pat in enumerate(surviving)]
        for result in pool.imap_unordered(_run_probe, payloads):
            idx = result["pat_index"]
            pat = surviving[idx]
            if handle_result(result, pat):
                pool.terminate()
                break

    if best_achieved is not None:
        return ("FEASIBLE", best_achieved)
    if not pats:
        return ("INCONCLUSIVE", None)
    return ("INCONCLUSIVE" if saw_nonproof_failure else "INFEASIBLE", None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/roads_first/test_probe_level.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add foeopt/roads_first.py tests/roads_first/test_probe_level.py
git commit -m "feat: add _probe_level to roads_first module"
```

---

### Task 6: Add RoadsFirstSearch class with callbacks

**Files:**
- Modify: `foeopt/roads_first.py`
- Test: `tests/roads_first/test_search.py`

**Interfaces:**
- Consumes: `_probe_level`, `pick_k_start`, `multiprocessing.Pool`, `time`, `json`
- Produces: `RoadsFirstSearch` class with `__init__(layout, *, time_box, patterns=200, probe_limit=60, workers=4, probe_workers=4, th_anchors="full", k_start="auto")` and `run(on_improvement=None, on_status=None, should_stop=None) -> dict`

- [ ] **Step 1: Write failing test for RoadsFirstSearch basic callbacks**

Create `tests/roads_first/test_search.py`:

```python
import time
import pytest
from types import SimpleNamespace
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.bounds import pick_k_start
from foeopt import roads_first as mod


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


def test_search_on_improvement_fires_on_sat(monkeypatch):
    """When _probe_level finds a SAT layout, on_improvement must be called
    with (layout, k, achieved) — the actual validated Layout object."""
    lay = _tiny_layout()
    improvements = []

    fake_layout_result = SimpleNamespace(roads={(0, 2)}, buildings=[])

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                         on_improvement=None):
        if on_improvement is not None:
            on_improvement(fake_layout_result, k, k)
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)

    def on_improvement(best_layout, k, achieved):
        improvements.append((best_layout, k, achieved))

    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    result = search.run(on_improvement=on_improvement)
    assert len(improvements) >= 1
    assert improvements[0][1] == 1  # k
    assert improvements[0][2] == 1  # achieved
    assert improvements[0][0] is fake_layout_result  # the actual layout


def test_search_should_stop_interrupts(monkeypatch):
    """If should_stop returns True, the search must wrap up and return best-so-far
    rather than continuing the k-walk."""
    lay = _tiny_layout()
    stop_flag = {"calls": 0}

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None):
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)

    def should_stop():
        stop_flag["calls"] += 1
        return stop_flag["calls"] > 1

    search = mod.RoadsFirstSearch(lay, time_box=600.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    result = search.run(should_stop=should_stop)
    assert result["verdict"] == "DONE"
    assert stop_flag["calls"] >= 1


def test_search_on_status_fires_after_level(monkeypatch):
    """on_status must fire after each k-level completes with (k, level_status, probes_done, probes_total)."""
    lay = _tiny_layout()
    statuses = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None):
        return ("FEASIBLE", k)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)

    def on_status(k, level_status, probes_done, probes_total):
        statuses.append({"k": k, "status": level_status,
                         "done": probes_done, "total": probes_total})

    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=1)
    result = search.run(on_status=on_status)
    assert len(statuses) >= 1
    assert statuses[0]["status"] == "FEASIBLE"


def test_search_k_start_auto_resolves(monkeypatch):
    """k_start='auto' must resolve to pick_k_start(layout) before first probe."""
    lay = _tiny_layout()
    captured_k = []

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None):
        captured_k.append(k)
        return ("FEASIBLE", 200)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    expected = pick_k_start(lay)
    search = mod.RoadsFirstSearch(lay, time_box=1.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start="auto")
    search.run()
    assert captured_k, "run() did not probe any level"
    assert captured_k[0] == expected


def test_search_family_too_weak(monkeypatch):
    """When all levels are INFEASIBLE and fallback exhausts, verdict=FAMILY_TOO_WEAK."""
    lay = _tiny_layout()

    def fake_probe_level(layout, region, consumers, k, rng, params, log, pool=None):
        return ("INFEASIBLE", None)

    monkeypatch.setattr(mod, "_probe_level", fake_probe_level)
    search = mod.RoadsFirstSearch(lay, time_box=60.0, patterns=5, probe_limit=1.0,
                                  workers=1, th_anchors="coarse", k_start=100)
    result = search.run()
    assert result["verdict"] == "FAMILY_TOO_WEAK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/roads_first/test_search.py -v`
Expected: FAIL with "AttributeError: module 'foeopt.roads_first' has no attribute 'RoadsFirstSearch'"

- [ ] **Step 3: Add RoadsFirstSearch class to roads_first.py**

Add import at top of `foeopt/roads_first.py`:

```python
from foeopt.bounds import pick_k_start
```

Append to `foeopt/roads_first.py` (after `_probe_level`):

```python
class RoadsFirstSearch:
    def __init__(self, layout: Layout, *, time_box: float, patterns: int = 200,
                 probe_limit: float = 60.0, workers: int = 4,
                 probe_workers: int = 4, th_anchors: str = "full",
                 k_start="auto"):
        self.layout = layout
        self.time_box = time_box
        self.patterns = patterns
        self.probe_limit = probe_limit
        self.workers = workers
        self.probe_workers = probe_workers
        self.th_anchors = th_anchors
        self.k_start = k_start

    def run(self, on_improvement=None, on_status=None, should_stop=None) -> dict:
        from dataclasses import SimpleNamespace

        layout = self.layout
        region = set(layout.region.cells)
        consumers = layout.road_needing()
        rng = random.Random(0)
        deadline = time.monotonic() + self.time_box

        pool = None
        if self.workers > 1:
            pool = multiprocessing.Pool(
                self.workers,
                initializer=_worker_init,
                initargs=(layout, self.probe_limit, self.probe_workers))

        params = SimpleNamespace(
            patterns=self.patterns,
            probe_limit=self.probe_limit,
            probe_workers=self.probe_workers,
            deadline=deadline,
            th_anchors=self.th_anchors,
        )

        results: dict[int, tuple[str, int | None]] = {}

        def _should_stop():
            if should_stop is not None and should_stop():
                return True
            return time.monotonic() >= deadline

        def level(k):
            if k not in results:
                results[k] = _probe_level(layout, region, consumers, k, rng,
                                          params, lambda r: None, pool=pool,
                                          on_improvement=on_improvement)
                if on_status is not None:
                    on_status(k, results[k][0], 0, 0)
            return results[k]

        try:
            truncated = False

            if self.k_start == "auto":
                k = pick_k_start(layout)
            else:
                k = self.k_start

            st, _ = level(k)
            if st != "FEASIBLE":
                k_max = len(layout.region.cells) - sum(
                    b.footprint.width * b.footprint.length for b in layout.buildings)
                while st != "FEASIBLE" and k < k_max:
                    if _should_stop():
                        truncated = True
                        break
                    k += 4
                    st, _ = level(k)
                if st != "FEASIBLE":
                    return {"verdict": "FAMILY_TOO_WEAK", "walk_complete": not truncated,
                            "deadline_hit": _should_stop(), "results": results}

            lo_feasible = k
            while True:
                if _should_stop():
                    truncated = True
                    break
                nxt = lo_feasible - 4
                if nxt < 1:
                    break
                st, _ = level(nxt)
                if st == "FEASIBLE":
                    lo_feasible = nxt
                else:
                    break

            lo, hi = lo_feasible - 4, lo_feasible
            while hi - lo > 1:
                if _should_stop():
                    truncated = True
                    break
                mid = (lo + hi) // 2
                st, _ = level(mid)
                if st == "FEASIBLE":
                    hi = mid
                else:
                    lo = mid

            best = min((r[1] for r in results.values() if r[1] is not None), default=None)
            unknowns = sum(1 for r in results.values() if r[0] == "INCONCLUSIVE")
            return {"verdict": "DONE",
                    "lowest_feasible_k_probed": hi if best is not None else None,
                    "best_achieved": best, "inconclusive_levels": unknowns,
                    "walk_complete": not truncated, "deadline_hit": _should_stop(),
                    "results": results}
        finally:
            if pool is not None:
                pool.close()
                pool.join()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/roads_first/test_search.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add foeopt/roads_first.py tests/roads_first/test_search.py
git commit -m "feat: add RoadsFirstSearch class with on_improvement/on_status/should_stop callbacks"
```

---

### Task 7: Refactor exp_roads_first.py CLI to import from foeopt.roads_first

**Files:**
- Modify: `scripts/exp_roads_first.py`

**Interfaces:**
- Consumes: `foeopt.roads_first.*` (all extracted functions + `RoadsFirstSearch`)
- Produces: unchanged CLI behavior (`--selftest`, `--dump-patterns`, `--smoke`, k-walk)

- [ ] **Step 1: Rewrite exp_roads_first.py as thin CLI wrapper**

Replace the entire contents of `scripts/exp_roads_first.py` with:

```python
"""Thin CLI wrapper around foeopt.roads_first.

The search logic now lives in foeopt/roads_first.py (RoadsFirstSearch class).
This script preserves the original CLI interface for experimentation:
  uv run python scripts/exp_roads_first.py --selftest
  uv run python scripts/exp_roads_first.py darkzig.json --dump-patterns 152
  uv run python scripts/exp_roads_first.py darkzig.json --smoke
  uv run python scripts/exp_roads_first.py darkzig.json --th-anchors full
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.roads_first import (
    Pattern, generate_patterns, prefilter, probe, validate,
    _check_pattern, _run_probe, _worker_init, _probe_level,
    RoadsFirstSearch,
)

# Re-export for existing tests that import from exp_roads_first
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]
multiprocessing = __import__("multiprocessing")


def _selftest() -> int:
    from rl.oracle import optimal_roads
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    c2 = Building(11, "c11", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "b")
    region_cells = frozenset((x, y) for x in range(6) for y in range(6))
    lay = Layout(Region(region_cells), [th, c1, c2], th, {})
    oracle = optimal_roads(lay, budget_s=60.0)
    region = set(region_cells)
    rng = random.Random(0)
    ok_k1 = False
    for pat in generate_patterns(region, 2, 2, 1, rng, 50):
        if prefilter(pat, region, [c1, c2]) is not None:
            continue
        st, pos = probe(pat, region, [c1, c2], probe_limit=30.0)
        if st != "SAT":
            continue
        vstat, vlay, achieved = validate(lay, pat, pos)
        if vstat == "OK" and achieved == oracle:
            ok_k1 = True
            break
    ok_k0 = generate_patterns(region, 2, 2, 0, random.Random(0), 50) == []

    import multiprocessing as _mp
    from foeopt import roads_first as mod
    seq_statuses = set()
    rng2 = random.Random(0)
    for pat in generate_patterns(region, 2, 2, 1, rng2, 50):
        if prefilter(pat, region, [c1, c2]) is not None:
            seq_statuses.add(("PREFILTERED", tuple(sorted(pat.params.items()))))
            continue
        st, _ = probe(pat, region, [c1, c2], probe_limit=30.0, probe_workers=1)
        seq_statuses.add((st, tuple(sorted(pat.params.items()))))

    par_statuses = set()
    pool = _mp.Pool(2, initializer=_worker_init, initargs=(lay, 30.0, 1))
    try:
        rng3 = random.Random(0)
        pats3 = [p for p in generate_patterns(region, 2, 2, 1, rng3, 50)]
        surviving = [(p, 1, idx) for idx, p in enumerate(pats3)
                    if prefilter(p, region, [c1, c2]) is None]
        prefiltered = [tuple(sorted(p.params.items())) for p in pats3
                       if prefilter(p, region, [c1, c2]) is not None]
        for pf in prefiltered:
            par_statuses.add(("PREFILTERED", pf))
        for result in pool.imap_unordered(_run_probe, surviving):
            par_statuses.add((result["status"],
                              tuple(sorted(pats3[result["pat_index"]].params.items()))))
    finally:
        pool.close(); pool.join()

    ok_parallel_equiv = par_statuses == seq_statuses
    print(f"selftest: parallel_equiv={ok_parallel_equiv} "
          f"(seq={len(seq_statuses)} par={len(par_statuses)})")
    ok = ok_k1 and ok_k0 and ok_parallel_equiv
    print(f"selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _k_start_type(s: str):
    if s == "auto":
        return "auto"
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("must be 'auto' or an integer")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("city", nargs="?")
    p.add_argument("--dump-patterns", type=int, default=None, metavar="K")
    p.add_argument("--patterns", type=int, default=200)
    p.add_argument("--th-anchors", choices=("coarse", "full"), default="coarse")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--k-start", type=_k_start_type, default="auto")
    p.add_argument("--probe-limit", type=float, default=120.0)
    p.add_argument("--time-box", type=float, default=21600.0)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--probe-workers", type=int, default=4)
    args = p.parse_args(argv)
    if args.smoke:
        args.patterns = 20
        args.probe_limit = 20.0
        args.time_box = 600.0
        args.workers = 1
        args.probe_workers = 1
    if args.selftest:
        return _selftest()
    if args.dump_patterns is not None:
        layout = load_layout(args.city)
        region = set(layout.region.cells)
        th = layout.townhall.footprint
        consumers = layout.road_needing()
        rng = random.Random(args.seed)
        pats = generate_patterns(region, th.width, th.length,
                                 args.dump_patterns, rng, args.patterns)
        kept = 0
        for pat in pats:
            if prefilter(pat, region, consumers) is None:
                kept += 1
        print(f"k={args.dump_patterns}: {len(pats)} generated, {kept} past prefilter")
        for pat in pats[:5]:
            print("  ", pat.params)
        return 0
    if args.city is None:
        p.error("city is required for the k-walk (or use --selftest / --dump-patterns)")

    layout = load_layout(args.city)
    search = RoadsFirstSearch(
        layout, time_box=args.time_box, patterns=args.patterns,
        probe_limit=args.probe_limit, workers=args.workers,
        probe_workers=args.probe_workers, th_anchors=args.th_anchors,
        k_start=args.k_start)
    result = search.run()
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=1))
    per_level = {k: v[0] + (f" achieved={v[1]}" if v[1] is not None else "")
                 for k, v in sorted(result["results"].items())}
    print("levels:", json.dumps(per_level, indent=1))
    if any(v[0] == "INFEASIBLE" for v in result["results"].values()):
        print("note: INFEASIBLE = all sampled patterns UNSAT at that k, not a family-wide floor proof")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify --selftest still passes**

Run: `uv run python scripts/exp_roads_first.py --selftest`
Expected: prints "selftest: PASS"

- [ ] **Step 3: Verify existing parallel tests still pass**

Run: `uv run pytest tests/test_roads_first_parallel.py -v`
Expected: PASS (existing tests import from `exp_roads_first` which now re-exports from `foeopt.roads_first`)

NOTE: The existing tests import `exp_roads_first as mod` and access `mod.generate_patterns`, `mod.prefilter`, `mod._run_probe`, `mod._worker_init`, `mod._probe_level`, `mod.multiprocessing`, `mod.json`, `mod.render_html` — the re-exports at the top of the rewritten script must cover all of these. If any test fails with an AttributeError, add the missing re-export to the import block in `scripts/exp_roads_first.py`.

- [ ] **Step 4: Commit**

```bash
git add scripts/exp_roads_first.py
git commit -m "refactor: exp_roads_first.py → thin CLI wrapper over foeopt.roads_first"
```

---

### Task 8: Port test_roads_first_parallel.py to import from foeopt.roads_first

**Files:**
- Modify: `tests/test_roads_first_parallel.py`

**Interfaces:**
- Consumes: `foeopt.roads_first` (all functions previously imported from `exp_roads_first`)
- Produces: tests that directly test the module (not the CLI wrapper)

- [ ] **Step 1: Update imports in test_roads_first_parallel.py**

Change the top of `tests/test_roads_first_parallel.py`:

Replace:
```python
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import pytest

import exp_roads_first as mod
```

With:
```python
import time
import pytest
from foeopt import roads_first as mod
```

Also update any tests that reference `mod.render_html` or `mod.json` — these are no longer on the module. The test `test_probe_level_sequential_fallback_matches_today` monkeypatches `mod.render_html` and `mod.json`; these patches can be removed since `_probe_level` in the new module no longer calls `render_html` or `json.dumps` (the callback handles output).

In `test_probe_level_sequential_fallback_matches_today`, remove these two lines:
```python
    monkeypatch.setattr(mod, "render_html", lambda lay: "<html/>")
    monkeypatch.setattr(mod.json, "dumps", lambda obj, indent=None: "{}")
```

In `test_k_start_auto_resolves_to_pick_k_start_value`, `test_k_start_explicit_integer_overrides_auto`, `test_fallback_cap_is_k_max_not_168`, and `test_smoke_does_not_override_k_start`, remove the `sys.path.insert` line and update `import exp_roads_first as mod` to `from foeopt import roads_first as mod`. For `test_smoke_does_not_override_k_start`, the test calls `mod.main(["darkzig.json", "--smoke"])` — this must change to import `exp_roads_first` separately:

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import exp_roads_first as cli
```
and call `cli.main(...)` instead of `mod.main(...)`. Also change `monkeypatch.setattr(mod, "run_search", spy_run_search)` to `monkeypatch.setattr(cli, "run_search", spy_run_search)` — but since `cli` now imports `RoadsFirstSearch` and calls `.run()` instead of `run_search()`, this test needs adaptation. The smoke test's purpose is to verify `--smoke` doesn't override `k_start` — change it to spy on `RoadsFirstSearch.run` instead, or simply verify the parsed args. Simplest: keep the `sys.path.insert` + `import exp_roads_first as cli` for this one test, and spy on `cli.RoadsFirstSearch`:

```python
def test_smoke_does_not_override_k_start(monkeypatch):
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import exp_roads_first as cli

    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")

    captured_args = []
    real_init = cli.RoadsFirstSearch.__init__
    def spy_init(self, *a, **kw):
        captured_args.append(kw)
    monkeypatch.setattr(cli.RoadsFirstSearch, "__init__", spy_init)
    def fake_run(self, **kw):
        return {"verdict": "DONE", "results": {}}
    monkeypatch.setattr(cli.RoadsFirstSearch, "run", fake_run)
    try:
        cli.main(["darkzig.json", "--smoke"])
    except Exception:
        pass
    monkeypatch.undo()
    assert captured_args, "main() did not create RoadsFirstSearch"
    assert captured_args[0]["k_start"] == "auto"
    assert captured_args[0]["workers"] == 1
    assert captured_args[0]["probe_workers"] == 1
    assert captured_args[0]["patterns"] == 20
    assert captured_args[0]["probe_limit"] == 20.0
    assert captured_args[0]["time_box"] == 600.0
```

For `test_k_start_auto_resolves_to_pick_k_start_value` and `test_k_start_explicit_integer_overrides_auto`, these test `run_search` which is now `RoadsFirstSearch.run`. Update them to create a `RoadsFirstSearch` instance and call `.run()`:

Replace `mod.run_search(lay, args)` with:
```python
search = mod.RoadsFirstSearch(lay, time_box=args.time_box, patterns=args.patterns,
                              probe_limit=args.probe_limit, workers=1,
                              probe_workers=1, th_anchors=args.th_anchors,
                              k_start=args.k_start)
search.run()
```

For `test_fallback_cap_is_k_max_not_168`, same replacement.

Remove `run_search` references — the function no longer exists on the module.

- [ ] **Step 2: Run ported tests**

Run: `uv run pytest tests/test_roads_first_parallel.py -v`
Expected: PASS (all existing tests pass against the new module)

- [ ] **Step 3: Run ALL new module tests**

Run: `uv run pytest tests/roads_first/ -v`
Expected: PASS (all tasks 2-6 tests)

- [ ] **Step 4: Run full test suite to catch regressions**

Run: `uv run pytest -x -q`
Expected: PASS (no regressions in existing tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_roads_first_parallel.py
git commit -m "test: port test_roads_first_parallel to import from foeopt.roads_first"
```

---

### Task 9: Final verification and cleanup

**Files:**
- Verify: all files

- [ ] **Step 1: Run --selftest one more time**

Run: `uv run python scripts/exp_roads_first.py --selftest`
Expected: "selftest: PASS"

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -q`
Expected: All pass (or skip for missing city files)

- [ ] **Step 3: Smoke test the CLI on darkzig**

Run: `uv run python scripts/exp_roads_first.py darkzig.json --smoke`
Expected: prints verdict + levels, exits 0

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: phase 1 cleanup and final verification" --allow-empty
```