# Project review and improvement roadmap

Review date: 2026-11-11. Initial observed HEAD: `8fe8d55`.

## Executive assessment

The project has a strong experimental optimizer and a comparatively immature application boundary. The highest-return next work is making existing capabilities reliable and visible: preserve completion diagnostics, prevent overlapping CPU-intensive jobs, fix split-file ingestion, validate API inputs, and establish one complete layout-validity contract. Another solver heuristic is not the first priority.

This is a static review, not a verified runtime audit. No tests, builds, benchmarks, dependency installs, indexing, solver runs, or application launches were performed. Historical measurements below are repository claims, not new measurements. Claude is working in this checkout, so application code and shared task files were deliberately left untouched. Only uniquely named review documents were added. Source references describe the inspected snapshot and may move during concurrent work.

## Reading guide

- [Speed and quality work plan](2026-11-11-speed-quality-work-plan.md): six actionable work packages with implementation approaches, experiment gates, and agent handoff instructions.
- [Backend and optimizer review](2026-11-11-backend-review.md): defects, lifecycle, validation, persistence, and proposed verification.
- [Frontend review](2026-11-11-frontend-review.md): stream handling, state transitions, import/export, usability, accessibility, and missing integration checks.
- [Research history](2026-11-11-research-history.md): what succeeded, what failed, what later evidence overturned, and worthwhile remaining experiments.

These companion reviews contain the detailed evidence and remediation plans; this document sets the overall priorities.

## Review plan and completion criteria

- [x] Inspect lessons, task history, remaining work, recent commits, and architecture.
- [x] Read source and existing test definitions without executing them.
- [x] Separate confirmed source defects from architectural risks and research hypotheses.
- [x] Produce prioritized remedies and deferred verification criteria.
- [x] Preserve concurrent implementation work; make no unverified application fixes.

## What has already been achieved

The data model handles multiple export formats, omitted zero coordinates, off-grid anchors, and building-specific road requirements. These details are hard-won domain knowledge, not cleanup opportunities. The router and local-search pipeline gained exact caching and incremental input updates, with historical full-output comparisons. The classical pipeline reportedly improved darkzig from 250 to 158 roads with all buildings placed.

Roads-first search was the substantial architectural advance: generate a road skeleton, solve consumer placement, pack fillers, route and validate the result. Subsequent nonuniform patterns, quality filtering, exact filler repair, and seed polishing produced documented records of 94 roads on darkzig and 76 on FR16. Record-quality campaigns must not be confused with what a short interactive run can promise.

Recent work also addressed misleading search conclusions. An unfinished level is now UNDERSAMPLED rather than a false infeasibility claim. Interleaved work and a 0.35 remaining-budget slice prevent one level monopolizing a run. The repeated study reported parity on FR16/FR17 and gains on darkzig; it does not establish universality.

The web application already has browser-side slimming in a worker, a React map, schema-driven optimizer options, SSE improvements, SQLite persistence, and TypeScript strict mode. Python and frontend lockfiles are committed. These are useful foundations worth retaining.

## Priority roadmap

### P1 — trustworthy end-to-end application behavior

1. **Connect final solver results to the UI.** `OptimizePanel.tsx` discards the `onDone` payload. Preserve final status, diagnostics, elapsed time, errors, and best result; render the existing coverage/filler explanations. Pure helper tests do not establish that users see them.
2. **Make job lifecycle explicit.** Atomically publish result and terminal state, distinguish failure/cancellation/completion, protect against duplicate submissions, close obsolete streams, and reject stale events after loading another city. A stopping request should not silently look successful when it failed.
3. **Bound total compute.** `JobManager.submit` starts a thread for every request; each can create solver processes. Per-option limits allow workers × probe_workers up to 4096 per job. Introduce a server-wide admission limit and thread budget, with a conservative local profile. Multiple tabs must not multiply CPU use unchecked.
4. **Fix split import across its complete lifecycle.** `/api/load/raw` reads `helper_data` but drops it. Normalize the split files into one durable payload or store both explicitly. Loading, optimization, export, and re-import must all use the same representation.
5. **Tighten request validation.** Reject non-object bodies, non-finite floats, booleans in numeric fields, fractional integers, malformed saved layouts, and unknown city references with structured 400 responses. `_as_number` currently accepts `float('nan')` because both range comparisons are false; `int` also silently truncates fractional numeric values. Do not rely on browser controls as the server contract.

These are bounded correctness/reliability changes, suitable for small independent PRs once the concurrent work is reconciled. They do not require a new research campaign.

### P2 — durable correctness and maintainability

**Define full validity.** `foeopt/validate.py:is_valid` currently means no unsatisfied road consumers. It does not itself prove full inventory preservation, unique IDs, non-overlap, region containment, canonical orientation, or road/building separation. Preserve the useful connectivity check, but introduce a separately named full validator against the original inventory. Apply it at publication and persistence boundaries. This prevents repeating the historical rotated-building record retraction.

