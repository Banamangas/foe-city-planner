# Newbie app, plan 3 of 4: the five-step wizard (French + English) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A player with no IT knowledge can drop in their Forge Hammer city file, adjust buildings, run the optimizer with one button while watching its progress, pick any legal layout found, and save the file for Forge Hammer, in French or English.

**Architecture:** A new wizard UI in the existing React app (`frontend/src/wizard/`), shown at `/`. Today's developer UI stays, unchanged, at `/advanced`. The wizard talks to the same Flask API. It reuses `useCityStore` (city, edits, map) and `CityMap`, and adds its own small zustand store for wizard state. Testable logic (translation, phase mapping, progress, layout list, stats rows, error sorting) lives in plain TypeScript modules with unit tests. Components get a few jsdom tests. One backend task adds what the wizard needs: localized names, an `exportable` flag, stored-building ranking, and edit info on every streamed layout.

**Tech Stack:** React 18 + TypeScript + zustand + Vite + vitest (new dev-only deps: `jsdom`, `@testing-library/react`); Flask/Python 3.12 for Task 1.

**Spec:** `docs/superpowers/specs/2026-11-24-newbie-desktop-app-design.md` (goals 2, 3, 4, 6; "Stats"; "Checks shown after loading"; anti-goals).

## Global Constraints

- The player never sees the words "JSON", "worker", "CP-SAT" or "k-walk", nor a raw server/Python error message. Server error text may only be copied to the clipboard via a "Copy details for a bug report" button, never rendered.
- Every user-facing wizard string comes from a translation file: `frontend/src/wizard/i18n/<lang>.json`. `en.json` and `fr.json` are complete. Adding a language = adding one file, with no code change. French uses "vous" and natural game wording.
- The default language is the system language (French when `navigator.languages` starts with `fr`, else English). There is a switch in the header, and the choice is remembered (localStorage key `foeopt.lang`, every access in try/catch).
- No settings screen. Every optimizer option comes from `/api/options` → `presets.best`. The only player choices are the run time (presets 2 / 5 / 15 min, default 5, plus custom 1–120 min) and building edits.
- The city never leaves the computer: the wizard makes only same-origin `/api/...` requests (guide images are local files under `frontend/public/guides/`).
- Forge Hammer (v3) files only. Any other file gets a friendly "export it from Forge Hammer" message (load response `exportable: false`).
- Today's UI is reachable at `/advanced` and behaves exactly as before. Changes to shared components (`CityMap`, `api.ts`) are backward compatible.
- Buildings never rotate. Every layout offered comes from the run's legality-checked layout stream (`layout` events / `done.result.layouts`).
- City/player files are never printed or committed; tests use synthetic data only.
- No new runtime dependency (react, react-dom, zustand only). New dev dependencies are allowed: `jsdom`, `@testing-library/react`.
- Out of scope (plan 4): the SQLite city cache / storage limits, keeping the last result across restarts, the "closing mid-run?" prompt, packaging and the desktop window.

## Review Focus

1. **A file that isn't a Forge Hammer city** (another planner's export, any random file, a picture): a friendly message with the export guide link, never a raw error. Task 4 tests `classifyLoadProblem` for 400, network failure and `exportable: false`.
2. **Starting a run while an earlier one is still going** (page refreshed mid-run): the server answers 409 with `active_job_id`. The wizard stops that job and retries once instead of showing an error. Task 6 tests `startDecision`.
3. **A run that finds no layout at all** (very crowded city): a clear message suggesting a longer run or removing a building, and no empty Choose step. Task 6 tests `afterRun`.
4. **A translation missing a key or a placeholder:** the text falls back to English, never shows a raw key, and the key-parity test fails the build. Task 2 tests.
5. **Layouts streaming in while the player is choosing:** the order stays stable (roads, then id) and the selected card stays selected (selection by id). Task 6 tests `mergeLayouts`; Task 7 tests that the selection survives a merge.

---

### Task 1: Backend additions for the wizard

**Files:**
- Modify: `webapp/app.py` (`_buildings_summary`, `search_catalog`, `_parse_and_cache`, `api_load`, `api_load_raw`, `api_catalog`)
- Modify: `webapp/collector.py` (`LayoutCollector.__init__`, `offer`), `webapp/runner.py` (pass `edit_info` to the collector)
- Test: `tests/test_api.py`, `tests/test_collector.py` (create it if absent)

