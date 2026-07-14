# React Frontend Build (Phases 3+4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full FoE City Planner frontend (React + Vite + TypeScript) against the existing Phase-2 JSON API: load/strip a city, view it on an interactive canvas, browse/filter buildings, run the roads-first optimizer with live SSE improvements, and save/export results.

**Architecture:** A Vite + React 18 + TypeScript SPA in `frontend/`, state in a `zustand` store, HTTP via native `fetch`/`EventSource`. It renders the map in **grid coordinates** under a Canvas transform matrix. The Flask API is unchanged except one additive field (`origin`) on `layout_to_view` so compact SSE layout updates align with the base map. In production, `npm run build` emits to `webapp/dist/`, which Flask serves; the old `webapp/static/` UI is deleted.

**Tech Stack:** React 18, Vite 5, TypeScript 5, zustand 4, Vitest 2; Python 3.12 / Flask 3 / pytest on the backend.

## Global Constraints

- Frontend stack: React 18 + Vite + TypeScript, `zustand`, native `fetch`/`EventSource`, one plain dark CSS file, **no UI component library**.
- City strip worker: **simple parse-then-strip** (`JSON.parse` whole file, then strip bloat). No streaming extractor.
- Frontend tests: **Vitest for pure logic only** (strip function, geometry helpers, api SSE parsing/conversion). No Canvas/DOM interaction tests.
- The map renders in **grid space**; the Canvas transform matrix does pixel scaling (`scale = cell * zoom`).
- Backend change is limited to adding `"origin": [min_x, min_y]` to `layout_to_view`; existing pixel fields stay for backward compatibility.
- API base path is `/api`; Vite dev server proxies `/api` → `http://localhost:5000`. `vite build` outputs to `../webapp/dist`.
- Node 22 / npm 11 are available. `.gitignore` already ignores `frontend/node_modules/`, `webapp/dist/`, `webapp/cities.db`.
- No comments in code unless the surrounding file already has them at that location.
- Existing API contract (do not change): `POST /api/load` → `{city_id, buildings, region_cells, road_estimate, map_view}`; `buildings` items are `{entity_id, name, width, length, needs_road, is_townhall}`; `map_view` is `layout_to_view(layout)`; `POST /api/optimize {city_id, time_box, ...}` → `{job_id}`; `GET /api/stream/<job_id>` streams `event: improvement|heartbeat|done`; improvement `data` = `{k, achieved, roads: [[x,y],...], buildings: {entity_id: [x,y,w,l], ...}}`; `POST /api/stop/<job_id>`; `GET /api/cities`, `GET /api/cities/<id>`, `GET /api/cities/<id>/export`, `POST /api/cities/import`; `GET/POST /api/layouts`, `GET /api/layouts/<id>`, `DELETE /api/layouts/<id>`.

---

### Task 1: Add `origin` to `layout_to_view` (backend)

**Files:**
- Modify: `foeopt/viz.py:124-142` (the `layout_to_view` return dict)
- Test: `tests/test_viz.py` (append)

**Interfaces:**
- Consumes: existing `_bounds(layout)`, `_CELL`.
- Produces: `layout_to_view(...)` return dict gains `"origin": [min_x, min_y]` (list of two ints). All existing keys unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_viz.py`:

```python
def test_layout_to_view_includes_grid_origin():
    from foeopt.viz import layout_to_view
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(3, 5, 2, 2),
                  False, 1, True, None, None, "TH")
    region = Region(frozenset((x, y) for x in range(3, 9) for y in range(5, 11)))
    lay = Layout(region, [th], th, {(3, 7): 1})
    view = layout_to_view(lay)
    assert view["origin"] == [3, 5]
    # base-map buildings stay relative (origin subtracted, times cell)
    assert view["buildings"][0]["x"] == 0
    assert view["buildings"][0]["y"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_viz.py::test_layout_to_view_includes_grid_origin -v`
Expected: FAIL with `KeyError: 'origin'`.

- [ ] **Step 3: Add `origin` to the return dict**

In `foeopt/viz.py`, change the `layout_to_view` return dict (starts at line 124) to add `origin` right after `cell`:

```python
    return {
        "cell": _CELL,
        "origin": [min_x, min_y],
        "width": width,
        "height": height,
        "region": region_cells,
        "buildings": buildings,
        "current_roads": road_list(layout.roads),
        "optimized_roads": road_list(optimized_roads) if optimized_roads else None,
        "palette": {
            "background": COLOR_BACKGROUND,
            "region": COLOR_REGION,
            "current_road": COLOR_CURRENT_ROAD,
            "optimized_road": COLOR_OPTIMIZED_ROAD,
            "townhall": COLOR_TOWNHALL,
            "road_building": COLOR_ROAD_BUILDING,
            "plain_building": COLOR_PLAIN_BUILDING,
            "border": COLOR_BUILDING_BORDER,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_viz.py -v`
Expected: PASS (all viz tests, including the two existing `layout_to_view` tests and the new one).

- [ ] **Step 5: Commit**

```bash
git add foeopt/viz.py tests/test_viz.py
git commit -m "feat: expose grid origin in layout_to_view for SSE alignment"
```

---

### Task 2: Scaffold the Vite + React + TypeScript project

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/src/vite-env.d.ts`

**Interfaces:**
- Produces: a buildable app. `npm run build` emits `webapp/dist/`. `npm test` runs Vitest (0 tests initially = pass). `App` renders a placeholder shell.

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "foe-city-planner-frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run --passWithNoTests",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^4.5.5"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`**

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:5000",
    },
  },
  build: {
    outDir: "../webapp/dist",
    emptyOutDir: true,
  },
  test: {
    environment: "node",
  },
});
```

- [ ] **Step 3: Create `frontend/tsconfig.json` and `frontend/tsconfig.node.json`**

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable", "WebWorker"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: Create `frontend/index.html`, `frontend/src/vite-env.d.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css`**

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>FoE City Planner</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

`frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

`frontend/src/App.tsx`:

```tsx
export function App() {
  return <div className="app">FoE City Planner</div>;
}
```

`frontend/src/styles.css`:

```css
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #141414;
  color: #e5e5e5;
  font: 14px/1.4 system-ui, sans-serif;
}
.app { display: flex; height: 100vh; }
```

- [ ] **Step 5: Install and verify build + test**

Run:
```bash
cd frontend && npm install && npm run build && npm test
```
Expected: `npm install` succeeds; `npm run build` writes `webapp/dist/index.html` + assets; `npm test` reports "No test files found" and exits 0 (Vitest treats no-tests as success with `vitest run`).

If `npm test` exits non-zero on "no tests", add `"test": "vitest run --passWithNoTests"` to `package.json` scripts and re-run.

- [ ] **Step 6: Commit**

```bash
git add frontend/ pyproject.toml
git commit -m "chore: scaffold Vite + React + TypeScript frontend"
```

(Note: `pyproject.toml` is unchanged here; drop it from the `git add` if git reports nothing for it.)

---

### Task 3: Types and geometry helpers

