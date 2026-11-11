# Overnight evidence review and revised research goals

Static review of `8fe8d55..59da75b`. No tests, solver runs, builds, or imports were executed. Numerical results below are read from committed manifests, not independently reproduced. This review distinguishes useful algorithmic evidence from game-validity and experimental-design gaps.

## Assessment

The position-indexed formulation is a substantial, well-motivated advance. Round 3 records better results in all six comparisons, and earlier first incumbents on all three cities. The objective also has meaningful positive evidence. These results justify retaining the implementations and expanding validation. They do not justify treating every record as game-compliant, every new option as independently proven, or the tested configuration as identical to the web preset.

## Findings requiring correction

### P1: darkzig records are known non-compliant, not current legal records

`tasks/todo.md:870–895` now records user-confirmed rules: level-2 consumers require a path of 2×2 two-lane tiles all the way to Townhall, and chain pieces must retain catalog linkPositions. Line 880 explicitly states every darkzig record violates both. The overnight headline (`tasks/overnight-2026-11-11.md:9–24,50–53`) still advertises verified 87-road results without that qualification.

Mark those artifacts and headline tables as results under the old simplified model. Preserve them for algorithm comparisons but do not claim they are buildable game layouts. Add a validity-schema/rules version to future records. Once the constraints are implemented, regenerate a compliant baseline and compare algorithms under identical rules. An extra three cells is not a reliable correction: full-width connectivity and chain constraints can change the entire solution.

FR exports lacking a catalog do not prove absence of chains. `tasks/todo.md:880–881` says “no detectable chains”; retain this uncertainty explicitly rather than treating missing metadata as verified absence.

### P1: benchmark settings differ from the shipped preset

`scripts/exp_objective_ab.py:31–32,80–101` uses a city-specific 90-second probe limit for FR17 and substitutes that same limit into objective_limit. `webapp/params.py:310–323` ships 30 seconds for both. Thus the 105-road FR17 result validates the 90/90 configuration, not the exact web preset. All committed main comparisons use 600-second boxes, while the UI supports shorter runs and historically defaults to a shorter box.

Next gate: run the actual resolved web preset unchanged at realistic short budgets and 600 seconds, after authorization. Separately test whether position encoding makes the old FR17 90-second allowance unnecessary. Keep configuration qualification in published claims until that check exists. Record all effective options, not merely arm names.

### P2: “every change passed never-worse paired adoption” overstates round 2

The precommitted rule is stated in `tasks/overnight-2026-11-11.md:50–51`. But round 2 (`scripts/_objective_ab2.jsonl`, summarized at overnight lines 44–48) compares polish+exact with in-walk-objective+polish+exact. The latter is worse on both darkzig repeats (90→91) and the second FR17 repeat (107→108). It does outperform the earlier round's objective-only numbers, but that is a cross-round comparison, not the paired baseline arm claimed by the headline.

Correct the narrative: round 1 supports in-walk objective versus off; round 2 demonstrates finishing can help and exposes a search/finishing tradeoff; round 3 supports position versus item under the combined policy. It does not isolate exact_finish or prove the combined policy dominates polish-only. A future small factorial comparison using the position model should distinguish in-walk objective, objective polish, and exact finishing under one fixed baseline and budget.

### P2: first-result latency regresses when in-walk optimization withholds feasibility

Round 2 darkzig first results arrive at 4.2/5.6 seconds for polish-only versus 35.1/36.6 for combined; FR17 at 68.2/64.9 versus 144.9/145.0. Round 3 position improves those combined latencies but still first publishes around 31 seconds on darkzig/FR16 and 91 seconds on FR17, consistent with spending the objective allowance before publishing a feasible result.

This is an interactive product tradeoff, not evidence of universally faster solving. Add time-to-first-valid-incumbent as an adoption gate. Consider publishing validated feasibility results immediately, then streaming objective improvements, without allowing two publications to corrupt incumbent/provenance ordering. Review worker/result transport before implementing this.

### P2: artifact verification checks reconstructed layouts, not saved roads/counts

`scripts/verify_layout_file.py:23–45` ignores saved roads and claimed achieved count, reroutes positions, then validates the newly generated roads. Consequently it can accept an artifact with a wrong advertised count or damaged stored road list. `scripts/exp_objective_ab.py:109–116` also serializes `route(best_layout)` instead of the actual exact-finished roads. Round 2 contains concrete best=90 / verify.route=91 / verify.exact=90 cases, so the distinction matters.

