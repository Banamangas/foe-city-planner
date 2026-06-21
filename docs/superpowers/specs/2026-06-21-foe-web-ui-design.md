# FoE City Layout Optimizer — City-Editor Web UI Design

**Date:** 2026-06-21
**Status:** Approved (brainstorming) — ready for implementation planning

## 1. Purpose

A local web UI to **curate a city's building set** (remove unwanted buildings, add new ones) and
**re-pack** it with the optimizer, viewing the result map inline. It makes the `layout` engine usable
without the CLI and adds light editing the CLI can't do.

## 2. Scope

- **Form factor:** a local web app — a Flask server you run, opening in the browser. Single-user, local.
- **First runtime dependency:** Flask (the project was stdlib-only; this is the agreed exception, runtime
  only — tests/optimizer core stay stdlib).
- **Run modes exposed:** Re-pack (`layout`/`repack`, single seed) and Parallel sweep (multi-seed,
  `scripts/sweep.py` logic). `improve`/`roads` are out of scope.
- **Editing (MVP):** a building **list editor** — remove buildings, add buildings (width, length,
  needs-road, optional name). No drag/map-based placement.
- **Out of scope (MVP):** drag-to-place editing; exporting a FoE-importable game file; `improve`/`roads`
  modes; multi-user/hosting; auth.

## 3. Architecture

Two layers — a pure editing layer in the package, and thin Flask glue:

- **`foeopt/editing.py`** (pure, unit-tested, stdlib): turns a loaded layout + edits into a `Layout`
  ready for `repack`.
- **`webapp/`** (Flask): `app.py` (endpoints + background-job runner), `static/` (one HTML page + JS +
  CSS). Reuses `foeopt.loader`, `foeopt.packer.repack`, `foeopt.report`, `foeopt.viz`,
  `foeopt.validate`.
- **`scripts/sweep.py`** logic is reused for the sweep mode (a shared helper in `webapp` or a thin call
  into the same parallel routine).

### 3.1 `foeopt/editing.py`

```
AddSpec = {width: int, length: int, needs_road: bool, name: str | None}

def apply_edits(loaded: Layout, remove_ids: set[int], add_specs: list[AddSpec]) -> Layout
```
- Keeps `loaded.region` and `loaded.townhall` unchanged.
- Drops every building whose `entity_id` is in `remove_ids` (the Townhall cannot be removed — ignored if
  passed).
- Appends one `Building` per `AddSpec`: a fresh unique `entity_id` (max existing + 1, incrementing),
  `cityentity_id="custom"`, `type="custom"`, `Footprint(0, 0, width, length)` (position irrelevant —
  `repack` ignores positions), `needs_road=spec.needs_road`, `road_level=1 if needs_road else 0`,
  `is_townhall=False`, `set_id=None`, `chain_id=None`, `name=spec.name or "Custom <w>x<l>"`.
- Validates `AddSpec`: `width >= 1`, `length >= 1` (raise `ValueError` otherwise).
- Returns `Layout(region=loaded.region, buildings=<kept + added>, townhall=loaded.townhall, roads={})`.

### 3.2 Endpoints (`webapp/app.py`)

- `POST /load` (multipart file upload) → save to a temp file, `load_layout(path)`, return JSON:
  `{buildings: [{entity_id, name, width, length, needs_road, off_grid}], region_cells, road_estimate,
  townhall_id}`. `off_grid` buildings (anchor outside region) are flagged and shown but excluded from
  packing/edits.
- `POST /run` (JSON `{remove_ids, add_specs, mode, budget, seed, seeds, workers}`) → `apply_edits(...)`
  on the last-loaded layout, start a background job, return `{job_id}`. `mode ∈ {"repack","sweep"}`.
- `GET /status/<job_id>` → `{state: "running"|"done"|"error", elapsed, error?, result?}` where
  `result = {placed, unplaced, roads, estimate, valid, map_html}` and `map_html` is `render_html` of the
  optimized layout.
- `GET /` → the single page; `GET /static/...` → JS/CSS.

State: the server keeps the last loaded `Layout` and a dict of jobs in memory (single-user local app).

### 3.3 Jobs

Each `/run` spawns a `threading.Thread` that calls `repack(edited, budget_seconds=budget, seed=seed)`
(repack mode) or the parallel sweep helper (sweep mode: `seeds`, `workers`), stores the result/elapsed,
and marks the job done/error. The page polls `/status` (~1 s) and shows elapsed time; on `done` it
injects `map_html` and the stats line. No per-trial progress streaming in MVP.

## 4. The page (single HTML + JS + CSS)

1. **Load**: file picker → `POST /load` → render the building table + region size + estimate.
2. **Building table**: rows (name, `w×l`, road-need badge, remove toggle). Off-grid rows visibly locked.
3. **Add building**: width, length, needs-road checkbox, optional name → adds a pending row (client-side
   list of `add_specs`).
4. **Run panel**: mode toggle (Re-pack / Sweep), budget (seconds, default 30), seed (default 0); sweep
   reveals seeds (default 8) + workers (default = cores). "Run" → disabled + spinner + elapsed via
   polling.
5. **Result**: stats line (`placed P/T · unplaced U · roads R (est E) · valid`) + the optimized map
   inline + **Download map** (saves the `map_html`).

Styling: a clean, single dark-themed page consistent with the existing map palette
(`COLOR_BACKGROUND`/`COLOR_ROAD_BUILDING`/etc. from `viz.py`). No frontend framework — vanilla JS.

## 5. Errors

- Invalid upload (not a recognizable city file) → `/load` returns 400 with a message shown in the UI.
- Invalid `AddSpec` (size < 1) → 400 with the field error.
- Job error (e.g., `repack` raised) → `/status` returns `state:"error"` + message; UI shows it.
- Re-pack leaving unplaced buildings is **not** an error — it's reported (`unplaced U`) as the honest
  best-effort result, same as the CLI.

## 6. Testing (TDD)

- **`foeopt/editing.apply_edits` unit tests:** remove excludes a building; remove ignores the Townhall;
  add appends with correct fields (unique ids, road_level, default name); region/townhall preserved;
  building conservation (kept + added counts); `ValueError` on size < 1.
- **Endpoint tests (Flask test client):** `/load` with a small fixture city returns the building list +
  estimate; `/run` (repack, tiny budget) then `/status` returns a valid result with `map_html`
  non-empty; bad upload → 400.
- **Existing 105 tests stay green** (editing/webapp are additive; the optimizer core is untouched).
- Flask is added as a dependency in the project metadata; tests that need it import `flask` (skipped
  with a clear message if unavailable, or declared a test dependency).

## 7. Risk / limitations

- First runtime dependency (Flask) — contained to `webapp/`; the core/CLI remain stdlib.
- In-memory single-user state (last layout + jobs) — fine for a local tool, not multi-user.
- Long runs block only that job's thread; the UI stays responsive via polling. Sweep can saturate cores
  (documented; `workers` is adjustable).
- No game round-trip: results are viewed/downloaded as HTML maps, not re-importable into Forge of
  Empires.
