# FoE Optimizer — Packer Road Minimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `repack` minimize roads by removing the place-everything early-exit, so the budget is spent finding the lowest-road layout among those that place all buildings (DarkZig 199 → ~169).

**Architecture:** Delete one early-exit branch from `repack`'s trial loop; the loop already keeps the best by `(unplaced, roads)` and is bounded by the wall-clock budget. Update the docstring and swap the now-obsolete early-exit test.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Touches `foeopt/packer.py` and `tests/test_packer.py`.

## Global Constraints

- Python **3.12**; standard library only. Test runner: `uv run pytest`.
- No change to `PackConfig`, `build_candidate`, the gap-fill pass, the CLI, budget resolution, or the `(len(unplaced), len(roads))` scoring.
- The loop still guarantees ≥1 trial (the `while True` body runs before the deadline check) and stays deterministic given `seed` and the number of trials completed.
- Sparse cities now use the full budget (the accepted `layout` contract; `--budget N` shortens it).

---

### Task 1: Remove the early-exit and update its test

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Produces: `repack(layout, *, thorough=False, budget_seconds=None, seed=0) -> PackResult` — unchanged signature; now runs until the budget (no early-exit on full placement), returning the lowest-road best-placement layout it found.

- [ ] **Step 1: Replace the obsolete early-exit test**

In `tests/test_packer.py`, replace `test_repack_early_exit_on_sparse` (it asserts `trials == 1`, which is no longer true) with:
```python
def test_repack_sparse_places_all():
    from foeopt.packer import repack
    from foeopt.validate import is_valid
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(3)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(20, 20), [th, *cons, *fill], th)  # very sparse
    res = repack(layout, budget_seconds=0.3, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(layout.buildings)
```

- [ ] **Step 2: Run the test to verify it passes against current code**

Run: `uv run pytest tests/test_packer.py::test_repack_sparse_places_all -v`
Expected: PASS (a sparse city places all regardless of the early-exit). This is the new guard; the behavioral change is verified by Step 5's DarkZig measurement.

- [ ] **Step 3: Remove the early-exit**

In `foeopt/packer.py`, in `repack`, delete these two lines from the trial loop:
```python
        if best_key[0] == 0:            # all placed: can't improve on placement
            break
```
And update the docstring's last sentence — change:
```python
    best by (fewest unplaced, then fewest roads). Deterministic given `seed` and
    the number of trials completed. Early-exits when a trial places everything."""
```
to:
```python
    best by (fewest unplaced, then fewest roads). Deterministic given `seed` and
    the number of trials completed. Runs until the time budget so it minimizes
    roads among fully-placed layouts (no early-exit on first full placement)."""
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/test_packer.py -v` then `uv run pytest -q`
Expected: all green — the determinism test (`budget_seconds=0.0` → exactly 1 trial: the `while True` body runs once, then the deadline check breaks), the no-worse-than-single-pass test, conservation, and real-city tests are all unaffected.

- [ ] **Step 5: Record the DarkZig road improvement (not a suite test)**

Run:
```bash
uv run python -c "
from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.validate import is_valid
L = load_layout('darkzig.json')
for b in (30.0, 120.0):
    r = repack(L, budget_seconds=b, seed=0)
    print(f'budget={b:.0f}s: trials={r.trials} unplaced={len(r.unplaced)} '
          f'roads={len(r.layout.roads)} (est {road_estimate(L)}) valid={is_valid(r.layout)}')
"
```
Expected: 0 unplaced, **roads ≈ 169 at 30s (down from 199)**, valid; 120s ≤ 30s. **Record in the report.**

- [ ] **Step 6: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat(packer): minimize roads by dropping the place-everything early-exit"
```

---

## Self-Review

**Spec coverage:**
- Remove the early-exit; docstring updated (spec §3/§4) → Task 1 Step 3. ✓
- No change to scoring / build_candidate / gap-fill / CLI (spec §3) → only the two early-exit lines + docstring change. ✓
- ≥1 trial + determinism preserved (spec §4/§5) → `while True` body-before-deadline unchanged; determinism test stays green (Step 4). ✓
- Test swap: `early_exit` → `sparse_places_all` (spec §6) → Task 1 Step 1. ✓
- Recorded DarkZig 199 → ~169 (spec §6) → Step 5. ✓

**Placeholder scan:** No placeholders. Step 5 is an explicit recorded measurement with expected numbers.

**Type consistency:** `repack` signature and `PackResult` unchanged. The deleted lines are the only logic change. The new test uses the existing `_b`/`_full_region`/`Layout`/`is_valid` helpers and the `repack(layout, budget_seconds=..., seed=...)` signature already in use across the file.