Persist the exact accepted road map including road levels/tile identity and verify that artifact directly. Require claimed achieved count to match the stored accepted metric. Keep re-routing and exact-routing as separate diagnostic comparisons. Fail the experiment gate when verification fails: `run_cell` currently records `ok=True` before verification and merely stores the verification dictionary; false validity fields do not independently flip ok or stop adoption. Extend checks to the newly confirmed game rules.

### P2: manifests are useful but insufficiently self-describing

Rows record arm, city, box, repeat and selected telemetry, but not revision, input fingerprint, solver version, resolved configuration, random seed, host load, or per-level coverage counts. Arm definitions and default implementations can change between rounds. `run_cell` measures wall_s after verification, which includes a separate exact-route call capped at 60 seconds; report search wall time separately from verification wall time.

Alternating A then B for every repeat does not eliminate ordering bias; balance AB/BA or use a recorded randomized order. Only two repeats per city were used, versus the earlier plan's initial four. More importantly, the final lesson acknowledges a depth experiment overlapped one A/B cell despite “strictly sequential” claims. Identify that exact row as contaminated and rerun the pair later. This does not erase the strong observed gains; it limits confidence in timings and universal never-worse claims.

## Challenge the next domain-model plan before implementing it

Validator-first is the right order. However, “no new solver machinery is needed” for composite chains (`tasks/todo.md:887–890`) is too strong. A general chain can have holes, directional link constraints, asymmetric road-access subsets, and identical bounding dimensions with different semantics. Grouping only by width/length would incorrectly make such composites interchangeable.

Define a composite shape as occupied offsets plus road-contact offsets, original member mapping and required road levels. Include all relevant semantics in equivalence-class keys. Support the simple rigid 16×3 chain first only if it exactly represents that catalog chain, without silently generalizing to every set/chain. Round-trip decomposed members to their original IDs and check chain legality independently after output.

Likewise, a two-cell-wide corridor is not automatically a valid arrangement of nonoverlapping 2×2 road tiles through bends and joins. Define tile anchors, occupied cells, attachment/connectivity rules, and the objective unit before generating skeletons. Validate actual tile realizability. The explicit unconnected-military option changes the optimization contract: persist it with results, show affected buildings, and compare records only under matching policies.

## Revised research priority

1. **Correctness baseline:** implement independent road-tile/chain validators; label old darkzig artifacts; document missing-catalog uncertainty. Do this before new record claims.
2. **Repair the experiment contract:** validate saved accepted output, fail closed, persist full provenance, separate timing phases, and mark contaminated rows.
3. **Validate the actual preset:** current position model, web 30/30 settings, short and 600-second budgets, held-out city when available. Use balanced order and at least four paired observations initially; report per-city distributions and failures.
4. **Fix unused-budget search termination:** committed `_objective_ab4.jsonl` user runs stop at ~182 seconds of 600 with one UNDERSAMPLED level; `_objective_ab5.jsonl` FR24 stops with budget and unfinished levels. This is a controller limitation before it is proof of geometric or filler infeasibility. Revisit remaining candidates and/or lower legal k while preserving coverage, rather than label the family weak on incomplete evidence.
5. **Publish feasibility early:** separate latency to feasible placement, validated complete layout, optimized placement, and final finishing. Then evaluate allocation policies with both quality and latency gates.
6. **Only then test integrated fillers:** position indexing makes it expressible, not demonstrably cheap. More filler classes/options can increase model size dramatically. First compare bounded fixed-skeleton consumer+filler feasibility on representative hard cases; inspect variable count, memory, solve time and complete-layout rate. The user's current UNSAMPLED run does not demonstrate filler failure as the root cause.
7. **Revisit advanced scheduling only against this new baseline:** old UNKNOWN-heavy evidence used the item model. Position indexing changes the value of retries, family portfolios and k-start exploration. Re-profile outcomes before implementing the earlier review's speculative policies.

## Evidence worth preserving

Round 3 is a real improvement under the tested simplified rules: darkzig 90/93→88/87, FR16 74/73→68/68, FR17 106/108→105/105. FR16 and FR17 are particularly valuable evidence because the known darkzig game-rule violations are not detected there. Agreement tests and explicit full-inventory/geometry checks are improvements over count-only experiments, though not substitutes for an independent full game-validity contract.

The correction of the degenerate placement proxy is also important. Future closure language should be “no benefit under this metric/model/sample” rather than “this direction is dead.” Conversely, the depth-gap experiment's small sample supports deprioritizing that tested generator change, not a universal refutation of depth-aware skeleton design.
