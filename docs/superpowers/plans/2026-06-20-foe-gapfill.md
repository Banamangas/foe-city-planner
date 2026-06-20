# FoE Optimizer — Post-Route Gap-Fill Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Place leftover fillers into the cells that `route()` frees, clearing the last unplaced decorations in the `layout` engine (DarkZig 6 → ~0).

**Architecture:** Add one pass at the end of `build_candidate` (after `route()` succeeds): compute the post-route free cells (`region − occupied − roads`) and `first_fit` the still-unplaced **fillers** into them, moving any that fit into the layout. Road-needing buildings are never gap-filled.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Touches `foeopt/packer.py` and `tests/test_packer.py`.

## Global Constraints

- Python **3.12**; standard library only. Test runner: `uv run pytest`.
- Only **fillers** (`needs_road == False`) are gap-filled; road-needing buildings stay road-adjacent (unplaced ones remain unplaced). The `RouteError` path is unchanged (gap-fill runs only after `route()` succeeds).
- Pack only into confirmed-free cells (`region − occupied − roads`) → no overlap, roads untouched, `is_valid` preserved, `route()` not re-run.
- **Conservation:** a gap-filled building moves from `unplaced` into the layout exactly once. `placed ∪ unplaced == all input buildings`, disjoint.
- **Determinism:** gap-fill ordering uses the trial's existing seeded `rng`; `build_candidate` stays deterministic given its `PackConfig`.
- Reuse `Grid`, `first_fit` (`foeopt.packing`), `dataclasses.replace`, `Footprint`.

---

### Task 1: Post-route gap-fill in `build_candidate`

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Consumes: `Grid`, `first_fit`, `route`, `Footprint`, `replace`, the trial `rng`, and locals `region`, `w`, `h`, `area` already present in `build_candidate`.
- Produces: `build_candidate` returns a `PackResult` whose `unplaced` no longer contains any filler that fits in the post-route free cells. Signature unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_packer.py`:
```python
def test_gapfill_places_filler_freed_by_routing():
    # 3x2 region, 2x2 townhall, two 1x1 fillers, no consumers.
    # The Townhall-border seed cell (2,0) is reserved during the main filler
    # pass, so only (2,1) is free then -> one filler is unplaced. With no
    # consumers, route() returns no roads, freeing the seed (2,0); the gap-fill
    # pass must place the leftover filler there.
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    f1 = _b(2, 0, 0, 1, 1, needs=False)
    f2 = _b(3, 0, 0, 1, 1, needs=False)
    layout = Layout(_full_region(3, 2), [th, f1, f2], th)
    res = build_candidate(layout, PackConfig("bl", 0))
    assert res.unplaced == []
    assert len(res.layout.buildings) == 3
    occ = set()
    for b in res.layout.buildings:
        cells = b.footprint.cells()
        assert not (cells & occ)          # no overlap
        occ |= cells


def test_gapfill_skips_road_needing_buildings():
    # Disconnected region: a 2x2 block (for the townhall) plus an isolated cell
    # at (5,5). The townhall has no in-region border cell, so no road seeds and
    # the road-needing building cannot attach -> it is unplaced. The isolated
    # (5,5) is free post-route, but gap-fill must NOT place a road-needing
    # building there (it would have no road).
    from foeopt.packer import build_candidate, PackConfig
    region = Region(frozenset({(0, 0), (1, 0), (0, 1), (1, 1), (5, 5)}))
    th = _b(1, 0, 0, 2, 2, th=True)
    consumer = _b(2, 0, 0, 1, 1, needs=True)
    layout = Layout(region, [th, consumer], th)
    res = build_candidate(layout, PackConfig("bl", 0))
    assert 2 in {b.entity_id for b in res.unplaced}        # road-needing stays unplaced
    assert 2 not in {b.entity_id for b in res.layout.buildings}
