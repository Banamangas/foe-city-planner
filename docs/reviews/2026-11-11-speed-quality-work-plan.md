# Faster solving and better layouts: agent work plan

## Scope and operating constraints

This is a proposed research and implementation plan, not a claim of measured improvements. Read the main project review and research-history appendix first. Source references reflect the November 11 review snapshot; inspect current code and concurrent work before editing. No experiments or tests were run to prepare this plan.

The user's restriction remains active: do not run tests, solvers, builds, indexing, or CPU-heavy commands while the machine is saturated. A later agent must obtain a changed instruction before executing those steps. Writing experimental code does not authorize executing campaigns. Use isolated feature branches/worktrees for subsequent implementation and do not change shipping defaults until the gates below pass.

## Baseline and shared acceptance protocol

Start with the CURRENT sliced scheduler (`level_slice_frac=0.35`), current start margins, exact filler repair, and budget-aware polish. Do not compare against an old unsliced scheduler and attribute its known defects to today's engine. Capture the actual revision and resolved settings; the web defaults, best preset, library defaults, and CLI defaults differ.

Before each experiment, record a short hypothesis, primary metric, allowed budget, stopping rule, and adoption rule. Change one policy at a time. Keep all feature flags off by default until evaluation. Suggested initial evaluation checkpoints are 60, 120, 300, and 600 seconds; these are future experiment candidates, not authorized workloads. Use a staged subset before expanding.

Use darkzig, FR16, FR17, and at least one held-out city when available. Add synthetic paired cases varying consumer count, pressure, region shape, and footprint sizes independently. Do not fabricate missing private exports. Report unavailable cases explicitly. Start with at least four paired repetitions for comparison with prior studies; increase only if variance makes the decision unclear. Four repeats are not a universal statistical guarantee.

Measure complete-layout success rate first, then achieved routed roads at matched budgets, time to first legal incumbent, actual wall time, resource consumption, coverage, and cancellation latency. Include failures; never compare a partial layout's low road count with a complete one. Retain per-city outcomes rather than hiding regressions in an aggregate mean.

For each accepted result verify original inventory and unique IDs, fixed ordered dimensions, in-region nonoverlapping footprints, legal roads, Townhall consistency, and every required road-level connection. `is_valid` alone is insufficient. Preserve the current best valid result throughout a run; never publish a worse incumbent.

Every experiment should produce a compact manifest: revision, input hash, configuration, seeds, worker counts, host/load description, timing, status/coverage, final road count, validity checks, and artifact hashes. Keep private exports out of Git. Run campaigns strictly sequentially on a suitable idle machine.

## 1. Protect useful CPU capacity

**Objective:** prevent contention and duplicate runs from degrading interactive solve time. This is a resource-control fix; the fastest worker configuration remains empirical.

**Entry points:** `webapp/runner.py:JobManager.submit`, `webapp/app.py:api_optimize`, `webapp/params.py`, and submission state in `frontend/src/components/OptimizePanel.tsx`.

**Approach:**

1. Add a server-wide admission policy before spawning a job thread. For the local single-process application, begin with one active optimization and an explicit busy response; a bounded queue can follow if needed. Protect admission and release with a lock and release in `finally` on success, failure, or cancellation.
2. Validate the product of pattern processes and probe threads against a configured total solver-thread budget. Independent per-field limits are insufficient. Document that this is a conservative concurrency estimate, not an exact cap on all OS threads or CPU utilization.
3. Provide an explicit conservative shared-machine profile and retain the historically measured 6×2 setting as a comparison point, not a hardware-independent optimum. Echo effective values to the client and include them in provenance.
4. Set a frontend submitting state before awaiting the API. Server admission remains authoritative for multiple tabs and direct requests.
5. Add completed-job retention limits separately from active admission. Do not evict active jobs or lose the latest incumbent while clients are reconnecting.

**Deferred checks:** fake worker tests for concurrent submissions, rejection/queue bounds, release after exceptions, cancellation, and job expiry. Later compare candidate allocations such as 2×1, 4×1, and 6×2 at matched wall budgets, recording total CPU consumption and responsiveness. Avoid intentional load-generation stress tests on the shared machine.

**Adoption gate:** admission never exceeds configured limits and cannot deadlock after failures. Select a default worker allocation based on complete-result latency/quality on target hardware; fewer threads are not automatically faster. Roll back the tuning independently from retaining admission control.

## 2. Reach a valid layout sooner through bounded initial exploration

**Hypothesis:** a small initial search around `k_start` can reduce sensitivity to initialization without sacrificing the good-start behavior of the current sliced walk.

**Entry points:** `foeopt/roads_first.py:RoadsFirstSearch.run`, local `level`/`levels` helpers, `_probe_levels_batch`, `classify_level`; existing experiment structure in `scripts/exp_level_budget_ab.py`.

**Approach:**

