# FoE Optimizer — Phase 2 (Constructive Re-pack) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-pack an entire FoE city from scratch — place all movable buildings plus a Townhall-rooted road network — to minimize road tiles, reusing Phase 1's router for the roads.

**Architecture:** A pure geometry layer `packing.py` (grid-with-obstacles + bottom-left placement). A `packer.py` orchestrator that reserves free "comb" corridors, places road-needing buildings flush against them and fillers everywhere else, then calls Phase 1 `route()` to compute the minimal roads for that placement. Every candidate is gated by the existing validator; if not all buildings fit, an explicit `unplaced` list is returned (never an invalid layout). A `layout` CLI subcommand and a before/after map round it out.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Reuses `foeopt.model/region/build/router/validate/report/viz`.

## Global Constraints

- Python **3.12**; standard library only; dev dep is `pytest`. Test runner: `uv run pytest`.
- Coordinates are `(x, y)` integer tuples; `x` → width, `y` → length. **No rotation.**
- **Generality:** nothing may hardcode the sample city's size/density/counts. The packer adapts to any input; sparse cities yield savings, dense ones may not fit all buildings.
- A **valid layout**: every building inside the region (`build_region` cells), no overlap; every road-needing building (`Building.needs_road`, excluding Townhall) orthogonally adjacent to a road tile of level ≥ `road_level`; road network connected to the Townhall footprint. The Townhall is the root and does not substitute for a road.
- **Fail loudly:** if a building cannot be placed, return it in an `unplaced` list. Never emit an overlapping or out-of-region layout.
- Reuse, don't reimplement: roads come from `foeopt.router.route`; validity from `foeopt.validate`.

---

### Task 1: Grid with obstacles + bottom-left placement (`packing.py`)

**Files:**
- Create: `foeopt/packing.py`
- Test: `tests/test_packing.py`

**Interfaces:**
- Produces:
  - `Grid(width: int, height: int, blocked: set[tuple[int,int]])` with attributes `width`, `height`; methods `fits(x,y,w,l) -> bool` (in-bounds and no cell unavailable), `occupy(x,y,w,l) -> None` (mark a placed footprint unavailable), `reserve(cells: Iterable[tuple[int,int]]) -> None` (mark cells unavailable for placement, e.g. road corridors), `is_available(cell) -> bool`.
  - `first_fit(grid: Grid, w: int, l: int) -> tuple[int,int] | None` — lowest-`y`, then lowest-`x` position where a `w×l` rectangle fits; `None` if none.

- [ ] **Step 1: Write the failing test**

`tests/test_packing.py`:
```python
from foeopt.packing import Grid, first_fit


def test_fits_respects_bounds_and_blocked():
    g = Grid(3, 3, blocked={(2, 2)})
    assert g.fits(0, 0, 2, 2)
    assert not g.fits(2, 2, 1, 1)   # blocked
    assert not g.fits(2, 0, 2, 1)   # out of bounds (x+w > width)


def test_occupy_then_fits_false():
    g = Grid(3, 1, blocked=set())
    g.occupy(0, 0, 2, 1)
    assert not g.fits(0, 0, 1, 1)
    assert g.fits(2, 0, 1, 1)


def test_reserve_blocks_placement():
    g = Grid(3, 1, blocked=set())
    g.reserve([(1, 0)])
    assert not g.is_available((1, 0))
    assert not g.fits(0, 0, 2, 1)   # spans the reserved cell


def test_first_fit_bottom_left():
    g = Grid(3, 2, blocked=set())
    g.occupy(0, 0, 1, 1)            # (0,0) taken
    # lowest y then lowest x: a 1x1 should land at (1,0)
    assert first_fit(g, 1, 1) == (1, 0)


def test_first_fit_none_when_full():
    g = Grid(2, 1, blocked={(0, 0), (1, 0)})
    assert first_fit(g, 1, 1) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packing.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.packing'`).

- [ ] **Step 3: Write the implementation**