**Interfaces:**
- Produces:
  - query param `lang` (`en` | `fr`; any other value ignored) on `POST /api/load`, `POST /api/load/raw` and `GET /api/catalog`. Building `name` fields use `Catalog.name(cityentity_id, lang)` for buildings with a catalog entry, otherwise the existing name.
  - the load response gains `"exportable": bool` (= `foeopt.export_v3.can_export(payload)`).
  - each `/api/catalog` result row gains `"stored": int`. With `city_id`, this is the number of that type in the uploaded file's `storedBuildings` (counted by `metaId`; 0 when the field is absent), and rows with `stored > 0` come first (then the existing order). Without `city_id`, `stored` is 0.
  - every collector entry (SSE `layout` event and `done.result.layouts[i]`) carries `to_store` and `added` when the run had edits (same values as improvements get from `edit_info`).

- [ ] **Step 1: Write the failing tests**
  - `test_load_lang_fr_localizes_names`: load a synthetic v3 city whose building type has `names: {"en": "Tree", "fr": "Arbre"}` in the bundled catalog (pick a real catalog id that has a French name, and assert against `Catalog.name(id, "fr")` rather than hard-coding the text). With `?lang=fr` the summary name equals the French name; without `lang` it equals today's name.
  - `test_load_reports_exportable`: a full v3 (with `mapBuildings` and `currentEra`) gives `exportable is True`; a non-v3 upload that loads today gives `False`.
  - `test_catalog_stored_first`: a v3 with `storedBuildings: [{"metaId": X, ...}, {"metaId": X, ...}]`. `GET /api/catalog?q=&city_id=...` gives first row `id == X` with `stored == 2`; the other rows have `stored == 0`.
  - `test_catalog_lang_fr`: `GET /api/catalog?q=<french name fragment>&lang=fr` finds the building, and its `name` is French.
  - `test_collector_entries_carry_edit_info` (`tests/test_collector.py`): `LayoutCollector(ref, military="connect", off_road=frozenset(), extra={"to_store": [1], "added": []})`, offer a legal layout, and the entry has `to_store == [1]` and `added == []`. Without `extra`, the entry has no `to_store` key.
- [ ] **Step 2: Run them and see them fail:** `.venv/bin/python -m pytest tests/test_api.py tests/test_collector.py -q -k "lang or exportable or stored or edit_info"`
- [ ] **Step 3: Implement.**
  - `_buildings_summary(layout, catalog=None, lang=None)`.
  - `search_catalog(catalog, q, limit=MAX_CATALOG_RESULTS, lang=None, stored=None)`: matching tests the query against both the default and the localized name; `stored: dict[str, int] | None`.
  - `_parse_and_cache(..., lang=None)`.
  - `LayoutCollector(..., extra: dict | None = None)` merges `extra` into each admitted entry.
  - In the runner, build the collector with `extra=edit_info`.
  - Read `lang` with a helper `_lang() -> str | None` that returns `request.args.get("lang")` only when it is in `("en", "fr")`.
- [ ] **Step 4: Run the focused tests, then the full suite:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5: Commit** `feat: localized names, exportable flag, stored-first catalog, edit info on every layout`

---

### Task 2: Translations foundation

**Files:**
- Create: `frontend/src/wizard/i18n/index.ts`, `frontend/src/wizard/i18n/en.json`, `frontend/src/wizard/i18n/fr.json`, `frontend/src/wizard/i18n/i18n.test.ts`
- Modify: `frontend/package.json` (dev deps `jsdom`, `@testing-library/react`, at current stable versions, installed with `npm install -D`)

