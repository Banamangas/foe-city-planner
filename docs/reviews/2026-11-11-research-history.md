# Research history and next experiments

Static review dated 2026-11-11, initial HEAD `8fe8d55`. All results below are historical repository records, not measurements reproduced during this review. No tests, solver runs, imports, builds, or indexing were performed.

## Read sources in the right order

`tasks/lessons.md` is an experimental diary ending with July 31 conclusions. `tasks/remaining-work.md` sections 9–11 contain August results that supersede important parts of that diary. Recent commits through `8fe8d55` confirm the level-budget work was integrated. The top of remaining-work still describes an unmerged branch and says everything is unfinished, despite later completed checklists. Treat current source and the later evidence as authoritative over old headings.

## What worked

### Domain correctness

`tasks/lessons.md:3–39` records essential export rules: omitted x/y means zero; on-grid inclusion uses anchor membership in unlocked areas; Townhall adjacency alone does not satisfy road need; multi-age dimensions require component lookup. Legacy road need is inferred from the connected key plus original road adjacency, assuming a valid original layout. Explicit newer-schema needsStreet flags take precedence where supported.

These rules should become a short invariant reference linked to permanent small fixtures. Do not simplify them based on generic metadata assumptions: several earlier simplifications silently dropped buildings or misclassified consumers.

### Exact performance improvements

`tasks/lessons.md:53–66` documents footprint caching, incremental free-cell inputs, and removal of road-equivalent swaps. Historical anneal throughput improved roughly 7.9 times while golden output comparisons preserved behavior. The useful lesson is to optimize repeated inputs and dead work without approximating the actual objective. Set iteration order can affect routing choices, so equality of counts alone is insufficient for a claimed output-preserving change.

### Roads-first search

The classical pipeline reportedly reduced darkzig from 250 to 158 roads. Validated roads-first results progressed through 106, 104, 98, 95, and 94 roads; FR16 reached 76. Record artifacts are under `docs/records/`. The earlier 127-road result was retracted because buildings were rotated (`lessons.md:505`). Preserve inventory, orientation, geometry, connectivity, and road-level checks in every future record gate.

A fixed-placement exact router matching a result proves optimality for those positions, not global city optimality. The exact-router study (`lessons.md:1689–1742`) matched greedy routing in 10 of 11 inspected layouts, with one road saved in a non-best case. This supports keeping it as an oracle/optional finishing tool, not assuming routing is the main remaining bottleneck.

### Filler repair

The July 31 open filler problem is substantially addressed in `remaining-work.md` sections 8A–8B. Best-fit greedy packing recovered half the initial failures; exact repair then recovered 18 of 22 residual failures in the recorded FR16 sample at about 0.27% runtime cost. The remaining four were proven impossible for those fixed consumer placements, which is narrower than proving the entire city impossible.

Do not propose adding exact filler repair as new work. Product defaults already enable it. Region partitioning would compete with a repair path that already covers most measured failures; reopen only when a new inventory/geometry regime demonstrates a real residual need.

### Budget accounting and scheduling

Warm start and polish were once outside the effective total budget. Later changes charge warm start against the budget and give polish deadline/cancellation checks and a conditional reserve. A documented 600-second comparison exercised actual polishing and improved 101 to 100 roads within budget. This is completed work, although cancellation during warm-start repacking remains a separate application concern.

More consequentially, earlier level classification reported INFEASIBLE even when zero patterns had been probed. `remaining-work.md` section 10 and `foeopt/roads_first.py:901` distinguish:

- FEASIBLE: a legal layout was found.
- INFEASIBLE: the surviving sampled patterns were all refuted; this is not global infeasibility.
- INCONCLUSIVE: the sample was attempted but non-proof failures remain.
- UNDERSAMPLED: the surviving sample was not completed.

Section 11 records the adopted `level_slice_frac=0.35`. Interleaving batch payloads alone did not change the measured outcomes; capping a level's share of remaining budget delivered the practical gain. Mid-run pool termination required rebuilding the pool before subsequent work.

The default-start repeat study had four observations per arm: darkzig baseline [104,104,104,104], sliced [99,99,103,104]; FR16 and FR17 tied their baselines. Bad-start experiments recovered layouts on all three cities where the old scheduler found none. This is encouraging evidence on three cities, not a universal theorem. A bad start still cost quality.

