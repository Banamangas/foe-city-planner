# FoE City Layout Optimizer — Phase 2 (Constructive Re-pack) Design

**Date:** 2026-06-18
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** `2026-06-17-foe-city-layout-optimizer-design.md` (Phase 0 + Phase 1, merged)

## 1. Purpose

Phase 2 re-packs an entire FoE city from scratch — placing **all** movable buildings plus a
road network — to **minimize the number of road tiles**, going beyond Phase 1 (which holds
buildings fixed and only re-routes roads).

## 2. Generality (first-class requirement)

The tool operates on **arbitrary user-uploaded city files** (`city-user-data.json` +
`city-user-data-foe-helper.json`), already passed as CLI arguments. **Nothing in Phase 2 may
hardcode the sample city's characteristics** (its size, density, building mix, or the 142/314
counts). The algorithm must adapt to whatever it is given:

- A **sparse** city (lots of empty buildable cells) has slack to cluster road-needing
  buildings tightly → larger road savings, easy packing.
- A **dense** city (the sample is **96.6% full**: 4079 building cells in a 4224-cell region,
  145 non-building cells, 142 already roads) has almost no slack → small or no savings, and
  fitting all buildings is itself hard.

Density is computed per input, not assumed. The sample city is an unusually hard (near-full)
case; it is a stress test, not the design target.

## 3. Goal & constraints

- **Objective:** minimize total road tiles (pure — disruption/move-count is **not** an
  objective; the optimizer may relocate every building).
- **Hard constraints (a valid layout):**
  - Every building placed inside the buildable region (union of `UnlockedAreas`), no rotation.
  - No two footprints overlap.
  - Every road-needing building (Phase 1 rule: had a `connected` key **and** was road-adjacent
    in the *input* layout) has an edge tile orthogonally adjacent to a road tile of
    level ≥ its requirement.
  - The road network is orthogonally connected to the Townhall footprint (Townhall is the
    root; it does not substitute for a road).
- **Building footprint area is fixed** (no resize/rotate). Therefore every valid layout leaves
  exactly `|region| − Σ footprint area` non-building cells for roads + empties. Road count is
  bounded by that budget regardless of arrangement.
- **Tunable** fast↔thorough (see §6).

### Out of scope
- Set/chain rigid-block preservation — **deferred (YAGNI)**: 0 placed buildings belong to any
  set/chain in the sample, and it cannot be exercised. To revisit when a city actually has them.
- Building rotation, outpost grids, bonus-value optimization.
- Minimizing the number of relocations.

## 4. Architecture (new modules; reuse Phase 0/1)

| Module | Responsibility | Depends on |
|---|---|---|
| `packing.py` | Low-level **grid-with-obstacles** and a bottom-left/skyline rectangle-placement primitive. Non-region cells are pre-marked blocked, turning the irregular region into a rectangle-with-holes. Pure, no FoE knowledge. | — |
| `packer.py` | Phase 2 orchestrator: lay a Townhall-rooted **road comb**, place road-needing buildings flush against it, skyline-fill the rest, prune, verify, emit a new `Layout`. Tunable. | model, region, packing, router, validate |
| reuse | `validate` (gate every candidate), `router`/prune (tidy comb connectivity & drop unused road tiles), `report` (stats + road diff), `viz` (before/after map), `build` (input `Layout`). | — |
| `cli.py` | add a `layout` subcommand (mirrors `roads`): `layout <city> <helper> [-o out.html] [--fast|--thorough]`. | all |

Each unit is independently testable: `packing.py` is pure geometry; `packer.py` composes it
with the existing validator/router.

## 5. Algorithm — "comb skeleton + skyline fill"

Work in the region's bounding box `[0,W) × [0,H)` with non-region cells marked **blocked**, so
the placement primitive treats the irregular region as a rectangle with holes.

1. **Root:** place the **Townhall** at a candidate root position; start a 1-cell **road trunk**
   from a Townhall border cell.
2. **Comb:** lay **road rows** (or columns) at a chosen spacing across the region, each joined
   to the trunk so the whole skeleton is connected to the Townhall.
3. **Road-needing buildings:** place each flush against a road row (an edge cell touching the
   road), packed along the rows — guaranteeing road adjacency by construction.
4. **Fillers:** skyline-pack the road-free buildings into all remaining region cells.
5. **Prune:** remove road tiles not needed to keep every road-needing building connected
   (reuse Phase 1 `_prune`).
6. **Validate:** the candidate must pass `validate.is_valid` and the no-overlap / in-region /
   all-placed checks. 
7. **Failure handling:** if not all buildings can be placed, return the best partial layout
   **with an explicit `unplaced` list** — never an overlapping or out-of-region layout.

## 6. Tunable fast↔thorough

- **fast:** a single pass with default comb spacing, orientation, Townhall position, and
  building ordering.
- **thorough:** sweep a small grid of configurations — comb spacing, orientation (rows vs
  columns), a few Townhall positions, and building orderings (e.g., decreasing footprint
  area) — and keep the **valid** layout that places all buildings with the fewest road tiles.
  If none place all buildings, keep the one that places the most (ties broken by fewest roads)
  and report the shortfall.

The knob is exposed as `--fast` / `--thorough` (default fast) on the `layout` command.

## 7. Output

- **Stats:** current vs optimized road count, tiles saved, buildings placed / unplaced,
  validity.
- **Before/after interactive map** (reuse `viz`): toggle current layout vs optimized
  placement and roads; hover a building for name + size.
- (No move-list or new-city JSON in this phase — deferred unless requested.)

## 8. Testing (TDD)

- **`packing.py` unit:** place N rectangles into a rectangle-with-holes with a known compact
  solution; reject overlaps and out-of-bounds; respect blocked cells. Deterministic ordering.
- **`packer.py`:**
  - Small synthetic city with a known compact optimum → packer places all and roads ≤ a known
    bound.
  - Property tests: output is always valid (in-region, no overlap, all road-needing connected)
    or returns an `unplaced` list; never an invalid layout.
  - A **sparse** synthetic city → demonstrates real road savings vs its input (proves the
    optimizer works when slack exists — the generality requirement).
  - **Real-city golden test:** asserts the result is either (all 314 placed AND roads ≤ 142)
    **or** a clear non-empty `unplaced` report — i.e. correctness is never silently violated,
    whatever the density.

## 9. Honest limitations

- At very high density (sample: 96.6%) a constructive packer may not fit all buildings; the
  deliverable then is a faithful unplaced report, not a usable full layout. This is expected
  and surfaced, not hidden.
- The packer is a best-effort heuristic; it targets beating the input road count when slack
  exists, not global optimality.
- Phase 1 (`roads`) remains the reliable path for fixed-building road minimization, and is the
  recommended fallback for dense cities.
