# FoE City Layout Optimizer — A3 Grow-Tree-and-Attach Packer Design

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — ready for implementation planning
**Replaces:** the comb-corridor packer inside the `layout` engine (`foeopt/packer.py`).

## 1. Purpose

Make the `layout` (from-scratch) engine usable on dense real cities by replacing its comb-corridor
packer — which reserves road corridors by region *area* and thus over-reserves at high density — with
a **grow-tree-and-attach** packer that grows a minimal road tree from the Townhall and snaps
road-needing buildings onto it, so reserved road space scales with the **road network actually
needed**, not the region.

## 2. Motivation

On DarkZig (region 2720 cells, building footprints 2437, **283 free**), the comb reserves 308–424
cells and fails to place 70–118 of 224 buildings. The road space a valid layout can spare is at most
283; the minimal road tree is far less. A useful lower-ish **target** for the road count is
`Σ min(width,length) over road-needing buildings / 2` (a road serves a double row of buildings, so
cells ≈ road-facing side / 2, minimized by facing the short side). On DarkZig that estimate is
**~114** — far below `improve`'s 191, because `improve` only nudges the existing 90%-packed layout
and structurally can't cluster road-needing buildings the way a from-scratch build can. A3 is the
tool that can chase that target.

The estimate is a guide, not a strict bound: on the already-tight sample it is 157 vs a true minimum
of 142 (clustered buildings share roads >2:1), so treat it as ±15–30%.

## 3. Scope

- Rewrite the internals of `foeopt/packer.py` to the A3 algorithm, **keeping** `repack(layout,
  thorough=False) -> PackResult` and `PackResult(layout, unplaced)` as the public interface and the
  `layout` CLI command unchanged.
- Add `road_estimate(layout) -> int` = `Σ min(w,l) over road-needing buildings // 2`, surfaced in the
  `layout` CLI output.
- Reuse `foeopt.packing` (Grid + placement primitives), `foeopt.router.route` (roads + prune),
  `foeopt.validate.is_valid`.
- The comb-specific internals and their tests are replaced. `improve`/`roads`/`view`/`anneal` are
  untouched.

## 4. Algorithm (one configuration)

Given the input `Layout` (used only for the building catalog + region; positions are discarded):

1. **Grid:** bounding box of the region; cells not in the region are blocked.
2. **Townhall:** place it at the configuration's anchor (a region corner/edge), respecting the grid.
   Seed the road network with a free region cell on the Townhall's border.
3. **Order** the road-needing buildings (config: by footprint area, largest first).
4. **Grow + attach** — for each road-needing building, search free cells for a placement whose
   footprint border touches the current road network:
   - Prefer a placement that adds **zero** road (an edge already sits against a road cell).
   - Otherwise extend the road by the **shortest free-cell path** (BFS) from the road network to a
     cell adjacent to the building, and add those cells to the road network.
   - Among feasible placements, prefer the building's **short side facing the road** (a placement
     choice; no rotation) to minimize road per building.
   - If no placement touches/reaches the network, the building is **unplaced**.
5. **Fillers:** densely pack the no-road buildings into all remaining free cells (bottom-left /
   skyline from `packing.py`). Unfittable fillers are **unplaced**.
6. **Route + prune:** build the candidate `Layout` (placed buildings; road network as free cells) and
   call `route()` to compute the minimal road set for the placement. On `RouteError`, the candidate
   is invalid → treated as all road-needing unplaced.
7. Return `PackResult(layout=candidate, unplaced=[...])`.

## 5. `repack` and tuning

- `repack(layout, thorough)`:
  - `thorough=False`: one configuration (default anchor + ordering).
  - `thorough=True`: sweep a few Townhall anchors (region corners) × building orderings.
  - Score each candidate by `(len(unplaced), len(roads))` — fewest unplaced first, then fewest roads
    (closest to the estimate). Deterministic; return the best.
- A returned layout is always valid in structure (in-region, no overlap); `unplaced` is the honest
  shortfall.

## 6. Output

`PackResult` is unchanged. The `layout` CLI additionally prints the road estimate:
`estimated optimal ≈ E | optimized roads R | placed P | unplaced U`. `road_estimate` lives in
`foeopt.report` and is reused by the CLI.

## 7. Success bar (best-effort)

- Place **all** buildings on DarkZig-like (~90%-full) cities and get roads near the Σ(min-side)/2
  estimate; retain the unplaced-report safety net for the densest inputs.
- Never emit an overlapping or out-of-region layout (the existing safety invariant).

## 8. Testing (TDD)

- **`road_estimate`** unit test (small known case, e.g. one 5×6 + one 4×4 road-needing → (5+4)//2 = 4).
- **`packing.py` primitives** — already covered; unchanged.
- **`build_candidate` / `repack` on a sparse synthetic city** → all buildings placed, valid, roads
  near the estimate, buildings conserved & non-overlapping & in-region.
- **Tight region** → reports `unplaced` (safety net), never an invalid layout.
- **Real-city golden** (`test_layout_cli`-style): the result is always valid-in-structure and either
  all-placed-and-valid or a non-empty `unplaced` list — for any density.
- **Recorded DarkZig measurement** (not a fast suite test): placed count + roads vs the ~114 estimate,
  confirming a material improvement over the comb's 70 unplaced. This is the early feasibility check.

## 9. Honest risk / limitations

- This is the most complex component in the project (joint from-scratch packing + routing). At ~90%
  density, fitting everything *and* reaching ~114 roads is genuinely hard; best-effort means it may
  fall short on the densest inputs, surfaced via `unplaced` and the estimate gap.
- **Feasibility-first:** the first implementation task validates the grow-tree core on DarkZig; if it
  cannot materially beat the comb (70 unplaced) there, we reassess before building the full sweep.
- For optimizing an *existing* city, `improve` remains the right tool; `layout`/A3 targets
  from-scratch/greenfield arrangements where the road floor (the estimate) is reachable.
