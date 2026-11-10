# Frontend static review — 2026-11-11

## Scope and confidence

Read-only inspection of frontend source, existing tests, relevant server payloads and lessons. No tests, builds, browser sessions, indexing, dependency installation or application execution were performed. Findings describe source-level behavior, not reproduced runtime failures. This checkout is being edited concurrently; recheck cited locations before implementing. Only this review document was written.

## Existing strengths

- A small React/Zustand dependency surface and a worker for parsing large FoE exports.
- Geometry and data stripping are separated from rendering and covered by focused tests.
- Server-owned option definitions drive controls, presets and CLI previews, reducing configuration duplication.
- Instance screening is advisory and explicitly acknowledges uncertainty.
- Store operations and metadata-to-pixel conversion have unit coverage.

## Priority 1: state ownership and truthful outcomes

### Stale optimization events can contaminate another city

Evidence: `frontend/src/components/OptimizePanel.tsx:109–118` starts an EventSource whose callbacks unconditionally update the global store. Its `esRef` is assigned but never closed on city changes, unmount or restart. `LoadPanel` remains usable during optimization. `cityStore.setCity` clears job state without invalidating callbacks, while `applyImprovement` interprets every incoming layout with the currently selected city's origin and metadata.

Scenario: start city A, load B, then receive an improvement from A. The application can display A's layout using B's metadata and save it with B's city ID. Later A heartbeats also replace B's job state.

Remedy: carry city and job identity through store actions; reject stale events; close obsolete streams; define whether changing city cancels or merely detaches from a running job. Do not rely solely on UI disabling because asynchronous completions can still arrive.

Deferred verification: mocked EventSource integration test in which A emits after B is loaded; verify B's result, job and saved payload remain unchanged.

### Historical results and import requests also lack ownership guards

Evidence: `ResultPanel.tsx:14–17` preserves old history until a new request finishes and accepts responses in arrival order. `43–46` applies fetched layouts without checking current city. `LoadPanel.tsx` likewise accepts multiple concurrent uploads/cached loads.

Remedy: clear city-specific history immediately, cancel obsolete requests or ignore them by request generation, and check layout ownership at application time. Use a single latest-request policy for imports, history and cached loads.

Deferred verification: resolve requests in reverse order and switch city while a historical layout is loading.

### The baseline road count is actually an estimated target

Evidence: `ResultPanel.tsx:20,56` renders `city.road_estimate` as “was ~…”. `webapp/app.py:59` obtains it from `foeopt/report.py:35–39`, whose definition is a target based on half the sum of shorter building sides, not the original road count.

Remedy: display actual original road count and absolute/percentage change; label the target estimate separately. The map's current road list is a candidate source after confirming its counting contract. Avoid presenting this heuristic as a proven bound.

Deferred verification: fixture with original road count intentionally different from the estimate; assert the before/after text uses the original.

### Completion diagnostics exist but are not rendered

Evidence: `OptimizePanel.tsx:118` ignores the done payload and simply marks the job done. `webapp/runner.py:122–126` separately records successful result versus error, and `webapp/app.py:150` emits the final payload. `frontend/src/options.ts:140,166` defines `fillerFailureNote` and `coverageNote`; references found in the frontend are their definitions and unit tests, with no component consumption.

Impact: tested explanatory helpers do not reach users. Solver failure, insufficient sampling, inconclusive search and filler-placement failure can all become an unexplained absence of a new layout. This undermines the lessons' emphasis on distinguishing proven infeasibility from incomplete search.

Remedy: preserve typed final result/error in job state; render coverage and filler diagnostics; retain elapsed time and explain cancellation. Add a component-level test asserting these messages actually appear, rather than only testing helper strings.

### Stream failures and duplicate starts are uncontrolled

Evidence: `api.ts` has no EventSource error callback or guarded JSON parsing. `OptimizePanel.tsx:113–114` marks running only after the optimize request returns, leaving a window for repeated starts.