**Files:**
- Create: `frontend/src/types.ts`, `frontend/src/geometry.ts`
- Test: `frontend/src/geometry.test.ts`

**Interfaces:**
- Produces:
  - `types.ts`: `RoadView`, `BuildingView`, `MapView`, `BuildingSummary`, `LoadResponse`, `Improvement`, `CityListItem`, `LayoutListItem`.
  - `geometry.ts`:
    - `regionBounds(view: MapView): {minGX: number; minGY: number; maxGX: number; maxGY: number}` — grid-cell bounds derived from `view.region` pixel coords and `view.cell`.
    - `fitTransform(view: MapView, canvasW: number, canvasH: number): {offsetX: number; offsetY: number; scale: number}` — zoom-to-fit.
    - `screenToGrid(sx, sy, t, cell): {gx: number; gy: number}` — inverse transform to absolute grid cell.
    - `buildingAt(gx, gy, buildings): BuildingView | null` — hit-test in relative grid units.

- [ ] **Step 1: Write `frontend/src/types.ts`**

```ts
export type RoadView = { x: number; y: number; level: number };

export type BuildingView = {
  x: number; y: number; w: number; h: number;
  name: string; size: string; needs_road: boolean; townhall: boolean;
};

export type Palette = {
  background: string; region: string;
  current_road: string; optimized_road: string;
  townhall: string; road_building: string; plain_building: string; border: string;
};

export type MapView = {
  cell: number;
  origin: [number, number];
  width: number; height: number;
  region: [number, number][];
  buildings: BuildingView[];
  current_roads: RoadView[];
  optimized_roads: RoadView[] | null;
  palette: Palette;
};

export type BuildingSummary = {
  entity_id: string | number; name: string;
  width: number; length: number; needs_road: boolean; is_townhall: boolean;
};

export type LoadResponse = {
  city_id: string;
  buildings: BuildingSummary[];
  region_cells: number;
  road_estimate: number;
  map_view: MapView;
};

export type Improvement = {
  k: number; achieved: number;
  roads: [number, number][];
  buildings: Record<string, [number, number, number, number]>;
};

export type CityListItem = {
  id: string; region_cells: number; road_estimate: number; created_at: string;
};

export type LayoutListItem = {
  id: string; city_id: string; k: number; achieved: number;
  roads_count: number; created_at: string;
};
```

- [ ] **Step 2: Write the failing geometry test**

`frontend/src/geometry.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { regionBounds, fitTransform, screenToGrid, buildingAt } from "./geometry";
import type { MapView, BuildingView } from "./types";

const view: MapView = {
  cell: 12,
  origin: [3, 5],
  width: 72,
  height: 72,
  region: [[0, 0], [12, 0], [0, 12], [60, 60]],
  buildings: [
    { x: 0, y: 0, w: 24, h: 24, name: "TH", size: "2x2", needs_road: false, townhall: true },
    { x: 36, y: 24, w: 12, h: 12, name: "Hut", size: "1x1", needs_road: true, townhall: false },
  ],
  current_roads: [],
  optimized_roads: null,
  palette: {} as never,
};

describe("geometry", () => {
  it("regionBounds returns grid-cell bounds from pixel region", () => {
    expect(regionBounds(view)).toEqual({ minGX: 0, minGY: 0, maxGX: 5, maxGY: 5 });
  });

  it("fitTransform centers and scales to fit", () => {
    const t = fitTransform(view, 600, 600);
    expect(t.scale).toBeGreaterThan(0);
    expect(Number.isFinite(t.offsetX)).toBe(true);
    expect(Number.isFinite(t.offsetY)).toBe(true);
  });

  it("screenToGrid inverts the transform to absolute grid cells", () => {
    const t = { offsetX: 0, offsetY: 0, scale: 1 };
    // pixel (0,0) at cell 12 → grid-relative (0,0) → absolute (origin) (3,5)
    const g = screenToGrid(0, 0, t, view.cell, view.origin);
    expect(g).toEqual({ gx: 3, gy: 5 });
    // pixel (13,25) → relative cell (1,2) → absolute (4,7)
    expect(screenToGrid(13, 25, t, view.cell, view.origin)).toEqual({ gx: 4, gy: 7 });
  });

  it("buildingAt hit-tests in relative grid units", () => {
    const bs: BuildingView[] = view.buildings;
    // absolute grid (3,5) → relative (0,0) → inside TH (0..2, 0..2)
    expect(buildingAt(3, 5, bs, view.origin, view.cell)?.name).toBe("TH");
    // absolute grid (6,7) → relative (3,2) → inside Hut at rel (3,2) size 1x1
    expect(buildingAt(6, 7, bs, view.origin, view.cell)?.name).toBe("Hut");
    // empty cell
    expect(buildingAt(8, 9, bs, view.origin, view.cell)).toBeNull();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/geometry.test.ts`
Expected: FAIL — cannot import from `./geometry` (module not found).

- [ ] **Step 4: Write `frontend/src/geometry.ts`**

```ts
import type { MapView, BuildingView } from "./types";

export type Transform = { offsetX: number; offsetY: number; scale: number };

export function regionBounds(view: MapView) {
  const c = view.cell;
  let minGX = Infinity, minGY = Infinity, maxGX = -Infinity, maxGY = -Infinity;
  for (const [px, py] of view.region) {
    const gx = px / c, gy = py / c;
    if (gx < minGX) minGX = gx;
    if (gy < minGY) minGY = gy;
    if (gx > maxGX) maxGX = gx;
    if (gy > maxGY) maxGY = gy;
  }
  return { minGX, minGY, maxGX, maxGY };
}

export function fitTransform(view: MapView, canvasW: number, canvasH: number): Transform {
  const b = regionBounds(view);
  const cols = b.maxGX - b.minGX + 1;
  const rows = b.maxGY - b.minGY + 1;
  const cell = view.cell;
  const pad = 20;
  const sx = (canvasW - pad * 2) / (cols * cell);
  const sy = (canvasH - pad * 2) / (rows * cell);
  const scale = Math.max(0.05, Math.min(sx, sy));
  const contentW = cols * cell * scale;
  const contentH = rows * cell * scale;
  const offsetX = (canvasW - contentW) / 2 - b.minGX * cell * scale;
  const offsetY = (canvasH - contentH) / 2 - b.minGY * cell * scale;
  return { offsetX, offsetY, scale };
}

export function screenToGrid(
  sx: number, sy: number, t: Transform, cell: number, origin: [number, number],
): { gx: number; gy: number } {
  const relPxX = (sx - t.offsetX) / t.scale;
  const relPxY = (sy - t.offsetY) / t.scale;
  const gx = Math.floor(relPxX / cell) + origin[0];
  const gy = Math.floor(relPxY / cell) + origin[1];
  return { gx, gy };
}

export function buildingAt(
  gx: number, gy: number, buildings: BuildingView[],
  origin: [number, number], cell: number,
): BuildingView | null {
  const relX = (gx - origin[0]) * cell;
  const relY = (gy - origin[1]) * cell;
  for (const b of buildings) {
    if (relX >= b.x && relX < b.x + b.w && relY >= b.y && relY < b.y + b.h) {
      return b;
    }
  }
  return null;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/geometry.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/geometry.ts frontend/src/geometry.test.ts
git commit -m "feat(frontend): add types and grid geometry helpers"
```

