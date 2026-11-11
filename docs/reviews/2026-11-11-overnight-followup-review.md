# Overnight implementation review and next goals

Static review of `8fe8d55..59da75b`, November 11, 2026. No tests, builds, solvers, imports, or benchmarks executed. Historical test counts and performance numbers are claims from recorded artifacts, not independently reproduced results. Source worktree was clean at review start. This review adds documentation only.

## Verdict

Keep the position-indexed formulation and hinted placement objective: the recorded improvements justify continuing with them. Request changes to correctness, phase orchestration, verification, and the scope of performance claims before treating the new records as game-compliant or the new preset as broadly validated.

The most important change in priorities is the latest user-confirmed domain rules (`tasks/todo.md`, commit `59da75b`). Every darkzig record violates two-lane-road or chain-placement requirements. Better scores under the old model remain useful experimental evidence, but are not playable-layout records. FR exports lacking catalog data also cannot establish absence of chain requirements merely because none were detected.

## Detailed companion reviews

- [Solver correctness and phase orchestration](2026-11-11-overnight-solver-review.md)
- [Experimental evidence and claims](2026-11-11-overnight-evidence-review.md)
- [Application fixes and remaining defects](2026-11-11-overnight-app-review.md)

## What genuinely improved

1. `minimize_needed` optimizes a meaningful choice of road contacts with parent closure, rather than the previous degenerate union-of-all-touched-cells proxy. The prior negative proxy study did not justify closing the whole placement direction. My earlier roadmap was too conservative in ranking this behind scheduling; the new direct formulation evidence supersedes that ranking.
2. The position model removes interchangeable-item permutations instead of adding symmetry-breaking constraints to the old item model. The earlier failure of lexicographic symmetry constraints was not evidence against this reformulation. The recorded third-round comparisons improve all six pairs across three cities.
3. Numeric API validation now rejects non-finite values, booleans, and fractional integer inputs. The preset tooltip was corrected. Filler-area prefiltering is now actually passed through production code.
4. A/B rows and independent verification tooling were committed, which improves auditability. However, the verifier and serialization still need the corrections below.

## Findings requiring action

### P0 — game validity has changed; records and validators have not

Evidence: the final section of `tasks/todo.md` confirms continuous two-lane connectivity using 2×2 tiles and catalog linkPositions for chains. `foeopt/validate.py`, `foeopt/exact_router.py`, and the current verifier still assess the older model. The overnight summary explicitly acknowledges every darkzig record breaks both rules.

Immediately label affected records as non-compliant under the confirmed rules. Preserve them as legacy-model experiments. Add a validation-version field and distinguish verified, invalid, and unknown due to missing metadata. Do not silently classify missing catalog metadata as “no chains.”

### P1 — finishing phases do not share a single incumbent and deadline contract

`RoadsFirstSearch.run` applies objective polish, then seed polish, then exact finish. Seed polish compares against the older walk incumbent in `best_holder`, not necessarily the better objective-polished result. A seed result can therefore be accepted as an improvement over the walk while worsening the already published best. The exact-finish wrapper retains a minimum internally but forwards every callback, so UI consumers can still receive a regression.

Use one incumbent owner for all phases. It should validate and atomically accept only strict improvements, update returned metrics and artifacts, and publish the same accepted layout. Regression scenario for later testing: walk 100, objective 90, seed 95 must finish and publish at most 90 regardless of exact-finish setting.

`_apply_exact_finish` grants a fresh 10-second solver limit and is called without checking the shared deadline or stop signal. Model construction is additional time. Objective polish likewise computes a solve allowance before model construction and can run exact filler repair afterward. Adopt a shared deadline/cancellation context, reserve finishing time explicitly, and recompute remaining time immediately before each solve and repair. A timeout cap on one solver invocation is not a cap on the phase.

### P1 — verification must inspect the delivered artifact

`scripts/verify_layout_file.py` ignores saved roads and rebuilds them using `route`. It does not check the claimed achieved count against the saved network. `scripts/exp_objective_ab.py` also serializes rerouted roads while retaining the achieved count from the accepted layout, potentially losing an exact-finish improvement. Its verification dictionary does not itself cause a failed invariant to reject the result.

Persist the actual accepted road network, including levels/tile semantics, and validate that network before optionally computing independent routing comparisons. Fail the gate on every invariant violation and count mismatch. Preserve actual search elapsed time separately from the extra post-run verification work currently included in `wall_s`.

### P1 — the demonstrated configuration is not always the shipped configuration

The A/B driver uses per-city probe limits: FR17 gets 90 seconds, and objective_limit follows that value. BEST_PRESET uses 30 seconds for both. The 600-second studies also do not validate the fixed 30% objective reserve at shorter interactive budgets. These are meaningful configuration differences, not cosmetic reporting issues.

Retain the useful records but label exact parameters. Run a later comparison using resolved API preset values verbatim, alongside the tuned research configuration. Do not assert universal improvement from two repetitions per city. The round-two blanket “never worse” narrative also needs the explicit comparator: polish versus both includes regressions; cross-round comparisons are not new matched pairs.

### P1 — k_start at the upper boundary can leave useful time unused

The existing ascent loop only proceeds while `k < k_max`. If the first level at the upper bound is UNDERSAMPLED, it can exit FAMILY_TOO_WEAK without retrying or exploring lower levels. This is already acknowledged for the user's dense city. Fix the control-flow defect separately from designing a general adaptive search algorithm, and never label incomplete coverage as evidence that the family cannot work.

### P1 — most application reliability fixes remain open

