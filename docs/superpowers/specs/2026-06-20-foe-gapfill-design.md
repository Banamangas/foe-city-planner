# FoE City Layout Optimizer — Post-Route Gap-Fill Pass Design

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the budgeted multi-start packer (merged).

## 1. Purpose

Clear the last unplaced **fillers** in the `layout` engine by giving them a chance at the free cells
that only open up *after* routing. On DarkZig the multi-start leaves 6 unplaced decorations even
though the final free space has 78 valid `1×4` slots and 44 `2×2` slots — because fillers are placed
before `route()` prunes the reserved road corridor.

## 2. Root cause (measured)

`build_candidate` places fillers against a **reserved** road corridor that is larger than the network
`route()` ultimately keeps. After `route()` prunes to the minimal roads (DarkZig: 169 cells), the
reserved-but-unused cells become free — but the filler pass is already over. On DarkZig that leaves
138 free cells (24 needed by the 6 unplaced), with plenty of correctly-shaped slots (`1×4`: 78,
`2×2`: 44). The shortfall is **timing**, not space or packing quality.

## 3. Scope

- Add one pass to `build_candidate` (`foeopt/packer.py`) that runs **after** `route()` succeeds:
  place still-unplaced fillers into the post-route free cells.
- No change to `repack`, `PackResult`, `PackConfig`, the CLI, or any other engine.
- Road-needing buildings are not gap-filled (they must stay road-adjacent); the `RouteError` path is
  unchanged.

## 4. Algorithm

After `candidate.roads = route(candidate)` succeeds (the normal return path of `build_candidate`):

1. Compute the **post-route free cells**: `region − occupied − candidate.roads`, where `occupied` is
   the union of every placed building's footprint cells.
2. Build a `Grid(w, h, blocked)` where `blocked` is every cell in the bounding box **not** in the
   post-route free set (so only genuinely-free, non-road cells are available).
3. Partition the current `unplaced` into fillers (`needs_road == False`) and the rest. For each filler
   in **largest-area-first** order (`sorted(key=lambda b: (-area(b), ...))`, matching the main filler
   pass; ties may use the same per-trial rng for consistency), `first_fit` it into the grid. On a hit:
   `grid.occupy(...)`, append the moved building (via `dataclasses.replace` with the new footprint) to
   the candidate layout's buildings, and drop it from `unplaced`.
4. Return `PackResult(layout=candidate, unplaced=<fillers that still did not fit> + <non-fillers>)`.

Road-needing buildings that were already unplaced (spatial failures) remain in `unplaced` untouched.

## 5. Invariants preserved

- **No overlap / in-region:** fillers are placed only into cells confirmed free (not roads, not other
  buildings, in the region) via the same `Grid`/`first_fit` machinery.
- **Roads unchanged / still valid:** fillers need no road; adding them into non-road free cells cannot
  disconnect any consumer, so `route()` is *not* re-run and `is_valid(candidate)` continues to hold.
- **Conservation:** a gap-filled building moves from `unplaced` into `candidate.layout.buildings`
  exactly once — never duplicated, never dropped. `placed ∪ unplaced == all input buildings`.
- **Determinism:** `first_fit` is deterministic; the ordering uses the trial's existing seeded rng, so
  `build_candidate` stays deterministic given its `PackConfig`.

## 6. Where it runs

Inside `build_candidate`, per trial — so the multi-start's `(len(unplaced), len(roads))` scoring sees
each trial's true post-gap-fill result.

## 7. Testing (TDD)

- **Gap-fill places a post-route filler:** a synthetic city where a filler cannot be placed during the
  main pass but fits once routing frees reserved cells → `build_candidate` returns it placed (smaller
  `unplaced`), the layout is valid, no overlap, and conservation holds.
- **Road-needing stays unplaced:** gap-fill never places a `needs_road` building into a non-road cell
  (if a road-needing building is unplaced, it remains unplaced).
- **Determinism:** same `PackConfig` → identical result (existing determinism test stays green).
- **Conservation / never-invalid / existing packer tests** stay green.
- **Recorded DarkZig measurement** (not a fast suite test): `repack` best unplaced (expect ~0, down
  from 6) with roads unchanged (~169).

## 8. Risk / limitations

- Low risk: purely additive; if the freed cells genuinely cannot fit a leftover shape, it stays
  unplaced (best-effort intact).
- A second small packing pass per trial adds negligible cost (only the few unplaced fillers).
- Does not change road counts; this is a placement-completeness fix, not a road-minimization one.
