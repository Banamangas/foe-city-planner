# FoE City Layout Optimizer — Simulated-Annealing Road Optimizer Design

**Date:** 2026-06-18
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** Phase 0/1/2 + local-search optimizer (all merged). Adds an annealing engine to the `improve` command.

## 1. Purpose

Reduce road tiles by exploring building rearrangements with **simulated annealing**, which can
accept temporarily-worse moves to escape the plateau where single-move hill-climbing stalls.
Annealing runs on a cheap proxy objective; the real road count (`route()`) is used only to
confirm and report improvements.

## 2. Motivation

On the available cities, single-move hill-climbing finds **zero** improving moves: no single
swap/relocate lowers the global road count, so it stops at the first plateau. Annealing accepts
some worsening moves to reach a *coordinated* rearrangement (clustering road-needing buildings)
that a strict descent cannot. The blocker is evaluation cost: SA needs thousands of iterations
but a full `route()` is ~0.2–0.9 s, so SA must score moves with a fast proxy.

## 3. Never-worse guarantee (preserved)

The returned **best** state is seeded as the input layout (valid, current road count) and is
replaced **only** when `route()` confirms a valid layout with strictly fewer roads. Therefore
the result is always valid and `roads ≤ input` — annealing can waste time but never regress.

## 4. Proxy objective

`mst_cost(layout) -> int` = total weight of the **Manhattan minimum spanning tree** over a point
per road-needing building (excluding Townhall) plus the Townhall point. Each building's point is
its footprint centroid `(x + width/2, y + length/2)` (integer/float; consistent across calls).
Edge weight is Manhattan distance. Lower MST ⇒ road-needing buildings clustered ⇒ shorter road
tree. Complexity O(n²) over ~56–82 points → microseconds per evaluation.

This is a **proxy**: it correlates with road length but does not equal it. It guides the search;
truth comes from `route()` at confirmation time.

## 5. Architecture

| Module | Responsibility | Depends on |
|---|---|---|
| `anneal.py` | `mst_cost`, `random_move`, and the `anneal(...)` loop (temperature schedule, acceptance, route-confirmed best tracking). | model, localsearch (`move_building`, `swap_buildings`, candidate helpers, `OptimizeResult`), router (`route`, `RouteError`), validate (`is_valid`) |
| reuse | `report.stats`, `viz.render_comparison`, `build.build_layout`. | — |
| `cli.py` | add `--anneal` and `--seed` options to the existing `improve` subcommand (hill-climbing remains the default engine). | all |

`anneal.py` reuses the local-search placement transforms; it does not duplicate them.

## 6. Algorithm — simulated annealing

```
state = current layout (valid); cost = mst_cost(state)
best = current; best_roads = len(current.roads)          # never-worse anchor
best_proxy = cost
T = T0                  # auto-scaled from sampled |Δcost| of a few random moves
rng = random.Random(seed)
while time.monotonic() < deadline:
    cand = random_move(state, rng)        # validated; None → skip (continue)
    if cand is None: continue
    new_cost = mst_cost(cand)
    delta = new_cost - cost
    if delta < 0 or rng.random() < exp(-delta / T):
        state, cost = cand, new_cost
        if cost < best_proxy:             # new proxy low → pay for confirmation
            best_proxy = cost
            try:
                roads = route(state)
            except RouteError:
                roads = None
            if roads is not None:
                confirmed = Layout(state.region, state.buildings, state.townhall, roads)
                if is_valid(confirmed) and len(roads) < best_roads:
                    best, best_roads = confirmed, len(roads)
    T *= cooling          # geometric; cooling chosen so T decays toward ~0 by the deadline
return OptimizeResult(layout=best, moves_applied=<count of confirmed best updates>)
```

- **Temperature:** `T0` auto-scaled from the mean of the POSITIVE sampled proxy deltas (zero-delta no-op moves excluded; fallback 1.0) over a small sample of random moves (so acceptance starts reasonable regardless of city scale). `cooling` is a geometric factor derived from an estimated iteration count for the budget; the schedule is bounded and deterministic given the seed.
- **Move proposal (`random_move`):** randomly choose a same-footprint swap (two random
  buildings of identical size) or a relocation (a random non-Townhall building to a random
  free cell). Returns a validated new `Layout` (via the local-search transforms) or `None`.
  Uses the passed `rng` only — deterministic for a fixed seed.
- **`route()` budget:** called only when the proxy reaches a new low, bounding expensive calls.
- Input is never mutated (moves build new `Layout`s via `dataclasses.replace`).

## 7. Determinism

Given a fixed `seed`, the run is deterministic (single `random.Random(seed)` drives all
choices). The CLI defaults the seed to a fixed value; tests pass an explicit seed.

## 8. CLI & output

`improve <city> <helper> [-o out.html] [--thorough] [--anneal] [--seed N]`:
- without `--anneal`: hill-climbing (unchanged).
- with `--anneal`: the SA engine; `--seed` sets the RNG seed (default fixed).
Output is unchanged: stats (current vs optimized roads, tiles saved, moves applied) + the
before/after map via `render_comparison`. Always exits 0 (never worse than input).

## 9. Testing (TDD)

- **`mst_cost` (unit):** known small point sets → known MST total (e.g. three collinear points;
  a square). Centroid computation verified.
- **`random_move` (unit):** with a seeded RNG, returns either a valid non-overlapping in-region
  `Layout` or `None`; never an invalid layout.
- **`anneal` property:** for any input, result is valid **and** `roads ≤ input roads`
  (never worse); deterministic for a fixed seed (two runs identical).
- **Improvement case:** a small **sparse** synthetic city whose road-needing buildings are
  scattered but could cluster → annealing (fixed seed, small budget) returns a layout with
  `roads <` input (demonstrates SA achieving what hill-climbing could not).
- **Real-city:** sample city and `city.txt` → result valid and `roads ≤ current` within a small
  test budget; record the achieved counts.

## 10. Honest limitations

- The MST proxy is an approximation; minimizing it does not guarantee fewer real roads. The
  `route()`-confirmed best tracking means the result is never worse, but savings are not
  guaranteed.
- At extreme density (sample 96.6%) the feasible random-move set is tiny, so SA may still find
  nothing. The expected payoff is on sparser cities with clustering slack.
- This is the last optimization lever planned; if SA also yields little on real cities, the
  practical conclusion is that well-built cities are already near-optimal and the tool's value
  is verification/visualization.