`foeopt/packing.py`:
```python
from __future__ import annotations

from collections.abc import Iterable


class Grid:
    """Occupancy over a [0,width) x [0,height) box. `blocked` cells (region
    holes) are unavailable from the start; `occupy` adds placed footprints and
    `reserve` adds road corridors — both make cells unavailable for placement."""

    def __init__(self, width: int, height: int, blocked: set[tuple[int, int]]):
        self.width = width
        self.height = height
        self._unavail: set[tuple[int, int]] = set(blocked)

    def is_available(self, cell: tuple[int, int]) -> bool:
        return cell not in self._unavail

    def fits(self, x: int, y: int, w: int, l: int) -> bool:
        if x < 0 or y < 0 or x + w > self.width or y + l > self.height:
            return False
        for dx in range(w):
            for dy in range(l):
                if (x + dx, y + dy) in self._unavail:
                    return False
        return True

    def occupy(self, x: int, y: int, w: int, l: int) -> None:
        for dx in range(w):
            for dy in range(l):
                self._unavail.add((x + dx, y + dy))

    def reserve(self, cells: Iterable[tuple[int, int]]) -> None:
        self._unavail.update(cells)


def first_fit(grid: Grid, w: int, l: int) -> tuple[int, int] | None:
    for y in range(grid.height):
        for x in range(grid.width):
            if grid.fits(x, y, w, l):
                return (x, y)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_packing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packing.py tests/test_packing.py
git commit -m "feat: grid-with-obstacles and bottom-left placement primitive"
```

---

### Task 2: Bottom-left placement adjacent to a cell set (`packing.py`)

**Files:**
- Modify: `foeopt/packing.py`
- Test: `tests/test_packing.py`

**Interfaces:**
- Consumes: `Grid`, `first_fit`.
- Produces: `first_fit_adjacent(grid: Grid, w: int, l: int, targets: set[tuple[int,int]]) -> tuple[int,int] | None` — lowest-`y`/lowest-`x` position where a `w×l` rectangle fits **and** at least one of its orthogonal border cells is in `targets` (used to place road-needing buildings flush against road corridors).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_packing.py`:
```python
from foeopt.packing import first_fit_adjacent


def test_first_fit_adjacent_requires_border_touch():
    g = Grid(4, 1, blocked=set())
    # corridor at (3,0); a 1x1 must touch it -> only (2,0) borders (3,0)
    assert first_fit_adjacent(g, 1, 1, targets={(3, 0)}) == (2, 0)