---

### Task 4: City strip worker (pure function + worker wrapper)

**Files:**
- Create: `frontend/src/workers/stripCity.ts` (pure logic), `frontend/src/workers/stripCity.worker.ts` (worker wrapper)
- Test: `frontend/src/workers/stripCity.test.ts`

**Interfaces:**
- Produces:
  - `stripCity.ts`: `stripCity(data: any): any` — returns `{CityMapData, UnlockedAreas, CityEntities}` with each `CityEntities` entry reduced to `{id, width, length, name, requirements:{street_connection_level?}, abilities:[{setId?|chainId?}], components:{k:{placement:{size}}}}`. Missing fields are omitted, not invented.
  - `stripCity.worker.ts`: a module worker that posts `{phase}` then `{phase:"done", slim}`.

- [ ] **Step 1: Write the failing test**

`frontend/src/workers/stripCity.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { stripCity } from "./stripCity";

const fat = {
  CityMapData: { a: { id: 1, x: 0, y: 0, cityentity_id: "E1" } },
  UnlockedAreas: [{ x: 0, y: 0, width: 4, length: 4 }],
  CityEntities: {
    E1: {
      id: "E1", width: 5, length: 5, name: "Armory", type: "military",
      asset_id: "junk", stateDefinitionHash: "junk", entity_levels: [1, 2, 3],
      requirements: { street_connection_level: 2, other: "drop" },
      abilities: [
        { __class__: "SetAbility", setId: "S1", reward: "drop" },
        { __class__: "ChainAbility", chainId: "C1" },
        { __class__: "BoostAbility", value: 999 },
      ],
      components: {
        p: { placement: { size: { x: 5, y: 5 } }, asset: "drop", state: "drop" },
      },
    },
    E2: { id: "E2", name: "NoSize", components: { c: { placement: { size: { x: 2, y: 3 } } } } },
  },
};

describe("stripCity", () => {
  it("passes CityMapData and UnlockedAreas through unchanged", () => {
    const slim = stripCity(fat);
    expect(slim.CityMapData).toEqual(fat.CityMapData);
    expect(slim.UnlockedAreas).toEqual(fat.UnlockedAreas);
  });

  it("keeps only catalog fields on entities", () => {
    const e = stripCity(fat).CityEntities.E1;
    expect(e).toEqual({
      id: "E1", width: 5, length: 5, name: "Armory",
      requirements: { street_connection_level: 2 },
      abilities: [{ setId: "S1" }, { chainId: "C1" }, {}],
      components: { p: { placement: { size: { x: 5, y: 5 } } } },
    });
  });

  it("omits missing fields instead of inventing them", () => {
    const e = stripCity(fat).CityEntities.E2;
    expect(e.width).toBeUndefined();
    expect(e.requirements).toBeUndefined();
    expect(e.components).toEqual({ c: { placement: { size: { x: 2, y: 3 } } } });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/workers/stripCity.test.ts`
Expected: FAIL — cannot import `./stripCity`.

- [ ] **Step 3: Write `frontend/src/workers/stripCity.ts`**

```ts
type AnyObj = Record<string, any>;

function slimAbility(ability: AnyObj): AnyObj {
  const out: AnyObj = {};
  if ("setId" in ability) out.setId = ability.setId;
  if ("chainId" in ability) out.chainId = ability.chainId;
  return out;
}

function slimComponents(components: AnyObj): AnyObj {
  const out: AnyObj = {};
  for (const key of Object.keys(components)) {
    const size = components[key]?.placement?.size;
    if (size !== undefined) out[key] = { placement: { size } };
  }
  return out;
}

function slimEntity(entity: AnyObj): AnyObj {
  const out: AnyObj = {};
  if ("id" in entity) out.id = entity.id;
  if ("width" in entity) out.width = entity.width;
  if ("length" in entity) out.length = entity.length;
  if ("name" in entity) out.name = entity.name;
  const scl = entity?.requirements?.street_connection_level;
  if (scl !== undefined) out.requirements = { street_connection_level: scl };
  if (Array.isArray(entity.abilities)) out.abilities = entity.abilities.map(slimAbility);
  if (entity.components && typeof entity.components === "object") {
    const c = slimComponents(entity.components);
    if (Object.keys(c).length > 0) out.components = c;
  }
  return out;
}

export function stripCity(data: AnyObj): AnyObj {
  const entities: AnyObj = {};
  const src = data.CityEntities ?? {};
  for (const id of Object.keys(src)) {
    entities[id] = slimEntity(src[id]);
  }
  return {
    CityMapData: data.CityMapData ?? {},
    UnlockedAreas: data.UnlockedAreas ?? [],
    CityEntities: entities,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/workers/stripCity.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Write `frontend/src/workers/stripCity.worker.ts`**

```ts
import { stripCity } from "./stripCity";

self.onmessage = async (e: MessageEvent<File>) => {
  const file = e.data;
  try {
    (self as unknown as Worker).postMessage({ phase: "parsing" });
    const text = await file.text();
    const data = JSON.parse(text);
    (self as unknown as Worker).postMessage({ phase: "stripping" });
    const slim = stripCity(data);
    (self as unknown as Worker).postMessage({ phase: "done", slim });
  } catch (err) {
    (self as unknown as Worker).postMessage({ phase: "error", message: String(err) });
  }
};
```

- [ ] **Step 6: Verify typecheck/build still passes**

Run: `cd frontend && npx tsc -b`
Expected: no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/workers/
git commit -m "feat(frontend): city bloat-strip worker (parse-then-strip)"
```

---

### Task 5: API client (`fetch` + SSE + improvement→view)

**Files:**
- Create: `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Consumes: types from `types.ts`.
- Produces:
  - `parseSSE(chunk: string): {event: string; data: any}[]` — parses one or more `event:`/`data:` SSE records from a text buffer; ignores incomplete trailing records.
  - `improvementToView(imp, summaryById, origin, cell, palette): {optimized_roads: RoadView[]; buildings: BuildingView[]}` — converts a compact improvement (absolute grid) to relative-pixel view data, joining metadata by entity id.
  - `apiLoad(slim): Promise<LoadResponse>`, `apiOptimize(body): Promise<{job_id: string}>`, `apiStop(jobId)`, `apiCities(): Promise<CityListItem[]>`, `apiCity(id)`, `apiLayouts(cityId?)`, `apiLayout(id)`, `apiSaveLayout(body)`, `apiDeleteLayout(id)`. (Thin `fetch` wrappers.)
  - `openStream(jobId, handlers): EventSource` — wires `improvement`/`heartbeat`/`done` listeners.

- [ ] **Step 1: Write the failing test**

`frontend/src/api.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseSSE, improvementToView } from "./api";
import type { BuildingSummary, Improvement, Palette } from "./types";

