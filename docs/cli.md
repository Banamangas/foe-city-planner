# Command line and developer reference

Everything the app does is also available from a terminal, plus tools the app
doesn't expose. This page assumes a source install (see the README's
"Install from source"); run every command from the project folder.

In the examples, `my-city.json` stands for your own city export. City files
contain player names and ids: keep them out of git (the usual names are already
in `.gitignore`).

## Input formats

Every command detects the format on its own; pass the file(s):

- **Forge Hammer (v3) file:** `{version, cityData, mapData, ...}`. The only format
  the app accepts, and the only one that can be exported back. It carries no
  building sizes, so these come from the building list (`foeopt/data/catalog.json`).
- **FOE Helper combined export:** one file with `CityMapData`, `UnlockedAreas` and
  `CityEntities` (old-style entities, or the newer `coords`/`size`/`needsStreet`
  ones; `needsStreet` is used directly as the road requirement).
- **Split export (two files):** the game's CityMap response plus a FOE Helper
  file holding `CityEntities`.

A UTF-8 BOM is tolerated.

## `foeopt` commands

    uv run python -m foeopt.cli <command> CITY [HELPER] [options]

Each command writes an interactive HTML map (open it in a browser: hover a
building for its name and size, toggle current vs optimized roads).

| Command | What it does | Main options |
|---|---|---|
| `view` | Draws the current city. | `-o FILE` |
| `roads` | Keeps every building in place and finds the fewest roads that connect them. | `-o FILE`, `--diff FILE` (road changes as JSON) |
| `layout` | Re-packs the whole city (moves buildings) to minimize roads. | `--thorough`, `--budget S`, `--seed N`, `--polish` (+ `--anneal-budget S`), experimental: `--safe-placements`, `--th-stub-template`, `--lns S` |
| `improve` | Starts from your layout and only makes moves that keep it valid and lower the road count, so it is never worse than the input. | `--thorough` (120 s), `--budget S`, `--anneal` (simulated annealing, deterministic per `--seed`) |

Examples:

    uv run python -m foeopt.cli view my-city.json -o output/current.html
    uv run python -m foeopt.cli improve my-city.json --anneal --budget 600 -o output/anneal.html

A city with little free space may not fit a full re-pack; `layout` then lists
the buildings it could not place instead of writing an invalid layout.
`improve` saves more on cities with empty cells and little or nothing on a
nearly full one.

## Roads-first optimizer (the app's engine)

The strongest method, and the one behind the app's Start button
(`foeopt.roads_first.RoadsFirstSearch`). It proposes road networks ("skeletons")
of a target size `k`, asks the CP-SAT solver (Google OR-Tools) whether every
building fits around one, and walks `k` down while that stays possible. Polish
phases then re-solve the best networks to shave off more roads, and a mutation
climb tries small changes to the network. Every result passes the full
legality check (`foeopt/legality.py`); buildings never rotate.

    # quick checks
    uv run python scripts/exp_roads_first.py --selftest
    uv run python scripts/exp_roads_first.py my-city.json --smoke

    # a 10-minute search (best layouts and a probe log under output/roads-first/)
    uv run python scripts/exp_roads_first.py my-city.json --th-anchors full --time-box 600

Main options: `--time-box S` (total budget), `--probe-limit S` (per solver call),
`--workers` / `--probe-workers`, `--k-start auto|N`,
`--military connect|unconnected` (whether road-needing buildings that are off
the road today must be connected). `--help` lists the rest. The script's
defaults are not the app's settings: the app uses `BEST_PRESET` in
`webapp/params.py`, which the advanced page (below) can load in one click.

Check any saved layout against its city with the full legality check:

    uv run python scripts/verify_layout_file.py my-city.json output/layout.json

## Web app (developer and advanced page)

The app is a Flask server (`webapp/`) plus a React + TypeScript frontend built
with Vite (`frontend/`). Two pages:

- `/`: the five-step wizard players see in the desktop app.
- `/advanced`: the original tuning page, with every optimizer option, presets,
  a city library (SQLite) and saved layouts.

With hot reload (two terminals):

    cd frontend && npm install && npm run dev    # http://localhost:5173, proxies /api to :5000
    uv run python -m webapp.app                   # API on :5000

Or built once, served by Flask:

    cd frontend && npm run build                  # writes webapp/dist/
    uv run python -m webapp.app                   # http://localhost:5000

Opening `/` before building returns a 503 message asking for `npm run build`.

## Desktop app from source

    uv sync --extra desktop
    cd frontend && npm ci && npm run build && cd ..
    uv run python -m desktop.main            # own window (browser on Linux)
    uv run python -m desktop.main --browser  # force the browser
    uv run python -m desktop.main --self-test

Data folder (last city, last session, log): `%LOCALAPPDATA%\foe-city-planner`
on Windows, `~/Library/Application Support/foe-city-planner` on macOS,
`~/.local/share/foe-city-planner` on Linux; `FOEOPT_DATA_DIR` overrides it.
Errors go to `app.log` there.

Build the one-file app for the current system (output in `dist-desktop/`):

    pip install -r desktop/requirements-build.txt
    python desktop/build.py

The "Desktop app" GitHub workflow builds and self-tests Windows, macOS and
Linux on "Run workflow"; pushing a `v*` tag also drafts a release. See
`docs/download.md` for what players see.

## Building list

Forge Hammer files only carry each building's game id, so the app looks up
names, sizes, road needs and chains in `foeopt/data/catalog.json`. A daily
GitHub workflow ("Building list") refreshes it from the game data and publishes
it on the `catalog` release; the app downloads it at startup when newer. Setup
and troubleshooting: [building-list.md](building-list.md).

    # rebuild from the game's building_entity_lookup export
    uv run python scripts/update_catalog.py --lookup LOOKUP.json --previous foeopt/data/catalog.json --out catalog.json
    # or from FOE Helper exports
    uv run python scripts/build_catalog.py EXPORT.json [EXPORT.json ...]

## Tests

    uv run pytest                    # Python
    cd frontend && npx vitest run    # frontend

Tests that need personal city exports skip when the files are absent, so a
fresh clone passes. Two long RL tests are usually left out:
`--ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`.

## Other folders

- `rl/`: an experimental reinforcement-learning placement policy
  (`uv sync --extra rl`). Not used by the app.
- `scripts/exp_*.py`, `scripts/bench.py`: experiments and benchmarks.
- `docs/records/`: best layouts found on the test cities.
- `docs/superpowers/specs/` and `plans/`: design documents.
