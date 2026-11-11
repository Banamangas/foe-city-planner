# Further Model Speed and Layout Quality — Research and Implementation Plan

> **For agentic workers:** This is a staged proposal, not a report of measured gains. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` when implementation is requested, and execute one independently evaluated task at a time. Do not implement all experiments together.

**Goal:** Improve time to a complete game-valid layout and final road quality by retaining useful solver output, removing repeated computation, and selectively expanding the current placement model.

**Architecture:** Keep the position-indexed CP-SAT formulation and hinted road objective. First preserve its explicit road witness and reuse immutable placement geometry; then compare incumbent-network polishing and a bounded optional-road neighborhood against the corrected baseline. All candidates pass the same legality, incumbent, deadline, and artifact contracts.

**Tech stack:** Existing Python, OR-Tools CP-SAT, and project geometry/validation code. No new solver dependency, RL framework, service, or GPU requirement.

**Design basis:** The design and tradeoffs are contained in this document. Read [overnight follow-up review](../../reviews/2026-11-11-overnight-followup-review.md) for prerequisite correctness work and [research history](../../reviews/2026-11-11-research-history.md) for failed experiments. This document adds model opportunities; it does not replace the correctness priorities.

## Global constraints and current state

- The user's no-tests/no-heavy-CPU restriction remains active. All tests and experiments below are **future validation, not authorized commands to run now**. A later agent must first have an instruction lifting that restriction.
- Initial inspected base: `59da75b`; final source check reached `9fc5b09`. During preparation Claude committed the shared incumbent/deadline fix (`f9c3737`), legality/record-status work (`3f85a36`), and chain composites (`9fc5b09`). These are prerequisites to integrate, not tasks to duplicate. Reconcile current source before implementation; symbol references are more durable than line numbers. The new `_class_key`, `contact_cells`, and `foeopt/chains.py` composition/expansion paths must be reused. This plan has not independently certified those concurrent changes.
- Only this new plan is created by this task. No application edits, tests, imports, solver runs, benchmarks, or generated indexes were performed.
- Game correctness precedes quality. Preserve inventory, fixed orientation, nonoverlap, region containment, chain geometry, and actual road-tile/level connectivity. Inputs with missing catalog facts have unknown validation scope, not automatically complete rule coverage.
- Do not evaluate new game-quality records using the non-compliant historical darkzig records. They may still serve as explicitly labeled legacy-model geometry fixtures.
- Never accept partial placement as a quality improvement. Retain the best fully validated incumbent; no objective or heuristic candidate may overwrite it without passing validation.
- Count generation, construction, solving, packing, validation, process startup, and cleanup in the run budget. A solver's `max_time_in_seconds` alone is not an end-to-end deadline.
- Future tests should be small and targeted before any serial campaign. Do not run expensive full suites as a default development loop.

## Decision summary

| Priority | Proposal | Intended benefit | Confidence / limitation |
|---|---|---|---|
| 1 | Preserve and validate the objective's selected roads | Avoid losing a feasible network; potentially fewer roads or filler failures | Concrete information loss in current interfaces; benefit unmeasured |
| 2 | Reuse placement geometry; complete feasible hints | Less Python setup and potentially faster objective progress | Repeated work is visible; hints may help or hurt |
| 3 | Optimize filler scanning without changing its choices | Reduce a likely new bottleneck after fast position solves | Historical packing costs are material; profile current workload first |
| 4 | Polish on the accepted network rather than only its original skeleton | Use newly available placement space around a known good solution | Small extension, but a smaller network may reduce flexibility |
| 5 | Local position model with optional road-support cells | Escape fixed-skeleton restrictions and couple packing to road selection | Highest quality potential and engineering risk; tightly bounded spike |
| Supporting | Persistent candidate ledger and local proof reuse | Avoid accidental repeated work and make coverage honest | Must preserve deliberate sample diversification |

**Recommended first implementation:** Task 1, then Task 2A. Task 0 supplies the measurements and correctness prerequisites. Do not jump to the optional-road model just because it is more ambitious.

## Why these rather than another generic heuristic

The recent gains came from a better formulation: identity-free position variables and a real road-selection objective. Preserve that advantage. Prior negative results for classical warm-start layouts, rigid-lane LNS, and giant joint CP-SAT models do not logically rule out these narrower changes, but they require explicit gates.

The main alternatives considered were more scheduler/worker tuning, stronger placement proxies, and whole-city joint optimization. Scheduler tuning remains useful after the new formulation is profiled; proxy tuning has repeatedly failed actual-road gates; whole-city coupling repeats a known scaling risk. The recommended path starts with information and computation already present, then explores a small known-feasible neighborhood.

No percentage speedup or road-count gain is claimed by this plan.

## Review focus: cases that must not break

1. **A greedy reroute is worse than the selected road witness:** retain the witness and compare complete layouts, not just consumer routes.
2. **Equal dimensions, different constraints:** never merge classes with different road-contact masks, road levels, chain members, or connection policy.
3. **A narrow restricted-model optimum versus a better unrestricted route:** do not turn a forest objective bound into a global quality bound.
4. **Neighborhood cuts through a footprint, chain, or exterior connection:** freeze the whole affected object/backbone or skip the neighborhood.
5. **Budget expires between solving and packing:** keep the accepted incumbent; never publish an incomplete candidate or launch unpaid cleanup solves.

Each case is assigned to a task below. Also test zero consumers, duplicate/reordered class members, negative/nonzero coordinate origins, irregular region holes, and no-op candidate fingerprints where relevant.

## Task 0 — establish a usable baseline and phase ledger

**Files:** Modify the current experiment driver or add `scripts/exp_model_pipeline.py`; add light diagnostic fields near `probe`, `minimize_needed`, `validate`, and finishing orchestration in `foeopt/roads_first.py`. Follow any telemetry structure Claude has already added rather than creating a competing one.

**Prerequisites:** One accepted-incumbent owner; actual accepted roads persisted and verified; shared deadlines; recorded legality scope. Implement those review fixes first if absent.

- [ ] Read the current branch and reconcile changes since `59da75b`; record resolved effective options, not an assumed preset.
- [ ] Separate phase timings: pattern generation, anchor enumeration, CP model assembly, solver time, routing, greedy fillers, exact filler repair, objective finishing, and validation. Store variable/anchor counts and per-phase call counts. In parallel runs retain per-task spans and a wall-clock timeline; summed worker time is not elapsed wall time.
- [ ] Record time to first complete valid incumbent and its quality; keep objective values, selected-road counts, routed counts, filler success, and accepted game-valid cost as separate fields.
- [ ] Add fake-clock/accounting tests later: construction and verification cannot disappear from timing; a failed validation is not `ok=True`; two concurrent task durations are not naively added to elapsed time.
- [ ] When execution is authorized, capture a small baseline using the literal shipped profile and a fixed-pattern micro-corpus. Include a warmed-worker and a cold-start case. Do not begin with a full parameter sweep.

**Output contract:** An experiment manifest contains source revision plus dirty-patch fingerprint if needed, input fingerprint, schema/rules version, exact effective options, solver version, hardware/thread allocation, status, timings, accepted incumbent trace, and validity scope. Keep private exports out of Git.

**Decision:** If construction/packing is now a large share of runtime, prioritize Tasks 2/3. If objective search dominates, compare hints and witness-backed finishing first. Historical 0.1–0.3-second position probes are a reason to measure again, not a guarantee for every city.

## Task 1 — preserve the objective's explicit road witness

### Finding

`minimize_needed` and `_minimize_needed_position` build `needed[c]` road variables and solve parent closure plus consumer contact. They return positions only. `validate` subsequently computes a new greedy route and packs fillers around it. The selected connected road network—and its known feasibility for those consumer anchors—is lost.

The current validator already routes before packing fillers, so unused original skeleton cells already become available to **fillers**. Do not propose that existing behavior as a new optimization. The missing information is the objective's selected network; consumers are still excluded from every original skeleton cell during placement.

### Proposed contract

Create `foeopt/placement_candidate.py` with immutable solver-result data, or extend an equivalent new type if the current branch already has one:

```python
Cell = tuple[int, int]
Placement = tuple[int, int, int, int, int]  # entity_id, x, y, width, length

