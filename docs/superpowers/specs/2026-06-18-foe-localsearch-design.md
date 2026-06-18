# FoE City Layout Optimizer — Local-Search Road Optimizer Design

**Date:** 2026-06-18
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** Phase 0 + Phase 1 (merged) and Phase 2 constructive re-pack (merged).
**Supersedes for real-density cities:** the constructive packer (`packer.repack`) over-reserves comb corridors by region *area* and fails to place all buildings at realistic densities (83%–97% full). This local-search optimizer is the practical road-minimizer; the constructive `layout` command remains for sparse/experimental use.

## 1. Purpose

Minimize the number of road tiles in a Forge of Empires city by starting from the player's
**current valid layout** and making small, validated building moves that let the router drop
road tiles.

## 2. Key guarantee (why local search)

The search begins from the current layout (already valid) and **only accepts a move that
keeps the layout valid and strictly lowers the road count**. Therefore:

- The result is **never worse than the input** and **never invalid** — at worst it returns
  the current layout unchanged.
- It **degrades gracefully with density**: where there is slack (e.g. an 83%-full city) more
  moves are feasible and more roads are saved; at extreme density (the 96.6% sample, 3 free
  cells) few moves are possible and savings are small or zero — but the result is still valid.

This is the decisive contrast with the constructive packer, which can fail to place buildings
at all.

## 3. Generality

Operates on any input the existing loader accepts (`build_layout(city_data, helper_data)`),
already parameterized by city. Budgets and move targeting derive from the input; nothing is
hardcoded to a specific city.

## 4. Constraints (unchanged from prior phases)

A **valid layout**: all buildings inside the region (union of `UnlockedAreas`), no overlap,
no rotation; every road-needing building (`Building.needs_road`, excluding the Townhall)
orthogonally adjacent to a road tile of level ≥ its requirement; road network connected to
the Townhall footprint (Townhall is the root, never a road substitute). Road levels honored.

Road-need is the established rule (a building had a `connected` key **and** was road-adjacent
in the input). Sets/chains remain out of scope (0 in sample data; YAGNI).

## 5. Architecture

| Module | Responsibility | Depends on |
|---|---|---|
| `localsearch.py` | The hill-climbing optimizer: move generation, validated move application, accept-on-improvement loop, budget control. Independent of `packer.py`. | model, router (`route`, `RouteError`), validate (`is_valid`) |
| reuse | `report.stats` (roads saved), `viz.render_comparison` (before/after map), `build.build_layout` (input). | — |
| `cli.py` | add an `improve` subcommand: `improve <city> <helper> [-o out.html] [--thorough]`. The existing `layout` (constructive) and `roads` (fixed-building) commands are unchanged. | all |

Each unit is independently testable: move operators are pure transforms on a `Layout`;
the loop composes them with `route`/`is_valid`.

## 6. Algorithm — hill-climbing, first-improvement

```
state  = current layout (valid)
best   = len(route(state))             # current road count
while within budget (time or iterations):
    improved = False
    for move in candidate_moves(state):          # targeted order, see §7
        cand = apply(move, state)                # placement validated: in-region, no overlap
        if cand is None:                         # invalid placement -> skip
            continue
        try:
            roads = route(cand)                  # minimal roads for the new placement
        except RouteError:
            continue                             # unroutable -> skip
        if len(roads) < best and is_valid(replace(cand, roads=roads)):
            state, best = replace(cand, roads=roads), len(roads)
            improved = True
            break                                # first-improvement: restart generation
    if not improved:
        break                                    # local optimum reached
return state                                     # valid; roads <= input roads
```

- Buildings are moved by constructing a new `Layout` with `dataclasses.replace` on the moved
  `Building`(s); the input layout is never mutated.
- Every accepted state is fully valid; the loop can always return the best state seen.

## 7. Move operators (each validated before scoring)

1. **Same-footprint swap.** Exchange the anchors of two buildings with identical
   `width×length`. Placement is always valid (the occupied cell set is unchanged). Needs no
   free space — the primary lever at high density. Targeted: pair a road-needing building that
   is far from / poorly served by the network with a filler nearer the network.
2. **Relocate to free-near-road.** Move one building into empty region cells (a free
   rectangle of its footprint) whose border touches the current road network. Frees its old
   cells. Available where slack exists.
3. **Targeted spur removal.** Detect road tiles forming a dead-end branch that serves a single
   road-needing building; attempt to relocate that building adjacent to the main network
   (swap or relocate) so the spur can be pruned. Directly targets road savings.

**Move generation order:** prioritize moves acting on road-needing buildings that sit on long
spurs or far from the network, so each (relatively expensive) `route()` evaluation is likely
to yield an improvement. Generation is deterministic given the state.

## 8. Budget & evaluation

- Scoring a candidate re-runs `route()` (≈0.9 s on the 314-building sample; faster on smaller
  cities). The search is bounded by a **budget**: `--fast` (small, ~30 s wall-clock or a small
  iteration cap) and `--thorough` (larger). The loop stops at the budget or at a local optimum
  and returns the best valid state.
- The budget is wall-clock-and-iteration based, computed from the run, not the city.

## 9. Output

- **Stats:** current vs optimized road count, tiles saved, number of moves applied.
- **Before/after interactive map** (reuse `viz.render_comparison`): toggle current vs improved
  placement & roads; hover for name + size.

## 10. Testing (TDD)

- **Move operators (unit):** same-footprint swap produces a valid, non-overlapping layout with
  swapped anchors; relocate finds a valid free-near-road spot or returns None; spur detection
  identifies a known dead-end branch on a small grid.
- **Loop:** a small synthetic city with one obvious improving move → the search finds it, road
  count drops, result is valid.
- **Property:** for any input, the result is valid **and** `roads ≤ input roads` (never worse);
  if no improving move exists, the input layout is returned unchanged.
- **Real-city:** on the sample city and on `city.txt`, assert the result is valid and
  `optimized_roads ≤ current_roads` within a small test budget; record the savings achieved.

## 11. Honest limitations

- At extreme density (sample 96.6%, 3 free cells) the feasible move set is mostly
  same-footprint swaps; savings may be small or zero. The guarantee is validity and
  never-worse, not a large reduction.
- `route()` cost bounds how many candidates are evaluated; very large cities explore fewer
  moves per second. A future router speed-up (incremental prune) would raise throughput but is
  out of scope here.
