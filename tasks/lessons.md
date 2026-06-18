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

### "Missing buildings" on the map was a contrast bug, not missing data
- **Symptom:** User reported buildings (top row of 4×4, left-side 7×7/5×6) not showing on the rendered map.
- **Investigation:** Confirmed via data that all 292 buildings reached the canvas payload at correct pixels (only the 7 off-grid hubs are excluded), and there were no overlapping footprints. Then **rendered the actual canvas draw order to a PNG and looked at it** — buildings were drawn but non-road `#555` was nearly identical to region `#3a3a3a`.
- **Root cause:** insufficient colour contrast between non-road buildings and the region background. Isolated/edge buildings read as background.
- **Fix:** hoisted the palette into testable `foeopt/viz.py` constants; non-road buildings are now amber (`#d89b3c`) on a darker region (`#262626`).
- **Test lesson:** a string-inequality check on colours is useless (`#555` != `#3a3a3a` is "true" but they look identical). The regression guard measures **channel-sum distance** and requires ≥150 (old pairing was 81).
- **Debugging lesson:** for a visual bug, render the real output to an image and inspect it — don't reason about pixels from code alone.

### Process lesson
- When a derived count "feels off" or contradicts domain knowledge (FoE: most buildings need roads), validate against the live game-state signal before designing around the metadata-derived value.
