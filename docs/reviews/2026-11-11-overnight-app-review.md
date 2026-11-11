# Overnight application review

Static comparison: `8fe8d55..59da75b`. No tests, builds, server launches, or solver execution. This report distinguishes new changes from pre-existing unresolved findings.

## Assessment

Only three application/frontend files changed: `webapp/params.py`, `webapp/runner.py`, and the preset tooltip in `OptimizePanel.tsx`. The overnight work principally advances the solver. It does not close the earlier application's lifecycle, persistence, import, or diagnostic findings. Avoid describing the overall review backlog as implemented.

## Improvements verified in source

- Numeric option coercion now rejects booleans, non-finite floats, and fractional integers (`webapp/params.py:334–357`). This directly addresses a prior finding; new cases appear in `tests/test_optimize_options.py`. Tests were read/not executed in this review.
- New objective, objective polish, exact finish, and position-model knobs are present in the shared option registry and forwarded by `JobManager.submit` into `RoadsFirstSearch` (`webapp/runner.py:122–125`). The existing schema-driven frontend can render them without manually duplicated controls.
- The best-preset tooltip no longer falsely says seed polishing is enabled (`frontend/src/components/OptimizePanel.tsx:139`). It labels the reported outcomes as measured ten-minute results.
- The seed-polish explanatory comment now acknowledges the prior deadline fix rather than presenting it as still unfixed.

## Findings and challenges

### P1: New solver telemetry still cannot reach the user as a final report

`OptimizePanel.tsx:118` discards the final event payload and unconditionally marks the job done with elapsed zero. `webapp/runner.py:88–89` also ignores status callbacks. Existing coverage/filler helpers remain disconnected from components. Adding stronger optimizer phases increases the need to distinguish search, objective polish, exact finish, failure, and early completion, but the UI still mostly says running/done.

**Fix:** define a terminal event envelope with state, result, error, cancellation, elapsed time, effective options, and phase metrics. Preserve it in the store and render final diagnostics. Do not infer success merely from receipt of a done event. Deferred verification should inject successful, failed, canceled, and empty-result searches through actual application callbacks.

### P1: Terminal publication race and hidden error remain

`webapp/runner.py:130–134` writes terminal state before result/error, without holding the lock used by readers. `webapp/app.py:137–150` may observe done and emit null; exceptions also produce null because the terminal event includes only `jobs.result()`. Unknown job IDs follow the same empty completion path.

**Fix:** atomically publish one terminal snapshot under lock; read coherent snapshots; reject nonexistent IDs before starting SSE. Provide an explicit terminal error event. This is unchanged code, not a regression introduced overnight.

### P1: Cross-city contamination and duplicate CPU jobs remain

`OptimizePanel.tsx:113–118` marks running only after the submission request resolves and streams unconditionally into global state. It never closes the prior stream or guards callbacks by current city/job. `ResultPanel.tsx:14–17,43–46` likewise accepts stale history responses. Loading another city while a run or history request is outstanding can apply the wrong layout; saving then uses the new city's ID (`ResultPanel.tsx:24–26`).

`JobManager.submit` admits every request and starts a thread (`webapp/runner.py:70–80,136`). No global CPU limit exists, and each admitted run may use additional solver threads in its finishing phase.

**Fix:** submit-state protection, city/job identity on every store mutation, cleanup and stale-response rejection, plus server-side admission and a shared resource budget. Test using controlled fake asynchronous jobs later; no solver benchmark is needed to establish these contracts.

### P2: Best-known settings is only a partial overlay, not necessarily the measured configuration

`frontend/src/options.ts:27–33` merges preset fields into existing values. `BEST_PRESET` (`webapp/params.py:310–324`) does not reset warm start, symmetry breaking, worker settings, time box, or a manually edited k_start. A user can enable previously harmful options, then press “Use best-known settings” and receive a hybrid that was never the measured preset. The new tooltip's detailed result claims make this mismatch more consequential.

**Fix:** decide explicitly whether the action means applying a complete measured profile or a partial parameter patch. Prefer resetting algorithmic knobs to a complete versioned profile while deliberately preserving user budget/resource controls and clearly showing deviations. Return/store resolved parameters and preset revision. Do not silently overwrite resource limits. Deferred test: enable warm start/symmetry or edit k_start, apply preset, and assert the documented behavior.

### P2: Ten-minute evidence is applied to every UI budget

`webapp/params.py` explicitly says objective_polish=0.3 was not measured below 600 seconds; nevertheless the preset applies it at one-minute, default five-minute, and other budgets. This is an evidence gap, not proof of regression. Short budgets can lose scarce exploration time to reserves.

**Fix:** first compare short-budget whole-run outcomes against the prior profile. Until then, label the profile's measured budget range and preserve an explicit baseline profile. If a budget-dependent profile is later adopted, make the effective configuration visible and recorded rather than changing knobs invisibly.

### P2: Numeric validation still has an uncaught overflow path

`webapp/params.py:341` converts JSON integers to float but catches only TypeError/ValueError at line 342. A valid JSON integer with several hundred digits can raise OverflowError during float conversion, escaping OptionError and producing a 500 from `/api/optimize`. This is statically identified, not executed here.

**Fix:** handle OverflowError as invalid input and avoid unnecessary floating-point conversion of integer values; enforce declared ranges before conversion where possible. Add a future API regression using an oversized numeric literal and require a structured 400. Large numeric strings yielding infinity are already rejected by the new finite check.

## Prior findings still open

- Split export helper is read then dropped (`webapp/app.py:94,102`). Preserve/normalize helper data in the cached representation as well as initial loading.
- Non-object JSON can fail `.get` (`app.py:118–119`); saved layout payloads and metrics remain unvalidated and ownership is unchecked.
- SSE uses a destructive per-job queue (`runner.py:145`), so subscribers compete rather than receive replayable events.
- Warm-start repacking has no cancellation callback (`runner.py:104–109`).
- Result comparison still labels the target estimate as the original count (`ResultPanel.tsx:20,56`). Use actual original roads and label the target separately.
- Job retention, upload resource limits, import worker cleanup, save errors, keyboard access, responsive layout, and full layout validation remain as in the original review.

## Next goals in order

1. **Reliable result ownership and terminal state:** atomic backend snapshots, typed terminal events, client error/diagnostic rendering, stale-event guards, and correct original-road baseline.
2. **Compute admission:** one local active run by default or an explicitly bounded queue, product-level solver thread cap, duplicate-submit protection, terminal cleanup, phase-aware cancellation.
3. **Versioned reproducible profiles:** explicit overlay/reset semantics, effective configuration provenance, and short-budget calibration of the new default profile.
4. **Input/persistence correctness:** split import round-trip, object-shape and overflow validation, full layout validation tied to a known city, calculated rather than trusted metrics.
5. **User interaction quality:** error recovery, accessibility, responsive map, and server/SSE integration checks.

The solver improvements can be valuable while these application problems remain. The appropriate response is to preserve the measured solver gains and give the next implementation pass a narrow application reliability scope, rather than start another large heuristic campaign immediately.
