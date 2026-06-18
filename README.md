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

Open the generated `.html` in a browser; hover a building to see its name and size,
and toggle current vs optimized roads.

This produces a before/after map (toggle current vs optimized). The optimizer adapts to the
city's density: sparse cities yield real road savings; very dense cities (little empty space)
may not fit a full re-pack, in which case it reports the buildings it could not place rather
than emitting an invalid layout.

## Tests
    uv run pytest

## Inputs
- `city-user-data.json` — live game CityMap response (authoritative state; a building
  needs a road iff it has the `connected` key and is currently road-adjacent).
- `city-user-data-foe-helper.json` — FOE Helper rework with building definitions
  (sizes, levels, sets/chains).
- `metadata-grid.json` — static grid geometry (reference).

See `docs/superpowers/specs/` for the full design and `tasks/lessons.md` for data-model notes.
