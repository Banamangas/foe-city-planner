# Lessons

## FoE data model

### Road-need detection: use the live `connected` field, NOT metadata
- **Mistake:** I derived "needs a road" from `CityEntities[id].requirements.street_connection_level`, getting only 16 buildings.
- **Reality:** That metadata field is only populated for a subset (Great Buildings, military, Townhall — ~16). Most event/special buildings (`W_MultiAge_*`) carry no road info in metadata at all.
- **Correct signal:** A placed entity needs a road **iff it has a `connected` key** in `city-user-data.json`. This is the game's authoritative flag (streets also carry it). In the sample city: 99 non-street buildings need roads.
- **Rule:** road-needing = non-street entity with `connected` key present. Road *level* = def `street_connection_level` if present, else default level 1.

### Townhall does NOT substitute for a road
- **Mistake:** Assumed a building adjacent to the Townhall footprint counts as connected without a road tile.
- **Reality:** Every road-needing building must be orthogonally adjacent to an actual **road tile**. The Townhall is only the network **origin** — the road network must connect back to it, but touching the Townhall does not satisfy a building's road requirement.

### Building footprint size resolution
- Top-level `width`/`length` exists for ~1446 defs only.
- Multi-age buildings store size in `components.<Age>.placement.size` → `(x, y)`, constant across ages.
- Resolution order: top-level `width`/`length`, else any component's `placement.size`. Resolves 100% of placed buildings.

### Process lesson
- When a derived count "feels off" or contradicts domain knowledge (FoE: most buildings need roads), validate against the live game-state signal before designing around the metadata-derived value.
