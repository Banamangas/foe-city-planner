# Roads optimizer — next things to try

_Started 2026-07-15, after Track C-bis (ML acceleration) was archived._

**Where we are:** the roads-first CP-SAT k-walk cuts darkzig to ~102–106 validated roads
(k≈110). Track C-bis showed the frontier is a **pattern-family limit**, not a scheduling
limit (Stage 1 ranking gave 0 benefit) nor a SAT-proving-speed limit that ML could fix
(Stage 1.5 autopsy: 0 SAT / 4 UNSAT / 4 UNKNOWN — no feasible-but-hard SAT to warm-start).
See `tasks/lessons.md` (2026-07-15). Ideas below, **cheapest first**. Discipline: A/B any
change vs baseline at **equal wall-clock, 0-unplaced, ≥ a few seeds** (the pool is
non-deterministic), and validate the *bottleneck* before building.

**Update 2026-07-16:** four ideas tested and closed, all negative — #1 pruning, #2 warm-start,
#3 symmetry breaking (none moved the CP-SAT proving-time bottleneck), and #5 lane/stub topology
(structurally closer to the expert city, but its geometry is *harder* for CP-SAT to decide,
netting worse results despite the better topology). #4 (UNSAT prefilter) is the only untested
cheap-tier idea left; #6 (minimize-roads CP-SAT) and the unmeasured hybrid-family follow-up
noted under #5 are the least-explored remaining directions.

**Update 2026-07-17 (revised):** #10 stub priority closed mixed (hurts comb, helps lane). #11
hybrid comb/lane (bounded lane length) is **open, not closed** — cap=24 reproducibly beats every
other lane-family result (106 roads, closest yet to comb's 102); see #11 below for the corrected
account (an earlier version of this entry, based on only caps 4/8, wrongly concluded the idea was
falsified). Next open threads: bracket the cap=24 sweet spot, #4 (UNSAT prefilter, still
untested), #6 (minimize-roads CP-SAT).

## Cheapest — reuse existing infra (hours)

1. ~~**Prune-mode guided walk.**~~ **TESTED 2026-07-16 — no gain, closed.** Swept
   `--score-threshold` 0.1/0.2/0.3/0.4 vs baseline, 30min/arm, equal wall-clock. Mechanism is
   safe (no false-negative INFEASIBLE at any threshold) and does free budget — pruned arms
   reached k=109/110 vs baseline's k=111 within the same 30min — but `best_achieved` stayed
   pinned at 102 roads in every arm, baseline included. Same root cause as the Stage 1 G1 null
   result: the k-walk frontier is decision-limited (per-probe SAT-proving time), not
   ordering/volume-limited, so visiting more k-levels faster doesn't help if the deeper levels
   are still undecidable within the probe-limit. Full numbers: `tasks/lessons.md` 2026-07-16
   entry. Sharpens priority toward #3 (symmetry breaking — attacks proving time directly) and
   #2 (warm-start).

2. ~~**Non-ML CP-SAT warm-start from the classical packer.**~~ **TESTED 2026-07-16 —
   reproducibly WORSE, closed.** Implemented `hints=`/`--warm-start` (`AddHint` snapped to the
   nearest valid anchor per building, via `foeopt.packer.repack()`'s output layout). A/B'd at
   equal *total* wall-clock (30s repack + 1770s walk = 1800s) x2 (reproduced exactly both
   times): baseline k=111/102 roads vs warm-start k=117/109 roads — two k-levels and 7 roads
   worse, the largest regression of the three cheap-tier ideas. Likely cause: `repack()` alone
   (no anneal polish) landed 199 roads in a diagnostic run — the hint source is a much looser,
   differently-structured layout than the ~102-118-road skeletons the k-walk actually probes,
   so the hint misdirects rather than helps. Not retested with a polished (~158-road) hint
   source — unmeasured follow-up, out of scope for this A/B. Full numbers: `tasks/lessons.md`
   2026-07-16 entry.

3. ~~**Symmetry breaking in the CP-SAT probe.**~~ **TESTED 2026-07-16 — reproducibly WORSE,
   closed.** Implemented lexicographic (x,y) ordering across same-footprint-size building
   groups (`--symmetry-breaking`, opt-in, off by default). A/B'd 30min/arm x2 (reproduced
   exactly both times): baseline k=111/102 roads vs symmetry-breaking k=115/105 roads — a full
   k-level and 3 roads worse. Per-probe timing on a small sample showed no obvious slowdown, so
   likely cumulative model-construction overhead across thousands of probes and/or interference
   with CP-SAT's own automatic presolve symmetry detection, not a fundamentally bad idea badly
   executed. Full numbers: `tasks/lessons.md` 2026-07-16 entry. Kept as tested, correct,
   zero-cost-when-off infrastructure; not a win.

