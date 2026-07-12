# Roads-First Webapp Productionization Design

**Date**: 2026-07-12  
**Status**: Approved (pending spec review)

## Goal

Rebuild the FoE City Planner webapp into a modern, practical tool that integrates
the roads-first CP-SAT optimizer. The user wants it to feel snappy, not bloated —
the current synchronous 93MB upload + `json.load()` parse with zero progress
feedback must be replaced.

## Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Primary goal | Full UX overhaul (roads-first as one mode in a modern webapp) |
| Frontend stack | React + Vite + TypeScript; Flask becomes pure JSON API |
| City load strategy | Client-side pre-filter (Web Worker strips bloated CityEntities fields, sends ~5MB slim payload) |
| Optimizer modes | Roads-first only (repack/sweep/anneal removed) |
| ortools dependency | Hard dependency in pyproject.toml |
| Optimization UX | Time-boxed + any-time best (SSE streams improvements live) |
| Map interaction | Pan + zoom + tooltip (Canvas with transform matrix) |
| Persistence | Server-side SQLite cache + export/import (.city and .layout.json files) |

## Architecture

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│   React + Vite SPA      │         │   Flask JSON API             │
│   (TypeScript)          │         │   (pure backend, no HTML)    │
│                         │  POST   │                              │
│  ┌─────────────────┐    │ ──────> │  /api/load                   │
│  │ Load panel       │    │  slim   │   → parse slim payload      │
│  │ (Web Worker      │    │  ~5MB   │   → cache to SQLite         │
│  │  strips bloat)   │    │  JSON   │   → return city_id          │
│  └─────────────────┘    │         │                              │
│                         │         │                              │
│  ┌─────────────────┐    │  POST   │  /api/optimize              │
│  │ Optimize panel   │ ──────────> │   → start RoadsFirstSearch  │
│  │ (time-box slider)│    │  job_id │     on bg thread            │
│  └─────────────────┘    │         │                              │
│                         │  SSE    │  /api/stream/{job_id}       │
│  ┌─────────────────┐    │ <────── │   → yields best-so-far      │
│  │ City Map canvas  │    │ events │     layouts as found        │
│  │ (pan/zoom/tip)   │    │         │                              │
│  └─────────────────┘    │  POST   │  /api/stop/{job_id}         │
│                         │ ──────> │   → signals search stop      │
│  ┌─────────────────┐    │         │                              │
│  │ Building table   │    │  GET    │  /api/cities/{id}/export   │
│  │ (search/filter)  │ <─────── ─── │   → .city file              │
│  └─────────────────┘    │         │  /api/layouts/{id}/export   │
└─────────────────────────┘         │   → .json layout            │
                                    │                              │
                                    │   SQLite (cities.db)        │
                                    │   - cities (slim payload)    │
                                    │   - layouts (best-so-far)    │
                                    └──────────────────────────────┘