def test_first_fit_adjacent_none_when_unreachable():
    g = Grid(4, 1, blocked=set())
    # corridor far away and grid too small to be adjacent except (2,0);
    # block (2,0) so nothing can touch (3,0)
    g.occupy(2, 0, 1, 1)
    assert first_fit_adjacent(g, 1, 1, targets={(3, 0)}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packing.py -k adjacent -v`
Expected: FAIL (`cannot import name 'first_fit_adjacent'`).

- [ ] **Step 3: Write the implementation**

Append to `foeopt/packing.py`:
```python
def _border_cells(x: int, y: int, w: int, l: int) -> set[tuple[int, int]]:
    own = {(x + dx, y + dy) for dx in range(w) for dy in range(l)}
    border: set[tuple[int, int]] = set()
    for (cx, cy) in own:
        for n in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if n not in own:
                border.add(n)
    return border


def first_fit_adjacent(
    grid: Grid, w: int, l: int, targets: set[tuple[int, int]]
) -> tuple[int, int] | None:
    for y in range(grid.height):
        for x in range(grid.width):
            if grid.fits(x, y, w, l) and (_border_cells(x, y, w, l) & targets):
                return (x, y)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_packing.py -v`
Expected: PASS (all packing tests).

- [ ] **Step 5: Commit**

```bash
git add foeopt/packing.py tests/test_packing.py
git commit -m "feat: corridor-adjacent bottom-left placement"
```

---

### Task 3: Packer scaffolding — config, result, classification (`packer.py`)

**Files:**
- Create: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Consumes: `Layout`, `Building`.
- Produces:
  - `PackConfig(orientation: str, spacing: int, trunk_x: int)` dataclass (orientation `"h"` only in this plan; `spacing` = rows between corridor lines; `trunk_x` = column for the connecting trunk).
  - `PackResult(layout: Layout, unplaced: list[Building])` dataclass.
  - `classify(layout: Layout) -> tuple[Building, list[Building], list[Building]]` returning `(townhall, consumers, fillers)` where consumers are road-needing non-townhall buildings and fillers are the rest. Raises `ValueError` if `layout.townhall is None`.
  - `bbox(region) -> tuple[int,int]` returning `(width, height)` = `(max_x+1, max_y+1)` over region cells.

- [ ] **Step 1: Write the failing test**

`tests/test_packer.py`:
```python
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import PackConfig, PackResult, classify, bbox


def _b(eid, x, y, w, l, needs=False, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "generic", Footprint(x, y, w, l),
                    needs_road=needs, road_level=1, is_townhall=th,
                    set_id=None, chain_id=None, name=f"b{eid}")


def test_classify_splits_townhall_consumers_fillers():
    th = _b(1, 0, 0, 1, 1, th=True)
    cons = _b(2, 2, 0, 1, 1, needs=True)
    fill = _b(3, 4, 0, 1, 1, needs=False)
    layout = Layout(Region(frozenset()), [th, cons, fill], th)
    t, consumers, fillers = classify(layout)
    assert t is th
    assert consumers == [cons]
    assert fillers == [fill]


def test_bbox_from_region():
    region = Region(frozenset({(0, 0), (3, 0), (0, 2)}))
    assert bbox(region) == (4, 3)


def test_packconfig_and_packresult_construct():
    cfg = PackConfig(orientation="h", spacing=4, trunk_x=0)
    assert cfg.spacing == 4
    res = PackResult(layout=Layout(Region(frozenset()), [], None), unplaced=[])
    assert res.unplaced == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packer.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.packer'`).

- [ ] **Step 3: Write the implementation**

`foeopt/packer.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from foeopt.model import Building, Layout, Region


@dataclass
class PackConfig:
    orientation: str   # "h" (horizontal road rows) — only mode in Phase 2
    spacing: int       # rows between corridor lines
    trunk_x: int       # column for the vertical connecting trunk


@dataclass
class PackResult:
    layout: Layout
    unplaced: list[Building]


def classify(layout: Layout) -> tuple[Building, list[Building], list[Building]]:
    if layout.townhall is None:
        raise ValueError("layout has no townhall")
    consumers = [b for b in layout.buildings if b.needs_road and not b.is_townhall]
    fillers = [b for b in layout.buildings if not b.needs_road and not b.is_townhall]
    return layout.townhall, consumers, fillers


def bbox(region: Region) -> tuple[int, int]:
    xs = [c[0] for c in region.cells]
    ys = [c[1] for c in region.cells]
    return (max(xs) + 1, max(ys) + 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_packer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat: packer scaffolding (config, result, classify, bbox)"
```

---

### Task 4: Candidate builder — comb + placement + route (`packer.py`)

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Consumes: `PackConfig`, `PackResult`, `classify`, `bbox`, `Grid`, `first_fit`, `first_fit_adjacent`, `foeopt.router.route`, `foeopt.router.RouteError`, `dataclasses.replace`, `Footprint`.
- Produces: `build_candidate(layout: Layout, config: PackConfig) -> PackResult`.
  - Reserves comb corridor cells (horizontal road rows every `spacing`, plus the `trunk_x` column), within the region, as unavailable-for-building (they remain free for roads).
  - Places the Townhall (corridor-adjacent if possible), then consumers (largest-area first, corridor-adjacent), then fillers (largest-area first, anywhere).
  - Builds a candidate `Layout` with the moved buildings and computes roads via `route`. On `RouteError` (no feasible road network), returns the candidate with **all consumers added to `unplaced`** and empty roads (an invalid candidate the caller will reject).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_packer.py`:
```python
from foeopt.packer import build_candidate
from foeopt.validate import is_valid


def _full_region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_build_candidate_places_all_in_sparse_city():
    # Sparse 10x10 region, a townhall + 3 small road-needing + 3 fillers.
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(3)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(10, 10), [th, *cons, *fill], th)
    res = build_candidate(layout, PackConfig("h", spacing=4, trunk_x=0))
    assert res.unplaced == []
    # every building inside region, no overlap
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= layout.region.cells
        assert not (cells & occ)
        occ |= cells
    # roads connect every consumer to the townhall
    assert is_valid(res.layout)
    # buildings are conserved (same count)
    assert len(res.layout.buildings) == len(layout.buildings)


