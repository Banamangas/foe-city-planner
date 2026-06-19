# FoE City Layout Optimizer — Articulation-Aware Prune Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the border-cache prune speedup and true-objective annealing (both merged).

## 1. Purpose

Make the road-network prune (`router._prune`) ~6× faster by replacing its per-trial-removal
connectivity BFS (O(roads²) per route) with a single Tarjan articulation-point pass
(O(roads) per pruning round). This speeds up every engine (`view`/`roads`/`improve`/`layout`)
and, by giving simulated annealing ~7× more iterations in the same budget, unlocks a materially
better result.

## 2. Motivation (measured)

`route()` is ~59ms on DarkZig; profiling shows **~94% is `_prune`**, dominated by the
connectivity BFS run for every trial cell removal (~1,000 BFS sweeps over ~236 cells). The road
network is ~94% degree-2 corridor cells (only 3–4% leaves), so leaf-awareness is a dead end —
but a **single articulation-point pass identifies all the non-removable corridor cells at once**.
A verified prototype produced the **identical** road cells as the current prune (DarkZig 236,
sample 142), cutting the prune to ~4ms (route ≈59ms → ≈10ms). With the faster route, a 600s
true-objective SA ran 302,502 iterations (vs 42,009) and reached **DarkZig 250 → 194 (−22.4%)**,
beating the prior 211.

## 3. Scope

- Add `_articulation_points(roads, th_border)` to `foeopt/router.py`.
- Rewrite `_prune` to use it.
- No change to `route()`'s signature or output, to `validate`, or to any public API. Pure
  internal speedup.

## 4. Algorithm

`_articulation_points(roads: dict[(x,y),int], th_border: set[(x,y)]) -> set[(x,y)]`:
- Build the undirected graph whose nodes are the road cells, with a **virtual Townhall root**
  node connected to every road cell in `th_border` (and those cells connected back to it).
- Run an **iterative** Tarjan articulation-point search from the virtual root (iterative to
  avoid recursion-depth limits on long corridors).
- Return the set of **road cells** that are articulation points — i.e. removing one would
  disconnect some other road cell from the Townhall. (The virtual root is never returned.)

`_prune(layout, roads)` — per pass:
1. `art = _articulation_points(roads, th_border)`; `connected = connected_road_cells(roads)`,
   each computed **once** for the pass. (`th_border` = the Townhall footprint's border cells;
   road-needing consumers' border cells + required levels are cached once, as today.)
2. Iterate cells in `sorted(roads, reverse=True)` (the current deterministic order). A cell is
   **removable** iff:
   - it is **not** in `art` (removing it keeps every other road connected to the Townhall), and
   - every road-needing consumer whose footprint borders this cell still has **another**
     adjacent road cell that is connected and of level ≥ its requirement.
3. Remove the first removable cell; restart the pass. Stop when a full pass removes nothing.

This reproduces the current prune's accept/reject decision and removal order: degree-2 corridor
cells are articulation points → kept; redundant leaf/cycle cells → removed. The difference is
that all articulation points are found in one O(roads) pass instead of a BFS per candidate.

## 5. Correctness contract — behavior-preserving + guard

The new prune must produce the same result as the current one where it matters, with a safety
net for unproven edge cases (ties/cycles):

- **Existing `tests/test_router.py` small-grid tests stay green** — they pin exact road counts
  on known graphs (straight line = 3, shared corridor ≤ 4, level-2 connector, unreachable →
  `RouteError`), precisely guarding the prune's decisions.
- **Real-city golden counts stay green:** `len(route(darkzig)) == 236`, `len(route(sample)) == 142`.
- **Property test:** the prune's output is always a valid network — every road-needing consumer
  has a connected adjacent road of sufficient level (i.e. `unsatisfied(...) == []`).
- **One-time implementation verification:** during the build, compare the new prune's output to
  the **old** prune's, set-for-set, on both real cities and confirm identical; record this in the
  task report before the old BFS-prune code is removed.
- If a future input ever differs in exact cells, the result must still be **valid** and have a
  road count **≤** the old prune's — never a functional regression.

## 6. Testing (TDD)

- **`_articulation_points` unit tests** (small graphs): a mid-chain cell on a path from the
  Townhall is an articulation point; a leaf is not; a cell on a cycle is not; the virtual root is
  never returned.
- **Prune behavior:** all existing `test_router.py` tests pass unchanged.
- **Property:** for the real cities, `route()`'s output passes `is_valid`/`unsatisfied == []` and
  matches the golden counts (236, 142).
- **Real-city route goldens** (already present): `route(darkzig)` == 236, `route(sample)` == 142.
- A non-suite check (recorded, not a fast test) confirms SA with the faster route reaches a lower
  road count on DarkZig (~194), demonstrating the payoff.

## 7. Out of scope / notes

- This does not change `route()`'s contract or any engine's behavior — only its speed (and,
  downstream, how far SA gets in a fixed budget).
- Further speedups (incremental connectivity across moves) remain a future option but are not
  needed: ~10ms/route is ample for SA.
