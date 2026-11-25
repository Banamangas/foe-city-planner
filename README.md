# FoE City Planner

Rearranges your Forge of Empires city so it needs as few roads as possible.

## Why

Every road tile in a Forge of Empires city is a tile that holds no building.
Fitting a city around fewer roads by hand is slow and hard. This tool does it
for you: it finds layouts with fewer roads, where every building that needs a
road is still connected to the Town Hall.

It runs on your own computer. Your city never leaves it, and there are no
accounts, telemetry or uploads. The only thing the app downloads is the public
list of game buildings.

## What it does

1. **Reads your city** from the file the Forge Hammer planner exports.
2. **Checks it:** points out buildings that need a road but have none (you say
   whether that's intended), relinks chain pieces that came apart, and asks the
   size of any building it doesn't know yet.
3. **Lets you edit it:** remove buildings, or add buildings from your storage
   or from the full building list.
4. **Optimizes it** for the time you choose (minutes, not hours), showing the
   progress and the road count as it improves.
5. **Shows every layout it found**, best first, next to your current city, with
   before → after numbers: roads, road efficiency, coverage, free area, and
   buildings with and without roads.
6. **Saves the layout you pick** as a file you load back into Forge Hammer.

Every layout passes a full check against the game's rules before you see it.
Buildings never rotate, and nothing is lost or left disconnected.

## How it works

- **The optimizer** (Python, `foeopt/`) works roads-first: it proposes many road
  networks of a given size, then asks a constraint solver (CP-SAT, from Google
  OR-Tools) whether every building can fit around one. It keeps shrinking the
  network while the buildings still fit. Polishing steps then re-solve the best
  networks and try small changes to remove more roads. The work is spread over
  several processes, sized to your computer so it stays usable during a search.
- **The app** is a small local web server (Flask) with a React + TypeScript
  interface, in French and English. The desktop version packs Python, the
  solver and the interface into one file per system (PyInstaller) and shows
  them in the app's own window (pywebview), or in your browser on Linux.
- **The building list:** Forge Hammer files only carry each building's game id.
  Names, sizes, road needs and chains come from a building list that a daily
  GitHub job refreshes from the game data. The app picks up new buildings at
  startup, with no new release needed.
- **Builds:** GitHub Actions builds and tests the Windows, macOS and Linux apps,
  and publishes them on the Releases page.

## Use it

### Players: the app (nothing to install)

1. Download the file for your computer from the
   [Releases page](../../releases/latest). The [download guide](docs/download.md)
   shows which file to pick and how to get past the "unknown app" warning
   Windows and macOS show the first time.
2. In Forge Hammer, export your city to a file.
3. Open the app and follow its five steps:
   - **Load city:** drop the file.
   - **Buildings:** remove or add buildings, or just press Next.
   - **Optimize:** pick a run time and press Start. Longer runs usually find
     fewer roads. You can stop early and keep what was found.
   - **Choose:** compare the layouts and pick one.
   - **Export:** save the file, then import it into Forge Hammer.

The app remembers your last city and where you were, so closing it loses
nothing. It keeps only that one city: it doesn't fill your disk.

### Advanced: install from source

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 18+ for
the interface.

    git clone https://github.com/Banamangas/foe-city-planner.git
    cd foe-city-planner
    uv sync
    cd frontend && npm ci && npm run build && cd ..
    uv run python -m webapp.app      # then open http://localhost:5000

From there you can:

- **Use the same wizard in your browser**, at `http://localhost:5000`.
- **Tune the optimizer** on the advanced page (`/advanced`): every option,
  presets, a city library and saved layouts. It also reads FOE Helper exports.
- **Script it from the command line:** view a city, optimize roads with
  buildings fixed, re-pack a city, check a layout's legality, and run long
  searches.
- **Run or build the desktop app** for your own system.
- **Refresh the building list** yourself.

The commands for all of these are in the
[command line and developer reference](docs/cli.md). For the daily building
list job, see [docs/building-list.md](docs/building-list.md).

Your own city files contain player names and ids. The usual file names are
already ignored by git; keep any others out of commits too.
