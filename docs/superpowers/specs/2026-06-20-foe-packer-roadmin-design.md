# FoE City Layout Optimizer — Packer Road Minimization Design

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the multi-start packer + post-route gap-fill (both merged).

## 1. Purpose

Let the `layout` engine minimize roads, not just placement. The multi-start `repack` already scores
candidates by `(unplaced, roads)`, but a place-everything **early-exit** stops the search at the first
fully-placed trial, capping road minimization. Removing it lets the budget hunt for lower-road
layouts among those that place all buildings.

## 2. Motivation (measured)

On DarkZig the gap-fill makes the **first** trial reach 0 unplaced, so the early-exit fires at that
trial's road count (seed 0: **199 roads**) and never uses the rest of the budget. The headroom is
real: other seeds reach 180–217, and letting seed 0 run the full 30s budget (no early-exit) reaches
**(0 unplaced, 169 roads)** — better than `improve --anneal`'s 191, because a from-scratch clustered
placement routes tighter than nudging the player's layout. The road estimate (theoretical floor) is
114; larger budgets should push further toward it.

## 3. Scope

- Remove the place-everything early-exit from `repack` (`foeopt/packer.py`); update its docstring.
- No other production change: `PackConfig`, `build_candidate`, the gap-fill pass, the `layout` CLI, the
  budget resolution, and the `(len(unplaced), len(roads))` scoring all stay exactly as they are.
- `improve`/`roads`/`view`/`anneal` untouched.

## 4. Change

In `repack`'s trial loop, delete:
```python
        if best_key[0] == 0:            # all placed: can't improve on placement
            break
```
The loop already keeps the best candidate by `(len(unplaced), len(roads))` (fewest unplaced first,
then fewest roads, ties keep the earlier result) and is bounded by the wall-clock budget and the
`while True` body-before-deadline structure (still guarantees ≥1 trial). With the early-exit gone, the
search spends the full budget and returns the lowest-road layout it found among the best-placement
tier. Update the docstring to drop the "Early-exits when a trial places everything" sentence.

## 5. Behavior

- **Dense cities:** roads minimized within the budget. DarkZig: 199 → ~169 at 30s (0 unplaced, valid);
  larger `--budget` trends lower toward the 114 estimate.
- **Sparse cities:** now use the full budget instead of returning in <1s. This matches `improve`
  (which never early-exits) and the chosen `layout` contract (30s default / 120s `--thorough` /
  `--budget N`). The returned result is still the optimum found; only the wall-clock changes.
- **Determinism unchanged:** deterministic given `seed` and the number of trials completed.

## 6. Testing (TDD)

- **Replace** `test_repack_early_exit_on_sparse` (which asserted `trials == 1`, no longer true) with
  `test_repack_sparse_places_all`: a sparse synthetic city at a small budget returns `unplaced == []`
  and `is_valid(res.layout)`.
- **Determinism** (`budget_seconds=0.0` → exactly 1 trial) stays green and unaffected.
- **No-worse-than-single-pass** stays green.
- **Existing packer / conservation / real-city tests** stay green.
- **Recorded DarkZig measurement** (not a fast suite test): `repack` at 30s and 120s — roads (expect
  ~169 at 30s, down from 199), 0 unplaced, valid.

## 7. Risk / limitations

- One line removed; minimal risk. The only behavioral cost is sparse cities using the full budget —
  the already-chosen `layout` contract, shortenable with `--budget N`.
- This minimizes roads for the *placement the packer finds*; it does not change `route()` (already
  optimal per placement). Reaching the 114 estimate would require tighter road-needing clustering — out
  of scope here.