```

- [ ] **Step 2: Run tests to verify the first fails**

Run: `uv run pytest tests/test_packer.py -k gapfill -v`
Expected: `test_gapfill_places_filler_freed_by_routing` FAILS (the leftover filler is unplaced — `res.unplaced` is not empty). `test_gapfill_skips_road_needing_buildings` already passes (guards the skip).

- [ ] **Step 3: Implement the gap-fill pass**

In `foeopt/packer.py`, in `build_candidate`, replace the final success return:
```python
    return PackResult(layout=candidate, unplaced=unplaced)
```
with the gap-fill pass:
```python
    # Post-route gap-fill: routing prunes the reserved corridor down to the
    # minimal roads, freeing reserved-but-unused cells. Offer them to the
    # still-unplaced fillers (road-needing buildings must stay road-adjacent and
    # are never gap-filled). Roads are unchanged, so no re-route is needed.
    occupied: set[tuple[int, int]] = set()
    for b in candidate.buildings:
        occupied |= b.footprint.cells()
    free = region - occupied - set(candidate.roads)
    gap_grid = Grid(w, h, {(x, y) for x in range(w) for y in range(h)} - free)
    still_unplaced: list[Building] = []
    for b in sorted(unplaced, key=lambda b: (-area(b), rng.random())):
        if b.needs_road:
            still_unplaced.append(b)
            continue
        bw, bl = b.footprint.width, b.footprint.length
        p = first_fit(gap_grid, bw, bl)
        if p is None:
            still_unplaced.append(b)
            continue
        gap_grid.occupy(p[0], p[1], bw, bl)
        candidate.buildings.append(
            replace(b, footprint=Footprint(p[0], p[1], bw, bl))
        )
    return PackResult(layout=candidate, unplaced=still_unplaced)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packer.py -k gapfill -v`
Expected: both PASS. Then the full packer suite + whole suite:
`uv run pytest tests/test_packer.py -v` then `uv run pytest -q` — all green (the existing determinism, conservation, sparse/tight, and real-city tests stay green).

- [ ] **Step 5: Record the DarkZig outcome (not a suite test)**

Run:
```bash
uv run python -c "
from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.validate import is_valid
L = load_layout('darkzig.json')
res = repack(L, budget_seconds=30, seed=0)
print('placed', len(res.layout.buildings), '/', len(L.buildings),
      '| unplaced', len(res.unplaced),
      '| roads', len(res.layout.roads), '| estimate', road_estimate(L),
      '| valid', is_valid(res.layout) if not res.unplaced else 'partial')
"
```
Expected: **unplaced ~0** (down from 6), roads ≈ 169, valid. **Record in the report.**

- [ ] **Step 6: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat(packer): post-route gap-fill places leftover fillers in freed cells"
```

---

## Self-Review

**Spec coverage:**
- Gap-fill pass after `route()` success: free = `region − occupied − roads`, `first_fit` fillers, move into layout (spec §3/§4) → Task 1 Step 3. ✓
- Only fillers; road-needing skipped; RouteError path unchanged (spec §3) → the `if b.needs_road` guard + placement before the `except RouteError` block is untouched. ✓
- Invariants: no overlap (packs into free cells only), roads unchanged / no re-route, conservation, determinism (seeded rng) (spec §5) → Task 1; covered by the overlap assertion, the skip test, and existing determinism/conservation tests. ✓
- Per-trial (inside build_candidate) so multi-start scoring reflects it (spec §6) → implemented in build_candidate. ✓
- Testing: places-freed-filler (RED→GREEN), skips-road-needing (guard), existing tests green, recorded DarkZig (spec §7) → Steps 1–5. ✓

**Placeholder scan:** No placeholders; the implementation and both tests are complete. Step 5 is an explicit recorded measurement with an expected outcome.

**Type consistency:** `build_candidate(layout, config) -> PackResult` unchanged. `candidate.buildings` is the `new_buildings` list (appendable); `replace(b, footprint=Footprint(...))` matches the existing move pattern in the same function. `region`, `w`, `h`, `area`, `rng` are all in scope at the return point. `Grid`/`first_fit` already imported. `b.footprint.cells()` is the existing Footprint API.