**Interfaces:**
- Produces (`i18n/index.ts`):
  - `LANGS: string[]` (codes of every `*.json` in the folder, via `import.meta.glob("./*.json", { eager: true })`, `en` first).
  - `languageName(lang: string): string` (each file's `"_language"` value: `"English"`, `"Français"`).
  - `detectLang(navigatorLanguages: readonly string[], saved: string | null): string`.
  - `translate(lang: string, key: string, vars?: Record<string, string | number>): string`: the language's value, else English, else the key itself; replaces `{name}` placeholders.
  - (`useT`, the React hook bound to the current language, belongs to Task 3's store.)
- Translation files are flat objects of dotted keys (`"step.load": "Load city"`). This task adds `_language`, `app.title` ("City road optimizer" / "Optimiseur de routes"), `lang.label`, `nav.back`, `nav.next`, `step.load`, `step.buildings`, `step.optimize`, `step.choose`, `step.export`, `error.copyDetails` ("Copy details for a bug report"), `error.copied`. Later tasks add their own keys to both files.

- [ ] **Step 1: Write the failing tests** (`i18n.test.ts`, node environment):
  - `every language has exactly the English keys`: for each file in `LANGS`, its key set equals `en.json`'s.
  - `placeholders match`: for every key, the set of `{...}` names in each language equals English's.
  - `no forbidden words`: no value in any language matches `/\bjson\b|worker|cp-sat|k-walk/i`.
  - `detectLang`: `(["fr-FR"], null) → "fr"`, `(["de-DE", "en-US"], null) → "en"`, `(["en-US"], "fr") → "fr"`, `(["fr-FR"], "xx") → "fr"`, `([], null) → "en"`.
  - `translate`: an unavailable language falls back to English (`translate("xx", "nav.next") === translate("en", "nav.next")`); an unknown key returns the key itself; placeholders are replaced. This task adds `"run.machine"` ("This computer: {cpus} processor threads, using {threads} (your computer stays usable)"), and `translate("en", "run.machine", {cpus: 16, threads: 12})` contains "16" and "12" and no "{".
- [ ] **Step 2: Run and fail:** `cd frontend && npx vitest run src/wizard/i18n`
- [ ] **Step 3: Implement `index.ts` and the two files**
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run` (all existing tests still pass)
- [ ] **Step 5: Commit** `feat: wizard translations (English, French)`

---

### Task 3: Wizard shell, store and routing

**Files:**
- Create: `frontend/src/wizard/wizardStore.ts`, `frontend/src/wizard/types.ts`, `frontend/src/wizard/Wizard.tsx`, `frontend/src/wizard/StepNav.tsx`, `frontend/src/wizard/wizard.css`, stub step components `frontend/src/wizard/steps/{LoadStep,BuildingsStep,OptimizeStep,ChooseStep,ExportStep}.tsx` (each renders its translated title; later tasks fill them), `frontend/src/wizard/Wizard.test.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/types.ts` (`LoadResponse` gains optional `stats?: CityStats`, `checks?: LoadChecks`, `exportable?: boolean`)

**Interfaces:**
- Produces (`types.ts`):
  - `CityStats = { area: number; roads: number; road_efficiency_pct: number | null; buildings_pct: number; roads_pct: number; free_pct: number; free_cells: number; with_roads: number; without_roads: number; unconnected: number[] }`
  - `LoadChecks = { unconnected: number[]; loose_chain_pieces: number[] }`
  - `MachineInfo = { workers: number; probe_workers: number; threads: number; logical_cpus: number | null; reduced: boolean; warn: boolean }`
  - `LayoutEntry = { id: number; k: number | null; achieved: number; stats: CityStats; legality: { status: string }; roads: [number, number, number][]; buildings: Record<string, [number, number, number, number]>; to_store?: StoredBuilding[]; added?: AddedBuilding[] }`
  - `RunState = { jobId: string; state: "running" | "done" | "error"; stopped: boolean; elapsed: number; timeBoxS: number; phase: string | null; maxPhaseIdx: number; layoutsFound: number; error: string | null }`
- Produces (`wizardStore.ts`, zustand `useWizardStore`):
  - `step: 1 | 2 | 3 | 4 | 5`, `go(step)`.
  - `lang: string`, `setLang(lang)` (initialised with `detectLang(navigator.languages, saved)`; saved and persisted under `foeopt.lang`).
  - `keepUnconnected: number[] | null` (null = not yet decided), `setKeepUnconnected(ids)`.
  - `run: RunState | null`, `setRun(patch: Partial<RunState> | null)`.
  - `layouts: LayoutEntry[]`, `addLayouts(entries)` (uses `mergeLayouts` from Task 6; until then, a plain append — Task 6 swaps it in).
  - `selectedId: number | "player" | null`, `select(id)`.
  - `reset()` (back to step 1, everything cleared except `lang`; also calls `useCityStore.getState().reset()`).
  - `useT(): (key: string, vars?: Record<string, string | number>) => string`: `translate` bound to the store's `lang`.
- Produces: `pickRoot(pathname: string): "advanced" | "wizard"` (in `main.tsx` or `wizard/route.ts`). `/advanced` and anything under it → `"advanced"`.
- Produces: `StepNav({ canBack, canNext, onBack, onNext, nextLabel? })`: translated Back/Next buttons.

- [ ] **Step 1: Write the failing tests** (`Wizard.test.tsx`, `// @vitest-environment jsdom`):
  - `pickRoot`: `"/" → "wizard"`, `"/advanced" → "advanced"`, `"/advanced/x" → "advanced"`, `"/whatever" → "wizard"`.
  - `renders five translated steps`: render `<Wizard />` with lang `en`: the step bar shows "Load city", "Buildings", "Optimize", "Choose", "Export", and step 1 is marked current (`aria-current="step"`).
  - `language switch`: choose `fr` in the header select, and the step labels are the French ones from `fr.json` (assert via `translate("fr", "step.load")`).
  - `reset keeps language`: set lang fr and step 3, call `reset()`, and expect step 1 with lang still fr.
- [ ] **Step 2: Run and fail:** `cd frontend && npx vitest run src/wizard`
- [ ] **Step 3: Implement.** Layout from the approved mockup (design A): header with title and language select; step bar (done / current / upcoming); the current step's component; each step renders its own `StepNav`. Use the mockup's colors (`#2f7d4f` green, `#b9d8c4` done, `#e4e4de` upcoming). Use plain CSS in `wizard.css`, scoped under `.wizard`. `main.tsx` renders `<App />` for `"advanced"`, else `<Wizard />`. The page title is set from `app.title`.
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run && npm run build`
- [ ] **Step 5: Commit** `feat: wizard shell with step bar, language switch and /advanced route`

---

### Task 4: Step 1, load city (unknown buildings, checks, export guide)

**Files:**
- Create: `frontend/src/wizard/loadCity.ts`, `frontend/src/wizard/loadCity.test.ts`, `frontend/src/wizard/steps/UnknownBuildingsForm.tsx`, `frontend/src/wizard/steps/ChecksPanel.tsx`, `frontend/src/wizard/Guide.tsx`, `frontend/src/wizard/steps/LoadStep.test.tsx`
- Modify: `frontend/src/wizard/steps/LoadStep.tsx`, `frontend/src/api.ts` (add `apiLoadResult`; keep `apiLoad` as is), both translation files

**Interfaces:**
- Consumes: Task 1 `lang`, `exportable`, 422 body `{ error, unknown_buildings: [{ cityentity_id, count }] }`, request key `custom_buildings: { [cid]: { width, length, road: 0 | 1 | 2 } }`; Task 3 store and types.
- Produces:
  - `apiLoadResult(slim: unknown, opts: { fileName?: string; lang: string; custom?: CustomBuildings }): Promise<{ ok: true; resp: LoadResponse } | { ok: false; status: number; body: any }>`. A network failure resolves to `{ ok: false, status: 0, body: { error: String(err) } }`.
  - `type CustomBuildings = Record<string, { width: number; length: number; road: 0 | 1 | 2 }>`.
  - `classifyLoadProblem(r: { status: number; body: any } | { resp: LoadResponse }): LoadProblem | null` where `LoadProblem = { kind: "unknown_buildings"; items: { cityentity_id: string; count: number }[] } | { kind: "not_forge_hammer" } | { kind: "app_not_running" } | { kind: "unreadable"; details: string }`. Rules: 422 with `unknown_buildings` → unknown_buildings; status 0 → app_not_running; any other 4xx → unreadable; a successful load with `exportable === false` → not_forge_hammer; a successful load with `exportable !== false` → null.
  - `validateCustom(c: CustomBuildings): string[]`: the ids whose width or length is not an integer 1–20, or whose road is not 0/1/2.
  - `Guide({ kind: "export" | "import", onClose })`: modal with numbered steps from keys `guide.<kind>.title` and `guide.<kind>.1`..`3`. Each step shows an image `/guides/<lang>/<kind>-<n>.png`, hidden on load error, so the guide works as text alone until screenshots are added.

- [ ] **Step 1: Write the failing tests:**
  - `loadCity.test.ts`: `classifyLoadProblem` for each rule above (`{status: 422, body: {unknown_buildings: [{cityentity_id: "W_X", count: 2}]}}` → unknown_buildings with that item; `{status: 0, ...}` → app_not_running; `{status: 400, body: {error: "could not parse city: KeyError 'x'"}}` → unreadable with `details` containing the error; `{resp: {...exportable: false}}` → not_forge_hammer; `{resp: {...exportable: true}}` → null). `validateCustom({a: {width: 0, length: 3, road: 1}, b: {width: 2, length: 2, road: 2}, c: {width: 2, length: 21, road: 0}})` → `["a", "c"]`.
  - `LoadStep.test.tsx` (jsdom): `UnknownBuildingsForm` with two items renders two rows. After filling width 3, length 2 and choosing "Two-lane road" for the first, and 1/1/"No road" for the second, submit calls back with `{W_X: {width: 3, length: 2, road: 2}, W_Y: {width: 1, length: 1, road: 0}}`. The unreadable message never contains the raw error text: render the LoadStep problem view with `details: "Traceback KeyError"` and assert the text is absent from the DOM.
- [ ] **Step 2: Run and fail:** `cd frontend && npx vitest run src/wizard`
- [ ] **Step 3: Implement.**
  - **Load screen:** a drop zone ("Drop your city file here", or a "Choose file" button) using the existing `stripCity.worker.ts`, then `apiLoadResult(..., { lang })`. A busy line ("Reading your city…") while it works. A "How to export your city from Forge Hammer" link opens `Guide kind="export"`. The line "Your city never leaves this computer." stays visible.
  - **Each problem gets a translated message and a way forward:**
    - unknown_buildings → `UnknownBuildingsForm`. One row per id, showing "Unknown building" + the id and × count, with width, length and road need (No road / Road / Two-lane road). Submit reloads with `custom`.
    - not_forge_hammer → a message saying to export the city from Forge Hammer, plus the guide link.
    - app_not_running → "The optimizer isn't responding. Close this window and start the app again."
    - unreadable → "This file couldn't be read. Make sure it's the file Forge Hammer saved." plus the copy-details button.
  - **On success:** `useCityStore.setCity(resp)`. If `checks` is non-empty, show `ChecksPanel`:
    - unconnected buildings, listed by name: "These buildings need a road but aren't connected. Is that intended?" with two buttons. "No, connect them (recommended)" → `setKeepUnconnected([])`. "Yes, leave them off the road" → `setKeepUnconnected(ids)`.
    - loose chain pieces: "These pieces will be linked back to their main building:" + names.
  - **Next** is enabled once a city is loaded and, when there are unconnected buildings, after the player has chosen. With no unconnected buildings, set `keepUnconnected([])` automatically.
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run && npm run build`
- [ ] **Step 5: Commit** `feat: wizard step 1, load city with unknown-building form and load checks`

---

### Task 5: Step 2, buildings (remove / add)

**Files:**
- Create: `frontend/src/wizard/steps/AddBuildingDialog.tsx`, `frontend/src/wizard/edits.ts` (wizard helpers), `frontend/src/wizard/edits.test.ts`
- Modify: `frontend/src/wizard/steps/BuildingsStep.tsx`, `frontend/src/components/CityMap.tsx` (optional props), `frontend/src/api.ts` (`apiCatalog` gains an optional `lang`; `CatalogEntry` gains `stored?: number`), both translation files

**Interfaces:**
- Consumes: `useCityStore` (`city`, `edits`, `setEdits`, `summaryById`), `apiPreviewEdits`, Task 1's `stored` rows.
- Produces:
  - `CityMap` props `{ labels?: Partial<CityMapLabels>; editable?: boolean }`. `CityMapLabels = { current; optimized; fit; townhall; needsRoad; removedClickToKeep }`, defaulting to today's English strings. `editable` defaults to true; when false, clicks never toggle removal. With no props, `CityMap` behaves exactly as today. Export `mapLabels(partial?: Partial<CityMapLabels>): CityMapLabels`.
  - `changesSummary(edits: Edits): { removed: number; added: number }` (added = the sum of `count`).
  - `addOne(edits: Edits, entry: CatalogEntry): Edits`: increments `count` when that `cityentity_id` is already in `add`, else appends `{ cityentity_id, count: 1, label: entry.name, size: "WxL" }`.
  - `removeAdded(edits: Edits, cityentityId: string): Edits`.

- [ ] **Step 1: Write the failing tests** (`edits.test.ts`):
  - `changesSummary({remove: [1, 2], add: [{cityentity_id: "A", count: 2}]})` → `{removed: 2, added: 2}`.
  - `addOne` twice with the same entry gives one row with count 2. With a different entry, two rows.
  - `removeAdded` drops the row.
  - `mapLabels({fit: "Ajuster"}).fit === "Ajuster"` and `mapLabels().current === "Current"`.
- [ ] **Step 2: Run and fail**
- [ ] **Step 3: Implement.**
  - **The step:** the map (`CityMap` with translated labels, `editable`) plus a "Changes" panel: Removed: N buildings / Added: N buildings, the added list with a remove ✕ per row, "+ Add a building", and "Nothing to change? Just press Next.". Clicking a building removes it; clicking again keeps it.
  - **`AddBuildingDialog`:** a search box. `apiCatalog(q, cityId, lang)` runs on typing (debounced 300 ms); an empty query lists stored buildings first. Each row shows the name, the size and an "In your storage: N" badge when `stored > 0`. Clicking a row calls `addOne`.
  - **Preview:** on every edit change (debounced 400 ms), call `apiPreviewEdits`. When `report.space.fits_without_roads` is false, show "The added buildings don't fit: {n} squares too many." and disable Next. For each `report.cascades` entry, show "Removing {main} also puts its linked pieces in storage." Preview errors show a generic translated line, never the raw text.
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run && npm run build`. Then open `/advanced` with `npm run dev` + the webapp and check that the old UI's map still toggles removal (a manual check; note it in the report).
- [ ] **Step 5: Commit** `feat: wizard step 2, remove and add buildings`

---

### Task 6: Step 3, optimize (run time, progress, phases, stop)

**Files:**
- Create: `frontend/src/wizard/run.ts`, `frontend/src/wizard/run.test.ts`
- Modify: `frontend/src/wizard/steps/OptimizeStep.tsx`, `frontend/src/wizard/wizardStore.ts` (`addLayouts` uses `mergeLayouts`), `frontend/src/api.ts` (`openStream` handlers gain `onLayout?: (entry: LayoutEntry) => void`; `OptionsResponse` gains `machine?: MachineInfo`; add `apiOptimizeResult(body): Promise<{ ok: true; job_id: string } | { ok: false; status: number; body: any }>`), both translation files

**Interfaces:**
- Consumes: `/api/options` (`presets.best`, `machine`); `POST /api/optimize`; the SSE stream (`heartbeat` data `{ state, elapsed, error, phase, layouts_found }`, `layout` = `LayoutEntry`, `done` = `{ state, result: { layouts?: LayoutEntry[], ... }, error, elapsed, stopped }`); `POST /api/stop/<id>`; the Task 3 store.
- Produces (`run.ts`):
  - `RUN_PRESETS_MIN = [2, 5, 15]`, `DEFAULT_MINUTES = 5`, `CUSTOM_MIN = 1`, `CUSTOM_MAX = 120`.
  - `PHASE_STEPS: { key: string; phases: (string | null)[] }[]`, in order:
    1. `phase.reading` ← `[null, "seed"]`
    2. `phase.sketching` ← `["walk"]`
    3. `phase.fitting` ← `["objective_polish", "union_polish", "rebased_polish"]`
    4. `phase.trying` ← `["mutation_polish", "seed_polish"]`
    5. `phase.finishing` ← `["exact"]`
  - English copy: "Reading your city", "Sketching road networks", "Fitting buildings around the best roads", "Trying small changes", "Fine-tuning the winner".
  - `phaseIndex(phase: string | null, previousMax: number): number`: the index of the step containing `phase`; an unknown phase keeps `previousMax`; never returns less than `previousMax`.
  - `progressPct(elapsed: number, timeBoxS: number, finished: boolean): number`: 100 when finished, else `min(99, floor(100 * elapsed / timeBoxS))`.
  - `timeLeft(elapsed: number, timeBoxS: number): string`: `"m:ss"`, never negative.
  - `buildOptimizeBody(a: { cityId: string; best: Record<string, unknown>; minutes: number; edits: Edits; keepUnconnected: number[] }): Record<string, unknown>` → `{ ...best, city_id, time_box: minutes * 60, edits, keep_unconnected, relink_chains: true }`. It never contains `workers` or `probe_workers`, so the server sizes them to the machine.
  - `mergeLayouts(existing: LayoutEntry[], incoming: LayoutEntry[]): LayoutEntry[]`: unique by `id`, the incoming copy winning; sorted by `stats.roads` ascending, then `id` ascending.
  - `startDecision(r: { ok: true } | { ok: false; status: number; body: any }, alreadyRetried: boolean): "started" | { stopThenRetry: string } | "failed"`: a 409 with `active_job_id` and no retry yet → stopThenRetry; everything else not ok → "failed".
  - `afterRun(layouts: LayoutEntry[], state: "done" | "error"): "choose" | "none_found" | "failed"`.

- [ ] **Step 1: Write the failing tests** (`run.test.ts`):
  - `phaseIndex`:
    - `(null, 0) → 0` and `("walk", 0) → 1`;
    - `("rebased_polish", 1) → 2` and `("exact", 2) → 4`;
    - `("seed_polish", 4) → 4` (never back) and `("mystery", 2) → 2`.
  - `progressPct`:
    - `(150, 300, false) → 50` and `(400, 300, false) → 99`;
    - `(10, 300, true) → 100`.
  - `timeLeft`:
    - `(0, 300) → "5:00"` and `(299, 300) → "0:01"`;
    - `(400, 300) → "0:00"`.
  - `buildOptimizeBody({..., minutes: 5, best: {patterns: 200}, keepUnconnected: [7]})`:
    - `time_box === 300`, `patterns === 200`;
    - `keep_unconnected` equals `[7]`, `relink_chains === true`;
    - no `workers` key.
  - `mergeLayouts`:
    - merging `[{id: 2, roads: 70}]` with `[{id: 1, roads: 70}, {id: 3, roads: 68}]` gives ids `[3, 1, 2]`;
    - re-merging an existing id doesn't duplicate it.
  - `startDecision`:
    - `({ok: false, status: 409, body: {active_job_id: "j1"}}, false) → {stopThenRetry: "j1"}`;
    - the same with `alreadyRetried: true` → "failed";
    - `({ok: true}, false) → "started"`.
  - `afterRun`: `([], "done") → "none_found"`, `([entry], "done") → "choose"` and `([], "error") → "failed"`.
- [ ] **Step 2: Run and fail**
- [ ] **Step 3: Implement the step.**
  - **Before the run:**
    - "How long should it search?" with buttons for 2 / 5 / 15 min and "Custom" (a minutes field, clamped 1–120), plus "longer usually finds fewer roads".
    - Start.
    - The machine line `run.machine` with `{cpus}` = `logical_cpus` and `{threads}` = `threads`.
    - When `machine.reduced`, add "On this computer results may be a little worse; a longer search helps." When `machine.warn`, add "This computer is on the small side: the search will be slower."
  - **During the run:**
    - A progress bar (`progressPct`) and the phase checklist (done ✓ / current ▶ / upcoming ○).
    - Live numbers: roads before → best so far (best = the minimum `stats.roads` over layouts), layouts found (`layouts_found`), and time left.
    - "Stop now and keep what's found" (`apiStop`).
  - **Back** is disabled while running.
  - **On `done`:** merge `result.layouts`, then act on `afterRun`:
    - "choose" → go to step 4 with the best layout selected;
    - "none_found" → "No layout was found this time. Try a longer search, or remove a building in the previous step." with Back enabled;
    - "failed" → a generic message plus the copy-details button.
  - **On a 409**, act on `startDecision`: stop the old job, wait for it to report `done` (poll `/api/stop` until `already_done`, max 10 s), then retry once.
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run && npm run build`
- [ ] **Step 5: Commit** `feat: wizard step 3, optimize with progress, phases and stop`

---

### Task 7: Steps 4 and 5, choose a layout and save it

**Files:**
- Create: `frontend/src/wizard/stats.ts`, `frontend/src/wizard/stats.test.ts`, `frontend/src/wizard/steps/ChooseStep.test.tsx`
- Modify: `frontend/src/wizard/steps/ChooseStep.tsx`, `frontend/src/wizard/steps/ExportStep.tsx`, both translation files

**Interfaces:**
- Consumes: Task 6 `layouts` / `selectedId`; `useCityStore.applyImprovement`, `setViewMode`, `city.stats`; `apiExportV3`; Task 4 `Guide`.
- Produces:
  - `statRows(before: CityStats, after: CityStats, lang: string): { key: string; before: string; after: string }[]`, in this order:
    1. `stat.roads`
    2. `stat.efficiency` (`null` → "—", else `"133%"`)
    3. `stat.buildingsCoverage` (`"62%"`)
    4. `stat.roadsCoverage`
    5. `stat.free` (`"12% (340)"`; the label says "Free area (squares)")
    6. `stat.withRoads`
    7. `stat.withoutRoads`
  - Numbers are formatted with `Intl.NumberFormat(lang)`, at most one decimal for percentages.
  - `layoutForExport(e: LayoutEntry): Record<string, unknown>` → `{ k, achieved, roads, buildings, to_store, added }` (`to_store` and `added` present only when the entry has them).

- [ ] **Step 1: Write the failing tests:**
  - `stats.test.ts`: `statRows` with `road_efficiency_pct: null` before and `133.3` after gives the efficiency row `{before: "—", after: "133.3%"}` for lang en. The free row with `free_pct: 12, free_cells: 340` gives `"12% (340)"`. The row order matches the list above. `layoutForExport` keeps `to_store`/`added` when present and omits them when absent.
  - `ChooseStep.test.tsx` (jsdom), with three layouts (roads 68, 66, 67) and a loaded city whose stats have roads 92:
    - the cards read in order "66 roads (best)", "67 roads", "68 roads", then the player's city ("Your city: 92") last;
    - clicking "67 roads" selects it;
    - after `addLayouts([a new layout with 65 roads])`, the 67 card is still the selected one.
- [ ] **Step 2: Run and fail**
- [ ] **Step 3: Implement.**
  - **Choose step:** a horizontally scrolling card row from `layouts` (all of them, best first), plus the player's city last.
    - Selecting a layout → `applyImprovement(entry)` and the map shows it (`CityMap editable={false}`).
    - Selecting the player's card → `setViewMode("current")`.
    - Next to the map, a "Before → after" table from `statRows(city.stats, selected.stats)`; for the player's card, both columns are the same.
    - Next is disabled when the player's card is selected.
  - **Export step:**
    - "Save file for Forge Hammer" → `apiExportV3(cityId, layoutForExport(selected))`, then a download through an object URL and an `<a download>` with the server's file name.
    - On error, a generic translated message plus the copy-details button.
    - Export warnings, if any, appear in a collapsed "Notes" block.
    - A "How to import it" link opens `Guide kind="import"`.
    - "Start again with another city" → `useWizardStore.reset()`.
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run && npm run build`
- [ ] **Step 5: Commit** `feat: wizard steps 4 and 5, choose a layout and save it for Forge Hammer`

---

### Task 8: Verification and review notes

**Files:**
- Modify: `tasks/todo.md` (append "Review (plan N3)")

- [ ] **Step 1:** Run `cd frontend && npx vitest run && npm run build` → all pass; the build writes `webapp/dist`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 3:** Search the wizard for raw strings: `grep -rnE ">[A-Za-z][^<{]{3,}<" frontend/src/wizard --include=*.tsx` → no user-facing English outside the translation files (report any hit with its justification).
- [ ] **Step 4:** Append "Review (plan N3)" to `tasks/todo.md`: what was built, the test totals, what the player sees at each step, and the open items for the user: the guide wording and screenshots (`frontend/public/guides/<lang>/<kind>-<n>.png`) and the French copy check. Commit `docs: plan N3 review`.
- [ ] **Step 5 (controller, after the task review):** a walkthrough in a real browser against the running webapp with a city file from the user's own disk (never printed), in both languages: load → buildings (remove one, add one) → a 2-minute run → choose → save. Note anything a newbie would trip on.