The overnight diff changes numeric parsing, option plumbing, and tooltip text; it does not resolve stale cross-city callbacks, ignored final diagnostics, job admission limits, split-upload helper loss, destructive SSE queues, or terminal-state publication races. These are still higher-confidence fixes than another speculative search policy. See the application appendix for source evidence and acceptance criteria.

## Challenge to the proposed domain implementation

“Chains are rectangles, so no new solver machinery is needed” is too broad. A known straight chain can be represented by a rectangular composite, but a general linked assembly may have holes, offsets, multiple eligible link locations, or member-specific road contacts. A bounding rectangle can falsely block usable space, and treating its whole perimeter as road-valid can connect a filler segment rather than the required base building.

Start with an explicit composite representation: member offsets and identities, occupied-cell mask, road-contact mask per requirement, and reversible expansion to original entities. Group position variables only when these full placement constraints are equivalent. The current `(width,length)` class key is insufficient once same-sized composites have different valid road borders, road levels, or member restrictions.

Similarly, a two-cell-wide corridor is not automatically a legal set of 2×2 road tiles. Define tile anchors, occupancy, permitted connections at turns, and Townhall/consumer contact semantics explicitly from the confirmed rules. Validate the actual tile representation, not a connected set of cells with level labels. The unconnected-military option must be explicit per run and visible in validation/export; never silently relax a requirement to improve the score.

## Next goals, in dependency order

### Goal 1 — authoritative legality and record status

Deliver a shared full validator with structured violations and unknown-metadata status. Keep old connectivity checks as helpers. Add fixtures later for a broken two-lane path, invalid tile corner connection, chain offset error, valid straight chain, valid behind-linked chain, and metadata-unavailable input. Update record metadata immediately; revalidation requiring solvers remains deferred.

Acceptance: an old invalid darkzig artifact cannot receive an unqualified valid verdict, and a catalog-free export cannot claim chain completeness without evidence. Preserve original inventory and record provenance.

### Goal 2 — reliable incumbent, artifacts, and phase budgets

Implement one incumbent store and one deadline across walk/objective/seed/exact/repair. Serialize its actual final layout. Separate search timings from verification. Make verification failures reject experimental results. Add later fake-clock/callback checks for the 100→90→95 scenario, stop before exact finish, exhausted budget, construction consuming budget, and corrupted saved roads.

Acceptance: emitted counts never increase; returned best, persisted count, actual road network, and last accepted event agree; stopping cannot launch a fresh finishing solve.

### Goal 3 — complete the application correctness work

First prevent city/job identity contamination and display final diagnostics; then implement admission control and coherent terminal events; then normalize split imports and saved-layout validation. Keep these small changes separate from solver research.

Acceptance: city A cannot update/save into city B, duplicate submissions cannot oversubscribe the server, and a split export survives load/cache/optimization/export round-trip. Tests remain deferred under the user's CPU restriction.

### Goal 4 — domain-compliant solver support

Implement composite chains and two-lane tile geometry against Goal 1's contract. Include complete constraint signatures in position classes. Apply the same semantics in probe, objective, greedy route, exact route, filler repair, serialization, and UI. A validator-only fix must reject unsupported layouts rather than falsely passing them while solver work is incomplete.

Acceptance: publish a new compliant darkzig baseline using explicit connection policy, inventory preservation, and independent validation. Do not compare its raw score directly against invalid legacy records as if they shared an objective.

### Goal 5 — boundary scheduling and dense packing

Fix the upper-bound UNDERSAMPLED exit with bounded retries/exploration and truthful termination status. Then prototype adding fillers as unconstrained-road placement classes for dense cities, behind a flag. Group fillers separately from equal-sized road consumers. Measure model size and construction time; position encoding does not make a large filler model automatically cheap. Validate first on small exact cases before a bounded dense-city campaign.

Acceptance: the boundary fixture uses its permitted budget without claiming a false refutation; joint filler placement produces complete legal layouts and is evaluated against existing exact repair at equal total budgets.

### Goal 6 — revalidate and tune the actual preset

Only after the correctness gates, compare literal API BEST_PRESET with the tuned research settings at representative short and 600-second budgets. Use paired repeats, balanced arm order, held-out cities, CPU headroom, and manifests containing code/input hashes and effective options. Verify that a faster model's early termination reflects a justified stopping policy rather than unexplored useful levels.

Acceptance: retain per-city success and quality distributions, include failures and unknown metadata, and select the reserve/timeouts on measured tradeoffs. If a setting only wins long runs, make it a long-run profile instead of claiming a universal default.

## Work intentionally deferred

Two additional near-term concerns should be included in the next changes. First, the UI's best-preset action overlays current values, retaining unrelated modified settings; reset to documented defaults before applying a reproducible preset, or clearly display the resulting deviations. Numeric validation also needs to catch `OverflowError` from oversized JSON integers. Second, faster final solving is not the same as faster feedback: in-walk objective work delays publication of the first feasible candidate. Consider publishing the validated feasibility incumbent before optimization through a safe progress channel, with bounded event volume and the shared incumbent gate, then measure first-result latency separately from final quality.

Qualify the objective's mathematical claim as well: BFS-parent closure optimizes the chosen parent forest, not arbitrary connectivity in a cyclic skeleton. The greedy router has no guarantee that its result is no larger than that objective. Keep actual final routing and full validation as the acceptance gate.

Generic family portfolios, learned allocation, and further surrogate tuning should wait until the new formulation is calibrated and domain validity is enforced. The previous six-package speed plan remains historical guidance; Goals 1–6 here supersede its execution order in light of the overnight evidence.

No source fixes were made during this review. All proposed runtime verification and campaigns remain deferred until the user lifts the no-tests/no-heavy-CPU restriction.
