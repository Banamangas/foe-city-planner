# FoE City Layout Optimizer — Multi-Schema Loader Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** Phase 0/1/2 + local-search + annealing (all merged).

## 1. Purpose

Let every `foeopt` command load any FOE-Helper export natively — the original two-file format,
a single combined file with old-style entities (`city.txt`), and the newer combined file with
`coords`/`size`/`needsStreet` entities (`darkzig.json`) — by auto-detecting the shape, with no
flags and full backward compatibility.

## 2. Input shapes to support

1. **Split-old (two files):** `city-user-data.json` with a top-level `entities` **list**
   (old-style entities: `cityentity_id`, top-level `x`/`y`, `connected`) plus a helper file with
   `CityEntities` and `UnlockedAreas`.
2. **Combined-old (one file):** top-level `CityMapData` (**dict** of old-style entities),
   `UnlockedAreas`, `CityEntities` (e.g. `city.txt`).
3. **Combined-new (one file):** top-level `CityMapData` (dict of **new-style** entities), plus
   `UnlockedAreas` and `CityEntities`. New entities carry `coords:{x,y}`, inline
   `size:{width,length}`, `needsStreet` (0/1/2), `isInInventory`, `entityId`, `type`, `name`
   (e.g. `darkzig.json`, which also has a UTF-8 BOM).

## 3. Architecture

| Unit | Responsibility |
|---|---|
| `loader.read_json(path) -> dict` | Read a file BOM-safe (`utf-8-sig`) and parse JSON. |
| `loader.load_layout(city_path: str, helper_path: str \| None = None) -> Layout` | Public entry: read, auto-detect shape, normalize entities, build the `Layout`. |
| shared assembler | One routine that turns a normalized entity stream + region into a `Layout`; used by both `load_layout` and the existing `build_layout`. |
| `build.build_layout(city_data, helper_data)` | **Refactored** to delegate to the shared assembler so its old-schema behavior is preserved exactly (two-file back-compat). |
| `cli.py` | The `helper` positional becomes **optional** (`nargs="?"`); each command calls `load_layout(args.city, args.helper)`. |

The loader is the only new surface; the optimizer/validator/viz are unchanged (they consume a
`Layout` as before).

## 4. Detection & normalization

**File level (in `load_layout`):**
- Top-level has `entities` (list) → split-old: `entities = data["entities"]`,
  `unlocked_areas = data["unlocked_areas"]`, defs `= helper_data["CityEntities"]` (helper
  required; raise a clear error if missing).
- Top-level has `CityMapData` (dict) → combined: `entities = list(CityMapData.values())`,
  `unlocked_areas = data["UnlockedAreas"]`, defs `= data["CityEntities"]`. A `helper_path`, if
  given, is ignored (warn).

**Entity level (per entity, during assembly):**
- *New-style* iff the entity has a `coords` key:
  - position `= (coords.get("x",0), coords.get("y",0))`
  - footprint `= size.width × size.length` (inline)
  - road-need `= needsStreet` (see §5)
- *Old-style* otherwise:
  - position `= (e.get("x",0), e.get("y",0))` (zero-omission)
  - footprint via `CityEntities` (`placement.size`, else top-level `width`/`length`)
  - road-need by the existing `connected`+road-adjacent rule (see §5)

**Common rules:**
- UTF-8 BOM tolerated on read.
- `isInInventory: true` → excluded.
- **Off-grid** = footprint anchor not in the region (union of `UnlockedAreas`). This is the
  only exclusion test for placement (consistent with current behavior); it covers off_grid,
  outposts, hubs, and inventory items lacking a real position.
- `street`-type entities are **not** buildings: each street expands its footprint cells into the
  road set at its level (a 2×2 street → 4 road cells). Old streets are 1×1; new exports may use
  larger street tiles.
- A building whose footprint size cannot be resolved is skipped with a recorded reason (the
  existing `ValueError` behavior is retained for the old two-file path to avoid changing its
  contract; combined files skip-and-continue to stay robust on real exports).

## 5. Road-need per schema

- **New-style entity:** `needs_road = needsStreet > 0`; `road_level = needsStreet` (1 or 2).
  Authoritative — no heuristic. For a `street`, `needsStreet` is the level it **provides**.
- **Old-style entity:** unchanged — `needs_road = ("connected" in entity) and
  (footprint is orthogonally adjacent to a road tile in the input layout)`; `road_level =
  street_connection_level` from the def, else 1. For a `street`, the provided level is the def's
  `street_connection_level`, else 1.

The Townhall (`type == "main_building"`) is the network root regardless of schema and is
excluded from `road_needing()` as before.

## 6. CLI

- `helper` positional becomes optional across `view`, `roads`, `layout`, `improve`.
- Each command: `layout = load_layout(args.city, args.helper)`.
- Combined file: `foeopt improve darkzig.json`. Split-old: `foeopt improve city.json helper.json`.
- Auto-detection means no `--format` flag; behavior is identical to today for the two-file case.

## 7. Backward compatibility

- `build.build_layout(city_data, helper_data)` keeps its signature and exact behavior; it is
  re-expressed on the shared assembler. Existing tests (sample: 314 buildings, 142 roads, 82
  road-needing consumers; Yukitomo not road-needing; hubs excluded) must remain green.
- The original two-file invocation and `city.txt` (combined-old) load identically.

## 8. Testing (TDD)

- **`read_json`:** reads a plain JSON file and a BOM-prefixed file identically.
- **Detection:** classifies split-old, combined-old, and combined-new inputs (small synthetic
  dicts).
- **New-schema assembly (unit):** a synthetic combined-new dict → correct footprints from inline
  `size`, road-need from `needsStreet` (0 vs 1 vs 2), `isInInventory` excluded, street cells in
  the road set.
- **Old-schema preserved:** existing `build_layout` tests stay green; `load_layout` on the
  sample two files yields the same `Layout` (314/142/82).
- **Real combined files:** `city.txt` (combined-old) loads (88 buildings / 92 roads as observed);
  `darkzig.json` (combined-new, BOM) loads to 224 buildings / 250 road cells / 63 road-needing,
  valid.
- **CLI:** a command accepts a single combined file with `helper` omitted and runs end-to-end
  (e.g. `roads`/`improve` on `darkzig.json`).

## 9. Honest limitations / notes

- Files are assumed single-schema; per-entity detection still handles a mixed file gracefully.
- `needsStreet` is trusted as the game's authoritative flag for new exports; if a future export
  changes the field, detection (presence of `coords`) still routes correctly but the level
  mapping would need revisiting.
- This is a loader/ingestion feature only; it does not change any optimizer behavior.
