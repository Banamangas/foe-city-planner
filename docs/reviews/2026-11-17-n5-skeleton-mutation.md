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

TODO

## Step 3: results

TODO