**Use typed contracts at boundaries.** Introduce explicit Python result/option/event types and discriminated frontend terminal states before decomposing large modules. `roads_first.py` is roughly 1,510 lines in this snapshot; extract pattern generation, probing, scheduling, and reporting incrementally, with public behavior held fixed. Do not combine this refactor with algorithm tuning.

**Make persistence explainable.** Store resolved options, input identity, engine version, terminal status, and result metrics alongside layouts. Add a deliberate retention/deletion policy and schema versioning. SQLite locking already addresses a historical cross-thread defect; replacing SQLite is not justified merely by its presence.

**Keep local and hosted operation distinct.** The current app is a local single-process tool. A public/multiuser deployment needs job ownership, authentication, upload limits, bounded queues, and a deployment model that does not scatter in-memory jobs across unrelated workers. Those are deployment prerequisites, not evidence that the present loopback workflow is compromised.

### P2 — engineering and documentation hygiene

- Runtime versions are not pinned with tracked `.nvmrc` / `.python-version` files in the inspected listing. Choose versions from the actual supported environment and lockfiles, then document `uv sync --locked` and `npm ci` for reproducible setup. Do not choose arbitrary versions during a review.
- No tracked GitHub workflow appeared in the scoped inventory. Add a cheap default CI tier for deterministic unit/contract checks and frontend type checking, with expensive solver and benchmark suites explicitly opt-in or scheduled on suitable hardware.
- Python dev configuration currently declares pytest but no Ruff/type-checking policy. Adopt checks gradually at API/model boundaries, avoiding a repository-wide style churn mixed with correctness fixes.
- Frontend `test` uses `--passWithNoTests`; remove that escape hatch when establishing the CI gate so a discovery regression fails visibly.
- README says city exports are not bundled, then lists the small city file as bundled; clarify which files ship. Its roads-first headline is also behind the later records, although the published records must be labeled with their actual budgets.
- `webapp/params.py` retains comments describing polish as unbounded after subsequent fixes. The preset tooltip says “with seed polish” while the preset sets zero. Correct stale explanations alongside the relevant behavior fixes.
- Keep an authoritative current-state page and decision index. Preserve old experiments as history with supersession links, rather than forcing every reader to reconcile thousands of lines of chronology.

## Research strategy after reliability work

The experiments already reject several generic suggestions: another greedy attachment proxy, wholesale RL replacement, city-scale joint exact optimization, or CNN scheduling justified by AUC alone. Read the companion history before proposing any of these again.

The most useful new evidence would isolate city characteristics: consumer count, road pressure, footprint distribution, region shape, and slack. Use a compact synthetic matrix plus held-out real cities to separate solver difficulty from geometric impossibility. Keep screening advisory until calibration justifies stronger claims.

Any search change should report complete legal layouts, actual routed roads, time to first feasible result, success rate, wall time, CPU/thread allocation, coverage, and timeout versus proof status. Use paired seeds/repeats, equal resource budgets, and machine-load records. Save compact nonpersonal experiment summaries with commit/config/input hashes, since many raw logs are gitignored. Do not launch this work while the machine is saturated.

Bidirectional exploration or adaptive allocation remains a hypothesis, not an automatic follow-up to the old “feasibility cliff.” Later coverage fixes showed that part of that cliff was starvation and incorrect classification. Evaluate against the current sliced scheduler, not the superseded baseline.

## Verification to perform later

The first verification pass should use fake searches and tiny synthetic fixtures, not real CP-SAT campaigns: split-file load→cache→optimize→export round-trip; error and success terminal SSE events; reconnect/duplicate subscriber behavior; rapid double submission; city switch during a run; malformed numeric inputs; invalid saved layouts; and retention/admission-limit behavior. Browser interaction checks should prove diagnostics are actually rendered and keyboard users can inspect the map's information.

Only after contract checks pass should solver changes receive golden-output checks and bounded multi-city comparisons. Preserve ordered dimensions, every original building, road levels, and Townhall connectivity. Historical test counts are not proof that this snapshot passes, and no fresh passing claim is made here.

## Recommended implementation order

1. Result/error contract and frontend wiring, including stale-event protection.
2. Admission control, job retention, and accurate cancellation states.
3. Split import normalization and strict API validation.
4. Complete layout validation and persistence provenance.
5. Focused CI, runtime pins, accessibility, and current-state documentation.
6. Only then, calibrated experiments against the current scheduler.

## Review outcome

No application fixes were applied in this pass: the deliverable is an evidence-backed implementation roadmap with companion source reviews. That preserves Claude's active checkout and avoids presenting untested changes as fixes. The immediate opportunity is to make the existing solver's strong work dependable, understandable, and resource-bounded for its users.
