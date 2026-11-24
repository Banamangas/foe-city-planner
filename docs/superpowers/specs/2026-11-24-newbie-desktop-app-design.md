# Newbie desktop app — design

Date: 2026-11-24. Status: draft for the user's approval.

## Intent and why

Turn the optimizer into something any Forge of Empires player can use with no IT
knowledge: download one thing, drop in the city file they exported from the
Forge Hammer planner, press one button, watch it work, pick a layout, save the
file, import it back into Forge Hammer.

The long-term ideal is a website, but a server running everyone's optimizations
costs money that grows with use and there is no budget for it. So for now the
optimizer runs on each player's own computer, as a downloadable app. The design
should not close the door on a hosted version later (same screens, different
backend location).

## Who it serves

Players who know the game well but may know nothing about computers: they don't
know what a JSON file is, have never opened a terminal, and will not read a
settings page. Experienced players use the same app; what they want extra is
numbers (road count, road efficiency, coverage, buildings with/without roads),
not more knobs.

## Goals

1. **One download per system, nothing else to install.** Windows first; Mac and
   Linux builds where practical.
2. **A five-step wizard (user's choice of design "A")**, one screen per step with
   Back/Next, so nobody gets lost:
   1. **Load city** — one drop zone ("Drop your city file here" / "Choose file").
      Never says "JSON". A "How to export your city from Forge Hammer" link opens
      a short picture guide. The screen says the city never leaves the computer.
   2. **Buildings** — the city map; click a building to remove it (click again to
      keep it), an "Add a building" button. Remove/add is kept in every version
      of the app (user requirement). "Nothing to change? Just press Next."
   3. **Optimize** — run time choice (presets, e.g. 2 / 5 / 15 min, plus custom),
      a Start button, a progress bar, the current phase shown as a short
      checklist in plain words (user: even if they don't understand it, it shows
      the tool does different things), and live numbers: roads so far, layouts
      found, time left. A "Stop now and keep what's found" button. A line
      showing what the machine check chose ("This computer: 8 cores, using 6").
   4. **Choose** — **every** layout the run found is available for picking
      (user: "all layouts found"), as cards sorted by road count, best first,
      with the player's own city as the last card for comparison; the selected
      one shown big, and a before → after panel (see Stats below). Today the
      runner only publishes strict improvements; it must also keep every other
      distinct layout that passes the full legality check (e.g. objective
      polish's other validated networks, mutation-climb acceptances).
   5. **Export** — one "Save file for Forge Hammer" button and a "How to import
      it" picture guide; "Start again with another city".
3. **Best-known settings by default, no settings screen.** Every optimizer option
   uses the current best preset (`BEST_PRESET`). The only user-facing choices are
   run time and building edits.
4. **Machine check.** At launch the app reads the core count (and memory) and
   picks the parallelism so an older computer or laptop is not overloaded and
   the computer stays usable during a run. Today's 6 workers x 2 threads is for
   a strong 8-core / 16-thread CPU; smaller machines get less. Below a minimum
   (e.g. 2 cores) it warns but still runs. On a reduced setting the app says
   plainly that results may be a little worse and a longer run helps.
5. **Light on storage.** No city library and no accumulated saved runs: it keeps
   the last city and the user's choices, plus whatever files the user saves.
   (Today's webapp caches every uploaded city in SQLite; the app does not.)
6. **French and English**, with every user-facing text in a per-language
   translation file so another language is added by adding a file. Default to
   the system language, with a switch.
7. **Unsigned builds with a picture walkthrough** (user's decision: no budget for
   code signing). The download page and first-run guide show how to get past
   "Windows protected your PC" (More info → Run anyway) and the Mac Gatekeeper
   block (right-click → Open, or Privacy & Security → Open anyway).

## Stats (before → after panel, user-confirmed)

- **Roads**: road cell count.
- **Road efficiency**: see below.
- **Coverage**, as % of the unlocked area: buildings, roads, and **free area**
  (also shown as a square count).
- **Buildings with roads**: need a road and are connected.
- **Buildings without roads**: don't need a road at all.

## Checks shown after loading (step 1 → 2)

- **Unconnected buildings.** If the uploaded city has buildings that need a road
  but aren't connected, show a warning listing them and ask whether that's
  intended. Not intended → the run connects them (today's default,
  `military=connect`). Intended → they stay off the road (`military=unconnected`;
  today that option covers two-lane/military buildings only, so extending it to
  any road-needing building is part of the work).
- **Unlinked chains.** If a chain's main building and its pieces are in the city
  but not linked to each other, tell the player they will be linked back, and
  link them. **This does not exist today** (checked 2026-11-24): linked groups
  are kept as rigid blocks (`foeopt/chains.py`), but unlinked pieces are treated
  as separate buildings and never relinked; only a patch *added* through the
  edits is auto-linked (`foeopt/editing.py`). The relink should reuse that
  add-patch logic (patch attaches at the free end slot of its main's chain).

## Road efficiency (user's definition)

> Required road area divided by built road area. Required means, for each
> connected building, its shorter side × road level (1 or 2) ÷ 2.

Shown as a percentage; above 100% means roads are shared well. The optimizer's
internal anchor `sigma_half` in `foeopt/bounds.py` is the same sum without the
road level; the displayed figure must include the level (2 for two-lane roads).

## Building list kept up to date (user-approved: daily GitHub copy)

A Forge Hammer file only carries each building's game id (`cityentity_id`), no
name, size or road need; the app looks those up in its building list
(`foeopt/data/catalog.json`, built by `scripts/build_catalog.py`). New event
buildings must reach players without a new app release, and without shipping an
API key (a key inside a downloadable app is public).

- **Source:** the user's FOE Buildings API, raw exports
  `GET /data/download/building_entity_lookup.json` (the game's full
  CityEntities, ~68 MB) and `building_chains.json`. Not the typed `/api/v1`
  endpoints: they only cover the newest building format and miss road level
  and chain data (user, 2026-11-24).
- **Checked 2026-11-24:** slimming the 68 MB export with the existing
  `build_catalog.trim` gives 2,894 buildings in 673 KiB (46 KiB gzipped). On the
  2,844 buildings both lists share, size, road level, chain id, link positions
  and chain heads are identical. The export has 50 buildings the app lacks; the
  app has 43 the export lacks (old `R_`/`D_` buildings players may still own), so
  the update **merges** (new data wins, old entries are kept). Newer
  `GenericCityEntity` buildings have no `type`: keep the previous type when the
  new one is empty. Export names are English only; French names come from the
  API's `/building-names` (en + fr) or the previous list.
- **Job:** a scheduled GitHub Actions workflow in this (public) repo, once a day
  plus a manual "Run workflow" button. It checks `/status` (last update) and
  stops if nothing changed; otherwise it downloads the export, slims and merges
  it, runs a sanity check (no building lost, sizes valid), and publishes only the
  slim file as an asset on a fixed release (tag `catalog`), overwritten each
  time: no daily commits, a stable download URL. The 68 MB export is never
  stored on GitHub. The key is a repository secret (`FOE_API_KEY`), ideally a
  dedicated read-only key that can be revoked on its own.
- **App:** ships with the list current at release time; at startup downloads the
  published file if newer (a plain GET of a public file; nothing about the city
  is sent), keeps it, and falls back to the last copy offline. A building still
  unknown → the app asks the player for its size and road need.

## Non-goals

- A hosted website (later, budget permitting).
- An "advanced settings" section (my call: none in the first version; the
  existing webapp stays available for development and tuning).
- Accounts, cloud sync, telemetry, or anything that sends data out (the only network use is downloading the public building list). City files
  contain player names and IDs; nothing leaves the computer.
- Code signing.
- Changing the optimizer's algorithm.

## Anti-goals (failure even if it works)

- The player sees a terminal window, a Python error, or a word like "JSON",
  "worker", "CP-SAT", "k-walk".
- A run makes a laptop unusable or overheats it with no warning.
- The app silently fills the disk.
- A result that is not legal in the game (every layout still goes through the
  full legality check; buildings never rotate).

## Constraints

- Builds on what exists: Python optimizer (`foeopt`, dependencies flask +
  ortools), Flask backend (`webapp/`), React + TypeScript frontend (`frontend/`),
  Forge Hammer v3 import/export (`foeopt/loader.py`, `foeopt/export_v3.py`),
  building edits (`foeopt/editing.py`).
- The optimizer uses multiprocessing (persistent worker processes, a pool in the
  mutation phase). A bundled app must keep that working on Windows and Mac
  (spawn start method, frozen-executable entry point).
- Results depend on available CPU (wall-clock limits): fewer threads or a busy
  computer find somewhat worse layouts. That is accepted; the app says so rather
  than hiding it.

## Decided

| Decision | By |
|---|---|
| Downloadable app now, website later | user |
| Windows mainly, Mac and Linux if possible | user |
| Wizard layout (design A, five steps above) | user |
| Run time, progress bar, phase list visible | user |
| Stats: roads, road efficiency, coverage, buildings with/without roads | user |
| Remove/add buildings in every version | user |
| Road efficiency formula as quoted | user |
| French + English, extensible | user |
| No code signing, picture walkthrough instead | user |
| Bundle Python + solver + built frontend into one download per OS (e.g. PyInstaller) | my call |
| Opens in its own window (e.g. pywebview), falling back to the default browser if a native window is unavailable | my call |
| Distribution on the project's GitHub Releases page | my call |
| Expected size ~100–150 MB, to be measured | my call (estimate) |
| No advanced settings section in v1 | my call |
| Every legal layout found is pickable | user |
| Stats incl. road coverage and free area (% and squares) | user |
| Unconnected-buildings prompt; unlinked chains relinked and announced | user |
| Accept Forge Hammer (v3) files only in v1; other formats get a friendly "export from Forge Hammer" message (export back needs a v3 original) | my call |
| Keep the last run's result (one copy, overwritten) so closing the window loses nothing; closing mid-run asks first | my call |
| Add a building: the player's stored buildings first, a search over the full catalog below | my call |
| Building list: daily GitHub copy of the API's raw export, slimmed; key stays a GitHub secret | user |
| Published as an overwritten release asset (tag `catalog`), not daily commits | my call |
| Unknown building after all that → ask the player for size and road need | my call |

## Left to the builder

- Packaging tool and window library specifics; CI that builds the three OS
  packages.
- The exact core → workers/threads table for the machine check (it should leave
  headroom, e.g. a core or two, and keep 6x2 on 8-core/16-thread machines).
- Plain-language phase names mapped from the optimizer's real phases (walk,
  objective polish, rebase polish, mutation climb, exact finish), and adding
  phase/progress events to the runner if it doesn't report them already.
- How the app frontend relates to today's webapp frontend (new simplified
  screens over the same API is the expected shape).
- Translation file format and language switch.
- The picture guides' content (export from Forge Hammer, import back, OS
  warnings).
- Where "last city and choices" are stored per OS.
