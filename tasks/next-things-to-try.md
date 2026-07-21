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

**Update 2026-07-17 (final):** #10 stub priority closed mixed (hurts comb, helps lane). #11
hybrid comb/lane (bounded lane length) closed **positive** — bracketed a genuine, reproduced,
isolated-optimum sweet spot at cap=24 (106 roads, closest yet to comb's 102); layering
`stub_priority` on top of it doesn't stack (makes it worse). This is the first lever in the whole
next-things-to-try line to reproducibly beat its own family's prior best rather than just fail
differently, though it still doesn't dislodge plain comb (102) as the project's best result. Next
open threads: #4 (UNSAT prefilter, still untested), #6 (minimize-roads CP-SAT), or understanding
*why* cap=24 specifically works if this thread gets picked up again.

**Update 2026-07-17 (later):** #4 and #6 both closed. #4 (tightened UNSAT prefilter) is a real,
sound, permanent improvement to `prefilter()` but null for the k-walk's actual operating range —
it rejects nothing extra at k~93-123 (where every real run probes), only at k far below where the
walk never goes. Kept unconditionally (strictly more correct, no downside). #6 (minimize-roads
CP-SAT) is a decisive kill — see item 6 below and `tasks/lessons.md` 2026-07-17. **No open
cheap/medium-tier ideas remain untested**; every idea in this document has now been tried and
closed (positive: #5's cap=24 hybrid follow-up; mixed: #10 stub priority; negative/null: #1, #2,
#3, #4, #5 as originally proposed, #6). Remaining unexplored items are the Speed-tier ones (#7-9,
infra/tuning rather than new levers) — the project's best validated result stays **102 roads**
(plain comb family, no levers), with the hybrid cap=24 family as the closest reproducible
runner-up at 106.

**Update 2026-07-20:** #7 (concurrent k-levels) closed — small reproducible speed win, see item 7
below and `tasks/lessons.md` 2026-07-19/20. First lever whose point was "same result, faster"
rather than a different search outcome; a naive `--workers` bump was tested first and found to
reproducibly *backfire* (CP-SAT thread contention), so the win came specifically from removing
the per-level dispatch barrier (`concurrent_levels=N`), not from raw core count. #8 and #9 (CP-SAT
parameter portfolio, assumption-based incremental solving) remain the only untested items.

**Update 2026-07-21:** #8 (CP-SAT parameter portfolio) closed — clean null across every candidate,
see item 8 below and `tasks/lessons.md` 2026-07-20/21. Useful side-finding: CP-SAT's parallel
portfolio isn't perfectly reproducible run-to-run even with a fixed seed (a no-override control
arm itself flipped 1/20 samples), which sets a real noise floor — none of the 5 candidate
strategies cleared it. **Every item in this document is now closed except #9** (assumption-based
incremental solving across a level), the last unexplored idea.

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

