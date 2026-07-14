# FoE City Layout Optimizer

Minimizes the number of road tiles in a Forge of Empires city while keeping every
road-needing building connected to the Townhall.

## Setup
    uv sync

This installs everything the CLI, the optimizer, and the Flask API need (including
`ortools`, used by the roads-first solver). For the web app's frontend you also need
Node 18+ and one `npm install` (see [Web app](#web-app)).

## Your city files are not bundled

You run the tool on your own FoE export. The large exports are gitignored and **not**
committed to this repo — download them from the game / FOE Helper and drop them in the
project root. The examples below reference `darkzig.json` and `city-user-data-foe-helper.json`
as stand-ins for your files. See [Input formats](#input-formats) and [Inputs](#inputs).

## CLI

Every command auto-detects the export format — pass a single combined file, or the
two-file split export.

View the current city as an interactive map:

    uv run python -m foeopt.cli view darkzig.json -o output/current.html

Optimize roads with buildings fixed (Phase 1):

    uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json -o output/roads.html --diff output/roads-diff.json

Re-pack the whole city to minimize roads (moves buildings):

    uv run python -m foeopt.cli layout darkzig.json -o output/layout.html --thorough

Lower the road count by moving buildings (local search; keeps everything else valid):

    uv run python -m foeopt.cli improve darkzig.json -o output/improve.html --thorough

`improve` starts from your current layout and only makes moves that keep the city valid and
reduce roads, so the result is never worse than what you have. Savings depend on free space:
a city with empty cells can cluster road-needing buildings and save more; a near-full city
saves little or nothing but stays valid. Produces a before/after map (toggle current vs improved).

For a deeper search that can escape the plateau where hill-climbing stalls, add `--anneal`
(simulated annealing on the real road count — accepts some worse moves to find a better one):

    uv run python -m foeopt.cli improve darkzig.json --anneal --thorough -o output/anneal.html

`--anneal` is deterministic for a given `--seed` (default 0) and is still never worse than your
current layout. The time budget defaults to 30s (`--thorough` raises it to 120s); set it
explicitly with `--budget SECONDS` (overrides both), e.g. a 10-minute anneal:

    uv run python -m foeopt.cli improve darkzig.json --anneal --budget 600 -o output/anneal.html

Open the generated `.html` in a browser; hover a building to see its name and size, and toggle
current vs optimized roads. Very dense cities (little empty space) may not fit a full re-pack,
in which case the tool reports the buildings it could not place rather than emitting an invalid
layout.

## Roads-first optimizer

The strongest method. Instead of moving buildings around a fixed road network, it searches for
a *road skeleton* of a target size `k` and asks a CP-SAT solver (OR-Tools) whether all
road-needing buildings can be placed against it, walking `k` downward while the layout stays
feasible. On the `darkzig` benchmark this reaches **~106 roads**, well below the local-search
floor (~158) and the input (250).

    # feasibility k-walk on a city (writes best layouts + a probe log under output/roads-first/)
    uv run python scripts/exp_roads_first.py darkzig.json --th-anchors full --time-box 600

    # quick sanity checks
    uv run python scripts/exp_roads_first.py --selftest
    uv run python scripts/exp_roads_first.py darkzig.json --smoke

Key flags: `--time-box SECONDS` (overall budget), `--probe-limit SECONDS` (per-CP-SAT-probe cap),
`--patterns N`, `--th-anchors coarse|full`, `--workers`/`--probe-workers`, `--k-start auto|INT`.
The same engine (`foeopt.roads_first.RoadsFirstSearch`) powers the web app's optimize button.

## Web app

A React + Vite single-page app backed by a Flask JSON API. Load a city, view it on an
interactive pan/zoom map, run the roads-first optimizer time-boxed with best-so-far
improvements streamed live (SSE), and save / export layouts (cached server-side in SQLite).
The large export is slimmed in the browser (a Web Worker strips the bloated `CityEntities`
fields to a ~5MB payload) before upload.

Dev (hot reload):

    cd frontend && npm install && npm run dev     # Vite dev server on http://localhost:5173 (proxies /api → :5000)
    uv run python -m webapp.app                    # Flask JSON API on :5000
    # open http://localhost:5173

Production build:

    cd frontend && npm run build                   # outputs to webapp/dist/
    uv run python -m webapp.app                     # Flask serves the built SPA + API on :5000
    # open http://localhost:5000

The API is under `/api/...` (load, optimize, stream, cities, layouts). If you open `/` before
building the frontend, Flask returns a 503 JSON hint reminding you to run `npm run build`.

## Input formats

Every command auto-detects the export format — just pass the file(s):

    # single combined FOE-Helper export (CityMapData + UnlockedAreas + CityEntities)
    uv run python -m foeopt.cli improve darkzig.json --anneal -o output/out.html

    # older split export (two files)
    uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json

Supported: the two-file split export, a single combined file with old-style entities, and the
newer combined file with `coords`/`size`/`needsStreet` entities (UTF-8 BOM tolerated). The
`needsStreet` flag, when present, is used directly as the road requirement.

## Tests
    uv run pytest

Tests that depend on the large user exports skip automatically when those files are absent, so a
fresh clone stays green. (Two long RL-gate tests are usually excluded:
`--ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`.)

## Inputs
- `city-user-data.json` — live game CityMap response (bundled; small). A building needs a road
  iff it has the `connected` key and is currently road-adjacent.
- `city-user-data-foe-helper.json` — FOE Helper export with building definitions
  (sizes, levels, sets/chains) under `CityEntities`. **User-supplied / gitignored** — required
  for the split-format path.
- Combined exports (e.g. `darkzig.json`, `CityMap-*.json`) — single-file exports that embed
  `CityEntities`. **User-supplied / gitignored.**
- `metadata-grid.json` — static grid geometry (reference; bundled).

See `docs/superpowers/specs/` for the full design and `tasks/lessons.md` for data-model notes.