4. **Stronger UNSAT prefilter.** Most probes are UNSAT and cost real solve time. Add a cheap
   pre-check that proves infeasibility without CP-SAT — e.g. road-adjacency capacity (each
   road cell serves ≤3 consumers; if Σ demand > available adjacency capacity → UNSAT), or a
   fast greedy first-fit whose hard failure flags likely-UNSAT. Skips expensive probes,
   buying more budget for the decidable ones. (`foeopt/bounds.py::bound_adjacency` is a start.)

## Medium — a focused build

5. ~~**Lane/stub topology generator.**~~ **TESTED 2026-07-16 — reproducibly WORSE, closed.**
   Implemented `generate_lane_patterns()`/`--pattern-family {comb,lane}` — parallel double-
   loaded lanes off a *minimal* trunk (spans only to the furthest lane seed, not
   `budget//2` like the comb family) + TH stubs, structurally closer to the expert city's real
   topology. Found and fixed a real connectivity bug pre-flight (`_trunk()`'s TH-adjacent
   anchor cell sits mid-list, not at index 0, for non-corner TH placements — a naive
   `trunk[:n]` prefix would silently disconnect the pattern). A/B'd 30min/arm x2: baseline
   k=111/102 roads vs lane-family k=115/109 and k=115/112 — a full k-level worse both times
   (not bit-identical like ideas #1-3, but consistently worse). **Mechanism, this time with a
   clear signal:** at k=115, comb probes are 4/6 fast UNSAT + 2/6 UNKNOWN, but lane probes are
   6/6 UNKNOWN — the lane geometry's long straight corridors are structurally *harder for
   CP-SAT to decide* than the comb's shorter teeth, even though they resemble the real city's
   topology more closely. Structural resemblance to the expert city and solver-decidability
   pull in opposite directions here. Full numbers: `tasks/lessons.md` 2026-07-16 entry. A
   possible follow-up (unmeasured): a *hybrid* family (comb near the frontier, lanes only
   where there's slack) might recover the structural win without the decidability cost.

6. **Minimize-roads CP-SAT (not fixed-k).** Replace the fix-k / bisect walk with a model that
   directly **minimizes road cells** subject to placement + TH-connectivity over a fixed
   decomposition/region. Harder model, but searches the road count directly and may beat what
   the bisection reaches in a budget.

## Speed — same result, less compute

7. **Concurrent k-levels.** The bisection is sequential; probe several k-levels in parallel
   (16 cores available; runs use ~12). Fills idle cores during the easy upper levels.

8. **CP-SAT parameter portfolio for the hard frontier.** The autopsy's 4/8 UNKNOWNs stayed
   undecided at 15 min. Try alternate CP-SAT strategies specifically on frontier probes (more
   LNS workers, different branching, `use_lns_only`, longer-but-fewer). Small tuning study.

9. **Assumption-based incremental solving across a level.** Patterns at one k share region +
   building set; only the road skeleton differs. Explore CP-SAT assumptions / clause reuse to
   amortize solving across a level's patterns.

## Follow-ups raised during the work above

10. ~~**Stub priority hint (biggest buildings next to TH stubs).**~~ **TESTED 2026-07-17 —
    mixed, family-dependent, closed.** User question after #5: does the model require the
    *biggest* buildings next to TH stubs, matching the expert-city heuristic? No — `probe()`
    has no objective, so CP-SAT seats whatever fits first regardless of size. Diagnostic found
    real headroom (existing solved layouts sometimes seat area-1/area-4 buildings on precious
    load-3 stub cells). Implemented `stub_priority=`/`--stub-priority` — `AddHint`s the largest
    buildings (top-3 per TH-flank stub cell present in the pattern, family-agnostic) toward
    their own valid stub-adjacent anchor options. A/B'd both families (30min/arm x2 each):
    **hurts comb** (production default) by 3 roads, reproducibly (102→105 both runs) — do not
    flip default there. **Helps and stabilizes lane** — 108/108 (reproduced exactly) vs the
    lane baseline's own variable 109/112 — though lane+stub_priority (108) still trails plain
    comb (102) outright. Per-probe SAT/UNSAT/UNKNOWN status was unchanged in a mechanism check
    (consistent with the correctness tests) — the shift in `best_achieved` likely comes from
    the hint changing *which* feasible placement CP-SAT finds (and thus what `route()` computes
    from it), not from changing decidability. Standing pattern across this session's levers:
    added hints/constraints help only when the underlying search is already struggling (lane,
    6/6 UNKNOWN per idea #5's mechanism check) and hurt when it's already efficient (comb,
    mostly fast UNSAT). Full numbers: `tasks/lessons.md` 2026-07-17 entry. Kept opt-in/off
    everywhere; revisit only if the lane family itself is picked back up.

11. **Hybrid comb/lane (bounded lane length) — cap=24 is a real, reproduced win, OPEN not
    closed.** Idea #5's flagged follow-up: cap lane length as a cheap proxy for a spatial
    comb/lane hybrid. Implemented `max_lane_len=`/`--lane-cap` on `generate_lane_patterns()`.
    **Not monotonic** — uncapped lane 109/112 → cap=16 111/111 (≈ uncapped) → **cap=24 106/106
    (reproduced — best lane-family result yet, closest to comb's 102)** → cap=8 119/119 (worse)
    → cap=4 FAMILY_TOO_WEAK (climbed to k=283, never found one SAT). The first two caps tried
    (4, 8) looked like a clean "smaller cap = worse" trend and the entry originally closed as
    falsified; testing 16 then 24 (user follow-ups) overturned that — there's a real optimum
    near cap=24, not a monotonic gradient. Best-guess mechanism (unconfirmed): a cap set above
    the *typical* productive lane length but below the *outlier* long-lane tail may selectively
    filter only the rare hardest-to-decide patterns rather than uniformly restricting everything.
    While sanity-checking this, found and fixed a real pre-existing bug in
    `scripts/exp_roads_first.py`'s `--dump-patterns` path (never threaded `th_mode` through —
    silently used `coarse` regardless of `--th-anchors`; the real A/B runs via `kwalk_gate.py`
    were unaffected, only informal diagnostics were). **Next step (not yet done): bracket the
    sweet spot (e.g. 20, 28, 32) and consider layering `stub_priority` on top of the winning
    cap** (stub priority independently helped the lane family in the earlier entry). Full
    numbers: `tasks/lessons.md` 2026-07-17 entry (revised).

## Kept assets that these can reuse
- Stage-0 corpus engine (`foeopt/corpus.py`, opt-in `--corpus`) — labeled instances for eval.
- Feasibility CNN (`rl/kwalk_*`, AUC 0.999) + opt-in scorer hook — for idea #1 (pruning).
- `scripts/kwalk_gate.py` (walk driver) and `scripts/kwalk_autopsy.py` (frontier probing).
