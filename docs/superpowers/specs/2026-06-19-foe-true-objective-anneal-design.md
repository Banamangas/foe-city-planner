# FoE City Layout Optimizer — True-Objective Annealing Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the annealing engine (`foeopt/anneal.py`) and the prune speedup (route ≈60ms), both merged.

## 1. Purpose

Replace the MST-proxy objective in `anneal()` with the **true road count** (`len(route(candidate))`).
The proxy existed only as a workaround for slow routing; with `route()` now ~60ms, annealing on
the real objective is both feasible and strictly better. A prototype reached **DarkZig 250 → 211
roads (−15.6%)**, beating the proxy (231) and hill-climbing (225).

## 2. Motivation

The MST proxy (Manhattan spanning tree over road-needing centroids) decorrelates from the actual
minimal road count on dense real cities, so proxy-annealing plateaus regardless of time (DarkZig
stuck at 231 even at 600s). Annealing directly on `len(route(candidate))` removes that gap. The
prune speedup makes ~42,000 routed evaluations affordable in 600s, enough for simulated annealing
to escape the local optimum where hill-climbing stops.

## 3. Scope

- Rewrite `anneal()` to use the true objective.
- **Delete** the obsolete proxy: `_mst_length`, `_centroid`, `mst_cost`, and their tests (YAGNI —
  strictly inferior, no remaining caller).
- Keep `random_move` (reused) and `OptimizeResult` (from `localsearch`).
- No CLI change: `improve --anneal [--seed N] [--budget S]` already exists and simply gets the
  better engine. Hill-climbing (`optimize`) is unchanged.

## 4. Algorithm

```
best = layout; best_roads = len(layout.roads)              # never-worse anchor (the input)
roads0 = route(layout)                                     # route the input placement (Phase-1 baseline)
state = Layout(layout.region, layout.buildings, layout.townhall, roads0)
cur = len(roads0)
if is_valid(state) and cur < best_roads:
    best, best_roads = state, cur                          # adopt the free routing win, if any
T = _initial_temperature(state, rng)                       # mean |Δroads| of sampled routed moves; fallback 1.0
rng = random.Random(seed)
for _ in range(max_iters):
    if time budget exhausted: break
    cand = random_move(state, rng)                         # validated placement; None -> cool & continue
    try: roads = route(cand)
    except RouteError: cool & continue
    delta = len(roads) - cur
    if delta < 0 or rng.random() < exp(-delta / max(T, _T_FLOOR)):
        state = Layout(cand.region, cand.buildings, cand.townhall, roads)
        cur = len(roads)
        if is_valid(state) and cur < best_roads:
            best, best_roads = state, cur                  # confirmed improvement
    T = max(T * _COOLING, _T_FLOOR)
return OptimizeResult(layout=best, moves_applied=<count of confirmed best updates>)
```

- **Objective:** `len(route(candidate))` — the real minimal road count for the candidate placement.
  `route()` is called on **every evaluated move** (no proxy, no new-low gating).
- **Acceptance:** Metropolis — accept if `delta < 0`, else with probability `exp(-delta / T)`.
- **Temperature:** `_initial_temperature` samples a handful of random routed moves and uses the mean
  of the positive `|Δroads|` (fallback 1.0); geometric cooling `T *= _COOLING` (0.9995) per iteration,
  floored at `_T_FLOOR` (1e-9).
- **Initial routing:** the input placement is routed once to seed `cur` (this also captures the
  "Phase-1" free win when the player's roads weren't minimal). `best` is anchored at the input so the
  result is never worse than what the user supplied.
- Input is never mutated (candidates are fresh `Layout`s via the local-search transforms).

## 5. Guarantees (preserved)

- **Never worse / never invalid:** `best` starts as the input layout and is replaced only when a
  candidate is `is_valid` AND has strictly fewer roads. Worsening moves are accepted for *exploration*
  but never returned unless a better validated layout is found.
- **Deterministic:** all randomness flows through a single `random.Random(seed)`; a fixed `seed` +
  fixed `max_iters` (budget not binding) yields an identical result.

## 6. Testing (TDD)

- **Remove** `test_mst_length_*` and `test_mst_cost_*`.
- **Never-worse property:** for any input, result valid and `roads ≤ input roads`.
- **Determinism:** same `seed` + `max_iters` → identical result (two runs).
- **Improvement case:** a sparse synthetic city with scattered road-needing buildings and an inflated
  starting road set → SA returns `roads <` input (the true objective genuinely improves, which the
  proxy could fail to do). Use a fixed seed and a small budget.
- **Real-city:** `darkzig.json` with a small test budget (e.g. 3–5 s) → result valid and
  `roads ≤ len(current.roads)`; record the count. (The full 600s/211 outcome is demonstrated outside
  the test suite to keep tests fast.)
- Existing `random_move` tests stay; existing engine/CLI tests stay green.

## 7. Honest limitations

- `route()` per move (~60ms) bounds iterations; the result improves with `--budget` and exhibits
  diminishing returns (more time → a few more tiles, not a step change).
- On already-tuned cities with no slack (the original 96.6%-full sample, `city.txt`) it may still find
  nothing — but it is now the strongest engine wherever savings exist.
- Further `route()` speedups (leaf/articulation-aware prune; incremental re-route) remain available as
  a future option but are out of scope here.