1. Instrument the baseline's time to first incumbent and per-level generated/surviving/probed counts. Include both the normal start and deliberately displaced starts already used by allocation studies.
2. Implement an opt-in scheduling policy that creates a small bounded neighborhood around the start, including lower and higher k. Use existing legal k constraints and deduplicate levels. The exact offsets and exploration share are experiment parameters, not new constants to declare optimal.
3. Allocate a capped fraction of the global remaining budget to this neighborhood. Ensure each scheduled probe has enough meaningful time; do not split a short run into many unusably small probes.
4. After finding a legal incumbent, concentrate remaining work on productive nearby levels while preserving limited exploration and the incumbent. If exploration produces no result, fall back to the current sliced policy with the remaining budget.
5. Preserve coverage across visits, avoid reprobing identical work accidentally, and maintain the existing distinction between an unfinished sample and a refuted sample. Audit pool termination/recreation when changing scheduling lifetimes.

**Deferred checks:** fake-clock scheduling and coverage tests, levels with zero surviving patterns, stop during exploration, no remaining budget, repeated visits, and preservation of incumbents. Then paired baseline-versus-policy runs at normal and bad starts.

**Adoption gate:** improve first-result time or bad-start success without observed normal-start success regressions; report any road-quality tradeoff explicitly. Require broader evidence before claiming universality. Reject policies whose extra exploration merely delays all good-start runs. Do not assume monotone feasibility or implement binary search based on old false INFEASIBLE logs.

## 3. Spend probe time according to actual outcomes

**Hypothesis:** selectively retrying unresolved probes can improve useful work per unit time relative to raising all timeouts.

**Entry points:** `probe`, `_run_probe`, `_run_probe_seq`, `_probe_levels_batch`, `classify_level`, and result telemetry in `foeopt/roads_first.py`.

**Approach:**

1. Preserve raw solver outcomes separately from level summaries. UNDERSAMPLED is a level coverage condition; UNKNOWN is a solver result. INCONCLUSIVE also includes routing/validation/filler failures, so it must not automatically mean “give CP-SAT longer.”
2. Track stable pattern identity, attempted timeout, elapsed time, seed, family, k, and result. Retain separate causes for solver UNKNOWN, route failure, invalid output, and filler failure.
3. Keep a bounded retry pool containing only eligible UNKNOWN patterns. Initially use a simple deterministic selection rule and small reserved retry budget; do not add a learned scorer before showing retries help.
4. Increase timeout in bounded stages for selected candidates, clamped to the shared remaining deadline and retry allocation. A retry is normally a new CP-SAT solve: do not assume incremental state reuse or count the earlier solve as resumable work.
5. Use proof outcomes only within their exact constraints. Do not retry a proven-infeasible identical model, but do not transfer that proof to another skeleton, seed-dependent restriction, or whole city.
6. When coverage is poor, allocate new-pattern work rather than retries. When UNKNOWN dominates completed samples, evaluate a larger retry share. Both are experimental policies, not fixed truth.

**Deferred checks:** outcome-specific dispatch, retry caps, deduplication, deadline exhaustion, and correct counters across retries. Compare no retries, uniform longer probes, and selective retries under identical TOTAL budgets.

**Adoption gate:** more valid results or better achieved roads per budget, with time-to-first-result and per-city success protected. Historical UNKNOWN autopsies found little recoverable frontier; stop this direction early if longer retries rarely turn UNKNOWN into useful valid layouts.

## 4. Evaluate a small pattern-family portfolio

**Hypothesis:** a bounded fallback can improve performance on unfamiliar cities while retaining the strength of nonuniform quality-band search on calibrated cities.

**Entry points:** `_pattern_generator`, `generate_patterns`, `generate_nonuniform_patterns`, quality filtering and scheduling in `foeopt/roads_first.py`; configuration in `webapp/params.py` only after validation.

**Approach:**

1. Start with an experimental driver sharing one absolute deadline and one incumbent across arms. Avoid launching independent full-budget searches or concurrent worker pools.
2. Primary arm: the current nonuniform/quality-band policy. Candidate fallback arms: alternate-comb and nonuniform without the quality band. Begin with one fallback at a time; do not spread a short run across all possibilities.
3. Give fallback a small, explicit budget share. Record generated, filtered, probed, and useful valid patterns per arm. Count startup/generation costs in the total budget.
4. Deduplicate equivalent skeletons where identities are well-defined. Do not compare families solely by k: final routed road count is the quality metric.
5. Only after a fixed-share portfolio wins should an adaptive allocator be considered. Sparse SAT rates make greedy early “winner” selection risky; retain minimum exploration if adapting.

**Deferred checks:** total deadline enforcement, worker-pool ownership, incumbent sharing, arm accounting, and same-pattern duplication. Compare each portfolio to the current single-family baseline on held-out cities as well as established ones.

