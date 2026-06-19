# FoE City Layout Optimizer

Minimizes the number of road tiles in a Forge of Empires city while keeping every
road-needing building connected to the Townhall.

## Setup
    uv sync

## Usage
View the current city as an interactive map:

    uv run python -m foeopt.cli view city-user-data.json city-user-data-foe-helper.json -o output/current.html

Optimize roads with buildings fixed (Phase 1):

    uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json -o output/roads.html --diff output/roads-diff.json

Re-pack the whole city to minimize roads (Phase 2, moves buildings):

    uv run python -m foeopt.cli layout city-user-data.json city-user-data-foe-helper.json -o output/layout.html --thorough

Lower the road count by moving buildings (local search; keeps everything else valid):

    uv run python -m foeopt.cli improve city-user-data.json city-user-data-foe-helper.json -o output/improve.html --thorough

This starts from your current layout and only makes moves that keep the city valid and reduce
roads, so the result is never worse than what you have. Savings depend on free space: a city
with empty cells can cluster road-needing buildings and save more; a near-full city saves
little or nothing but stays valid. Produces a before/after map (toggle current vs improved).

For a deeper search that can escape the plateau where hill-climbing stalls, add `--anneal`
(simulated annealing on a fast spanning-tree proxy, confirmed with the real router):

    uv run python -m foeopt.cli improve city-user-data.json city-user-data-foe-helper.json --anneal --thorough -o output/anneal.html

`--anneal` is deterministic for a given `--seed` (default 0) and is still never worse than your
current layout. Like every engine here, it only finds savings when the city has free space to
rearrange into; on a near-full, already-tuned city it may report no improvement.

Open the generated `.html` in a browser; hover a building to see its name and size,
and toggle current vs optimized roads.

This produces a before/after map (toggle current vs optimized). The optimizer adapts to the
city's density: sparse cities yield real road savings; very dense cities (little empty space)
may not fit a full re-pack, in which case it reports the buildings it could not place rather
than emitting an invalid layout.

## Input formats

Every command auto-detects the export format — just pass the file(s):

    # newer single-file FOE-Helper export (CityMapData + UnlockedAreas + CityEntities)
    uv run python -m foeopt.cli improve darkzig.json --anneal -o output/out.html

    # older split export (two files)
    uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json

Supported: the two-file split export, a single combined file with old-style entities, and the
newer combined file with `coords`/`size`/`needsStreet` entities (UTF-8 BOM tolerated). The
`needsStreet` flag, when present, is used directly as the road requirement.

## Tests
    uv run pytest

## Inputs
- `city-user-data.json` — live game CityMap response (authoritative state; a building
  needs a road iff it has the `connected` key and is currently road-adjacent).
- `city-user-data-foe-helper.json` — FOE Helper rework with building definitions
  (sizes, levels, sets/chains).
- `metadata-grid.json` — static grid geometry (reference).

See `docs/superpowers/specs/` for the full design and `tasks/lessons.md` for data-model notes.
