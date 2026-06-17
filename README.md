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

Open the generated `.html` in a browser; hover a building to see its name and size,
and toggle current vs optimized roads.

## Tests
    uv run pytest

## Inputs
- `city-user-data.json` — live game CityMap response (authoritative state; a building
  needs a road iff it has the `connected` key and is currently road-adjacent).
- `city-user-data-foe-helper.json` — FOE Helper rework with building definitions
  (sizes, levels, sets/chains).
- `metadata-grid.json` — static grid geometry (reference).

See `docs/superpowers/specs/` for the full design and `tasks/lessons.md` for data-model notes.