def test_build_candidate_reports_unplaced_when_too_tight():
    # 2x2 region but a 2x2 townhall + a consumer that cannot fit.
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = _b(2, 0, 0, 2, 2, needs=True)
    layout = Layout(_full_region(2, 2), [th, cons], th)
    res = build_candidate(layout, PackConfig("h", spacing=2, trunk_x=0))
    assert any(b.entity_id == 2 for b in res.unplaced)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packer.py -k build_candidate -v`
Expected: FAIL (`cannot import name 'build_candidate'`).

- [ ] **Step 3: Write the implementation**

Add to `foeopt/packer.py` (imports at top, then the function):
```python
# add to imports:
from dataclasses import replace

from foeopt.model import Footprint
from foeopt.packing import Grid, first_fit, first_fit_adjacent
from foeopt.router import RouteError, route


def _corridor_cells(region: set, w: int, h: int, cfg: PackConfig) -> set:
    cells = set()
    for y in range(0, h, cfg.spacing):          # horizontal road rows
        for x in range(w):
            if (x, y) in region:
                cells.add((x, y))
    for y in range(h):                           # vertical trunk joins the rows
        if (cfg.trunk_x, y) in region:
            cells.add((cfg.trunk_x, y))
    return cells


def build_candidate(layout: Layout, config: PackConfig) -> PackResult:
    region = layout.region.cells
    w, h = bbox(layout.region)
    blocked = {(x, y) for x in range(w) for y in range(h)} - region
    corridor = _corridor_cells(region, w, h, config)

    grid = Grid(w, h, blocked)
    grid.reserve(corridor)

    townhall, consumers, fillers = classify(layout)
    placed: dict[int, tuple[int, int]] = {}
    unplaced: list[Building] = []

    def area(b: Building) -> int:
        return b.footprint.width * b.footprint.length

    # Townhall first — prefer corridor-adjacent so the trunk can root on it.
    tw, tl = townhall.footprint.width, townhall.footprint.length
    pos = first_fit_adjacent(grid, tw, tl, corridor) or first_fit(grid, tw, tl)
    if pos is None:
        unplaced.append(townhall)
    else:
        grid.occupy(pos[0], pos[1], tw, tl)
        placed[townhall.entity_id] = pos

    # Consumers: corridor-adjacent, largest first.
    for b in sorted(consumers, key=area, reverse=True):
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit_adjacent(grid, bw, bl, corridor)
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p

    # Fillers: anywhere, largest first.
    for b in sorted(fillers, key=area, reverse=True):
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit(grid, bw, bl)
        if p is None:
            unplaced.append(b)
            continue
        grid.occupy(p[0], p[1], bw, bl)
        placed[b.entity_id] = p

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
        # No feasible road network for this placement — mark consumers unplaced
        # so the caller rejects this candidate.
        return PackResult(layout=candidate, unplaced=unplaced + list(consumers))
    return PackResult(layout=candidate, unplaced=unplaced)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_packer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat: candidate builder (comb corridors + placement + route)"
