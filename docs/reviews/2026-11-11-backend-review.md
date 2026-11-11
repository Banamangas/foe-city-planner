# Backend and optimizer static review

Date: 2026-11-11. Scope: API, job orchestration, persistence, validation boundaries, and research history. Read-only source inspection; no tests, builds, solver runs, benchmarks, imports, or indexing were performed. Findings below distinguish direct code defects from deployment risks and proposed experiments. The checkout is being edited concurrently; verify line locations and current behavior before implementation.

## Findings and remedies

### P1 — Split-format upload drops the helper

`webapp/app.py:94` reads `helper_data`, but line 102 calls `_parse_and_cache(data)` without it. That helper calls `load_layout_from_dict(data)` at line 49; `foeopt/loader.py:101–106` requires helper data for split exports. The upload therefore fails despite receiving the required file.

Normalize split and combined inputs into a canonical persisted city representation. Merely passing the helper to the initial parser is insufficient: optimize reloads the cached payload at `app.py:129`. Preserve all data required for that reload and export/import round trip. Deferred verification: split upload with helper succeeds, missing helper returns a clear 400, cached reload and re-import preserve buildings, coordinates, region and road requirements.

### P1 — Terminal job state is published before its payload

`webapp/runner.py:122–126` sets state to done before storing result, and error before storing the error message. Worker mutations do not use the manager lock. A stream reader can observe completion before its result and emit null. Publish payload and terminal status atomically under the same lock, and return coherent reader snapshots. Deferred verification: controlled thread interleaving proves no observer can see terminal success without its result or terminal failure without its error.

### P1 — Error and unknown-job streaming contracts are ambiguous

`webapp/app.py:135–150` never checks existence before streaming. Unknown IDs immediately produce `done: null`. Failed jobs also retain a null result and the terminal event excludes the stored exception. Return 404 before opening unknown-job streams and define an explicit terminal schema containing status, result, error and cancellation outcome. Preserve diagnostic detail in server logs while returning an actionable client error. Deferred verification: unknown ID, worker failure before first improvement, failure after an improvement, success, and cancellation each have distinct expected outcomes.

### P1 — Resource admission is unbounded

Every submit starts a thread (`runner.py:128`), retains a job (`:48,72`), and can launch solver processes/threads. `webapp/params.py:148,156` independently permits 64 pattern workers and 64 probe workers. `app.py:130` has no shared admission budget. Per-field numeric validation does not bound aggregate CPU demand across jobs.

Introduce a configurable total worker budget, bounded pending queue, clear overload response, and job cleanup policy. Account for nested solver parallelism and other jobs rather than defaulting blindly to all CPUs. Retain completed results for a documented interval and bound event history. This matters even in local use when another agent or application is working on the machine. Deferred verification: admission and cleanup using fake jobs, followed later by a deliberately small real concurrency exercise.

### P1 — Saved layouts are trusted rather than validated

`app.py:206–216` accepts arbitrary layout JSON and claimed road counts, does not check that the city exists, and performs unhandled integer conversions. A truthy JSON list also fails `.get` in both optimize and save. `webapp/cache.py` has no foreign key linking layouts to cities.

Validate request object shape and field types, reject malformed input with controlled 400 responses, verify city existence, reconstruct layouts against canonical city data, and derive stored metrics from validated geometry. Add a migration for relational integrity. `foeopt/validate.py:43` checks road satisfaction only: it is not a comprehensive geometry validator. A full validator should check exact building identity/count, fixed dimensions, region containment, overlaps, legal road placement, connectivity and road levels, and townhall consistency. Deferred verification should use malformed small synthetic payloads and valid saved-layout round trips.

### P2 — SSE consumers compete for a single queue

`runner.py:68,79,137` implements improvements with one destructive queue per job. Two clients divide events between them; reconnection cannot recover consumed improvements. Retain a latest incumbent plus bounded sequence-numbered event history; give clients independent cursors or replay the latest snapshot on connection. Deferred verification: two subscribers receive the same improvement, and a disconnected subscriber recovers a valid latest state.

### P2 — Warm-start cancellation is not propagated

