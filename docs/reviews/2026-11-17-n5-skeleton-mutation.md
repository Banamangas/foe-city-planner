# N5: directed search over concrete skeletons (2026-11-17)

Branch `feat/n5-skeleton-mutation` (from `feat/backlog-2026-11`). Code:
`foeopt/skeleton_mutation.py` (operators, pure), `scripts/exp_skeleton_mutation.py`
(experiment), `tests/roads_first/test_skeleton_mutation.py`. No production code changed.

## Hypothesis

Q3-gen: the rooted family can express the expert networks (best single-skeleton coverage
0.51-0.63), but random draws almost never land near one (mean coverage 0.04-0.09). If
sampling is the bottleneck, a directed search that starts from a good skeleton and mutates
it locally should find networks the random walk does not.

## Step 1: prior check

What was tested before, and how N5 differs:

| prior | what exactly was tested | judged by | N5 |
|---|---|---|---|
| perturb-25 / perturb-50 (2026-07-30, `exp_ood_skeletons.py --mode v1`, lessons "OOD check") | relocate 25 or 50 random LEAF cells of a working lane skeleton, same k | feasibility only, item model, no objective: **0 SAT / 64** | structural moves of one arm (1-12 cells), position model, objective on, judged by achieved roads |
| skeleton bandit / CEM / RL (2026-07-31, lessons "classifier, not a gradient") | a policy over the generator's PARAMETER vector (pitch, stubs, per-branch lengths) | no in-band feature predicts `achieved` (all \|rho\| < 0.22); amended 2026-11-11: that residual was a feasibility-only solver's spread | no parameter vector, no learned policy: hill climbing on concrete cell sets |
| rebased polish (T4, shipped) | re-solve on the incumbent's own roads | objective | = the `prune` move; reused as N5's final step |
| union polish (Q2, merged, off) | incumbent network (hard) + 23-67 new soft cells from other same-TH networks, exact flow closure | objective: FR17 103 and FR16 67 **proven optimal** for those unions; darkzig unsettled | covers "add cells" only for cells inside the union; shift / remove-and-add / new-TH-side spokes are outside it |
| T5 optional-road windows <= 20x20 | free road cells inside a window | objective: null | N5 moves are not windowed, and change the skeleton itself |

Verdict (5 lines):
1. Concrete-skeleton mutation is not the refuted bandit/CEM/RL: those searched generator
   parameters and were closed for lack of a gradient in feasibility-only data.
2. The closest prior is perturb-25/50 (0/64), but it moved 25-50 random leaf cells and
   asked only "is it still feasible at the same k" with the old item model and no objective.
3. N5 moves one arm at a time and asks "how many roads after the objective", which is the
   signal that made T4/T1/FR17-103; that question has never been asked of skeleton moves.
4. Adjacent nulls are a warning, not a refutation: union polish proves the incumbent optimal
   for supersets at FR17/FR16, so "add cells" moves there are expected to be null.
5. Reuse: `_run_probe` (evaluator), `incumbent_positions` (hints), `polish_rebased` (final),
   `bench.verify` (legality). Proceeded.

## Step 2: implementation

- **Operators** (`foeopt/skeleton_mutation.py`): extend, shorten, remove (one arm =
  leaf back to the first junction), shift (translate a straight arm 1-3 cells along its
  trunk), add (new straight arm off any road cell), spoke (new arm off a TH side no road
  touches), merge (two parallel arms on one trunk -> one in the middle), prune (keep the
  network the objective used). Pure functions; a non-None result always passes
  `_check_pattern`; growth never touches a road other than its source, so no loops or 2x2
  blocks. Buildings are never touched (no rotation possible). 19 tests, including 300
  random mutants of darkzig's real 88 network.
