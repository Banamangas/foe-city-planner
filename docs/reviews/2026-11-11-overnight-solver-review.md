# Overnight solver review

Static inspection of `8fe8d55..59da75b`; no tests, imports, solvers or benchmarks executed. Findings are source-derived, not newly reproduced. The position-indexed encoding and objective are substantial credible advances, but the following integration defects should precede further tuning.

## Findings

### High: seed polish can replace a better objective-polish result

`foeopt/roads_first.py:1717` records the pre-polish best in `best_holder`. Objective polish at 1937 can improve the global best, but does not update that holder. `_apply_seed_polish` at 1626 compares only against the stale holder, and `run` at 1946 assigns its result unconditionally when `improved` is true.

Concrete path: walk best 100, objective polish 90, seed polish 95. Seed polish calls 95 an improvement over 100, emits it after 90, and `best` becomes 95. With exact_finish disabled, final metrics regress. With exact_finish enabled the wrapper preserves a private best of 90 but still forwards the worse callback (1645); if exact routing does not strictly improve 90, no corrective callback is emitted. The UI can therefore end displaying 95 while terminal metrics say 90.

Fix: centralize the incumbent and accept/emit only globally strict improvements. Pass the current best into finishing phases or update the shared holder after every phase. Add a fake-phase regression covering 100→90→95, exact finish both on/off, and assert monotonically decreasing callbacks and consistent final layout/count. This is accessible through manually combining seed_polish with the shipped objective-polish preset, even though seed polish defaults off.

### High: exact finish is outside the budget and ignores cancellation

`_apply_exact_finish` at 1555 always calls `exact_route(time_limit=10.0)`; the call at 1948 does not check the deadline or should_stop. This phase is now enabled in BEST_PRESET. A run can consume its entire budget, receive Stop, then start another exact solve anyway. Ten seconds is material for short boxes, and model construction adds time beyond solver time limits.

Fix: reserve/clamp finishing time against one absolute deadline and check cancellation before entering. Return an explicit skipped reason when no meaningful time remains. Use a cancellation-capable solver callback or document bounded cancellation latency where interruption cannot be supported. Test expired budget and already-cancelled cases with a fake exact router that must not be called.

### Medium: objective solve budgets exclude construction and can be followed by substantial repair

The deadline-aware calculation in `_run_probe:1161` is a good improvement, but `minimize_needed` constructs the model before setting a solver duration. `_apply_objective_polish:1583` reserves a fixed margin, then `validate:1591` may spend `min(exact_repair, limit)` on a further solve. The fixed margin is not a contractual bound on model construction, routing, or exact repair, especially with user-raised repair settings.

Fix: pass an absolute deadline through construction/solve/validation; recompute remaining time immediately before each solver invocation and clamp repair separately. Stop/cancel is checked only between objective skeletons, so a single long polish solve can also delay Stop substantially. Verify with fake clocks and expensive-validation stubs before any real campaign. Do not claim the current time box is a hard bound.

### Medium: the saved-layout verifier verifies a replacement road network

`scripts/verify_layout_file.py:29–33` reconstructs buildings, discards the artifact's roads, and calls `route()` to generate new roads. Its exit status checks validity of that regenerated layout, not the saved artifact. It also does not require the artifact's claimed road count to match the saved roads or verify exact optimality to return success.

This supports a statement that the saved building positions can be routed legally. It does not independently certify that the exported record itself is correct.

Fix: validate the serialized road cells/levels and claimed metrics first, preserving the exact artifact. Separately report greedy reroute and exact-route comparison. Reject missing/duplicate/illegal roads and mismatched declared counts. A corrupted-road artifact with valid building positions must fail. Retain the current geometric/inventory checks.

### Medium: model interchangeability will break when new domain constraints are added

`_size_classes:706` groups solely by ordered dimensions; `_position_solution:766` assigns identities arbitrarily. This matches the CURRENT anchor constraints, which themselves only use dimensions and road adjacency. It is not a drop-in representation for the newly planned two-lane/chain constraints: equal-size buildings can differ in road access requirements or adjacency partners.

Before implementing the latest domain plan, define interchangeability by every constraint-relevant property or keep identity variables for constrained members. Add mixed same-size fixtures with different access/chain requirements. The current random equivalence tests use road_level=1 and no chains; they cannot establish equivalence for future rules. This is a prospective design blocker, not proof that today's position encoding differs from today's item encoding.

## Claims to qualify

`minimize_needed` describes its objective as exact for the skeleton and says route can only match or beat it. The model actually enforces closure on ONE BFS parent forest. For a cyclic skeleton, alternative paths are excluded, so optimality is only within that forest restriction. In addition, a greedy router searching a broader domain is not mathematically guaranteed to beat a feasible restricted solution merely because that solution exists. Actual final-routing comparison in callers is the correct safeguard. Update wording and add cyclic-skeleton examples before extending families.

The new objective successfully challenges the old constant-proxy study; do not retain the prior conclusion that all within-skeleton quality variation is irreducible noise. Conversely, a six-pair result on three cities is promising evidence, not a broad generalization guarantee. New records establish lower achieved counts, not global optimality.

## Next goals

1. Fix shared-incumbent handling across all finishing phases; enforce one publication gate.
2. Make exact finish and objective/repair phases obey a shared deadline/cancellation contract.
3. Correct artifact verification before treating new export records as independently certified.
4. Incorporate the newly confirmed road/chain semantics into the validity contract and class representation before performance tuning those constraints.
5. After authorization to run workloads, add small deterministic fake-phase tests, then repeat the current preset comparison on held-out instances with clean resource accounting.

Keep the position model and objective advances; the review does not justify reverting them. It does justify deferring additional heuristic complexity until result ownership, budget behavior, and record verification are reliable.