describe("parseSSE", () => {
  it("parses complete event records and ignores an incomplete trailer", () => {
    const buf =
      "event: improvement\ndata: {\"k\":92,\"achieved\":79}\n\n" +
      "event: done\ndata: {\"verdict\":\"DONE\"}\n\n" +
      "event: heartbeat\ndata: {\"stat";
    const events = parseSSE(buf);
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: "improvement", data: { k: 92, achieved: 79 } });
    expect(events[1]).toEqual({ event: "done", data: { verdict: "DONE" } });
  });
});

describe("improvementToView", () => {
  it("joins metadata by id and converts absolute grid to relative pixels", () => {
    const cell = 12;
    const origin: [number, number] = [3, 5];
    const summary: BuildingSummary[] = [
      { entity_id: "E1", name: "Armory", width: 2, length: 2, needs_road: true, is_townhall: false },
    ];
    const byId = new Map(summary.map((s) => [String(s.entity_id), s]));
    const imp: Improvement = {
      k: 10, achieved: 7,
      roads: [[4, 6]],
      buildings: { E1: [5, 7, 2, 2] },
    };
    const palette = {} as Palette;
    const out = improvementToView(imp, byId, origin, cell, palette);
    // road at abs (4,6) → relative pixel ((4-3)*12,(6-5)*12) = (12,12)
    expect(out.optimized_roads[0]).toEqual({ x: 12, y: 12, level: 1 });
    // building E1 at abs (5,7) size 2x2 → rel px ((5-3)*12,(7-5)*12)=(24,24), w/h 24
    expect(out.buildings[0]).toMatchObject({
      x: 24, y: 24, w: 24, h: 24, name: "Armory", needs_road: true, townhall: false,
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: FAIL — cannot import `./api`.

- [ ] **Step 3: Write `frontend/src/api.ts`**

```ts
import type {
  LoadResponse, CityListItem, LayoutListItem, Improvement,
  BuildingSummary, BuildingView, RoadView, Palette,
} from "./types";

export function parseSSE(buffer: string): { event: string; data: any }[] {
  const out: { event: string; data: any }[] = [];
  const records = buffer.split("\n\n");
  for (const record of records) {
    if (!record.includes("data:")) continue;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of record.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    try {
      out.push({ event, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      // incomplete/invalid JSON (partial trailing record) — skip
    }
  }
  return out;
}

export function improvementToView(
  imp: Improvement,
  summaryById: Map<string, BuildingSummary>,
  origin: [number, number],
  cell: number,
  _palette: Palette,
): { optimized_roads: RoadView[]; buildings: BuildingView[] } {
  const [ox, oy] = origin;
  const optimized_roads: RoadView[] = imp.roads.map(([x, y]) => ({
    x: (x - ox) * cell, y: (y - oy) * cell, level: 1,
  }));
  const buildings: BuildingView[] = [];
  for (const id of Object.keys(imp.buildings)) {
    const [x, y, w, l] = imp.buildings[id];
    const meta = summaryById.get(id);
    buildings.push({
      x: (x - ox) * cell, y: (y - oy) * cell, w: w * cell, h: l * cell,
      name: meta?.name ?? id, size: `${w}x${l}`,
      needs_road: meta?.needs_road ?? false, townhall: meta?.is_townhall ?? false,
    });
  }
  return { optimized_roads, buildings };
}

async function jsonPost(path: string, body: unknown): Promise<any> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ?? `${path} failed (${r.status})`);
  return data;
}

async function jsonGet(path: string): Promise<any> {
  const r = await fetch(path);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ?? `${path} failed (${r.status})`);
  return data;
}

export const apiLoad = (slim: unknown): Promise<LoadResponse> => jsonPost("/api/load", slim);
export const apiOptimize = (body: { city_id: string; time_box: number }): Promise<{ job_id: string }> =>
  jsonPost("/api/optimize", body);
export const apiStop = (jobId: string): Promise<any> => jsonPost(`/api/stop/${jobId}`, {});
export const apiCities = (): Promise<CityListItem[]> => jsonGet("/api/cities");
export const apiCity = (id: string): Promise<any> => jsonGet(`/api/cities/${id}`);
export const apiLayouts = (cityId?: string): Promise<LayoutListItem[]> =>
  jsonGet(cityId ? `/api/layouts?city_id=${encodeURIComponent(cityId)}` : "/api/layouts");
export const apiLayout = (id: string): Promise<any> => jsonGet(`/api/layouts/${id}`);
export const apiSaveLayout = (body: unknown): Promise<{ id: string }> => jsonPost("/api/layouts", body);
export const apiDeleteLayout = (id: string): Promise<any> =>
  fetch(`/api/layouts/${id}`, { method: "DELETE" }).then((r) => r.json());

export function openStream(
  jobId: string,
  handlers: {
    onImprovement?: (data: Improvement) => void;
    onHeartbeat?: (data: any) => void;
    onDone?: (data: any) => void;
  },
): EventSource {
  const es = new EventSource(`/api/stream/${jobId}`);
  es.addEventListener("improvement", (e) => handlers.onImprovement?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("heartbeat", (e) => handlers.onHeartbeat?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("done", (e) => {
    handlers.onDone?.(JSON.parse((e as MessageEvent).data));
    es.close();
  });
  return es;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(frontend): api client with SSE parsing and improvement conversion"
```

---

### Task 6: Zustand store

**Files:**
- Create: `frontend/src/stores/cityStore.ts`
- Test: `frontend/src/stores/cityStore.test.ts`

**Interfaces:**
- Consumes: `api.ts`, `types.ts`.
- Produces: `useCityStore` (zustand hook) with state:
  - `city: LoadResponse | null`, `summaryById: Map<string, BuildingSummary>`
  - `optimized: { roads: RoadView[]; buildings: BuildingView[]; k: number; achieved: number } | null`
  - `optimizedRaw: Improvement | null` — the raw compact layout (grid coords, entity-keyed), for saving/exporting
  - `job: { id: string; state: "running" | "done" | "idle"; elapsed: number } | null`
  - `showCurrent: boolean`, `showOptimized: boolean`
  - actions: `setCity(resp)`, `applyImprovement(imp)`, `clearOptimized()`, `setJob(job)`, `toggleCurrent()`, `toggleOptimized()`, `reset()`. (`applyImprovement` doubles as "load a saved layout onto the map" — pass a saved `Improvement`.)

- [ ] **Step 1: Write the failing test**

`frontend/src/stores/cityStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { useCityStore } from "./cityStore";
import type { LoadResponse, Improvement, MapView } from "../types";

const mapView: MapView = {
  cell: 12, origin: [0, 0], width: 24, height: 24,
  region: [[0, 0]], buildings: [], current_roads: [], optimized_roads: null,
  palette: {} as never,
};

const resp: LoadResponse = {
  city_id: "c1",
  buildings: [
    { entity_id: "E1", name: "Armory", width: 2, length: 2, needs_road: true, is_townhall: false },
  ],
  region_cells: 1, road_estimate: 3, map_view: mapView,
};

describe("cityStore", () => {
  beforeEach(() => useCityStore.getState().reset());

  it("setCity stores the response and builds summaryById", () => {
    useCityStore.getState().setCity(resp);
    const s = useCityStore.getState();
    expect(s.city?.city_id).toBe("c1");
    expect(s.summaryById.get("E1")?.name).toBe("Armory");
    expect(s.showCurrent).toBe(true);
  });

  it("applyImprovement converts and stores optimized layout", () => {
    useCityStore.getState().setCity(resp);
    const imp: Improvement = { k: 10, achieved: 7, roads: [[1, 1]], buildings: { E1: [2, 2, 2, 2] } };
    useCityStore.getState().applyImprovement(imp);
    const s = useCityStore.getState();
    expect(s.optimized?.achieved).toBe(7);
    expect(s.optimized?.roads[0]).toEqual({ x: 12, y: 12, level: 1 });
    expect(s.optimized?.buildings[0].name).toBe("Armory");
    expect(s.showOptimized).toBe(true);
  });

  it("reset clears everything", () => {
    useCityStore.getState().setCity(resp);
    useCityStore.getState().reset();
    expect(useCityStore.getState().city).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/stores/cityStore.test.ts`
Expected: FAIL — cannot import `./cityStore`.

- [ ] **Step 3: Write `frontend/src/stores/cityStore.ts`**

```ts
import { create } from "zustand";
import type { LoadResponse, BuildingSummary, Improvement, RoadView, BuildingView } from "../types";
import { improvementToView } from "../api";

type Optimized = { roads: RoadView[]; buildings: BuildingView[]; k: number; achieved: number };
type Job = { id: string; state: "running" | "done" | "idle"; elapsed: number };

type CityState = {
  city: LoadResponse | null;
  summaryById: Map<string, BuildingSummary>;
  optimized: Optimized | null;
  optimizedRaw: Improvement | null;
  job: Job | null;
  showCurrent: boolean;
  showOptimized: boolean;
  setCity: (resp: LoadResponse) => void;
  applyImprovement: (imp: Improvement) => void;
  clearOptimized: () => void;
  setJob: (job: Job | null) => void;
  toggleCurrent: () => void;
  toggleOptimized: () => void;
  reset: () => void;
};

export const useCityStore = create<CityState>((set, get) => ({
  city: null,
  summaryById: new Map(),
  optimized: null,
  optimizedRaw: null,
  job: null,
  showCurrent: true,
  showOptimized: true,
  setCity: (resp) =>
    set({
      city: resp,
      summaryById: new Map(resp.buildings.map((b) => [String(b.entity_id), b])),
      optimized: null,
      optimizedRaw: null,
      job: null,
    }),
  applyImprovement: (imp) => {
    const city = get().city;
    if (!city) return;
    const mv = city.map_view;
    const { optimized_roads, buildings } = improvementToView(
      imp, get().summaryById, mv.origin, mv.cell, mv.palette,
    );
    set({
      optimized: { roads: optimized_roads, buildings, k: imp.k, achieved: imp.achieved },
      optimizedRaw: imp,
      showOptimized: true,
    });
  },
  clearOptimized: () => set({ optimized: null, optimizedRaw: null }),
  setJob: (job) => set({ job }),
  toggleCurrent: () => set((s) => ({ showCurrent: !s.showCurrent })),
  toggleOptimized: () => set((s) => ({ showOptimized: !s.showOptimized })),
  reset: () =>
    set({
      city: null, summaryById: new Map(), optimized: null, optimizedRaw: null,
      job: null, showCurrent: true, showOptimized: true,
    }),
}));
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/stores/cityStore.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/
git commit -m "feat(frontend): zustand city store with improvement application"
```

---

### Task 7: `CityMap` canvas component

**Files:**
- Create: `frontend/src/components/CityMap.tsx`

**Interfaces:**
- Consumes: `useCityStore`, `geometry.ts` (`fitTransform`, `screenToGrid`, `buildingAt`), `types.ts`.
- Produces: `<CityMap />` — a self-contained canvas with pan (drag), zoom (wheel), fit-to-view, current/optimized toggles, and a tooltip.

- [ ] **Step 1: Write `frontend/src/components/CityMap.tsx`**

```tsx
import { useEffect, useRef, useState, useCallback } from "react";
import { useCityStore } from "../stores/cityStore";
import { fitTransform, screenToGrid, buildingAt, type Transform } from "../geometry";
import type { BuildingView } from "../types";

export function CityMap() {
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const showCurrent = useCityStore((s) => s.showCurrent);
  const showOptimized = useCityStore((s) => s.showOptimized);
  const toggleCurrent = useCityStore((s) => s.toggleCurrent);
  const toggleOptimized = useCityStore((s) => s.toggleOptimized);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [t, setT] = useState<Transform>({ offsetX: 0, offsetY: 0, scale: 1 });
  const [tip, setTip] = useState<{ x: number; y: number; b: BuildingView } | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);

  const view = city?.map_view ?? null;

  const fit = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv || !view) return;
    setT(fitTransform(view, cv.width, cv.height));
  }, [view]);

  useEffect(() => { fit(); }, [fit]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !view) return;
    const ctx = cv.getContext("2d")!;
    const p = view.palette;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = p.background;
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.setTransform(t.scale, 0, 0, t.scale, t.offsetX, t.offsetY);
    const cell = view.cell;

    ctx.fillStyle = p.region;
    for (const [x, y] of view.region) ctx.fillRect(x, y, cell, cell);

    if (showCurrent) {
      ctx.fillStyle = p.current_road;
      for (const r of view.current_roads) ctx.fillRect(r.x, r.y, cell, cell);
    }
    if (showOptimized && optimized) {
      ctx.fillStyle = p.optimized_road;
      for (const r of optimized.roads) ctx.fillRect(r.x, r.y, cell, cell);
    }

    const buildings = showOptimized && optimized ? optimized.buildings : view.buildings;
    ctx.lineWidth = 1;
    ctx.strokeStyle = p.border;
    for (const b of buildings) {
      ctx.fillStyle = b.townhall ? p.townhall : b.needs_road ? p.road_building : p.plain_building;
      ctx.fillRect(b.x, b.y, b.w, b.h);
      ctx.strokeRect(b.x, b.y, b.w, b.h);
    }
  }, [view, t, optimized, showCurrent, showOptimized]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = Math.pow(1.1, -e.deltaY / 100);
    setT((prev) => {
      const scale = Math.max(0.1, Math.min(8, prev.scale * factor));
      const rect = canvasRef.current!.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const k = scale / prev.scale;
      return { scale, offsetX: mx - (mx - prev.offsetX) * k, offsetY: my - (my - prev.offsetY) * k };
    });
  };

  const onMouseDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY }; };
  const onMouseUp = () => { drag.current = null; };

  const onMouseMove = (e: React.MouseEvent) => {
    if (drag.current) {
      const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
      drag.current = { x: e.clientX, y: e.clientY };
      setT((prev) => ({ ...prev, offsetX: prev.offsetX + dx, offsetY: prev.offsetY + dy }));
      setTip(null);
      return;
    }
    if (!view) return;
    const rect = canvasRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const { gx, gy } = screenToGrid(sx, sy, t, view.cell, view.origin);
    const buildings = showOptimized && optimized ? optimized.buildings : view.buildings;
    const b = buildingAt(gx, gy, buildings, view.origin, view.cell);
    setTip(b ? { x: sx, y: sy, b } : null);
  };

  return (
    <div className="citymap">
      <div className="citymap-toolbar">
        <label><input type="checkbox" checked={showCurrent} onChange={toggleCurrent} /> Current roads</label>
        <label><input type="checkbox" checked={showOptimized} onChange={toggleOptimized} /> Optimized roads</label>
        <button onClick={fit}>Fit</button>
      </div>
      <div className="citymap-canvas-wrap">
        <canvas
          ref={canvasRef}
          width={900}
          height={640}
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseUp={onMouseUp}
          onMouseLeave={() => { drag.current = null; setTip(null); }}
          onMouseMove={onMouseMove}
        />
        {tip && (
          <div className="citymap-tip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
            {tip.b.name} ({tip.b.size}) {tip.b.townhall ? "· townhall" : tip.b.needs_road ? "· needs road" : ""}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd frontend && npx tsc -b`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CityMap.tsx
git commit -m "feat(frontend): CityMap canvas with pan/zoom/tooltip"
```

---

### Task 8: `LoadPanel` component

**Files:**
- Create: `frontend/src/components/LoadPanel.tsx`

**Interfaces:**
- Consumes: `useCityStore` (`setCity`), `api.ts` (`apiLoad`, `apiCities`, `apiCity`), the strip worker.
- Produces: `<LoadPanel />` — file input → worker strip → `apiLoad` → `setCity`; a "cached cities" dropdown that re-loads a city by re-POSTing its cached payload; a `.city` file import (parse slim JSON → `apiLoad`).

- [ ] **Step 1: Write `frontend/src/components/LoadPanel.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiLoad, apiCities, apiCity } from "../api";
import type { CityListItem } from "../types";

export function LoadPanel() {
  const setCity = useCityStore((s) => s.setCity);
  const [phase, setPhase] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [cities, setCities] = useState<CityListItem[]>([]);
  const workerRef = useRef<Worker | null>(null);

  const refreshCities = () => apiCities().then(setCities).catch(() => {});
  useEffect(() => { refreshCities(); }, []);

  const loadSlim = async (slim: unknown) => {
    setPhase("uploading");
    try {
      const resp = await apiLoad(slim);
      setCity(resp);
      setPhase("");
      refreshCities();
    } catch (err) {
      setError(String(err));
      setPhase("");
    }
  };

  const onFile = (file: File) => {
    setError("");
    setPhase("parsing");
    const worker = new Worker(new URL("../workers/stripCity.worker.ts", import.meta.url), { type: "module" });
    workerRef.current = worker;
    worker.onmessage = (e: MessageEvent<any>) => {
      const msg = e.data;
      if (msg.phase === "error") { setError(msg.message); setPhase(""); worker.terminate(); return; }
      if (msg.phase === "done") { worker.terminate(); loadSlim(msg.slim); return; }
      setPhase(msg.phase);
    };
    worker.postMessage(file);
  };

  const onCityFile = async (file: File) => {
    setError("");
    try {
      const slim = JSON.parse(await file.text());
      loadSlim(slim);
    } catch (err) {
      setError(String(err));
    }
  };

  const loadCached = async (id: string) => {
    if (!id) return;
    setError("");
    try {
      const city = await apiCity(id);
      loadSlim(city.payload);
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="panel">
      <h3>Load city</h3>
      <label className="filebtn">
        Choose FoE export (.json)
        <input type="file" accept=".json,application/json" hidden
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      </label>
      <label className="filebtn">
        Import .city
        <input type="file" accept=".city,.json" hidden
          onChange={(e) => e.target.files?.[0] && onCityFile(e.target.files[0])} />
      </label>
      {cities.length > 0 && (
        <select defaultValue="" onChange={(e) => loadCached(e.target.value)}>
          <option value="">Load cached city…</option>
          {cities.map((c) => (
            <option key={c.id} value={c.id}>{c.id} ({c.region_cells} cells)</option>
          ))}
        </select>
      )}
      {phase && <div className="status">Working… {phase}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd frontend && npx tsc -b`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/LoadPanel.tsx
git commit -m "feat(frontend): LoadPanel with worker strip, cached load, .city import"
```

---

### Task 9: `BuildingsPanel` component

**Files:**
- Create: `frontend/src/components/BuildingsPanel.tsx`

**Interfaces:**
- Consumes: `useCityStore` (`city`).
- Produces: `<BuildingsPanel />` — search box + type filter (all / road-needing / plain / townhall) over `city.buildings`.

- [ ] **Step 1: Write `frontend/src/components/BuildingsPanel.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useCityStore } from "../stores/cityStore";

type Filter = "all" | "road" | "plain" | "townhall";

export function BuildingsPanel() {
  const city = useCityStore((s) => s.city);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const rows = useMemo(() => {
    const all = city?.buildings ?? [];
    const ql = q.toLowerCase();
    return all.filter((b) => {
      if (ql && !b.name.toLowerCase().includes(ql)) return false;
      if (filter === "road") return b.needs_road && !b.is_townhall;
      if (filter === "plain") return !b.needs_road && !b.is_townhall;
      if (filter === "townhall") return b.is_townhall;
      return true;
    });
  }, [city, q, filter]);

  if (!city) return null;
  const roadCount = city.buildings.filter((b) => b.needs_road && !b.is_townhall).length;

  return (
    <div className="panel">
      <h3>Buildings ({city.buildings.length} · {roadCount} road-needing)</h3>
      <div className="row">
        <input placeholder="search…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          <option value="all">all</option>
          <option value="road">road-needing</option>
          <option value="plain">plain</option>
          <option value="townhall">townhall</option>
        </select>
      </div>
      <div className="btable">
        {rows.map((b, i) => (
          <div className="brow" key={`${b.entity_id}-${i}`}>
            <span className="bname">{b.name}</span>
            <span className="bsize">{b.width}×{b.length}</span>
            <span className="btype">{b.is_townhall ? "townhall" : b.needs_road ? "road" : "plain"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd frontend && npx tsc -b`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BuildingsPanel.tsx
git commit -m "feat(frontend): BuildingsPanel with search and type filter"
```

---

### Task 10: `OptimizePanel` + `ResultPanel` components

**Files:**
- Create: `frontend/src/components/OptimizePanel.tsx`, `frontend/src/components/ResultPanel.tsx`

**Interfaces:**
- Consumes: `useCityStore` (`city`, `optimized`, `optimizedRaw`, `job`, `applyImprovement`, `setJob`), `api.ts` (`apiOptimize`, `apiStop`, `openStream`, `apiSaveLayout`, `apiLayouts`, `apiLayout`).
- Produces:
  - `<OptimizePanel />` — time-box input, Optimize/Stop buttons; opens the SSE stream and feeds `applyImprovement`.
  - `<ResultPanel />` — shows best `achieved`/`k`, a Save button (`apiSaveLayout` with the raw layout), a history list (`apiLayouts`) whose rows load onto the map (`apiLayout` → `applyImprovement`), and a layout export (client-side JSON download of the raw layout).

- [ ] **Step 1: Write `frontend/src/components/OptimizePanel.tsx`**

```tsx
import { useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiOptimize, apiStop, openStream } from "../api";

export function OptimizePanel() {
  const city = useCityStore((s) => s.city);
  const job = useCityStore((s) => s.job);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const setJob = useCityStore((s) => s.setJob);
  const [minutes, setMinutes] = useState(5);
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const running = job?.state === "running";

  const start = async () => {
    if (!city) return;
    setError("");
    try {
      const { job_id } = await apiOptimize({ city_id: city.city_id, time_box: minutes * 60 });
      setJob({ id: job_id, state: "running", elapsed: 0 });
      esRef.current = openStream(job_id, {
        onImprovement: (imp) => applyImprovement(imp),
        onHeartbeat: (st) => setJob({ id: job_id, state: "running", elapsed: st.elapsed ?? 0 }),
        onDone: () => setJob({ id: job_id, state: "done", elapsed: 0 }),
      });
    } catch (err) {
      setError(String(err));
    }
  };

  const stop = async () => {
    if (job) await apiStop(job.id).catch(() => {});
  };

  if (!city) return null;
  return (
    <div className="panel">
      <h3>Optimize</h3>
      <label className="row">
        Time-box (min)
        <input type="number" min={1} max={120} value={minutes}
          onChange={(e) => setMinutes(Math.max(1, Number(e.target.value) || 1))} disabled={running} />
      </label>
      <div className="row">
        <button onClick={start} disabled={running}>Optimize</button>
        <button onClick={stop} disabled={!running}>Stop</button>
      </div>
      {running && <div className="status">Running… {Math.round(job!.elapsed)}s</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Write `frontend/src/components/ResultPanel.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiSaveLayout, apiLayouts, apiLayout } from "../api";
import type { LayoutListItem } from "../types";

export function ResultPanel() {
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const optimizedRaw = useCityStore((s) => s.optimizedRaw);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const [history, setHistory] = useState<LayoutListItem[]>([]);
  const [msg, setMsg] = useState("");

  const refresh = () => {
    if (city) apiLayouts(city.city_id).then(setHistory).catch(() => {});
  };
  useEffect(() => { refresh(); }, [city]);

  if (!city) return null;
  const estimate = city.road_estimate;

  const save = async () => {
    if (!optimizedRaw) return;
    await apiSaveLayout({
      city_id: city.city_id, k: optimizedRaw.k, achieved: optimizedRaw.achieved,
      layout_json: optimizedRaw, roads_count: optimizedRaw.achieved,
    });
    setMsg("saved");
    refresh();
  };

  const exportLayout = () => {
    if (!optimizedRaw) return;
    const blob = new Blob([JSON.stringify(optimizedRaw)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${city.city_id}-k${optimizedRaw.k}.layout.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const loadHistory = async (id: string) => {
    try {
      const rec = await apiLayout(id);
      if (rec?.layout) applyImprovement(rec.layout);
    } catch { /* ignore */ }
  };

  return (
    <div className="panel">
      <h3>Result</h3>
      {optimized ? (
        <div className="result">
          <div className="big">{optimized.achieved} roads</div>
          <div className="sub">was ~{estimate} · k={optimized.k}</div>
          <div className="row">
            <button onClick={save}>Save</button>
            <button onClick={exportLayout}>Export</button>
          </div>
          {msg && <div className="status">{msg}</div>}
        </div>
      ) : (
        <div className="sub">No optimized layout yet.</div>
      )}
      {history.length > 0 && (
        <div className="history">
          <h4>History</h4>
          {history.map((h) => (
            <div className="brow clickable" key={h.id} onClick={() => loadHistory(h.id)}>
              <span>{h.achieved} roads</span>
              <span className="bsize">k={h.k}</span>
              <span className="btype">{h.created_at}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify typecheck passes**

Run: `cd frontend && npx tsc -b`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/OptimizePanel.tsx frontend/src/components/ResultPanel.tsx
git commit -m "feat(frontend): OptimizePanel (SSE) and ResultPanel (save/history/export)"
```

---

### Task 11: Assemble `App` + `Sidebar` + styles

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/styles.css`
- Create: `frontend/src/components/Sidebar.tsx`

**Interfaces:**
- Consumes: all components above.
- Produces: full app layout (sidebar 320px + map). `npm run build` produces the production bundle.

- [ ] **Step 1: Create `frontend/src/components/Sidebar.tsx`**

```tsx
import { LoadPanel } from "./LoadPanel";
import { OptimizePanel } from "./OptimizePanel";
import { ResultPanel } from "./ResultPanel";
import { BuildingsPanel } from "./BuildingsPanel";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <h2>FoE City Planner</h2>
      <LoadPanel />
      <OptimizePanel />
      <ResultPanel />
      <BuildingsPanel />
    </aside>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/App.tsx`**

```tsx
import { Sidebar } from "./components/Sidebar";
import { CityMap } from "./components/CityMap";
import { useCityStore } from "./stores/cityStore";

export function App() {
  const city = useCityStore((s) => s.city);
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        {city ? <CityMap /> : <div className="empty">Load a city to begin.</div>}
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Replace `frontend/src/styles.css`**

```css
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #141414;
  color: #e5e5e5;
  font: 14px/1.4 system-ui, sans-serif;
}
.app { display: flex; height: 100vh; }
.sidebar {
  width: 320px; flex: 0 0 320px; overflow-y: auto;
  padding: 12px 14px; background: #1b1b1b; border-right: 1px solid #2a2a2a;
}
.sidebar h2 { font-size: 16px; margin: 4px 0 12px; }
.main { flex: 1; display: flex; min-width: 0; }
.empty { margin: auto; color: #888; }
.panel { margin-bottom: 18px; }
.panel h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: #9a9a9a; margin: 0 0 8px; }
.panel h4 { font-size: 12px; color: #9a9a9a; margin: 10px 0 6px; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
button, select, input[type="number"], input[type="text"], input:not([type]) {
  background: #262626; color: #e5e5e5; border: 1px solid #3a3a3a; border-radius: 4px; padding: 5px 8px;
}
button { cursor: pointer; }
button:disabled { opacity: 0.5; cursor: default; }
.filebtn {
  display: block; background: #2980b9; color: #fff; padding: 7px 10px; border-radius: 4px;
  text-align: center; cursor: pointer; margin-bottom: 8px;
}
select, input:not([type]), input[type="text"] { width: 100%; }
.status { color: #7fd18f; font-size: 12px; }
.error { color: #e07a5f; font-size: 12px; white-space: pre-wrap; }
.result .big { font-size: 24px; font-weight: 600; }
.result .sub, .sub { color: #9a9a9a; font-size: 12px; }
.btable, .history { max-height: 260px; overflow-y: auto; }
.brow { display: flex; gap: 8px; padding: 3px 0; border-bottom: 1px solid #222; font-size: 12px; }
.bname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bsize { color: #9a9a9a; }
.btype { color: #6a6a6a; width: 64px; text-align: right; }
.brow.clickable { cursor: pointer; }
.brow.clickable:hover { background: #222; }
.citymap { flex: 1; display: flex; flex-direction: column; }
.citymap-toolbar { display: flex; gap: 14px; align-items: center; padding: 8px 12px; background: #1b1b1b; border-bottom: 1px solid #2a2a2a; font-size: 12px; }
.citymap-canvas-wrap { position: relative; flex: 1; overflow: hidden; }
.citymap-canvas-wrap canvas { display: block; width: 100%; height: 100%; cursor: grab; }
.citymap-tip {
  position: absolute; pointer-events: none; background: #000c; color: #fff;
  padding: 4px 8px; border-radius: 4px; font-size: 12px; white-space: nowrap;
}
```

- [ ] **Step 4: Build and run all frontend tests**

Run:
```bash
cd frontend && npm test && npm run build
```
Expected: Vitest passes (geometry, stripCity, api, cityStore = 12 tests); `npm run build` writes `webapp/dist/index.html` + hashed assets with no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/src/components/Sidebar.tsx
git commit -m "feat(frontend): assemble App shell, Sidebar, and dark theme styles"
```

---

### Task 12: Cutover — Flask serves `dist/`, delete old static, final verification

**Files:**
- Modify: `webapp/app.py` (serve built SPA), `tests/test_webapp.py` (build-guarded check)
- Delete: `webapp/static/index.html`, `webapp/static/app.js`, `webapp/static/style.css`

**Interfaces:**
- Consumes: `webapp/dist/` (Vite build output, gitignored).
- Produces: `/` serves `webapp/dist/index.html` when present; unknown non-`/api` paths fall back to `index.html`; if `dist/` is absent, `/` returns a 503 JSON hint (so pytest passes without a build).

- [ ] **Step 1: Rewrite the static-serving part of `webapp/app.py`**

Replace the `_STATIC = ...` line and the `index()` route. Change:

```python
_STATIC = os.path.join(os.path.dirname(__file__), "static")
```
to:
```python
_DIST = os.path.join(os.path.dirname(__file__), "dist")
```

Replace the app construction line:
```python
    app = Flask(__name__, static_folder=_STATIC, static_url_path="/static")
```
with:
```python
    app = Flask(__name__, static_folder=_DIST, static_url_path="/assets_root")
```

Replace the `index()` route:
```python
    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")
```
with:
```python
    @app.get("/")
    def index():
        if not os.path.exists(os.path.join(_DIST, "index.html")):
            return jsonify(error="frontend not built; run `npm run build` in frontend/"), 503
        return send_from_directory(_DIST, "index.html")

    @app.get("/assets/<path:filename>")
    def spa_assets(filename):
        return send_from_directory(os.path.join(_DIST, "assets"), filename)

    @app.get("/<path:path>")
    def spa_fallback(path):
        if path.startswith("api/"):
            return jsonify(error="not found"), 404
        full = os.path.join(_DIST, path)
        if os.path.isfile(full):
            return send_from_directory(_DIST, path)
        if not os.path.exists(os.path.join(_DIST, "index.html")):
            return jsonify(error="frontend not built; run `npm run build` in frontend/"), 503
        return send_from_directory(_DIST, "index.html")
```

Note: the `/<path:path>` fallback is defined LAST so it does not shadow the `/api/...` routes (Flask matches static/explicit rules before the catch-all, but `/api/` routes are registered earlier and take precedence; the `path.startswith("api/")` guard is belt-and-suspenders).

- [ ] **Step 2: Delete the old static UI**

```bash
git rm webapp/static/index.html webapp/static/app.js webapp/static/style.css
```

- [ ] **Step 3: Rewrite `tests/test_webapp.py` to a build-guarded check**

Replace entire contents of `tests/test_webapp.py`:

```python
import os
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app

_DIST = os.path.join(os.path.dirname(__file__), "..", "webapp", "dist")


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_serves_built_spa_or_503(client):
    """/ serves the built SPA when webapp/dist exists, else a 503 JSON hint.
    Either is correct — the build is not a pytest prerequisite."""
    r = client.get("/")
    if os.path.exists(os.path.join(_DIST, "index.html")):
        assert r.status_code == 200
    else:
        assert r.status_code == 503
        assert r.is_json and "error" in r.get_json()


def test_unknown_api_route_is_404_json(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 4: Run backend suite**

Run: `uv run pytest tests/test_webapp.py tests/test_api.py -v`
Expected: PASS. `test_index_serves_built_spa_or_503` passes in both states.

- [ ] **Step 5: Full backend regression**

Run: `uv run pytest -q --ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`
Expected: all pass.

- [ ] **Step 6: Build the frontend and verify Flask serves it**

Run:
```bash
cd frontend && npm run build && cd ..
uv run python -c "
from webapp.app import create_app
c = create_app(db_path=':memory:').test_client()
r = c.get('/')
print('index status', r.status_code)
assert r.status_code == 200 and b'<div id=\"root\">' in r.data
print('OK: Flask serves built SPA')
"
```
Expected: `index status 200` and `OK: Flask serves built SPA`.

- [ ] **Step 7: Manual end-to-end smoke (verification gate)**

Run the two servers and drive the flow in a browser:
```bash
# Terminal A:
uv run python -m webapp.app          # Flask API :5000
# Terminal B:
cd frontend && npm run dev           # Vite :5173 (proxies /api → :5000)
```
Check in the browser at http://localhost:5173:
1. Load `darkzig.json` → progress shows parsing/stripping/uploading → map renders (region, current roads gray, buildings colored), tooltip on hover, pan/zoom work.
2. Set time-box 1 min → Optimize → optimized roads (green) appear and the "roads" number drops live as improvements stream.
3. Stop → search ends; Save → appears in History; Export → downloads a `.layout.json`.
Record the observed final road count in the commit message.

- [ ] **Step 8: Commit**

```bash
git add webapp/app.py tests/test_webapp.py
git commit -m "feat: serve built React SPA from webapp/dist; remove legacy static UI"
```

---

## Notes for the implementer

- Run every `npx vitest run` / `npx tsc -b` / `npm run build` from inside `frontend/`.
- The backend must be reachable at `:5000` for the Vite proxy during dev; production serves everything from Flask after `npm run build`.
- Do not add `frontend/node_modules/` or `webapp/dist/` to git — both are already gitignored.
- If `npx tsc -b` complains about unused React imports, this project uses the automatic JSX runtime (`"jsx": "react-jsx"`), so component files do not `import React` — only import hooks/APIs you use.