@dataclass(frozen=True)
class PlacementCandidate:
    placements: tuple[Placement, ...]
    selected_road_cells: frozenset[Cell]
    objective_value: int | None
    objective_bound: float | None
    solver_status: str
    model_fingerprint: str
    rules_version: str
```

`selected_road_cells` initially represents single-lane geometry only. It must not pretend to encode 2×2 road tiles. Reuse the project's eventual authoritative road-network type when broadening domain coverage.

**Files:** Modify both objective result paths and `_run_probe`/objective polish in `foeopt/roads_first.py`; factor candidate-specific packing/validation out of `validate` while preserving its default adapter. Add `tests/roads_first/test_road_witness.py`.

- [ ] Add a pure witness checker: selected nodes are reachable from the Townhall in the chosen forest, every selected nonroot has its parent selected, every consumer has eligible contact, and no selected cell overlaps a footprint or lies outside the region.
- [ ] Extract selected `needed` values and return the candidate plus status/value/bound. Never read assignment values on UNKNOWN, INFEASIBLE, or MODEL_INVALID.
- [ ] Refactor finalization so it can evaluate a supplied road network without silently replacing it. Preserve the existing reroute path.
- [ ] Evaluate the witness and the greedy route as two candidates under a shared budget. Run filler packing against each candidate's own occupancy. Do not reuse filler placements across different roads without checking overlap and legality.
- [ ] If the first complete candidate is better, retain it immediately; consider the second only when time remains. A smaller consumer road network is not necessarily more packable.
- [ ] Initially evaluate the existing greedy candidate first for baseline compatibility; admit the witness candidate only with a capped remaining packing/repair allowance. All phase loops need deadline checkpoints. Measure a witness-first variant separately rather than silently changing both routing choice and budget order.
- [ ] Initially enable witness evaluation only for supported single-lane/no-unresolved-chain cases. Route all other cases through the authoritative domain path until equivalent witness semantics exist.

**Future tests and expected assertions:**

- `test_objective_witness_is_connected_and_serves_every_consumer`: closure/contact/occupancy checks all hold.
- `test_witness_survives_a_worse_greedy_reroute`: inject two valid networks, e.g. witness cost 6 and reroute cost 7; accepted full layout is 6.
- `test_smaller_witness_does_not_displace_complete_layout_when_fillers_fail`: keep the larger complete result.
- `test_witness_artifact_roundtrip_preserves_roads`: stored and loaded geometry/count match exactly.
- `test_unsupported_road_tiles_do_not_receive_single_lane_certificate`: unsupported semantics are explicit, not silently downgraded.

**Gate:** Compare witness-only, current-route-only, and bounded dual evaluation on the same consumer candidates. Measure additional complete results, road differences, and extra packing cost. Adopt dual evaluation only where its whole-run cost is justified; retain the witness in diagnostics even if evaluation is selective.

## Task 2A — compile immutable placement geometry once

### Finding and boundary

`_probe_position` and `_minimize_needed_position` both invoke `_position_model`, independently enumerating anchors and cell coverage for the same pattern. Objective polish may repeat this again. Existing footprint caches reduce cell construction but not all candidate filtering and incidence assembly.

**Files:** Create `foeopt/placement_geometry.py`; adapt `_anchor_candidates`, `_position_model`, feasibility and objective builders. Add `tests/roads_first/test_placement_geometry.py`.

**Interfaces:**

- `compile_geometry(reference: Layout, pattern: Pattern) -> PlacementGeometry`
- `PlacementGeometry`: immutable ordered semantic classes, class demands, anchors, occupied-cell indices, eligible road-contact indices, and per-cell covering anchor IDs.
- `ConstraintClassKey`: includes ordered footprint/occupied mask, road requirement/contact mask, composite member restrictions, and connection policy. Reuse the legality layer's representation; do not create a second source of game rules.

Keep the geometry module independent of solver orchestration: use type-only imports for `Layout`/`Pattern` where possible, or move shared descriptors into an existing neutral model module. Do not create a `roads_first` ↔ geometry runtime import cycle. The current `_class_key` already includes dimensions, contact data, and road level; extend only for additional constraints actually represented by the new mode.

- [ ] Produce identical ordered anchor lists to the old builder on supported cases. Maintain a stable class/anchor order so any trajectory changes are attributable.
- [ ] Build separate CP models from the same immutable geometry. Do not share mutable solver variables or model instances across tasks/processes.
- [ ] Reuse the geometry within one probe→objective task first. Only add a small worker-local cache if finishing/retries demonstrate reuse; bound it by estimated bytes, not just entry count.
- [ ] Include region, Townhall, road support, inventory constraint signatures, and rules version in fingerprints. Invalidate on changed metadata or connection policy.
- [ ] Compare candidate/constraint equivalence on holes, origin offsets, touching footprints, and same-size objects with different contact masks. Reordering identities within a truly interchangeable class must not change the feasible anchor sets.

**Gate:** Reduced construction time and memory-safe whole-run behavior at equal budgets. The feasible set may be preserved while solver timing and returned ties change; do not promise bit-identical time-limited outputs. Model cloning is a later experiment only if assembly remains expensive—geometry reuse is not incremental CP-SAT search-state reuse.

## Task 2B — complete feasible hints and scoped upper bounds

**Files:** New pure helpers in `foeopt/placement_geometry.py` or a small `foeopt/road_witness.py`; objective builders; `tests/roads_first/test_objective_hints.py`.

**Algorithm:** For the known feasible consumer placement, compute every reachable contact's ancestor closure in `skeleton_parents`. In deterministic consumer order, choose a contact requiring the fewest additional selected ancestors; union its closure into the witness. Hint every position literal and every needed-road Boolean consistently. This greedy selection constructs a feasible hint; it is not used as a new optimization score or a hard restriction.

This construction must satisfy every independent **contact obligation**, not merely one contact per composite object. Start with single-obligation classes; when a composite contains multiple independently road-needing members, process each obligation or skip the new hint helper. Use `contact_cells`/the authoritative constraint representation rather than the composite bounding-box border. Position and needed literals cover the simple position model's assignment; the item model also has coordinates and auxiliaries. Either populate them consistently or describe the result as a feasible partial hint, not a complete solver assignment.

- [ ] Verify the hint's full assignment against the current model semantics. If it cannot be verified, retain partial/no hints rather than inventing a proof.
- [ ] A feasible witness with `U` selected cells permits `sum(needed) <= U` without removing the optimum of this restricted objective.
- [ ] Optionally precompute each contact's ancestor-closure size. For an anchor, the minimum size among eligible contacts is a lower bound on required selected cells. Omit an anchor only if that bound exceeds `U`.
- [ ] Measure complete hints alone, then the upper bound, then anchor pruning. Keep them independent flags so a null/regression can be isolated.

**Critical restriction:** `U` must come from a feasible witness **in this exact forest model**, never from a smaller unrestricted routed incumbent. Likewise, `objective_bound >= routed_best` does not prove that a skeleton cannot yield a better final routed city. An optimal forest solution does not settle all equal-objective placements' filler feasibility.

The bound can also exclude a HIGHER forest-objective placement that would have produced a BETTER unrestricted routed result or a complete filler packing. Thus bound/pruning is optimum-preserving for the restricted objective only, not for downstream city quality. Keep that policy independently optional and evaluate accepted complete layouts, not just equality of objective optima.

**Future tests:** tiny exhaustive tree cases preserve the restricted optimum before/after pruning; a contact path larger than `U` is removed; feasible hinted anchors remain; a cyclic skeleton with a cheaper outside route cannot substitute that routed count for `U`.

**Gate:** Improve first objective incumbent time or whole-run outcome; reject if complete hints slow search. This differs from old packer warm starts because the hint already satisfies the same skeleton model, but it is still not a guaranteed speedup.

## Task 3 — accelerate the existing best-fit filler scan

### Why it may matter now

`_place_fillers` scans every coordinate for each filler, invoking `Grid.fits` over footprints and neighboring perimeter cells. Its comment cites roughly 42 ms on FR16 and 434 ms on darkzig, justified then as a small fraction of a 30-second probe. With some position probes now subsecond, that rationale needs remeasurement. This is a new bottleneck hypothesis, not evidence that best-fit should be removed.

**Files:** `foeopt/packing.py` and `_place_fillers`; `tests/test_packing.py` plus small exact-choice regression fixtures.

**Approach:** Preserve descending area, stable original-order ties, ascending y/x anchor scan, and “strictly greater tightness” choice. Implement row occupancy masks to check a rectangle against each affected row rather than visiting every cell. Compute the SAME blocked-perimeter score, including out-of-grid boundaries and region holes. Update masks on every placement.

- [ ] First profile how much `fits` versus scoring consumes; skip this task if immaterial.
- [ ] Add a test oracle using the old scan. Compare complete placement lists, unplaced lists, and chosen anchors over small deterministic irregular grids.
- [ ] Implement a fast path without changing geometric semantics. Never cache a fit decision across occupancy updates.
- [ ] If masks become the primary representation, make occupancy mutation have one owner; avoid two divergent mutable representations.
- [ ] Retain the general path for nonrectangular composites until exact occupied/contact-mask handling exists. A bounding-box approximation is not an acceptable speedup.

**Gate:** Same choices on the fixed-work oracle corpus, lower packing time, and bounded memory. Only then evaluate more candidate throughput under equal time. Do not replace best-fit with first-fit: that previously reduced completeness.

## Task 4 — rebase polishing on the accepted road network

### Hypothesis

The original skeleton may contain many cells no longer used in the accepted result. `_apply_objective_polish` still uses the original pattern and blocks all of those cells to consumer placement. Rebuilding the pattern from the actual accepted network can expose additional consumer anchors while providing a known feasible starting point.

**Files:** Add `foeopt/incumbent_polish.py` (or a narrow helper if existing architecture already separates finishers); integrate into current finishing dispatch; `tests/roads_first/test_rebased_polish.py`; extend the experimental driver.

**Interface:** `polish_rebased(reference, incumbent, budget, on_candidate) -> PolishReport`, where `budget` is the current shared deadline/cancellation object, not a new independent duration. `PolishReport` records attempts, topology fingerprints, validated improvements, and consumed time.

- [ ] Require a fully valid incumbent; construct a pattern from its actual saved roads and actual Townhall, not a fresh `route()` result.
- [ ] Verify the incumbent is a feasible hint under that pattern. For initial supported single-lane cases, all consumer contacts and all selected roads must pass root-reachability checks.
- [ ] Run the position objective using the compiled geometry and explicit witness from Tasks 1–2.
- [ ] Finalize both consumer and filler placement under the current whole-layout legality contract; accept only a strict improvement in actual complete-layout road cost.
- [ ] Rebase again only after acceptance. Proposed initial cap: two solves, within an existing finishing allocation. Fingerprint geometry to avoid repeated no-op attempts.
- [ ] Compare against original-skeleton polish using the same finishing budget; do not add this as unpaid extra work after the deadline.

**Two separate variants:** baseline-compatible repacking of fillers; and preserving incumbent fillers as fixed blockers for a narrower but known-feasible neighborhood. Do not implement both before the first variant has a clear measurement purpose. First prefer the existing repacking path and preserve the untouched incumbent as fallback.

**Future tests:** the incumbent stays feasible after rebasing; vacated old-skeleton cells become legal consumer anchors; same-road-network revisits terminate; a smaller network that loses useful anchors causes a safe no-op; a better consumer arrangement with failed fillers is not published.

**Limits:** shrinking the network also removes contact opportunities and can stall. On cycles, a BFS parent forest is a restriction, not an exact model of every connected subnetwork. Do not call this global optimization or infer city impossibility from its UNSAT result.

**Gate:** Repeatable accepted improvements at equal budgets on more than one held-out case, or a clear latency advantage. If almost every rebase is a no-op, stop; do not automatically grow into unrestricted topology search.

## Task 5 — bounded optional-road neighborhood (research spike)

### The structural opportunity

The current objective chooses which skeleton road cells are needed, but `_anchor_candidates` excludes **all** skeleton cells from consumer footprints even when `needed[c] == 0`. That artificially reserves cells which the model itself says can be unused. Fillers are placed after solving, so consumer placement also cannot account directly for their competition for scarce space.

A position-indexed model can instead treat a small road support as optional occupancy. This is not a parameter adjustment: it is a new, bounded joint formulation. The old city-scale joint model failed on scale; do not repeat it over the full region.

### Scope for the first spike

Start on a single-lane, fully understood toy neighborhood containing all movable consumers AND fillers. Then use small neighborhoods from valid incumbents. Freeze Townhall, exterior buildings, and a connected exterior road backbone. Freeze any chain/two-lane structure unless the authoritative constraint model supports moving it atomically.

Proposed engineering caps for the first spike (unvalidated resource guards, not mathematical thresholds): at most 12 movable atomic units, 64 optional road cells, and 10,000 anchor literals. Count before model construction and skip oversized neighborhoods. Do not weaken validity to meet these caps.

### Model

Let `S` be the optional road support, `B` the fixed backbone, and `z[g,a]` select a legal anchor for semantic class `g`. `n[c]` selects road cell `c` in `S`.

1. **Inventory:** `sum_a z[g,a] == demand[g]` for each class. Fillers and road consumers are different classes even if their dimensions match.
2. **Occupancy:** for each local cell, sum of selected anchors covering it plus `n[c]` when `c in S` is at most one. Unlike the current model, an anchor may cross `S`; it only conflicts with roads actually selected there.
3. **Road contact:** if a road-consuming anchor does not already have valid fixed-backbone contact, `z[g,a]` implies OR of eligible active `n[c]` on its contact border. Fillers have no such condition.
4. **Connectivity:** initially use a fixed parent forest on `S`, rooted at contacts to `B`, with `n[child] => n[parent]`. Retain only root-reachable support cells. It is an intentionally restricted, sound connectivity model for single-lane cells.
5. **Objective:** minimize selected local road cells; fixed exterior road cost is constant. The incumbent provides a feasible placement and road-selection hint. Use its actual feasible model cost for an upper bound.

The exterior backbone must remain independently connected to the Townhall and serve all frozen consumers. If removing local roads disconnects exterior branches, retain the necessary incumbent paths as protected backbone or skip that neighborhood. A pair of boundary contacts alone is not a connectivity certificate.

Define the road partition explicitly: `B` and `S` are disjoint, every incumbent road is either fixed in `B` or represented in `S`, and the reconstructed network is exactly `B ∪ {c in S: n[c] = 1}`. There are no implicit leftover road cells. Require `B` to provide every frozen consumer's eligible contact as well as its root connectivity; a non-articulation road can still be a frozen consumer's only contact.

Use a forest that preserves paths for the incumbent selected local roads before attaching new halo cells. An arbitrary forest over an expanded halo may require extra parent roads and destroy the claimed incumbent hint. Verify hint feasibility; if it fails, repair the forest or skip, never silently assume feasibility.

### Candidate support and neighborhood construction

- Start with a bounded patch around incumbent local roads. Add at most a one-cell halo drawn from currently free cells and cells vacated by selected movable units.
- Include every atomic building intersecting the movable patch; freeze or expand around a whole chain, never split it.
- Enumerate anchors in the local allowed area excluding fixed occupied cells and fixed backbone. Avoid arbitrary cross-boundary movement; preserve a complete fixed/movable partition of the original inventory.
- Include the incumbent support and placements exactly. Do not rely on constructing a new solution from scratch.
- Stop after the capped local budget and validate the entire expanded city before accepting.

**Files:** Create `foeopt/local_support.py`, `tests/roads_first/test_local_support.py`, and `scripts/exp_local_support.py`. Keep the new formulation out of existing production `prefilter` until proven. Reuse semantic geometry and legality interfaces; do not fork domain rules.

### Critical distinctions

- The existing area prefilter uses `building_area + len(pattern.roads)`. It is sound for permanently reserved skeleton cells but **not** for optional support: support size is not selected road occupancy. Use only bounds justified for this new model.
- There is no need to add general city-wide flow variables in the first spike. Parent closure restricts possible topologies; failure means no solution in that restricted neighborhood/forest, not no city solution.
- Real two-lane roads require tile variables, occupied masks, and tile/path semantics. Unit-cell `n[c]` is not a valid substitute. Generalize only after domain support is proven.
- The old rigid-lane LNS rebuilt buildings into predefined lanes. This model preserves a known incumbent, includes fillers, and permits optional local road occupancy. That is a materially different mechanism, not evidence it will outperform current polish.

**Future tests:**

- `test_unused_support_can_hold_a_building`: a fixed-skeleton exclusion rejects a toy placement that optional occupancy can legally realize.
- `test_selected_support_cannot_overlap_a_building`: selected road and anchor overlap is impossible.
- `test_filler_and_consumer_of_same_size_keep_different_constraints`: only consumer anchors require a road contact.
- `test_frozen_exterior_stays_connected`: protecting a local articulation preserves distant service; unsafe patches are skipped.
- `test_frozen_consumer_keeps_its_only_local_contact`: protect a contact road even when removing it would not disconnect the road graph, or include the consumer as movable.
- `test_incumbent_is_feasible_and_expands_to_same_inventory`: no hidden identity loss or chain splitting.
- `test_resource_caps_skip_before_model_allocation`: oversized inputs do not start an uncontrolled solve.
- Enumerate a tiny case later and compare the model optimum with exhaustive feasible layouts under the SAME local forest constraints.

**Go/no-go:** first demonstrate a known toy improvement unavailable to the fixed-skeleton model. Then compare a few bounded real neighborhoods with equal-budget incumbent polish. Proceed only if valid accepted gains justify construction/solve cost. Stop if the model repeatedly hits caps, solves only roomy toys, or reproduces the old near-zero LNS acceptance rate. Do not enlarge to the whole city as a response to failure.

## Supporting task — retain completed pattern work and scoped proof information

Current retries of UNDERSAMPLED levels rebuild state and may generate different samples. A per-level ledger can retain pending/completed pattern IDs, compiled-geometry fingerprints, and statuses. Resume pending work on a retry; generate a fresh sample only through an explicit diversification policy.

Deduplicate only exact model fingerprints. Include region, Townhall, support, inventory constraints, rules version, and any objective restrictions. A pure-feasibility UNSAT proof is local to that model. UNKNOWN is not a proof. An objective optimum is local to the forest objective; equal-objective placements may still have different filler/routing outcomes.

Do not blindly suppress all later solves after one objective OPTIMAL result. Separate **proving the same objective again** from **searching alternative equally optimal placements**. The latter is a heuristic diversity choice that must earn its budget.

Implement this only after the profiling ledger shows repeated work is material, or when retry correctness requires persistent coverage. Preserve a bounded memory footprint and discard invalidated entries on rule changes.

## Deferred ideas: evidence needed before building

**Filler failure cuts:** exact repair currently returns placements/unplaced, not enough proof information. A partial packing or UNKNOWN cannot justify a permanent cut. Even proven failure under one fixed greedy road network does not refute the same consumer positions under another network. Only use sound no-goods in a model where road selection is fixed or included in the excluded assignment; otherwise call it a reversible heuristic taboo. Measure residual proven failure volume before investing.

**Stronger capacity screens:** class-demand area exceeding the union of all candidate occupied cells is a necessary rejection. Small class-pair union checks may strengthen it. They can duplicate CP-SAT presolve work, and prior adjacency screens were sound but ineffective at the frontier. Require net time saved, not just more rejected patterns.

**Alternative parent forests / restricted flow:** cyclic supports may benefit from more connectivity choices, but this changes the formulation and belongs in a separate gated experiment. Never mix it with optional occupancy and claim to know which change helped.

**More callbacks:** solution callbacks can capture intermediate objective assignments, but do not run expensive packing/routing on every callback. Capture a bounded snapshot and validate outside; retain the prior full incumbent. Correct early feasibility publication is a prerequisite UX fix, not evidence that objective search itself became faster.

## Evaluation and adoption rules

Run only after authorization and CPU availability, serially. First use fixed-work, fixed-pattern comparisons to isolate computation changes; then equal-wall-budget comparisons to evaluate actual user benefit. Do not mix solver time with post-run verification time. Include process startup and any candidate-generation overhead in user-visible latency.

Use the corrected literal API preset, not a manually tuned lookalike. Keep a separate named research profile if per-city probe limits differ. Begin with two representative budgets, proposed 120 and 600 seconds, before a wider sweep. Compare at least four paired repetitions as an initial variance check, not a universal statistical guarantee. Balance arm order and record host contention.

Adoption requires: no validity regression; failures included in comparisons; per-city success rate and first-incumbent latency reported; complete-layout road distributions reported; memory bounded. Predeclare allowable tradeoffs. A quality-only long-run improvement should become a long-run mode rather than silently degrading short runs.

Report result classifications explicitly: **implemented/no evidence yet**, **promising micro-result**, **end-to-end gain**, **null**, **regression**, or **blocked by unsupported domain metadata**. Retain rejected experiments and their reopening conditions.

## Handoff checklist

- [ ] Re-read current lessons, overnight fixes, and active edits; record the actual baseline.
- [ ] Confirm legality/incumbent/deadline/artifact prerequisites exist.
- [ ] Implement Task 0 instrumentation and Task 1 witness contract.
- [ ] Implement Task 2A geometry reuse; evaluate Task 2B independently.
- [ ] Use measurements to decide whether Task 3 is worth doing.
- [ ] Compare Task 4 against current finishing at equal budgets.
- [ ] Only then consider the bounded Task 5 spike, preserving its caps and fallback.
- [ ] Document each adopt/reject decision; change one default at a time.

Recommended commit boundaries: `feat(solver): preserve selected road witnesses`; `perf(solver): reuse immutable placement geometry`; `perf(solver): hint feasible road closures`; `perf(packing): accelerate exact best-fit scans`; `feat(solver): add opt-in incumbent-network polish`; `experiment(solver): evaluate bounded optional-road neighborhoods`. Use the repository's accepted Conventional Commit types when committing.

## External API references and scope

The novel model proposals above are deductions from this repository, not claims of externally benchmarked gains. OR-Tools distinguishes FEASIBLE, OPTIMAL, INFEASIBLE, MODEL_INVALID, and UNKNOWN; use those statuses without collapsing timeouts into refutations. See the [official CP-SAT solver guide](https://developers.google.com/optimization/cp/cp_solver/).

Hints and solution callbacks are available in the [official Python CP-SAT API](https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model). Verify exact method names against the project's locked installed version before implementing; do not upgrade dependencies merely to match current online examples. Neither hints nor rebuilding a model imply retained search state across solves.
