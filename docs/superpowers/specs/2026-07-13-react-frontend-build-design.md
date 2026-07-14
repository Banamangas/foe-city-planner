# React Frontend Build (Phases 3+4) Design

**Date**: 2026-07-13
**Status**: Approved (pending spec review)

## Goal

Build the full FoE City Planner frontend against the Phase-2 JSON API: load a
city (client-side bloat-stripping), view it on an interactive map, browse/filter
buildings, run the roads-first optimizer with live any-time-best streaming, and
save/export results. This combines the productionization design's Phase 3
(viewing) and Phase 4 (optimize/SSE) into one build. It supersedes the
Phase-3/Phase-4 split in
`docs/superpowers/specs/2026-07-12-roads-first-webapp-productionization-design.md`;
that document remains the source of truth for the overall architecture, API
contract, and SQLite schema, all of which are unchanged.

## Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Scope | Combine Phase 3 + Phase 4 (view **and** optimize in one build) |
| Frontend stack | React 18 + Vite + TypeScript, `zustand`, native `fetch`/`EventSource`, one plain dark CSS file, no component library |
| City strip worker | Simple parse-then-strip (`JSON.parse` whole file, then strip bloat) — not the streaming extractor |
| Frontend tests | Vitest for pure logic only (strip worker, coord/geometry helpers, api SSE parsing); no Canvas/DOM interaction tests |
| Old static UI | Deleted in this phase once the React app renders |
| Backend change | Add `origin: [min_x, min_y]` to `layout_to_view` so SSE grid coords align with the base map |

Everything else (routes, SSE event shapes, SQLite schema, palette) is inherited
unchanged from the productionization design.

## Backend addition: grid origin in `layout_to_view`

**Problem.** The base map is delivered by `map_view = layout_to_view(layout)`,
whose coordinates are already offset by `-min_x,-min_y` and multiplied by
`cell`. SSE `improvement` events are compact **absolute grid** coords
(`roads: [[x,y],...]`, `buildings: {id: [x,y,w,l]}`) with no origin. The frontend
therefore cannot place optimized roads/buildings onto the same coordinate frame
as the base map.

**Fix.** `layout_to_view` gains `"origin": [min_x, min_y]` in its returned dict
(alongside the existing `cell`). The frontend renders everything in **grid
space** — it converts base-map pixel coords back to grid via `px / cell` (already
relative) and converts SSE absolute grid coords to the same relative frame via
`(x - min_x, y - min_y)`. The Canvas transform matrix (`scale = cell * zoom`)
does all pixel scaling. This is a small, additive, separately-tested change to
`foeopt/viz.py`; the existing pixel fields stay for backward compatibility with
`test_viz.py` and any `render_html` consumers.

## Frontend architecture

```
frontend/
├── package.json          # react, react-dom, zustand; dev: vite, typescript, vitest, @vitejs/plugin-react
├── vite.config.ts        # /api → http://localhost:5000 proxy; build.outDir = ../webapp/dist
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx           # sidebar (300px) + map layout
    ├── api.ts            # fetch helpers + EventSource wrapper + SSE-event parsing
    ├── types.ts          # CityMapData, BuildingView, RoadView, Improvement, etc.
    ├── geometry.ts       # grid<->pixel helpers, buildingAt hit-test, bounds-fit
    ├── stores/cityStore.ts   # zustand: city, mapView, buildings, optimized layout, job state
    ├── components/
    │   ├── LoadPanel.tsx
    │   ├── CityMap.tsx
    │   ├── BuildingsPanel.tsx
    │   ├── OptimizePanel.tsx
    │   ├── ResultPanel.tsx
    │   └── Sidebar.tsx
    ├── workers/stripCity.worker.ts
    └── styles.css
```

### Data flow

1. **Load.** `LoadPanel` reads the file, hands it to `stripCity.worker`, which
   returns the slim payload. `POST /api/load` → `{city_id, buildings,
   region_cells, road_estimate, map_view}`. Store `map_view` (base) + `buildings`
   in the zustand store. "Load cached city": `GET /api/cities` lists them,
   `GET /api/cities/<id>` returns the stored slim `payload`, and the frontend
   re-POSTs that `payload` to `/api/load` to obtain `map_view` (hash-dedup
   returns the same `city_id`; no 93MB re-parse). `.city` import works the same
   way (parse the uploaded slim JSON → `POST /api/load`). No new backend route.
