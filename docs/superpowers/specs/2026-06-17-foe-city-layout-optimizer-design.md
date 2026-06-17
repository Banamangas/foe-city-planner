# FoE City Layout Optimizer — Design

**Date:** 2026-06-17
**Status:** Approved (brainstorming) — ready for implementation planning

## 1. Purpose

Given a Forge of Empires city export, produce a layout that **minimizes the number of
road (street) tiles** while ensuring every building that requires a road connection has
one, with the road network rooted at the Townhall. The tool may relocate buildings to
achieve a better (lower) road count.

## 2. Goal & scope

- **Objective:** minimize total road tiles.
- **Freedom:** all main-grid buildings may be repositioned. No rotation (FoE does not
  allow rotating footprints).
- **Quality:** tunable fast↔thorough (time/iteration budget). Best-effort heuristic by
  default; exact solver reserved for tractable subproblems. Global optimality is **not**
  guaranteed.
- **Phased delivery** (each phase independently verifiable):
  - **Phase 0 — Data + viewer:** parsers, building catalog, region model, validators, and
    an interactive HTML map of the *current* city.
  - **Phase 1 — Roads-only optimizer:** buildings fixed; compute minimal Townhall-rooted
    road network. (The original literal goal; verifiable against the current 142-road layout.)
  - **Phase 2 — Full layout solver:** building placement metaheuristic on top, reusing the
    Phase 1 router as the inner evaluator.

### Out of scope
- Rotating building footprints.
- Optimizing outpost grids (`cultural_outpost`, `era_outpost`, `guild_raids`).
- Re-deriving game balance (production, happiness) — we preserve set/chain groupings but do
  not optimize for bonus value.

## 3. Inputs

| File | Role |
|---|---|
| `city-user-data.json` | Live game `CityMap` response: `entities` (placed buildings + streets), `unlocked_areas`, `blocked_areas`, `gridId`. **Authoritative city state.** |
| `city-user-data-foe-helper.json` | FOE Helper rework: `CityMapData`, `UnlockedAreas`, and `CityEntities` (2733 building **definitions** with sizes, requirements, sets/chains). **Metadata source.** |
| `metadata-grid.json` | Static grid geometry (`main` 72×72 plus offset outpost grids). Reference only. |

## 4. Domain model (validated against the data)

### 4.1 Buildable region
- The region is the **union of `UnlockedAreas` rectangles** (`x`, `y`, `width`, `length`).
  In the sample city: 4224 cells spanning x 0–72, y 0–68.
- All building footprints and road tiles must lie entirely within the region. No two
  footprints may overlap. `blocked_areas` cells are unavailable.

### 4.2 Buildings
- A *placed building* is an `entities` element with integer `x`, `y` whose coordinates fall
  on the main grid (0 ≤ x,y < ~200; excludes outposts at 500+ and off-grid negatives).
- **Footprint size** resolution order:
  1. Definition top-level `width` / `length` (≈1446 defs).
  2. Else any `components.<Age>.placement.size` → `(x, y)` (size is constant across ages).

  This resolves 100% of placed buildings. `x` → width, `y` → length.
- **No rotation:** footprint orientation is fixed.

### 4.3 Road-need detection (derived from the player's valid layout)
A building **needs a road iff** in the input city it (a) has a `connected` key **and**
(b) is orthogonally adjacent to a road tile. Both conditions are required; the rule is
computed once at load time, treating the exported city as a *validly connected* layout
(true of any real export), and then the result is a fixed per-building property used by
all phases.