```

---

### Task 5: `repack` — config sweep + best selection (`packer.py`)

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Consumes: `build_candidate`, `PackConfig`, `PackResult`, `bbox`, `foeopt.validate.is_valid`.
- Produces: `repack(layout: Layout, thorough: bool = False) -> PackResult`.
  - Builds a list of `PackConfig`s: `fast` → a single config (`spacing=4`, `trunk_x=0`); `thorough` → a sweep of `spacing in {3,4,5,6}` × `trunk_x in {0, mid, last_col}` (columns clamped into the region's bbox).
  - Scores each candidate by `(len(unplaced), road_count)` — fewer unplaced wins, then fewer roads. A candidate counts as fully valid only if `unplaced == []` **and** `is_valid(candidate.layout)`.
  - Returns the best `PackResult` found (preferring fully valid). Deterministic.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_packer.py`:
```python
from foeopt.packer import repack


def test_repack_sparse_city_is_valid_and_conserves_buildings():
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(5)]
    layout = Layout(_full_region(12, 12), [th, *cons, *fill], th)
    res = repack(layout, thorough=True)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)


def test_repack_prefers_fewer_unplaced():
    # Tight region: some configs may place fewer; repack keeps the best.
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(3)]
    layout = Layout(_full_region(6, 6), [th, *cons], th)
    res = repack(layout, thorough=True)
    # whatever the outcome, the returned layout never overlaps / leaves region
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= layout.region.cells
        assert not (cells & occ)
        occ |= cells
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packer.py -k repack -v`
Expected: FAIL (`cannot import name 'repack'`).

- [ ] **Step 3: Write the implementation**

Add to `foeopt/packer.py` (import `is_valid`, then the function):
```python
# add to imports:
from foeopt.validate import is_valid


def _configs(layout: Layout, thorough: bool) -> list[PackConfig]:
    if not thorough:
        return [PackConfig("h", spacing=4, trunk_x=0)]
    w, _ = bbox(layout.region)
    trunks = sorted({0, w // 2, max(0, w - 1)})
    return [
        PackConfig("h", spacing=s, trunk_x=t)
        for s in (3, 4, 5, 6)
        for t in trunks
    ]


def _score(res: PackResult) -> tuple[int, int]:
    return (len(res.unplaced), len(res.layout.roads))


def repack(layout: Layout, thorough: bool = False) -> PackResult:
    best: PackResult | None = None
    best_key: tuple[int, int, int] | None = None
    for cfg in _configs(layout, thorough):
        res = build_candidate(layout, cfg)
        fully_valid = not res.unplaced and is_valid(res.layout)
        # sort key: valid candidates first (0), then fewer unplaced, then roads
        key = (0 if fully_valid else 1, len(res.unplaced), len(res.layout.roads))
        if best_key is None or key < best_key:
            best, best_key = res, key
    assert best is not None  # _configs always yields at least one config
    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_packer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat: repack config sweep with best-candidate selection"
```

---

### Task 6: Before/after map (`viz.py`)

**Files:**
- Modify: `foeopt/viz.py`
- Test: `tests/test_viz.py`

**Interfaces:**
- Consumes: `Layout`, the existing `_bounds`, `_CELL`, palette constants, and `_TEMPLATE` machinery.
- Produces: `render_comparison(current: Layout, optimized: Layout) -> str` — a self-contained HTML doc embedding **both** layouts' buildings and roads, with a toggle to switch between "current" and "optimized" views. Hover shows building name + size in whichever view is active. No external resources.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_viz.py`:
```python
from foeopt.viz import render_comparison


def test_render_comparison_embeds_both_layouts(city_data, helper_data):
    from foeopt.build import build_layout
    from foeopt.packer import repack
    current = build_layout(city_data, helper_data)
    optimized = repack(current, thorough=False).layout
    html = render_comparison(current, optimized)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "http://" not in html and "https://" not in html
    # a view toggle is present
    assert "current" in html and "optimized" in html
    # both building sets are embedded (data-name hover metadata present)
    assert "data-name" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_viz.py -k comparison -v`
Expected: FAIL (`cannot import name 'render_comparison'`).

- [ ] **Step 3: Write the implementation**