4. ~~**Stronger UNSAT prefilter.**~~ **TESTED 2026-07-17 — sound tightening, null at the
   k-walk's real range, closed.** Tightened `prefilter()`'s adjacency-capacity check from a
   flat 3-per-cell to `min(3, actual free orthogonal neighbor count)` — strictly tighter,
   still 100% sound, no `reach.py`-style false-reject risk (deliberately skipped the backlog's
   heuristic-greedy-first-fit alternative, since a hard reject on greedy failure isn't a
   certificate and reordering-only would just be idea #1 again, already null). Diagnostic
   before any A/B: zero additional patterns rejected at the k-walk's actual operating range
   (k~93-123, comb or lane) — the tightened bound only bites at k far below where the walk
   ever probes (k=25: 200/200 newly caught; by k=40 already down to ~1-4/200). Kept as a
   permanent, always-on correctness improvement (not opt-in — strictly better with no
   downside), but a null result for real search performance; no 30min A/B was warranted or
   run. Full numbers: `tasks/lessons.md` 2026-07-17 entry.

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

6. ~~**Minimize-roads CP-SAT (not fixed-k).**~~ **TESTED 2026-07-17 — decisive kill, closed.**
   Built `foeopt/minroads.py`: road-cell selection as a CP-SAT decision variable (BFS-tree
   connectivity via reified distance-labeling) jointly `Minimize()`d with one-hot placement
   variables, replacing the fixed-skeleton-then-place two-stage split entirely. Toy-scale gate
   (`tests/test_minroads.py`) matches `rl.oracle.optimal_roads` exactly on 2/3/4-building cases
   — model is correct. Real-scale gate on darkzig (2720 region cells, 63 consumers): 60s budget
   returned `UNKNOWN` (no feasible solution found at all); 300s budget went further than the
   plan anticipated — RSS climbed to ~3.9GB within 17 CPU-seconds and kept growing, exhausting
   the machine's RAM+swap and **crashing the user's terminal**, force-killed via `pkill -9`. Not
   just slow — memory-catastrophic before completing a first search pass. Confirms the two-stage
   architecture's fixed, pre-verified-connected skeleton (`O(buildings)` placement variables)
   isn't an implementation shortcut, it's load-bearing for tractability at this problem size.
   Full details: `tasks/lessons.md` 2026-07-17 entry. Kept as a documented throwaway, not
   productionized, not imported by any production path. **Do not re-attempt without a hard
   memory ulimit and much smaller regions first**, if ever revisited.

## Speed — same result, less compute

7. ~~**Concurrent k-levels.**~~ **TESTED 2026-07-19/20 — small reproducible win, closed.**
   Phase 0 diagnostic (no code): naively bumping `--workers 8` (16 of 16 cores) reproducibly made
   the walk **worse** (k=113/105 vs baseline k=111/102) — CP-SAT thread contention with zero core
   headroom, not the fix the "idle cores" framing suggested. Phase 1: added
   `_probe_levels_batch()` + opt-in `RoadsFirstSearch(concurrent_levels=N)` (default 1 = today's
   exact behavior) — merges several k-levels' patterns into one shared `pool.imap_unordered` call
   instead of draining one level before generating the next, removing the per-level barrier
   without changing worker count (so it doesn't reintroduce Phase 0's contention). A/B (equal
   1800s wall-clock x2, reproduced): `concurrent_levels=4` matched baseline's `best_achieved=102`
   exactly both times, but reproducibly resolved one level further (`k=107: INFEASIBLE`) than
   sequential baseline reached in the same budget. Real, if modest, "same result, faster" win —
   the first lever in the whole next-things-to-try line whose entire point was speed rather than a
   different search outcome. Full details: `tasks/lessons.md` 2026-07-19/20 entry.

8. ~~**CP-SAT parameter portfolio for the hard frontier.**~~ **TESTED 2026-07-20/21 — clean null,
   closed.** Added an opt-in `probe(..., solver_overrides={...})` hook and re-solved 20 sampled
   frontier UNKNOWN patterns (reused from the existing darkzig corpus, k=107–123) under 5
   candidates (`portfolio_search`, `lp_search`, `linearization_max`, `more_probe_workers_4` — the
   literal "longer-but-fewer" lever — and `use_lns_only`) at the walk's real 30s/probe_workers=2
   budget. A `default_reconfirm` control (no override, re-solved fresh) itself flipped 1/20 (5%)
   to decided — CP-SAT's parallel portfolio isn't perfectly reproducible run-to-run even with a
   fixed seed, setting a real noise floor. No candidate cleared it: 4 of 5 landed at or below the
   control's 5%. Consistent with, and reinforcing, the Stage 1.5 autopsy's reading that this
   frontier is genuinely hard for CP-SAT at this problem size, not a strategy artifact. Full
   details: `tasks/lessons.md` 2026-07-20/21 entry.

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

11. ~~**Hybrid comb/lane (bounded lane length).**~~ **TESTED 2026-07-17 — cap=24 is a real,
    bracketed, isolated-optimum win, but doesn't stack with stub_priority; closed.** Idea #5's
    flagged follow-up: cap lane length as a cheap proxy for a spatial comb/lane hybrid.
    Implemented `max_lane_len=`/`--lane-cap` on `generate_lane_patterns()`. **Not monotonic —
    bracketed a narrow, isolated dip centered exactly at cap=24**: 16→111, 20→110, **24→106/106
    (reproduced)**, 28→111, uncapped→109/112, 8→119, 4→FAMILY_TOO_WEAK. 106 is the best
    lane-family result found and the closest anything but plain comb has come to comb's 102.
    Best-guess mechanism (unconfirmed): a cap above the *typical* productive lane length but
    below the *outlier* long-lane tail may selectively filter only the rare hardest-to-decide
    patterns rather than uniformly restricting everything. **Layering `stub_priority` on top of
    cap=24 does not stack — makes it worse** (110/110, reproduced, back to the cap=20/uncapped
    range): whatever makes cap=24 work well alone is disturbed by also biasing toward
    big-buildings-at-stubs, matching this session's "helps a struggling search, hurts an
    already-tuned one" pattern showing up *within* the lane family this time. While
    sanity-checking this, found and fixed a real pre-existing bug in `scripts/exp_roads_first.py`'s
    `--dump-patterns` path (never threaded `th_mode` through — silently used `coarse` regardless
    of `--th-anchors`; the real A/B runs via `kwalk_gate.py` were unaffected, only informal
    diagnostics were). **Verdict: cap=24 alone is the winning configuration; closed with a real,
    positive, bracketed result** — first lever in the whole next-things-to-try line to
    reproducibly beat its own family's prior best rather than just fail differently. Still short
    of dislodging comb (102). Natural next step if revisited: understand *why* cap=24 works (a
    per-pattern lane-length histogram vs uncapped) rather than more parameter search. Full
    numbers: `tasks/lessons.md` 2026-07-17 entry (revised).

## Kept assets that these can reuse
- Stage-0 corpus engine (`foeopt/corpus.py`, opt-in `--corpus`) — labeled instances for eval.
- Feasibility CNN (`rl/kwalk_*`, AUC 0.999) + opt-in scorer hook — for idea #1 (pruning).
- `scripts/kwalk_gate.py` (walk driver) and `scripts/kwalk_autopsy.py` (frontier probing).
