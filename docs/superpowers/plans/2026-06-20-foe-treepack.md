# FoE Optimizer — A3 Grow-Tree-and-Attach Packer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the comb-corridor packer inside the `layout` engine with a grow-tree-and-attach packer that reserves road space proportional to the road network needed (not region area), so it places far more buildings on dense cities.

**Architecture:** Rewrite `foeopt/packer.py`'s `build_candidate`/`_configs`/`PackConfig` to grow a minimal road tree out from the Townhall and attach road-needing buildings to it (extending the road one cell at a time only when needed), then densely pack the no-road buildings, then `route()` for the minimal roads. `repack`/`PackResult` interface and the `layout` CLI stay the same. Add `road_estimate` = Σ(min side)/2 over road-needing buildings.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Reuses `foeopt.packing` (Grid, first_fit, first_fit_adjacent), `foeopt.router.route`, `foeopt.validate`, `foeopt.model`.

## Global Constraints

- Python **3.12**; standard library only; dev dep `pytest`. Test runner: `uv run pytest`.
- Coordinates are `(x, y)` int tuples; `x` → width, `y` → length. **No rotation.**
- **Public interface unchanged:** `repack(layout, thorough=False) -> PackResult`, `PackResult(layout, unplaced)`, and the `layout` CLI command keep their shapes. `classify`/`bbox` are reused.
- **Feasibility by construction:** the reserved road set grows by adjacency from a free Townhall-border cell (so it's connected and rooted at the Townhall); each road-needing building is placed only when it borders a road cell; road cells are never overwritten — so `route()` can always connect every *placed* consumer. `unplaced` holds buildings that couldn't be placed.
- **Best-effort:** place all buildings on ~90%-dense cities and get roads near `road_estimate`; keep the `unplaced` report for the densest inputs. Never emit an overlapping or out-of-region layout.
- `road_estimate(layout) = sum(min(w, l) for road-needing buildings) // 2`.

---

### Task 1: `road_estimate` metric

**Files:**
- Modify: `foeopt/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `road_estimate(layout: Layout) -> int` — `sum(min(width, length) for b in layout.road_needing()) // 2`. A target/lower-ish bound for the road count.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_report.py`:
```python
def test_road_estimate():
    from foeopt.report import road_estimate
    from foeopt.model import Building, Footprint, Layout, Region

    def rn(eid, w, l):
        return Building(eid, f"c{eid}", "generic", Footprint(0, 0, w, l),
                        needs_road=True, road_level=1, is_townhall=False,
                        set_id=None, chain_id=None, name=f"b{eid}")

    th = Building(1, "TH", "main_building", Footprint(0, 0, 1, 1),
                  needs_road=False, road_level=0, is_townhall=True,
                  set_id=None, chain_id=None, name="TH")
    # road-needing min-sides: 5 (from 5x6) + 4 (from 4x4) = 9 -> //2 = 4
    layout = Layout(Region(frozenset()), [th, rn(2, 5, 6), rn(3, 4, 4)], th)
    assert road_estimate(layout) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report.py::test_road_estimate -v`
Expected: FAIL (`cannot import name 'road_estimate'`).

- [ ] **Step 3: Write the implementation**

Add to `foeopt/report.py`:
```python
def road_estimate(layout: Layout) -> int:
    """Target road-tile count: a road serves a double row of buildings, so the
    minimal road is ~ (sum of each road-needing building's shorter side) / 2."""
    return sum(min(b.footprint.width, b.footprint.length)
               for b in layout.road_needing()) // 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_report.py::test_road_estimate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/report.py tests/test_report.py
git commit -m "feat(report): road_estimate target metric"
```

---

### Task 2: A3 grow-tree-and-attach `build_candidate`

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Consumes: `Grid`, `first_fit`, `first_fit_adjacent` (packing), `route`/`RouteError`, `Footprint.border_cells()`, `classify`, `bbox`.
- Produces:
  - `PackConfig(anchor: str, order: str)` — `anchor` ∈ `{"bl","br","tl","tr"}` (Townhall start corner); `order` reserved (`"area"`).
  - `build_candidate(layout: Layout, config: PackConfig) -> PackResult` — grow-tree-and-attach (see Global Constraints). Helpers `_corner_fit`, `_road_frontier_cell`, module constant `_ORTHO`.

- [ ] **Step 1: Write the failing tests**

Replace the existing `build_candidate`/`PackConfig` tests in `tests/test_packer.py`. Keep `_b`, `_full_region`. Replace the `PackConfig(...)` construction in any kept test (e.g. `test_unplaced_has_no_duplicate_entity_ids`) to use `PackConfig("bl", "area")`. Add:
```python
def test_build_candidate_grows_tree_in_sparse_city():
    from foeopt.packer import build_candidate, PackConfig
    from foeopt.validate import is_valid
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(12, 12), [th, *cons, *fill], th)
    res = build_candidate(layout, PackConfig("bl", "area"))
    assert res.unplaced == []
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= layout.region.cells
        assert not (cells & occ)
        occ |= cells
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)
    # roads should be modest on a sparse city (near the estimate, not the whole map)
    assert len(res.layout.roads) <= 30


def test_build_candidate_reports_unplaced_when_too_tight():
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = _b(2, 0, 0, 2, 2, needs=True)
    layout = Layout(_full_region(2, 2), [th, cons], th)  # townhall fills the region
    res = build_candidate(layout, PackConfig("bl", "area"))
    assert any(b.entity_id == 2 for b in res.unplaced)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packer.py -k build_candidate -v`
Expected: FAIL (old `PackConfig("h", ...)` signature / new test names).

- [ ] **Step 3: Rewrite the implementation**

In `foeopt/packer.py`, replace `PackConfig`, `_corridor_cells`, and `build_candidate` with:
```python
_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class PackConfig:
    anchor: str   # Townhall start corner: "bl" | "br" | "tl" | "tr"
    order: str    # building order; "area" = largest first (reserved knob)


def _corner_fit(grid: Grid, w: int, l: int, anchor: str) -> tuple[int, int] | None:
    xs = range(grid.width) if anchor in ("bl", "tl") else range(grid.width - 1, -1, -1)
    ys = range(grid.height) if anchor in ("bl", "br") else range(grid.height - 1, -1, -1)
    for y in ys:
        for x in xs:
            if grid.fits(x, y, w, l):
                return (x, y)
    return None


def _road_frontier_cell(grid: Grid, road: set, region) -> tuple[int, int] | None:
    """Bottom-left-most free region cell orthogonally adjacent to the road set."""
    best = None
    for (rx, ry) in road:
        for dx, dy in _ORTHO:
            n = (rx + dx, ry + dy)
            if n in region and n not in road and grid.is_available(n):
                if best is None or n < best:
                    best = n
    return best


def build_candidate(layout: Layout, config: PackConfig) -> PackResult:
    region = layout.region.cells
    w, h = bbox(layout.region)
    blocked = {(x, y) for x in range(w) for y in range(h)} - region
    grid = Grid(w, h, blocked)
    townhall, consumers, fillers = classify(layout)
    placed: dict[int, tuple[int, int]] = {}
    unplaced: list[Building] = []

    def area(b: Building) -> int:
        return b.footprint.width * b.footprint.length

    # 1. Townhall at the chosen corner.
    tw, tl = townhall.footprint.width, townhall.footprint.length
    pos = _corner_fit(grid, tw, tl, config.anchor)
    if pos is None:
        empty = Layout(layout.region, [], None, {})
        return PackResult(layout=empty, unplaced=list(layout.buildings))
    grid.occupy(pos[0], pos[1], tw, tl)
    placed[townhall.entity_id] = pos
    th_border = Footprint(pos[0], pos[1], tw, tl).border_cells()

    # 2. Seed the road network with a free Townhall-border cell.
    road: set[tuple[int, int]] = set()
    seed = min((c for c in th_border if c in region and grid.is_available(c)),
               default=None)
    if seed is not None:
        road.add(seed)
        grid.reserve([seed])

    # 3. Grow the road and attach road-needing buildings.
    remaining = sorted(consumers, key=area, reverse=True)
    while remaining and road:
        b = remaining[0]
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit_adjacent(grid, bw, bl, road)
        if p is not None:
            grid.occupy(p[0], p[1], bw, bl)
            placed[b.entity_id] = p
            remaining.pop(0)
            continue
        cell = _road_frontier_cell(grid, road, region)
        if cell is None:
            break  # cannot grow the road any further
        road.add(cell)
        grid.reserve([cell])
    unplaced.extend(remaining)

    # 4. Fillers: densest first, anywhere free.
    for b in sorted(fillers, key=area, reverse=True):
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit(grid, bw, bl)
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p

    # 5. Build candidate + route for the minimal road set.
    new_buildings: list[Building] = []
    new_townhall: Building | None = None
    for b in layout.buildings:
        if b.entity_id not in placed:
            continue
        x, y = placed[b.entity_id]
        moved = replace(b, footprint=Footprint(x, y, b.footprint.width, b.footprint.length))
        new_buildings.append(moved)
        if moved.is_townhall:
            new_townhall = moved
    candidate = Layout(region=layout.region, buildings=new_buildings,
                       townhall=new_townhall, roads={})
    try:
        candidate.roads = route(candidate)
    except RouteError:
        placed_consumers = [b for b in consumers if b.entity_id in placed]
        return PackResult(layout=candidate, unplaced=unplaced + placed_consumers)
    return PackResult(layout=candidate, unplaced=unplaced)
```
Also remove the now-unused `Region` import only if nothing else uses it (it is used by `bbox`'s type hint — keep it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packer.py -v`
Expected: PASS (the two new build_candidate tests + the kept ones updated to `PackConfig("bl","area")`).

- [ ] **Step 5: Feasibility check on DarkZig (the early de-risk — record, not a suite test)**

Run:
```bash
uv run python -c "
from foeopt.loader import load_layout
from foeopt.packer import build_candidate, PackConfig
from foeopt.report import road_estimate
from foeopt.validate import is_valid
L = load_layout('darkzig.json')
res = build_candidate(L, PackConfig('bl','area'))
print('placed', len(res.layout.buildings), '/', len(L.buildings),
      '| unplaced', len(res.unplaced),
      '| roads', len(res.layout.roads), '| estimate', road_estimate(L),
      '| valid', is_valid(res.layout) if not res.unplaced else 'partial')
"
```
Expected: **materially better than the comb's 70 unplaced** (ideally near 0 unplaced; roads in the ballpark of the ~114 estimate). **Record the numbers in the task report.** If it does not clearly beat the comb (≥70 unplaced or invalid), STOP and report as a concern — the controller will reassess before Task 3.

- [ ] **Step 6: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat(packer): grow-tree-and-attach build_candidate (adaptive corridors)"
```

---

### Task 3: `repack` config sweep over corners

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Consumes: `build_candidate`, `PackConfig`, `is_valid`.
- Produces: updated `_configs(layout, thorough) -> list[PackConfig]` (fast = one `PackConfig("bl","area")`; thorough = the four corner anchors). `repack(layout, thorough)` unchanged in shape; scores by `(len(unplaced), len(roads))` preferring fully-valid.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_packer.py`:
```python
def test_repack_sparse_city_valid_and_conserves_buildings():
    from foeopt.packer import repack
    from foeopt.validate import is_valid
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(5)]
    layout = Layout(_full_region(14, 14), [th, *cons, *fill], th)
    res = repack(layout, thorough=True)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)


def test_repack_configs_are_corner_anchors():
    from foeopt.packer import _configs
    th = _b(1, 0, 0, 1, 1, th=True)
    layout = Layout(_full_region(6, 6), [th], th)
    fast = _configs(layout, False)
    thorough = _configs(layout, True)
    assert len(fast) == 1 and fast[0].anchor == "bl"
    assert {c.anchor for c in thorough} == {"bl", "br", "tl", "tr"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packer.py -k "repack or configs" -v`
Expected: FAIL (old `_configs` returns `PackConfig("h", ...)` with no `anchor`).

- [ ] **Step 3: Rewrite `_configs`**

Replace `_configs` in `foeopt/packer.py` with:
```python
def _configs(layout: Layout, thorough: bool) -> list[PackConfig]:
    if not thorough:
        return [PackConfig("bl", "area")]
    return [PackConfig(a, "area") for a in ("bl", "br", "tl", "tr")]
```
(`repack` itself is unchanged: it already iterates `_configs`, scores by `(0 if fully_valid else 1, len(unplaced), len(roads))`, and returns the best.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packer.py -v`
Expected: PASS. Then the full suite: `uv run pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat(packer): repack sweeps the four corner anchors"
```

---

### Task 4: Surface the estimate in the `layout` CLI + real-city outcome

**Files:**
- Modify: `foeopt/cli.py`
- Test: `tests/test_layout_cli.py`

**Interfaces:**
- Consumes: `repack`, `road_estimate`, `render_comparison`, `load_layout`, `stats`.
- Produces: `_cmd_layout` additionally prints `estimated optimal ≈ E` using `road_estimate(current)`. The real-city golden invariant (valid-in-structure; all-placed-and-valid OR non-empty unplaced) still holds.

- [ ] **Step 1: Write the failing test**

In `tests/test_layout_cli.py`, the existing `test_repack_real_city_is_valid_or_reports_unplaced` already asserts the invariant — keep it. Add:
```python
def test_layout_reports_road_estimate(city_data, helper_data):
    from foeopt.build import build_layout
    from foeopt.report import road_estimate
    current = build_layout(city_data, helper_data)
    est = road_estimate(current)
    assert isinstance(est, int) and est >= 0
```

- [ ] **Step 2: Run the invariant + new test (baseline)**

Run: `uv run pytest tests/test_layout_cli.py -v`
Expected: PASS (invariant holds with the new packer; estimate is a non-negative int).

- [ ] **Step 3: Add the estimate line to `_cmd_layout`**

In `foeopt/cli.py`, add `road_estimate` to the `from foeopt.report import ...` line, and in `_cmd_layout` add an estimate line to the printed stats (after the buildings/roads lines):
```python
    print(f"  estimated optimal roads (target): {road_estimate(current)}")
```

- [ ] **Step 4: Run tests + record the DarkZig outcome**

Run: `uv run pytest -q`
Expected: all green.

Run (record in the report):
```bash
uv run python -m foeopt.cli layout darkzig.json --thorough -o output/darkzig_treepack.html
```
Expected: prints placed/unplaced, optimized roads, and the estimate. **Record: placed vs 224, roads vs ~114 estimate, vs the old comb's 70 unplaced.**

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/test_layout_cli.py
git commit -m "feat(cli): layout prints the road estimate target"
```

---

## Self-Review

**Spec coverage:**
- Grow-tree-and-attach replaces the comb (spec §1/§4) → Task 2. ✓
- Road space scales to need, not area; feasibility-by-construction (spec §4) → Task 2 (grow-on-demand, connected reserved road) — documented in Global Constraints. ✓
- `road_estimate` = Σ(min side)/2, surfaced in `layout` (spec §2/§6) → Task 1 + Task 4. ✓
- `repack`/`PackResult`/CLI interface kept; reuse packing/router/validate (spec §3) → Tasks 2–4. ✓
- Tuning sweeps corners (spec §5) → Task 3. ✓
- Best-effort + unplaced safety net + never invalid (spec §7) → Task 2 (`unplaced`), real-city golden (Task 4). ✓
- Testing: road_estimate unit, sparse places-all+valid+roads-near-estimate, tight reports unplaced, real-city golden, recorded DarkZig feasibility (spec §8) → Tasks 1–4 (Task 2 Step 5 + Task 4 Step 4). ✓
- Feasibility-first de-risk (spec §9) → Task 2 Step 5 (stop-and-reassess if it doesn't beat the comb). ✓

**Placeholder scan:** No placeholders; every code step has complete code; the two "record, not a suite test" steps (Task 2 Step 5, Task 4 Step 4) are explicit measurements with expected outcomes and a stop condition, not vague TODOs.

**Type consistency:** `PackConfig(anchor, order)` defined in Task 2, used by `_configs` (Task 3) and tests. `build_candidate(layout, config) -> PackResult`, `repack(layout, thorough) -> PackResult`, `PackResult(layout, unplaced)`, `road_estimate(layout) -> int` consistent across tasks. `Grid`/`first_fit`/`first_fit_adjacent` from `packing.py` (existing signatures). `route`/`RouteError`/`is_valid`/`classify`/`bbox` reused unchanged.