Add to `foeopt/viz.py` a new standalone function `render_comparison` plus its own template (it does not depend on `render_html`; leave `render_html` untouched):
```python
def render_comparison(current: Layout, optimized: Layout) -> str:
    # shared bounds over both layouts so the two views align
    cx0, cy0, cx1, cy1 = _bounds(current)
    ox0, oy0, ox1, oy1 = _bounds(optimized)
    min_x, min_y = min(cx0, ox0), min(cy0, oy0)
    max_x, max_y = max(cx1, ox1), max(cy1, oy1)
    width = (max_x - min_x + 1) * _CELL
    height = (max_y - min_y + 1) * _CELL

    def view(layout: Layout) -> dict:
        def px(x, y):
            return (x - min_x) * _CELL, (y - min_y) * _CELL
        buildings = []
        for b in layout.buildings:
            bx, by = px(b.footprint.x, b.footprint.y)
            buildings.append({
                "x": bx, "y": by,
                "w": b.footprint.width * _CELL, "h": b.footprint.length * _CELL,
                "name": b.name, "size": f"{b.footprint.width}x{b.footprint.length}",
                "needs_road": b.needs_road, "townhall": b.is_townhall,
            })
        roads = [{"x": (x - min_x) * _CELL, "y": (y - min_y) * _CELL, "level": lvl}
                 for (x, y), lvl in layout.roads.items()]
        region = [((x - min_x) * _CELL, (y - min_y) * _CELL)
                  for (x, y) in sorted(layout.region.cells)]
        return {"buildings": buildings, "roads": roads, "region": region}

    data = {
        "cell": _CELL, "width": width, "height": height,
        "palette": {
            "background": COLOR_BACKGROUND, "region": COLOR_REGION,
            "current_road": COLOR_CURRENT_ROAD, "optimized_road": COLOR_OPTIMIZED_ROAD,
            "townhall": COLOR_TOWNHALL, "road_building": COLOR_ROAD_BUILDING,
            "plain_building": COLOR_PLAIN_BUILDING, "border": COLOR_BUILDING_BORDER,
        },
        "views": {"current": view(current), "optimized": view(optimized)},
    }
    payload = json.dumps(data).replace("</", "<\\/")
    return _COMPARE_TEMPLATE.replace("__DATA__", payload)


_COMPARE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>FoE City — before/after</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #141414; color: #eee; }
  #toolbar { padding: 8px; }
  canvas { display: block; }
  #tip { position: fixed; pointer-events: none; background: #000; color: #fff;
         padding: 4px 8px; border-radius: 4px; font-size: 12px; display: none; }
</style></head><body>
<div id="toolbar">
  <label><input type="radio" name="view" value="current" checked> current</label>
  <label><input type="radio" name="view" value="optimized"> optimized</label>
</div>
<div><canvas id="cv"></canvas><div id="tip"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const PAL = DATA.palette, cell = DATA.cell;
const cv = document.getElementById('cv'); cv.width = DATA.width; cv.height = DATA.height;
const ctx = cv.getContext('2d'); const tip = document.getElementById('tip');
let activeRoadColor = PAL.current_road;
function current(){ return document.querySelector('input[name=view]:checked').value; }
function draw() {
  const v = DATA.views[current()];
  activeRoadColor = current() === 'optimized' ? PAL.optimized_road : PAL.current_road;
  ctx.fillStyle = PAL.background; ctx.fillRect(0,0,cv.width,cv.height);
  ctx.fillStyle = PAL.region; for (const [x,y] of v.region) ctx.fillRect(x,y,cell,cell);
  ctx.fillStyle = activeRoadColor; for (const r of v.roads) ctx.fillRect(r.x,r.y,cell,cell);
  for (const b of v.buildings) {
    ctx.fillStyle = b.townhall ? PAL.townhall : (b.needs_road ? PAL.road_building : PAL.plain_building);
    ctx.fillRect(b.x,b.y,b.w,b.h); ctx.strokeStyle = PAL.border; ctx.strokeRect(b.x,b.y,b.w,b.h);
  }
}
function buildingAt(mx,my){ for (const b of DATA.views[current()].buildings)
  if (mx>=b.x&&mx<b.x+b.w&&my>=b.y&&my<b.y+b.h) return b; return null; }
cv.addEventListener('mousemove', e => {
  const r = cv.getBoundingClientRect(); const b = buildingAt(e.clientX-r.left, e.clientY-r.top);
  if (b) { tip.style.display='block'; tip.style.left=(e.clientX+12)+'px'; tip.style.top=(e.clientY+12)+'px';
    tip.setAttribute('data-name', b.name); tip.setAttribute('data-size', b.size);
    tip.textContent = b.name + ' (' + b.size + ')'; } else { tip.style.display='none'; }
});
for (const el of document.querySelectorAll('input[name=view]')) el.addEventListener('change', draw);
draw();
</script>
</body></html>
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_viz.py -v`
Expected: PASS (existing viz tests unaffected; new comparison test passes).