Remedy: enter submitting state immediately, disable duplicate submission, expose reconnect/disconnected status, reconcile against server job status, and handle malformed events. Pair UI safeguards with server admission control. Keep valid prior results available when a new run fails.

Deferred verification: double click before response; transient disconnect; terminal server error; malformed event; reconnect after completion.

## Priority 2: import, persistence and contracts

- **Worker lifecycle:** `LoadPanel.tsx` never terminates a previous worker or cleans up on unmount, and has no worker error handler. Rapid file selection may finish out of order. Use one cancellable import lifecycle with explicit error handling and a documented file-size limit. The `.city` path currently parses on the main thread; consider routing both formats through the worker.
- **Save failures:** `ResultPanel.tsx:22–29` has no catch or pending state. Failed saves can become unhandled rejections and repeated clicks can create duplicates. Show success only after confirmation, expose failure, and disable duplicate saves while pending.
- **Silent failures:** history loading, list refresh and Stop swallow exceptions. Explain actionable errors without discarding the last valid state.
- **Network contracts:** `api.ts` uses widespread `any`; successful non-JSON responses are converted to `{}` and accepted as typed responses. Parse as `unknown`, validate expected fields, and centralize HTTP/error handling. `apiDeleteLayout` also omits `response.ok` checking.
- **Preset copy drift:** `OptimizePanel.tsx:139` says the best preset uses seed polish, but `webapp/params.py:253` sets it to zero. The tooltip also cites two-city records without the FR17 qualification recorded in lessons. Serve preset descriptions and evidence alongside preset values.

## Priority 2: accessibility and responsive behavior

- Hidden file inputs leave non-focusable labels as the only visible import entry points. Use a keyboard-accessible native input/button pattern.
- History entries are click-only divs (`ResultPanel.tsx:70`); use buttons with accessible names.
- Building search/filter and cached-city selector need explicit labels.
- Status/error regions need live-region semantics; current/optimized toggles should expose selected state.
- CityMap is mouse-only: pan, hover and wheel have no keyboard or touch equivalent. Add pointer events, keyboard pan/zoom, zoom buttons, accessible building details and an equivalent coordinate/list view where needed.
- `styles.css:9–12` fixes a 320px sidebar beside the map without a mobile breakpoint. Use a collapsible or stacked layout on narrow screens.
- Canvas dimensions match CSS pixels rather than device-pixel ratio, which can blur high-DPI rendering. Scale the backing buffer while keeping logical geometry unchanged. Constrain tooltips within the viewport.

Deferred verification: keyboard-only import/history navigation, screen-reader names/status announcements, narrow viewport and touch navigation, high-DPI render check. No claim of WCAG compliance is made from static inspection.

## Test strategy once CPU capacity is available

Existing tests emphasize pure functions. `api.test.ts` tests a custom `parseSSE`, but production uses native EventSource directly; those tests do not establish stream lifecycle correctness.

First add cheap mocked integration coverage for stale events, reversed request completion, duplicate starts, final diagnostics, disconnected streams and failed saves. Then run one browser smoke for import → optimize → stop → save → reload and a keyboard accessibility smoke. Keep solver benchmarks separate from frontend validation; do not launch expensive optimization just to verify an error banner.

## Lessons that should shape the work

The lessons file contains superseding conclusions: short user budgets differ from research budgets; seed polish is disabled in the short-budget preset; two-city settings are not universal because FR17 disagrees; heuristic targets cannot replace complete valid outcomes; and test-client coverage did not exercise real streaming/threading. The most valuable frontend work is therefore accurate result reporting and asynchronous state ownership before adding more controls or speculative rendering optimization.

## Suggested delivery order

1. City/job/request identity guards and stream cleanup.
2. Correct original-road baseline and render final diagnostics.
3. Submission, stop, reconnect and save error states.
4. Typed boundary validation and shared preset descriptions.
5. Keyboard/mobile map and import/history accessibility.

Each change should remain independently reviewable. Application fixes are intentionally deferred while another agent is editing this shared checkout and the user has prohibited test execution.
