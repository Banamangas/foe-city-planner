# FoE Optimizer — Short-Side-Facing Attachment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower `layout` road counts by attaching road-needing buildings short-side-to-road (DarkZig 169 → ~135–145, 0 unplaced).

**Architecture:** Add `first_fit_adjacent_short` to `foeopt/packing.py` (bottom-left scan returning the first fit whose *short-side* border touches the road targets; `None` for squares / no short-side spot). Use it with a fallback to `first_fit_adjacent` in `build_candidate`'s road-needing attachment.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Touches `foeopt/packing.py`, `foeopt/packer.py`, and their tests.

## Global Constraints

- Python **3.12**; standard library only. Test runner: `uv run pytest`.
- Short-side geometry for `w × l` at `(x, y)`: if `w < l` → top/bottom edges `{(x+i, y-1)} ∪ {(x+i, y+l)}` for `i in range(w)`; if `l < w` → left/right edges `{(x-1, y+j)} ∪ {(x+w, y+j)}` for `j in range(l)`; if `w == l` → no short side.
- Placement must not regress: attachment falls back to `first_fit_adjacent` when no short-side spot exists (incl. squares), so any building that placed before still places. The multi-start `(unplaced, roads)` scoring is unchanged.
- Determinism preserved (bottom-left scan). No change to fillers, gap-fill, routing, `repack`, `PackConfig`, or the CLI.

---

### Task 1: `first_fit_adjacent_short` + short-side attachment

**Files:**
- Modify: `foeopt/packing.py`, `foeopt/packer.py`
- Test: `tests/test_packing.py`, `tests/test_packer.py`

**Interfaces:**
- Produces: `first_fit_adjacent_short(grid: Grid, w: int, l: int, targets: set) -> tuple[int,int] | None` and `_short_border_cells(x, y, w, l) -> set`. Used in `build_candidate` as `first_fit_adjacent_short(...) or first_fit_adjacent(...)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_packing.py` (it already imports from `foeopt.packing` and constructs `Grid`):
```python
def test_first_fit_adjacent_short_prefers_short_side():
    from foeopt.packing import Grid, first_fit_adjacent, first_fit_adjacent_short
    grid = Grid(4, 8, set())
    targets = {(2, 0), (2, 1)}          # a vertical pair (a long-edge for a 2x4 at origin)
    # plain takes the earliest touching spot — (0,0), where the road meets the LONG edge
    assert first_fit_adjacent(grid, 2, 4, targets) == (0, 0)
    # short-side variant skips it and returns the spot whose SHORT (top) edge touches
    assert first_fit_adjacent_short(grid, 2, 4, targets) == (1, 1)


def test_first_fit_adjacent_short_square_returns_none():
    from foeopt.packing import Grid, first_fit_adjacent_short
    grid = Grid(6, 6, set())
    assert first_fit_adjacent_short(grid, 2, 2, {(2, 0), (0, 2)}) is None


def test_first_fit_adjacent_short_none_when_no_short_spot():
    from foeopt.packing import Grid, first_fit_adjacent_short
    grid = Grid(4, 8, set())
    assert first_fit_adjacent_short(grid, 2, 4, set()) is None        # no targets
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packing.py -k short -v`
Expected: FAIL (`cannot import name 'first_fit_adjacent_short'`).

- [ ] **Step 3: Implement the helper**

In `foeopt/packing.py`, after `first_fit_adjacent`, add:
```python
def _short_border_cells(x: int, y: int, w: int, l: int) -> set[tuple[int, int]]:
    """Border cells along the short-side edges (perpendicular to the long axis).
    Empty for a square — no preferred side."""
    if w < l:        # taller than wide: short edges are top and bottom (width w)
        return ({(x + i, y - 1) for i in range(w)}
                | {(x + i, y + l) for i in range(w)})
    if l < w:        # wider than tall: short edges are left and right (height l)
        return ({(x - 1, y + j) for j in range(l)}
                | {(x + w, y + j) for j in range(l)})
    return set()


def first_fit_adjacent_short(
    grid: Grid, w: int, l: int, targets: set[tuple[int, int]]
) -> tuple[int, int] | None:
    """Like first_fit_adjacent, but only accepts a position whose SHORT-side
    border touches `targets`. Returns None for a square or when no such spot
    exists (the caller should then fall back to first_fit_adjacent)."""
    if w == l:
        return None
    for y in range(grid.height):
        for x in range(grid.width):
            if grid.fits(x, y, w, l) and (_short_border_cells(x, y, w, l) & targets):
                return (x, y)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packing.py -k short -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire it into `build_candidate`**

In `foeopt/packer.py`: add `first_fit_adjacent_short` to the `from foeopt.packing import ...` line. In `build_candidate`'s road-needing attachment (currently `p = first_fit_adjacent(grid, bw, bl, road)`), replace with:
```python
        p = (first_fit_adjacent_short(grid, bw, bl, road)
             or first_fit_adjacent(grid, bw, bl, road))
```

- [ ] **Step 6: Run the suite**

Run: `uv run pytest -q`
Expected: all green (existing packer/determinism/conservation/real-city tests unaffected — placement still succeeds via the fallback).

- [ ] **Step 7: Record the DarkZig outcome (not a suite test)**

Run:
```bash
uv run python -c "
from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.validate import is_valid
L = load_layout('darkzig.json')
res = repack(L, budget_seconds=30, seed=0)
lay = res.layout
rn = [b for b in lay.buildings if b.needs_road]
adj = sum(1 for b in rn for c in b.footprint.border_cells() if c in set(lay.roads))
print('unplaced', len(res.unplaced), '| roads', len(lay.roads),
      '(was 169, est', road_estimate(L), ') | bldg-road adjacencies', adj,
      '(was 302, ideal 228) | valid', is_valid(lay))
"
```
Expected: 0 unplaced, **roads < 169**, adjacencies closer to 228, valid. **Record in the report.** (If roads did not drop, record that honestly — the multi-start guarantees it is never worse, so this is informational, not a failure.)

- [ ] **Step 8: Commit**

```bash
git add foeopt/packing.py foeopt/packer.py tests/test_packing.py tests/test_packer.py
git commit -m "feat(packer): attach road-needing buildings short-side-to-road"
```

---

## Self-Review

**Spec coverage:**
- `first_fit_adjacent_short` + `_short_border_cells` with the §4 geometry (spec §4/§5) → Task 1 Steps 1–4. ✓
- Fallback wiring in `build_candidate` (spec §6) → Step 5. ✓
- Placement-not-regressed / determinism / validity preserved (spec §7) → fallback + bottom-left scan; verified by Step 6 suite + Step 7 (0 unplaced). ✓
- Tests: short-side unit tests, square → None, suite green, recorded DarkZig with adjacency metric (spec §8) → Steps 1–7. ✓

**Placeholder scan:** No placeholders. The discriminating test (plain → `(0,0)` long-side, short → `(1,1)` short-side) asserts real, verified geometry. Step 7 is an explicit recorded measurement with an honest "never worse" note.

**Type consistency:** `first_fit_adjacent_short(grid, w, l, targets) -> tuple[int,int] | None` matches `first_fit_adjacent`'s shape; both used as `short(...) or plain(...)` in `build_candidate`. `_short_border_cells` returns `set[tuple[int,int]]` intersected with `targets` (also a set). `Grid`/`first_fit_adjacent` already imported in `packer.py`; the new name is added to that import.