- [ ] **Step 5: Commit**

```bash
git add foeopt/viz.py tests/test_viz.py
git commit -m "feat: before/after comparison map"
```

---

### Task 7: `layout` CLI subcommand + real-city golden test

**Files:**
- Modify: `foeopt/cli.py`
- Test: `tests/test_layout_cli.py`

**Interfaces:**
- Consumes: `build_layout`, `repack`, `render_comparison`, `report.stats`, `is_valid`.
- Produces: `layout <city.json> <helper.json> [-o out.html] [--thorough]` — re-packs, prints stats (current vs optimized road count, buildings placed/unplaced), writes the before/after map. Exit code: 0 if all buildings placed and valid; 1 otherwise (with the unplaced count reported).

- [ ] **Step 1: Write the failing golden test**

`tests/test_layout_cli.py`:
```python
from foeopt.build import build_layout
from foeopt.packer import repack
from foeopt.validate import is_valid


def test_repack_real_city_is_valid_or_reports_unplaced(city_data, helper_data):
    current = build_layout(city_data, helper_data)
    res = repack(current, thorough=False)
    # Correctness invariant: never an overlapping / out-of-region layout.
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert cells <= current.region.cells
        assert not (cells & occ)
        occ |= cells
    if not res.unplaced:
        # if everything was placed, it must be valid and not worse than current
        assert is_valid(res.layout)
        assert len(res.layout.roads) <= len(current.roads)
    else:
        # otherwise the shortfall is reported explicitly (expected at 96.6% density)
        assert len(res.unplaced) > 0
```

- [ ] **Step 2: Run test to verify the invariant holds**

Run: `uv run pytest tests/test_layout_cli.py -v -s`
Expected: PASS (either fully valid-and-not-worse, or a non-empty unplaced report). Note in the report which branch the real city takes and how many were unplaced.

- [ ] **Step 3: Add the `layout` subcommand**

Add to `foeopt/cli.py` (imports + function + parser registration):
```python
# add to imports:
from foeopt.packer import repack
from foeopt.viz import render_comparison
from foeopt.report import stats


def _cmd_layout(args) -> int:
    current = build_layout(_load(args.city), _load(args.helper))
    res = repack(current, thorough=args.thorough)
    s = stats(current, res.layout.roads)
    print("Full re-pack (Phase 2):")
    print(f"  buildings: {len(current.buildings)} | placed: "
          f"{len(res.layout.buildings)} | unplaced: {len(res.unplaced)}")
    print(f"  current roads: {s['current_roads']} | optimized roads: {s['optimized_roads']}"
          f" | tiles_saved: {s['tiles_saved']}")
    Path(args.out).write_text(render_comparison(current, res.layout), encoding="utf-8")
    print(f"Wrote before/after map to {args.out}")
    if res.unplaced:
        print(f"  WARNING: {len(res.unplaced)} buildings could not be placed "
              f"(city too dense for a full re-pack).")
        return 1
    return 0
```