2. **View.** `CityMap` draws region → current roads → optimized roads →
   buildings from the store, in grid space under a pan/zoom transform.
   `BuildingsPanel` renders the buildings summary with search + type filter.
3. **Optimize.** `OptimizePanel` `POST /api/optimize {city_id, time_box}` →
   `{job_id}`, then opens `EventSource('/api/stream/<job_id>')`. On
   `improvement`, convert the compact layout to the store's grid frame using
   `origin` + `cell`, update optimized roads/buildings, and update
   `ResultPanel` stats. On `done`, finalize. "Stop" → `POST /api/stop/<job_id>`.
4. **Persist.** `ResultPanel` saves the best layout (`POST /api/layouts`), lists
   history (`GET /api/layouts?city_id=`), loads a past layout onto the map, and
   exports (`GET /api/cities/<id>/export`, layout as a client-side JSON download).

### `stripCity.worker.ts` (simple parse-then-strip)

```
onmessage(file):
  post {phase: "parsing"}
  data = JSON.parse(await file.text())
  post {phase: "stripping"}
  for each entry in data.CityEntities:
    keep {id, width, length, name,
          requirements: {street_connection_level},
          abilities: [ability objects reduced to their setId/chainId keys],
          components: {k: {placement: {size}}}}
  pass CityMapData and UnlockedAreas through unchanged
  post {phase: "done", slim}
```

Runs off the main thread so the ~93MB `JSON.parse` doesn't freeze the UI. Slim
payload is ~3–5MB. Progress is phase-granular (parsing/stripping/uploading/done),
not byte-accurate.

### `CityMap.tsx`

- Canvas 2D. State `{offsetX, offsetY, scale}`; `ctx.setTransform(cell*scale, 0,
  0, cell*scale, offsetX, offsetY)` so drawing is in grid units.
- Wheel zoom (clamped), drag pan, zoom-to-fit to region bounds.
- Toolbar toggles: current roads / optimized roads.
- Tooltip: `onMouseMove` → inverse-transform to grid → `buildingAt` hit-test →
  absolutely-positioned div (`name (w×l) · road status`).
- Redraw on store change and on transform change.

## Testing

### Frontend (Vitest, logic only)
- `stripCity.worker` logic (extract the pure strip function): feeds a small
  combined JSON, asserts bloat dropped and slim fields preserved (incl.
  `components.*.placement.size` fallback and `setId`/`chainId` retention).
- `geometry.ts`: grid↔pixel round-trip, `buildingAt` hit-test, bounds-fit.
- `api.ts`: SSE-event parsing (`improvement`/`heartbeat`/`done` lines →
  structured objects); compact-layout → grid-frame conversion using `origin`.

No Canvas/DOM interaction tests (brittle, low value here).

### Backend (pytest)
- Extend `test_viz.py`: `layout_to_view` returns `origin == [min_x, min_y]`;
  existing view assertions still hold.
- Full suite stays green.

### Manual end-to-end smoke (verification gate)
Load `darkzig.json` in the browser → map renders → optimize ~1 min → live
improvements appear → Stop → save + export a layout. Plus `npm run build`
succeeds and Flask serves `webapp/dist/`.

## Cutover

- `app.py`: serve `webapp/dist/index.html` at `/` and `webapp/dist/` assets;
  fall back to `index.html` for client routes. Keep serving during dev via the
  Vite proxy (`npm run dev` at :5173 → Flask :5000).
- Delete `webapp/static/{index.html,app.js,style.css}` and reduce/remove the two
  old-static-serving tests in `test_webapp.py` (replace with a "serves built
  index" check, guarded to skip when `webapp/dist/` is absent so pytest passes
  without a build).
- `.gitignore` already covers `frontend/node_modules/`, `webapp/dist/`.

## Non-goals

- No streaming byte-accurate strip (deferred; parse-then-strip is enough).
- No component/interaction test suite.
- No auth, no multi-user, no deployment tooling.
- No changes to the optimizer, SQLite schema, or API routes beyond the
  `origin` addition.
```