```

### Stack

- **Frontend**: React 18 + Vite + TypeScript. No UI component library. State via
  `zustand` (minimal, no provider boilerplate). HTTP via native `fetch` + `EventSource`.
  CSS: plain file (dark theme, ~50 lines). Canvas with native pan/zoom transform matrix.
  Web Worker for city file bloat-stripping.
- **Backend**: Flask 3 + SQLite (stdlib `sqlite3`). `ortools>=9` as hard dependency.
  Pure JSON API (`/api/...` routes). No server-rendered HTML.
- **Build**: `npm run dev` (Vite dev server at :5173, proxies `/api` to Flask :5000)
  for dev; `npm run build` outputs to `webapp/dist/`; Flask serves `webapp/dist/` in
  production, falling back to `index.html` for client-side routing.

## City Loading (Client-Side Pre-Filter)

### Bottleneck

Current flow uploads 93MB, writes to tempfile, reads back, and runs CPython
`json.load()` deserializing the entire JSON including bloated `CityEntities`
(one entity alone is 1.68MB of `abilities`/`components`/`entity_levels`). The
catalog only needs `width`, `length`, `requirements.street_connection_level`,
`abilities` (for `setId`/`chainId`), and `name`.

### Client-side flow (Web Worker)

1. User selects file (93MB).
2. Web Worker: `file.stream()` → hand-rolled streaming top-level key extractor
   (no npm dependency — the top-level structure is three known keys:
   `CityMapData`, `UnlockedAreas`, `CityEntities`).
3. Extract and pass through `CityMapData` (~475 entries, ~200KB) and
   `UnlockedAreas` (~156 entries, ~20KB) unchanged.
4. Strip each `CityEntities` entry to:
   ```json
   {
     "id": "...",
     "width": 5,
     "length": 5,
     "name": "...",
     "requirements": { "street_connection_level": 2 },
     "abilities": [ {"setId": "..."}, {"chainId": "..."} ]
   }
   ```
   Only these fields — `abilities`, `components`, `entity_levels` and all other
   bloat dropped. Resulting slim payload: ~3-5MB.
5. POST slim payload to `/api/load`.
6. Web Worker posts progress messages (bytes processed / total) to React.
   React shows progress bar: "Stripping bloat… 45MB / 90MB".

### Fallback (no `file.stream()`)

If the browser doesn't support `file.stream()` (Safari < 16.4), fall back to
uploading the raw file (existing `_save_tmp` + `load_layout` path), with a
server-side slim parser that skips bloated fields. UX degrades to "upload, wait"
but still works.

### Server-side `/api/load`

- Receives slim JSON (~5MB), validates keys, builds `Layout` via a new
  `load_layout_from_dict(data)` entry point (refactor `_build_combined` to accept
  a dict directly instead of a path).
- Computes city hash (SHA-256 of slim payload) for dedup — if already in SQLite,
  skip re-parsing.
- Stores slim payload + parsed building summaries in SQLite.
- Returns `{city_id, buildings, region_cells, road_estimate, current_roads}`.

### SQLite schema

```sql
CREATE TABLE cities (
  id TEXT PRIMARY KEY,          -- SHA-256 hash of slim payload
  payload BLOB NOT NULL,        -- slim JSON
  buildings JSON NOT NULL,      -- summary list for table
  region_cells INTEGER,
  road_estimate INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE layouts (
  id TEXT PRIMARY KEY,          -- uuid
  city_id TEXT NOT NULL REFERENCES cities(id),
  k INTEGER,
  achieved INTEGER,
  layout JSON NOT NULL,         -- {buildings: {id: [x,y,w,l]}, roads: [...]}
  roads_count INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);
```

## Optimization (Any-Time Best via SSE)

### Module: `foeopt/roads_first.py`

Extract from `scripts/exp_roads_first.py` into a clean importable module:

- `Pattern` dataclass, `generate_patterns`, `th_anchor_candidates`, `prefilter`,
  `probe`, `validate` — move in as-is (already pure functions).
- `RoadsFirstSearch` class wraps `run_search`:

```python
class RoadsFirstSearch:
    def __init__(self, layout, *, time_box, patterns=200, probe_limit=60,
                 workers=4, probe_workers=4, th_anchors="full", k_start="auto"):
        ...

    def run(self, on_improvement=None, on_status=None, should_stop=None):
        """
        on_improvement: callback(best_layout, k, achieved) — fires each time
                        a better validated layout is found.
        on_status:      callback(k, level_status, probes_done, probes_total)
                        — fires as each k-level completes.
        should_stop:    callable() -> bool — checked between probes; if True,
                        search wraps up and returns best-so-far.
        Returns: {verdict, best_layout, best_achieved, results, ...}
        """
```

- `on_improvement` fires inside `handle_result` (replaces disk-writing of
  `best-k*.json`).
- `should_stop` checked alongside the deadline — allows `/api/stop` to signal
  via a `threading.Event`.
- `on_status` fires after each `_probe_level` completes (replaces `print()`).

### Flask SSE endpoint

```python
@app.post("/api/optimize")
def optimize():
    city_id = request.json["city_id"]
    time_box = request.json["time_box"]
    layout = load_from_cache(city_id)  # rebuild Layout from SQLite
    search = RoadsFirstSearch(layout, time_box=time_box, ...)
    job_id = jobs.submit(search.run, on_improvement=..., should_stop=...)
    return jsonify(job_id=job_id)

@app.get("/api/stream/<job_id>")
def stream(job_id):
    def generate():
        while not jobs.is_done(job_id):
            improvement = jobs.pop_improvement(job_id)  # per-job queue
            if improvement:
                yield f"event: improvement\ndata: {json.dumps(improvement)}\n\n"
            else:
                yield f"event: heartbeat\ndata: {json.dumps(jobs.status(job_id))}\n\n"
            time.sleep(0.2)
        final = jobs.result(job_id)
        yield f"event: done\ndata: {json.dumps(final)}\n\n"
    return Response(generate(), mimetype="text/event-stream")
```

Each job has a thread-safe queue of improvement events. The search thread pushes
layouts to it; the SSE generator drains it. Heartbeat every 200ms keeps the
connection alive and sends status (current k, elapsed).

`/api/stop/<job_id>` sets a `threading.Event` that `should_stop` checks.

### SSE event format

```
event: improvement
data: {"k": 92, "achieved": 79, "roads": [[x,y],...], "buildings": {"id": [x,y,w,l],...}}

event: status
data: {"k": 88, "elapsed": 45.2, "phase": "probing"}

event: done
data: {"verdict": "DONE", "best_achieved": 79, "lowest_feasible_k": 92}
```

### React SSE consumer

- `EventSource` connects to `/api/stream/{job_id}` immediately after POSTing to
  `/api/optimize`.
- On `improvement`: parses roads + buildings, updates the Canvas, updates stats
  ("79 roads — improved from 92").
- On `status` (heartbeat): updates a progress panel (current k-level, elapsed
  time, phase).
- On `done`: shows final verdict, offers save layout to SQLite.
- "Stop" button calls `/api/stop/{job_id}` — search wraps up within ~1
  probe-limit cycle and sends a final `done` event.

### Layout serialization

Compact dict format (same as experiment script's `best-k*.json` output):

```json
{
  "k": 92, "achieved": 79,
  "roads": [[x, y], ...],
  "buildings": {"entity_id": [x, y, w, l], ...}
}
```

No nested objects, no field names per building. Fast to serialize/deserialize.
React reconstructs Canvas geometry from this.

## City Map (Pan + Zoom + Tooltip)

React Canvas component driven by JSON data (not server-rendered HTML).

### Component: `<CityMap />`

```
┌──────────────────────────────────────────┐
│  [Current roads] [Optimized roads]  [-][+]│  ← toolbar toggles + zoom buttons
├──────────────────────────────────────────┤
│         ┌─────────┐                      │
│         │ Townhall│  (red)               │  ← Canvas with transform matrix
│         └─────────┘                      │     (pan via drag, zoom via wheel)
│     ┌──┐ ┌──┐ ┌────┐                    │
│     │  │ │  │ │    │  (blue = road-needing)
│     └──┘ └──┘ └────┘                    │
│              ════  (green = optimized roads)
│              ════                        │
│                              ┌──┐       │
│                              │  │ (amber = no road needed)
│                              └──┘       │
└──────────────────────────────────────────┘
  Tooltip: "Armory of Ares (5×5) · needs road"
```

### Canvas rendering

- State: `{offsetX, offsetY, scale}` — applied as
  `ctx.setTransform(scale, 0, 0, scale, offsetX, offsetY)`.
- Wheel: `scale *= 1.1^(deltaY/100)`, clamped to [0.2, 8].
- Drag: `onMouseDown` captures pointer, `onMouseMove` updates `offsetX/Y`.
- Zoom-to-fit button resets to fit region bounds.
- `_CELL = 12` px per grid cell (same as current).

### Draw loop

Called on every state change:
1. Clear + fill background.
2. Fill region cells (dark gray).
3. If `showCurrent`: draw current roads (gray).
4. If `showOptimized`: draw optimized roads (green).
5. Draw buildings (red/amber/blue by type), stroke borders.

Re-render via `useMemo`. For a 475-building city this is ~500 fillRects per
frame — trivial for Canvas 2D, no virtualization needed.

### Data contract

React receives from the load response or SSE events:

```typescript
type BuildingView = {
  x: number; y: number; w: number; h: number;
  name: string; size: string; needs_road: boolean; townhall: boolean;
};
type RoadView = { x: number; y: number; level: number };
type CityMapData = {
  cell: number;
  width: number; height: number;
  region: [number, number][];
  buildings: BuildingView[];
  current_roads: RoadView[];
  optimized_roads: RoadView[] | null;
  palette: { ... };
};
```

A new `foeopt/viz.py:layout_to_view(layout)` function returns this dict (pure
data, no HTML template). `render_html` stays for CLI/export use, built on top of
`layout_to_view`.

### Tooltip

- `onMouseMove` on Canvas: convert mouse coords to grid coords via inverse
  transform.
- Hit-test against buildings (same `buildingAt` logic from current template).
- Show absolutely-positioned div with name, size, and road status.
- Hidden when not hovering a building.

### Current-vs-optimized

On initial load, `optimized_roads` is null (only current shown). When an SSE
improvement arrives, React parses the new layout and updates `buildings` +
`optimized_roads` — Canvas re-renders immediately. Both road overlays can show
simultaneously (current in gray, optimized in green) for visual diff.

## Buildings Panel + Persistence

### Buildings Panel

Simplified — no "keep" checkboxes (roads-first places all road-needing
buildings; the list is informational, not a gate to optimization).

```
┌─────────────────────────────────────────────────┐
│  Buildings (475 total · 88 road-needing)         │
│  [search: ___________________] [filter: all ▾]   │
│                                                 │
│  name              size      road   type        │
│  ─────────────────────────────────────────────  │
│  Town Hall         7×7       —      townhall   │
│  Armory of Ares    5×5       ✓      road       │
│  Watchfire          3×3      —      plain       │
│  ...                                             │
│                                                 │
│  [Add custom building: w×l, needs road, name]   │
└─────────────────────────────────────────────────┘
```

- **Search/filter**: text filter by name, dropdown by type
  (all/road-needing/plain/townhall). No virtualization needed (max ~500 rows).
- **Add custom buildings**: same form as current. Trash icon on added rows to
  remove.

### Persistence (SQLite cache)

Server endpoints:

```
GET  /api/cities                      → list cached cities
GET  /api/cities/{id}                 → city summary
GET  /api/cities/{id}/export          → .city file (slim JSON attachment)
POST /api/cities/import               → upload .city → dedup by hash → city_id
GET  /api/layouts                     → list saved layouts
GET  /api/layouts/{id}                → full layout JSON
GET  /api/layouts/{id}/export         → .json layout file (attachment)
POST /api/layouts                     → save a layout
DELETE /api/layouts/{id}              → delete a saved layout
```

### City loaded screen layout

```
┌────────────────────┬──────────────────────────────────────────┐
│  [Load New City ▾]  │                                          │
│  City: FR16         │                                          │
│  1026 bldgs · 92    │           <CityMap />                     │
│  current roads      │                                          │
│                     │                                          │
│  ─ Optimize ─       │                                          │
│  Time-box: [5min]   │                                          │
│  [Optimize] [Stop]  │                                          │
│                     │                                          │
│  ─ Best Result ─    │                                          │
│  79 roads (was 92)  │                                          │
│  saved [export]    │                                          │
│                     │                                          │
│  ─ Buildings ─      │                                          │
│  [search] [filter]  │                                          │
│  (scrollable table) │                                          │
└────────────────────┴──────────────────────────────────────────┘
  left sidebar (300px)        map fills remaining width, 70vh
```

After optimization, the result appears under "Best Result" with `k`,
`achieved`, `roads`, `efficiency%`. A "History" dropdown lists past runs on this
city. Clicking any past result loads it into the map.

### Export/import files

- `.city` file = the slim JSON payload (same format stored in SQLite).
  Re-importing loads instantly (no parsing of the 93MB original). Sharable
  between users.
- `.json` layout = the `{k, achieved, roads, buildings}` dict. Can be
  re-imported to view a saved layout without re-running the search.

## Project Structure

### New/changed files

```
foe-city-planner/
├── pyproject.toml                    # +ortools>=9
├── foeopt/
│   ├── roads_first.py                # NEW: RoadsFirstSearch class
│   ├── viz.py                        # ADD: layout_to_view() pure-data function
│   ├── loader.py                     # ADD: load_layout_from_dict()
│   └── ... (unchanged)
├── webapp/
│   ├── app.py                        # REWRITE: pure JSON API
│   ├── runner.py                     # REWRITE: RoadsFirstSearch job runner + SSE queue
│   ├── cache.py                      # NEW: SQLite cache
│   ├── static/                       # DELETE (replaced by built React app)
│   └── dist/                         # NEW: Vite build output (gitignored)
├── frontend/                         # NEW: React + Vite project
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                   # top-level layout (sidebar + map)
│       ├── api.ts                    # fetch helpers + SSE EventSource wrapper
│       ├── components/
│       │   ├── LoadPanel.tsx
│       │   ├── OptimizePanel.tsx
│       │   ├── CityMap.tsx
│       │   ├── BuildingsPanel.tsx
│       │   ├── ResultPanel.tsx
│       │   └── Sidebar.tsx
│       ├── workers/
│       │   └── stripCity.worker.ts
│       ├── stores/
│       │   └── cityStore.ts          # zustand store
│       └── styles.css
├── tests/
│   ├── test_roads_first.py           # NEW
│   ├── test_cache.py                 # NEW
│   ├── test_api.py                   # NEW (replaces test_webapp.py)
│   └── ... (existing tests unchanged)
```

### Removed

- `webapp/static/index.html`, `app.js`, `style.css` — replaced by React app.
- `scripts/exp_roads_first.py` — logic moves to `foeopt/roads_first.py`; script
  becomes a thin CLI wrapper (or deleted if no longer needed).

### Build/dev workflow

```bash
# Dev (HMR):
cd frontend && npm run dev     # Vite :5173, proxies /api → Flask :5000
uv run python -m webapp.app    # Flask API :5000
# Open http://localhost:5173

# Production build:
cd frontend && npm run build   # outputs to webapp/dist/
uv run python -m webapp.app    # Flask serves webapp/dist/ + /api/
```

### Tech choices

- State: `zustand` (minimal, no provider boilerplate).
- HTTP: native `fetch` + `EventSource` (no axios).
- CSS: plain CSS file (dark theme, like current `style.css`).
- No UI component library (MUI, etc.) — keep it lean.

### pyproject.toml

```toml
dependencies = ["flask>=3", "ortools>=9"]
```

### .gitignore additions

```
frontend/node_modules/
webapp/dist/
webapp/cities.db
```

## Testing

### Backend (pytest)

- `tests/test_roads_first.py` — `RoadsFirstSearch` unit tests:
  - `on_improvement` fires with correct `(layout, k, achieved)` on SAT.
  - `should_stop` interrupts between probes, returns best-so-far.
  - `on_status` fires after each k-level completes.
  - `k_start="auto"` resolves to `pick_k_start(layout)`.
  - FAMILY_TOO_WEAK verdict when fallback exhausts.
  - Existing selftest assertions (`ok_k1`, `ok_k0`, `parallel_equiv`) ported.
- `tests/test_cache.py` — SQLite CRUD: city dedup by hash, layout
  save/list/delete.
- `tests/test_api.py` — Flask endpoint tests (replaces `test_webapp.py`):
  - `POST /api/load` with slim payload → returns city_id + buildings.
  - `POST /api/load` with raw upload (fallback) → same.
  - `POST /api/optimize` → returns job_id.
  - `GET /api/stream/<id>` → SSE stream yields improvement events then done.
  - `POST /api/stop/<id>` → search stops, final `done` event sent.
  - Bad input → structured 400 JSON (never 500 HTML).
  - Export/import endpoints return correct file attachments.

### Frontend (Vitest + React Testing Library)

- `stripCity.worker.test.ts` — feeds a small combined JSON, asserts bloat fields
  stripped, slim fields preserved.
- `CityMap.test.tsx` — renders Canvas, simulates wheel zoom, drag pan, tooltip
  hit-test.
- `OptimizePanel.test.tsx` — mock EventSource, verifies improvement events
  update stats.

## Migration Plan (4 phases)

Each phase is independently shippable.

### Phase 1 — `foeopt/roads_first.py`

Extract `RoadsFirstSearch` + all pure functions from
`scripts/exp_roads_first.py`. Port existing `test_roads_first_parallel.py`
tests to test the new module. Keep the script as a thin CLI wrapper delegating
to the module. `exp_roads_first.py --selftest` still passes.

**Verification**: pytest passes (existing + new), `exp_roads_first.py --selftest`
passes.

### Phase 2 — Flask API + SQLite cache

Rewrite `webapp/app.py` as pure JSON API (`/api/...` routes). Add
`webapp/cache.py` (SQLite). Add `foeopt/loader.py:load_layout_from_dict()` for
slim payload. New `tests/test_api.py` + `tests/test_cache.py`. Old
`test_webapp.py` updated to hit new API endpoints. Old `webapp/static/` still
served temporarily.

**Verification**: pytest passes, API endpoints respond correctly via
`flask.test_client()`.

### Phase 3 — React frontend

Scaffold Vite + React + TypeScript. Implement `LoadPanel` + Web Worker
stripping + progress. `CityMap` Canvas with pan/zoom/tooltip. `BuildingsPanel`
with search/filter. Delete `webapp/static/{index.html,app.js,style.css}`.

**Verification**: pytest passes, `npm run build` succeeds, manual smoke test of
load + map render.

### Phase 4 — SSE + any-time best

Implement `OptimizePanel` + `EventSource` integration. `ResultPanel` + history +
export/import. SSE stream tests in `tests/test_api.py`. End-to-end: load
darkzig → optimize 1min → see live improvements → stop → export layout.

**Verification**: pytest passes (including SSE stream tests), `npm run build`
succeeds, manual end-to-end smoke test.