## Conclusions that must not be repeated as current facts

The late July diary says the third city disproves nonuniform superiority and suggests a sharp feasibility cliff. August evidence shows that bad initial settings, starvation, and falsely classified unprobed levels confounded those conclusions. The nonuniform start margin is now zero, and slicing is already shipped. Do not implement cliff bisection merely because an old lesson calls for it.

Similarly, the budget warning remains unchecked in the backlog but exists in `frontend/src/options.ts` and is rendered by `OptimizePanel.tsx`. Screen-banner helper tests also exist. However, helper tests are not component integration tests, and the coverage/filler helper functions are not wired into the actual completion UI. Distinguish implemented helpers from delivered user behavior.

Earlier declarations that packer replacement was closed were later overtaken by roads-first success. Retain negative experiments as evidence about their tested architecture, budgets, and instances; avoid treating them as permanent impossibility claims.

## Directions with existing negative evidence

| Direction | Existing lesson | Reopening condition |
|---|---|---|
| Short-side, sharing, rigid lanes, multi-trunk classical heuristics | Improved proxies but regressed complete-placement results | New mechanism plus paired complete-layout gate |
| City-scale joint placement/routing CP-SAT | Toy correctness did not scale in memory/time | Demonstrated bounded model on representative size |
| RL placement | Failed its own evaluation gate | New evidence and held-out end-to-end advantage |
| CNN feasibility scheduling | Good AUC did not improve final walk results | Budget-matched outcome improvement, not classifier score |
| Symmetry breaking / classical hints | Regressed measured search | Narrow justified regime with reproducible benefit |
| Solver parameter portfolios | Tested candidates yielded a null | New candidate with causal evidence |
| More worker threads | Oversubscription regressed results | Equal-resource measurements with headroom |
| Shorter default boxes | Repeated 30/45/60-second runs yielded 105/104/101 roads | Quality/time distribution across cities |
| Filler region partitioning | Current measured residual largely covered by exact repair | New near-zero-slack, large-footprint case |
| Skeleton surrogate as optimization gradient | Tested features lacked useful within-band signal | Held-out predictive feature and downstream gain |

The last result does not prove no useful predictor can ever exist. It says the measured feature family did not justify further complexity.

## Worthwhile future research

First complete application reliability and resource limits described in the main review. Then use a small explicit evaluation matrix to separate consumer count from road pressure: many consumers with low pressure, few with high pressure, and matched variants of footprint distribution and region shape. Current calibration on three cities confounds these factors. FR24's UNKNOWN results do not prove geometric impossibility.

Evaluate adaptive scheduling or bounded family portfolios against the current sliced scheduler. Preserve incumbents, reserve exploration, and distinguish unexplored regions from refuted sampled patterns. Any bidirectional strategy needs its own precommitted acceptance gate; it is not automatically justified by superseded cliff narratives.

Use the expert dense city as a documented hard regime, not the sole benchmark. A nearly perfect hand-packed city can hide useful gains on badly arranged cities with slack, while roomy examples can conceal catastrophic behavior near full occupancy.

## Evidence protocol

For each experiment retain input fingerprint, code revision, solver version, resolved options, random seed, hardware/thread allocation, machine contention, wall time, time to first feasible layout, coverage, statuses, final achieved roads, full validity outcome, and artifact hashes. Compare only complete legal layouts when making quality claims. Report failures alongside successful-run road counts to avoid survivor bias.

Use paired repeats and equal resource budgets. Separate interactive budgets from record campaigns. Do not claim a 94-road research record is the expected result of a short web run. Keep private city exports private; commit compact privacy-safe manifests because important overnight and allocation raw logs are currently gitignored.

No new experiments are recommended while this machine is saturated. The immediate low-compute work is reconciling documentation, preserving evidence, and planning focused correctness changes.

## Documentation structure to adopt

Maintain four distinct resources: a short current verified baseline, a current backlog with stable IDs, an experiment ledger with outcomes and reopening gates, and the historical lessons diary. Link superseded conclusions to replacements instead of deleting their history. Label production modules versus archived research explicitly, and retain useful reference oracles.

Historical passing-test counts should remain dated evidence. They do not establish that the current checkout passes, and this review makes no such claim.