Why this rule (validated against the sample city's 2×2 of `connected`-key × road-adjacent):

| in-region building | road-adjacent | count | meaning |
|---|---|---|---|
| has `connected` key | yes | **81** (incl. Townhall) | needs a road |
| has `connected` key | no | 11 | Yukitomo residences — confirmed by the player to **not** need roads |
| no `connected` key | yes | **0** | (none — roads are placed only where needed) |
| no `connected` key | no | 200 | no road needed |

- The decisive cell is **0**: no building lacking the `connected` key sits next to a road,
  and the only `connected`-key buildings without a road (the Yukitomo) genuinely don't need
  one. So `connected`-key **and** road-adjacent cleanly isolates the 80 consumers + Townhall.
- **Do NOT use** `requirements.street_connection_level` as the road-need test (only ~16 defs
  carry it) **nor** the `connected` key alone (it over-counts the Yukitomo by 11).
- **Road level required** by a building = its def `street_connection_level` if present, else
  **default level 1**. In the sample city all needs are level 1.

### 4.4 Roads
- A road is a 1×1 `street` entity. Multiple street defs exist (50), each with a level it
  *provides* (its own `street_connection_level`).
- Higher-level roads satisfy lower-level requirements.
- Sample city: 142 street tiles currently.

### 4.5 Townhall
- The single `main_building` entity (`H_SpaceAgeSpaceHub_Townhall`, 6×7). It is the **road
  network origin/root**.

### 4.6 Connection rule (the satisfaction predicate)
A road-needing building is **connected** iff **both** hold:
1. At least one tile orthogonally adjacent to its footprint is a **road tile** of level ≥
   the building's required level.
2. That road network is orthogonally connected (road-to-road adjacency) back to the
   **Townhall footprint**.

**The Townhall does not substitute for a road.** A building adjacent only to the Townhall
(with no adjacent road tile) is **not** connected. The Townhall itself is the root and
needs no adjacent road.

### 4.7 Sets and chains (preserve groupings)
- `setId` (ability) groups buildings into a set.
- `chainId` + `linkPositions` (ability) define rigidly-linked buildings via relative
  positions.
- Buildings sharing a set/chain are treated as a **rigid block** (fixed relative offsets)
  when relocated, so groupings stay intact.
- **Sample city: 0 placed buildings belong to any set or chain** — this constraint is
  inactive here but supported for generality.

### 4.8 Exclusions (off-grid = outside the buildable region)
A building participates in optimization **iff its footprint anchor `(x, y)` is inside the
buildable region** (the union of `UnlockedAreas`). Everything else is **off-grid**:
immovable and ignored for both road routing and layout (rendered for context only).

This single region-membership test cleanly excludes, with no per-type list:
- `off_grid` entities (negative / special coords),
- `outpost_ship` and any entity on a non-`main` grid (coords ≥ 500),
- `friends_tavern` (negative coords),
- the settlement **hub** structures (`hub_main` / `hub_part` — e.g. *Port de l'arctique*,
  *Terminal océanique*) which sit outside the region (x > 72 or y > 68),
- inventory entities lacking `x`/`y`.

The player confirmed all such off-grid buildings are immovable and must not be considered.

## 5. Architecture — Python package `foeopt/`

| Module | Responsibility | Depends on |
|---|---|---|
| `loader.py` | Parse the three JSON files into raw structures | — |
| `catalog.py` | Building definitions: footprint-size resolution, road need/level, set/chain extraction | loader |
| `model.py` | Core dataclasses: `Region`, `Building`, `Layout`, `RoadNetwork` | — |
| `region.py` | Build region from `UnlockedAreas`; occupancy, overlap, bounds, blocked-cell checks | model |
| `router.py` | **Phase 1**: minimal road network for a *fixed* placement (heuristic + optional CP-SAT exact) | model, region |
| `packer.py` | **Phase 2**: placement metaheuristic; greedy initializer; uses `router` as inner evaluator | model, region, router |
| `validate.py` | Feasibility checks: in-bounds, no overlap, all road-needing buildings connected | model, region |
| `report.py` | Stats summary + road-diff JSON | model, validate |
| `viz.py` | Emit self-contained interactive HTML map | model |
| `cli.py` | Entrypoint: `view` / `roads` / `layout`; `--fast` / `--thorough` / time budget | all |

### Design principles
- Each module has one clear purpose, communicates via the `model.py` dataclasses, and is
  independently testable.
- The `router` is the shared core: Phase 1 calls it once on the fixed layout; Phase 2 calls
  it many times inside the metaheuristic loop.

## 6. Data flow

```
loader + catalog ── build ──► Layout (buildings + current roads) + Region
        │
        ├─ view   (Phase 0): viz.render(current Layout)
        ├─ roads  (Phase 1): router.solve(fixed buildings) ─► optimized RoadNetwork
        └─ layout (Phase 2): packer.solve() ─► optimized Layout (placement + roads)
                                   │ (inner: router.solve per candidate)
        ▼
   validate.check(result)  ──►  report.stats + report.road_diff + viz.render
```

Every result passes through `validate` before being reported.

## 7. Algorithms (the fast↔thorough knob)

### 7.1 Router (Phase 1 core)
- **Fast (default):** rectilinear-Steiner-tree heuristic. Grow a road tree rooted at the
  Townhall footprint that brings a road tile adjacent to every road-needing building, using
  shortest-path expansion and reuse of existing road corridors. Greedy with local cleanup
  (remove redundant tiles).
- **Thorough:** CP-SAT / ILP exact minimum-tile connected network over the target
  adjacency set, for tractable instances or subregions. With ~99 targets on 4224 cells this
  is heavy; used opportunistically (subproblem decomposition, time budget permitting).
- Respects road levels: a building's adjacent road tile must be ≥ its required level;
  network connectivity treats roads of any level as connecting.

### 7.2 Packer (Phase 2)
- **Greedy initializer:** cluster road-needing buildings near the Townhall along road
  corridors/spines; fill remaining region with no-road buildings; keep set/chain blocks
  rigid.
- **Improvement:** simulated annealing / local search over placements. Move operators:
  relocate a building (or rigid block), swap two, shift a row. Each candidate is scored by
  `road_tiles (via router) + penalties(out-of-bounds, overlap)`.
- **Knob:** iteration / time budget; `--fast` runs the greedy + short local search,
  `--thorough` runs longer annealing and may invoke the exact router.

## 8. Outputs

1. **Stats summary** (stdout / JSON): current vs optimized road count, tiles saved, count of
   road-needing buildings, count satisfied / unsatisfiable, building-move count (Phase 2).
2. **Road-diff JSON:** streets to **remove** and to **add**, each as `{x, y, level}`.
3. **Self-contained interactive HTML map** (single `.html`, no server):
   - Renders the region, building footprints, road tiles, and Townhall.
   - **Hover a building → tooltip with its name and size.**
   - Toggle between current and optimized roads (and, in Phase 2, current vs optimized
     placement).

## 9. Validation & testing (TDD)

- **Unit:** small handcrafted grids with known-optimal road counts (router); region
  overlap/bounds/blocked checks; footprint-size resolution (top-level and component paths);
  road-need detection from `connected`; connectivity validator (including the "Townhall is
  not a road" case).
- **Property:** optimized layout has no overlaps, all footprints in-bounds, every
  road-needing building satisfied, road network connected to Townhall.
- **Golden (real city):** load the sample city; Phase 1 connects all 99 road-needing
  buildings with substantially fewer than 142 road tiles; round-trip parse is lossless for
  excluded entities.

## 10. Key risks / open items

- **Router scale:** 99 targets makes exact routing expensive; the fast heuristic is the
  primary path and must produce strong results. Validate the heuristic's quality against the
  current layout in Phase 1 before building Phase 2.
- **Road-level generality:** sample city is all level 1; multi-level handling is implemented
  but only lightly exercisable with available data.
- **Disruption:** Phase 2 may relocate ~all buildings. The road-diff and move-count outputs
  make the scale of change explicit; "stay close to current layout" is *not* a current
  objective (deferred).