- **Search** (`scripts/exp_skeleton_mutation.py`): (1+lambda) hill climb, lambda = 6 per
  generation (1 move 70%, 2 moves 30%; plus the parent's pruned network), tabu on seen
  cell sets. Accept the best mutant (by achieved, then k) if achieved <= parent (ties
  accepted, so the climb drifts along plateaus). End: one rebased polish (60 s).
- **Evaluator, two halves, keep the better**:
  * cold = production `_run_probe` in a 6x2 pool (position-model probe 30 s, objective
    30 s, validate with the road witness);
  * warm = the same objective hinted from the PARENT's placement and the mutant's cells
    (`hint_roads`), i.e. a rebased-polish solve, run in the parent with 12 threads, 10 s.
- **Two evaluator defects found by the smoke runs** (fixed before the measured runs):
  1. Cold alone is ~4 roads weaker than the incumbent's own quality: record-network mutants
     scored 92-95 while rebased polish of the same layout gives 88. The search was
     judging noise. Fix: the warm half (in the measured runs warm beat cold in 184 of 240
     mutants where both were SAT, cold beat warm in 1).
  2. With 2 threads the hinted objective did not recover even a COMPLETE hint in 20 s
     (darkzig record network, UNKNOWN); with 12 threads it proved the optimum in 5 s.
     Fix: warm solves run sequentially with all threads.
- FR24 needs `--fillers-in-model`: the upload network fails filler repacking otherwise
  (start = SAT_FILLER_FAIL, every mutant too).
- Every new best passes bench.py `verify()` in-run; the two records were re-verified from
  their files with `scripts/verify_layout_file.py --reroute`.

## Step 3: results

All runs under `flock output/bench/.lock`, 6x2 workers, <= 33 min each. Data:
`output/n5/*.jsonl` (one row per evaluation, per generation, summary), logs `output/n5/*.log`.

| city | start | record before | start achieved | trajectory (s: best) | final (after rebase) | evals |
|---|---|---|---|---|---|---|
| darkzig s0 | record network (88) | 88 | 88 | 34: 88, **1009: 87** | **87** (verified) | 151 |
| darkzig s1 | record network (88) | 88 | 88 | 37: 88 (flat to 1841) | 88 | 151 |
| FR17 s0 | best of 24-skeleton walk at record TH, k=116 | 103 | 104 | 124: 104, 208: 103, **592: 102** | **102** (verified) | 270 |
| FR17 s1 | same, seed 1 | 103 | FR17S1START | FR17S1TRAJ | FR17S1FINAL | FR17S1EVALS |
| FR24 s0 | upload network (232), fillers in model | 220 | 230 (warm) | 51: 230 (flat to 1905) | 228 | 91 |

New legal records: **darkzig 87** (`docs/records/darkzig-87-roads-n5-mutation.json`) and
**FR17 102** (`docs/records/fr17-102-roads-n5-mutation.json`). Both files carry their
skeleton (`pattern_roads`), the first records that do. Both verify as valid, count matches,
and greedy and exact reroute equal the delivered count (exact proven optimal for the placement).

What moved:
- darkzig 87: 70 of 87 cells shared with the 88 record. The column at x=42 (y 13-27) is
  gone; arms at x=38 (y 13-17) and x=46 (y 19-30) replace it, and the x=54 stub is gone.
  The climb accepted 12 tie moves (8 with `shift`, 2 extend, 2 prune) on the 88 plateau before a `shorten`
  went to 87. No single move from the record does it: the drift along ties was needed.
- FR17 102: 65 of 102 cells shared with the 103 record, at the same TH. A walk skeleton
  (104) went to 103 by a `spoke` (k 116 -> 112), was pruned to k=103, and a `shorten` gave
  102 at 592 s. The final rebased polish proves 102 optimal on that network in 0.3 s.
- Acceptance rates: darkzig 20 and 22 accepted moves in 25 generations; FR17 31 in 41. The
  objective landscape is a wide plateau with many ties, not "sharp": most one-arm
  mutants are within 0-2 roads of the parent.
- FR24: inconclusive, evaluator-limited. 88 of 91 mutants were UNKNOWN or UNSAT (cold
  probe never SAT on a 230-cell network in 30 s; warm 20 s rarely recovers the hint). The
  start itself scored 230 (warm) and 228 after a 57 s rebase, against the 220 that the
  production rebased polish reaches from the same upload with more time. Nothing about
  the mechanism can be read from this run.

## Verdict

- **Mechanism: PASS on darkzig and FR17** (one new record each, from a single 25-30 min
  run each), **null on darkzig's repeat**, **untestable on FR24** at these solve limits.
  The Q3-gen diagnosis holds: the grammar was not the bottleneck; a directed search from
  a good skeleton finds better networks that random draws do not.
- The old "neighbourhood of a good skeleton is sharp (0/64)" closure does not transfer:
  it was measured on feasibility with 25-50 random cell moves. Judged by the objective,
  one-arm moves form a plateau the climb can walk.
- The search is cheap to productionise as a polish phase: it needs one incumbent (layout +
  network) and the existing objective/rebase code. It is NOT yet shown to beat the
  production pipeline at equal wall time: the gains came at 592-1009 s of mutation search
  on top of an existing record (darkzig) or a 2-min walk (FR17).

Next (not done here):
1. Paired A/B as a polish phase: preset 600 s vs preset 600 s + 600 s mutation polish
   from the incumbent, 2+ reps, darkzig/FR16/FR17 (FR16 was not run).
2. FR24: warm solves need 60 s+ with fillers in the model; or start from the 220 record.
3. Restarts from the new records (87 / 102) to see whether the climb continues.