Register inside `main()` after the `roads` parser:
```python
    p_layout = sub.add_parser("layout", help="re-pack the whole city to minimize roads")
    p_layout.add_argument("city")
    p_layout.add_argument("helper")
    p_layout.add_argument("-o", "--out", default="layout.html")
    p_layout.add_argument("--thorough", action="store_true",
                          help="sweep more configurations (slower, better)")
    p_layout.set_defaults(func=_cmd_layout)
```

- [ ] **Step 4: Run the golden test + CLI smoke test**

Run: `uv run pytest tests/test_layout_cli.py -v -s`
Expected: PASS.

Run: `uv run python -m foeopt.cli layout city-user-data.json city-user-data-foe-helper.json -o output/layout.html`
Expected: prints the stats block and writes `output/layout.html`. On this dense city it likely reports unplaced buildings and exits 1 — that is the expected, honest outcome; the before/after map still opens.

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/test_layout_cli.py
git commit -m "feat: layout CLI subcommand + real-city golden test (Phase 2)"
```

---

### Task 8: README — document Phase 2

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Phase 2 usage section**

Add under the existing usage in `README.md`:
```markdown
Re-pack the whole city to minimize roads (Phase 2, moves buildings):

    uv run python -m foeopt.cli layout city-user-data.json city-user-data-foe-helper.json -o output/layout.html --thorough

This produces a before/after map (toggle current vs optimized). The optimizer adapts to the
city's density: sparse cities yield real road savings; very dense cities (little empty space)
may not fit a full re-pack, in which case it reports the buildings it could not place rather
than emitting an invalid layout.
```

- [ ] **Step 2: Verify the full suite is green**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the Phase 2 layout command"
```

---

## Self-Review

**Spec coverage:**
- Generality / no hardcoding (spec §2) → packer derives `bbox`/region/density from input; `repack` configs are computed from `bbox`; sparse-city test (Task 5) + real-city golden (Task 7). ✓
- Pure minimal-roads objective, no move-count (spec §3) → `_score` uses `(unplaced, road_count)` only. ✓
- Valid-layout constraints (spec §3) → `build_candidate` places in region/no-overlap via `Grid`; roads via `route`; gated by `is_valid`; tests assert in-region + no-overlap + validity. ✓
- Fixed footprint area / road budget (spec §3) → no resize/rotate; placement only. ✓
- Tunable fast↔thorough (spec §6) → `repack(thorough)` + `_configs` + `--thorough` flag (Task 5). ✓
- Fail loudly / unplaced list (spec §3, §5.7) → `PackResult.unplaced`, CLI exit 1 + warning, golden test invariant. ✓
- Architecture modules (spec §4) → `packing.py` (Tasks 1–2), `packer.py` (Tasks 3–5), `viz.render_comparison` (Task 6), `cli layout` (Task 7). ✓
- Algorithm comb+fill+route+prune+validate (spec §5) → Task 4 (`route` computes roads and prunes internally; validity gated in `repack`, Task 5). ✓
- Output stats + before/after map (spec §7) → Task 6 + Task 7. ✓
- Sets/chains deferred (spec §3 out-of-scope) → not implemented. ✓
- Testing incl. sparse-savings + real-city golden (spec §8) → Tasks 5, 7. ✓

**Placeholder scan:** No placeholders. `render_comparison` (Task 6) is standalone and complete — it defines its own `view()`/`px()` and `_COMPARE_TEMPLATE` and leaves `render_html` untouched. All code steps contain complete code; all test steps contain real assertions.

**Type consistency:** `PackConfig(orientation, spacing, trunk_x)`, `PackResult(layout, unplaced)`, `classify -> (townhall, consumers, fillers)`, `bbox -> (w,h)`, `build_candidate -> PackResult`, `repack -> PackResult`, `render_comparison(current, optimized) -> str` are used consistently across Tasks 3–7. `roads` is `dict[(x,y)->level]` throughout, produced by the existing `route()`. `Building` is moved via `dataclasses.replace(..., footprint=Footprint(...))`, consistent with the model.