**Adoption gate:** improved robustness or final quality with no unexplained success-rate regression. If calibrated-city performance falls, retain the portfolio as an explicit exploratory mode rather than replacing the default. Do not justify it with the superseded claim that FR17 definitively refuted nonuniform superiority.

## 5. Use finishing time only when it earns its cost

**Objective:** evaluate a better search-versus-polish allocation while preserving the already implemented deadline-aware polish and exact filler repair.

**Entry points:** `RoadsFirstSearch._apply_seed_polish`, reserve calculation in `run`, `foeopt/seed_search.py`, `validate` and `foeopt/exact_packing.py`.

**Approach:**

1. Retain exact filler repair; it already rescues useful candidates cheaply in the recorded sample. Measure its current cost and success rather than reimplementing it.
2. Log actual polish seeds attempted, time spent, accepted road reductions, and the search time displaced by reserve. Distinguish “enabled but skipped” from “executed without gain.”
3. Compare existing reserve policy with polish off and one bounded alternative policy for longer runs. Candidate triggers include a valid incumbent, enough remaining time for a meaningful seed, and a period without incumbent improvement. Trigger values must be predeclared experimental settings.
4. Charge all finishing work to the same deadline; check cancellation before each seed and within phases where supported. Preserve the original incumbent unless a fully validated strictly better result is found.
5. Do not assume a stagnation trigger is beneficial: a rare better skeleton may be worth more than repeated solves on the current one. Report displaced exploration alongside polish gains.

**Deferred checks:** reserve arithmetic with fake clocks, insufficient time, no incumbent, cancellation, worse/invalid polish candidates, and actual phase execution in a small integration case. Later compare whole-run outcomes, not just polish's isolated improvement.

**Adoption gate:** better final layouts at equal total budgets on suitable long runs. Keep polish off for short runs unless new data establishes a benefit. Historical 101→100 improvement demonstrates possibility, not a guaranteed gain per run.

## 6. Improve placement within a fixed skeleton

**Hypothesis:** among legal consumer placements against the same skeleton, some leave more useful filler space and yield fewer final routed roads. A useful objective may exploit this, but prior proxy failures make evidence essential.

**Entry points:** `foeopt/roads_first.py:probe` and `validate`, `foeopt/placement_proxies.py`, `scripts/exp_placement_objective.py`, filler packing and routing. Read the existing placement-objective study before designing new features.

**Approach:**

1. First reuse available artifacts. For fixed city/skeleton pairs, collect multiple consumer placements under controlled seeds only when later authorized. Record actual filler success, repair cost, final routed count, and validity for each placement.
2. Separate between-skeleton correlation from within-skeleton predictive power. A feature that identifies good skeletons does not necessarily choose better placements on the same skeleton.
3. Candidate signals may include usable contiguous space for remaining footprint classes and final routing waste. Treat them as hypotheses; avoid reintroducing raw adjacency-sharing or short-side proxies without new evidence.
4. Evaluate candidate predictors on held-out cities AND skeletons, preventing near-duplicate seed samples leaking between train/evaluation sets. Report failure prediction separately from road-count prediction among complete layouts.
5. If a predictor passes, first try bounded reranking of a small placement set. Count the cost of producing all placements. Only then consider adding a CP-SAT objective; optimize lexicographically so full feasibility remains mandatory.
6. Compare the objective's model/solve overhead with the actual routed-road gain. An objective can destroy the fast feasibility behavior that makes roads-first useful. Keep the feasibility-only path as a fallback and default until the end-to-end gate passes.

**Deferred checks:** canonical orientation, inventory, geometry and road levels on every candidate; no regression in filler completion; objective off reproduces baseline behavior where determinism permits. Evaluate final complete layouts under equal whole-run budgets.

**Adoption gate:** held-out predictive evidence followed by an end-to-end improvement without unacceptable success/latency cost. Stop after a predeclared bounded study if signals do not predict within-skeleton outcomes. Do not escalate directly to RL or full-city joint optimization.

## Execution order and agent handoff

1. Reconcile current source, open branches, lessons, and existing experiments. Record what changed since this review.
2. Implement resource admission and diagnostic/provenance foundations independently of search tuning.
3. Establish the current baseline manifest and staged experiment budget once execution is authorized.
4. Test initial-neighborhood scheduling first; follow with outcome-aware retry only if telemetry shows recoverable UNKNOWN work.
5. Evaluate one portfolio fallback, then finishing allocation. Do not combine individually unproven changes.
6. Treat placement objectives as a separate research track with an offline evidence gate before solver integration.

For each work package deliver: concise design, opt-in implementation, targeted deferred-or-executed validation record, experiment manifests, per-city comparison, explicit adopt/reject/defer decision, and rollback path. Update the current backlog and add supersession links to historical conclusions. A null result is useful and should close the hypothesis rather than invite silent retuning until one run looks favorable.
