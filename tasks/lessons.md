# Lessons

## FoE data model

### Road-need detection: `connected` key AND currently road-adjacent (derived from the valid layout)
- **Mistake 1:** Derived "needs a road" from `CityEntities[id].requirements.street_connection_level` → only 16 buildings (Great Buildings/military/Townhall). That field is absent for event buildings.
- **Mistake 2:** Switched to "has `connected` key" → 99 buildings, but this **over-counts by 11**: the Yukitomo residences (`W_MultiAge_WIN24A13` *Yukitomo Impérial*, `W_MultiAge_WIN24A14` *Résidence Céleste Yukitomo*) have `connected=1` yet are buried with no adjacent road, and the player confirmed they do **not** need roads. Event-building defs carry no road/street info at all.
- **Correct rule (player-confirmed):** a building needs a road **iff** it has a `connected` key **AND** is orthogonally adjacent to a road tile in the input layout. Computed once at load, treating the export as a valid layout; then a fixed per-building property. Sample city: **80 consumers + Townhall**.
- **Key data fact:** the 2×2 of (`connected` key) × (road-adjacent) had **0** in the "no key + road-adjacent" cell — roads are placed only where needed, so the rule is unambiguous.
- Road *level* = def `street_connection_level` if present, else default 1.

### Off-grid = footprint anchor outside the buildable region
- **Mistake:** Excluded off-grid by a type list (`off_grid`/`outpost_ship`/`friends_tavern`) + `coords < 200`. This missed the settlement **hub** structures (`hub_main`/`hub_part`: *Port de l'arctique*, *Terminal océanique*) which have in-range coords but sit outside the unlocked region.
- **Correct rule (player-confirmed):** a building is on-grid (movable, optimization-relevant) **iff its footprint anchor `(x,y)` is inside the buildable region** (union of `UnlockedAreas`). Anything else is off-grid, immovable, ignored. One test replaces the type list and catches hubs + the other ~10–13 off-grid buildings.

### Townhall does NOT substitute for a road
- **Mistake:** Assumed a building adjacent to the Townhall footprint counts as connected without a road tile.
- **Reality:** Every road-needing building must be orthogonally adjacent to an actual **road tile**. The Townhall is only the network **origin** — the road network must connect back to it, but touching the Townhall does not satisfy a building's road requirement.

### Building footprint size resolution
- Top-level `width`/`length` exists for ~1446 defs only.
- Multi-age buildings store size in `components.<Age>.placement.size` → `(x, y)`, constant across ages.
- Resolution order: top-level `width`/`length`, else any component's `placement.size`. Resolves 100% of placed buildings.

### FoE omits the x (or y) coordinate when it is 0 — don't require both keys
- **Symptom:** User reported buildings missing on the **left side** and **top line** of the map; building count was 292 but should be 314.
- **Misdiagnosis (avoid repeating):** I first assumed it was a colour-contrast problem (non-road `#555` vs region `#3a3a3a`) and "fixed" the palette. That was wrong — it addressed a real but secondary issue and did NOT restore the buildings. **The count (292 vs 314) was the decisive clue I should have checked first.**
- **Root cause:** `city-user-data.json` **omits the `x` field when x=0 and the `y` field when y=0** (same zero-omission convention as `unlocked_areas`). `build_layout` required both keys present, silently dropping all 22 buildings on the x=0 column (left edge) and y=0 row (top edge) — including 2 Great Buildings.
- **Fix:** `x, y = e.get("x", 0), e.get("y", 0)`, then exclude by region membership. Verified: 0 entities have *neither* coord, edge cells are in-region, result = 314 buildings / 82 road-needing consumers.
- **Lessons:**
  - When a **count** is off, chase the count directly — it localises the bug faster than reasoning about symptoms (rendering, contrast).
  - Apply the zero-omission rule **everywhere** coordinates are read, not just `unlocked_areas`.
  - For a visual bug, render the real output to a PNG and inspect it (this did confirm the buildings once coords were fixed).

### Map contrast (secondary improvement, kept)
- Non-road buildings were `#555` on region `#3a3a3a` (channel distance 81) — low contrast. Hoisted the palette into testable `foeopt/viz.py` constants; non-road buildings are now amber (`#d89b3c`) on darker region (`#262626`). Regression guard measures **channel-sum distance ≥150** (string inequality is useless: `#555` != `#3a3a3a` is "true" yet they look identical).

### Process lesson
- When a derived count "feels off" or contradicts domain knowledge (FoE: most buildings need roads), validate against the live game-state signal before designing around the metadata-derived value.