`runner.py:100–105` calls `repack` without a cancellation predicate; stop is passed only to the later search. The total time allocation is improved compared with the historical bug, but pressing Stop during warm start cannot be observed by that phase. Use one deadline/cancellation context across phases, with checkpoints in repack and before starting the search. This is a static finding, not a measured cancellation latency. Deferred verification: cancellation during warm start prevents subsequent search and releases worker resources.

### P2 — Temporary upload cleanup excludes save failures

`app.py:42–46` creates a temporary file before saving; the cleanup scope starts only after both upload saves. A failing helper save can leave the first file behind. Enclose the complete operation in a temporary-directory context and apply upload size bounds. Deferred verification: injected failure in either save leaves no temporary files.

### P2 — Multi-process deployment would split job ownership

`JobManager` is in-memory and constructed per Flask application. Under multiple WSGI worker processes, a stream or stop request can reach a process that does not own the job. Document and enforce the intended single-process local deployment, or introduce a shared registry and worker service before supporting that topology. This is a deployment risk, not evidence that the current local deployment is broken.

### P2 — Persist result provenance

Current layout storage records city, k, achieved, geometry and road count, but not resolved options, solver version, code revision, elapsed/core time, or termination reason. Store this provenance with accepted results, distinguishing an imported layout from an optimizer-produced one. Keep the canonical city hash stable across equivalent serialization where practical. Deferred verification: an exported/reloaded result retains enough metadata to explain and reproduce its configuration.

## Research history: what is already fixed

The latest record is `tasks/remaining-work.md` sections 10–11, which supersedes older interpretations in `tasks/lessons.md`.

Section 10 records that pre-2026-08-03 INFEASIBLE results could mean a level received zero probes. Current classification distinguishes FEASIBLE, sample-exhausted INFEASIBLE, fully probed but undecided INCONCLUSIVE, and incomplete UNDERSAMPLED. Coverage and filler failures are forwarded through both probing paths and surfaced to users. Do not repeat the older FR17 feasibility-cliff/window narrative as established evidence without checking coverage. Even genuine sample exhaustion refutes that sample, not every possible member of a pattern family.

Section 11 records shipped `level_slice_frac=0.35`, interleaved batch payloads, UNDERSAMPLED-aware control flow, and rebuilding a terminated pool when slices end before the overall deadline. The documented matched study rescued bad starts on three cities; subsequent repeats showed improvement on darkzig and parity on FR16/FR17 from correct starts. This is already implemented work, not an outstanding proposal. Bad starts still reduce quality, so adaptive scheduling remains an experimental refinement rather than a missing emergency fix.

Any future scheduler experiment should compare against the current sliced baseline, retain coverage vocabulary, use held-out cities, and measure valid fully placed outcomes, time to first incumbent, achieved roads, failure rate, actual resource use, and cancellation/deadline latency at user-sized budgets. Do not introduce binary search based on an unproven monotonicity assumption, or infer impossibility from unprobed/undecided samples.

Earlier lessons remain valuable constraints: compare roads only for complete valid layouts; validate domain counts before changing presentation; preserve fixed building orientation and the zero-coordinate omission rule; check full outputs when optimizing iteration-sensitive geometry; benchmark the phase changed rather than wall time alone; and keep research defaults separate from measured interactive defaults.

## Strengths to preserve

- The API parameter spec is centralized and resolved run options are echoed to clients.
- SQLite statements are parameterized and access is serialized by a lock, addressing the recorded cross-thread connection failure.
- Roads-first validation includes filler completion and orientation checks beyond connectivity.
- Pre-screening is advisory and can report uncertainty.
- The research record preserves negative results, corrections and increasingly realistic budget gates.
- Coverage classification and level slicing address important previously misleading conclusions.

## Suggested implementation order and deferred verification

1. Fix import normalization and atomic job completion; specify terminal stream behavior.
2. Add request/layout validation and resource admission/retention.
3. Make streaming reconnectable and cancellation phase-complete.
4. Document deployment constraints and persist result provenance.
5. Only then consider new solver scheduling experiments against the current baseline.

No performance claim or runtime reproduction is made in this review. Once CPU capacity is available, first run focused API/manager tests with fake workers and tiny fixtures; then a bounded integration run covering load, start, improvement, stop, save and reload. Broad solver matrices should be separately budgeted and should not run concurrently with active development workloads.
