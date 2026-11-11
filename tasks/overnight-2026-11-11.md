# Overnight 2026-11-11: what changed, what was measured

Branch `feat/placement-objective` (not merged, not pushed). Start with
`tasks/analysis-2026-11-11.md` (the review) and the lessons entry
"CORRECTION: the placement objective..." at the end of `tasks/lessons.md`.

## Headline

Two formulation changes to the CP-SAT inner problem, both found by the review and both
measured end to end at a **600 s box** (strictly sequential, paired repeats, every best
layout independently verified):

1. **Placement objective** (`minimize_needed`, `objective_limit`, `objective_polish`):
   minimise the skeleton cells the placement actually needs, hinted from the feasible
   placement. The July study that closed this lever used a proxy that always equalled k.
2. **Position-indexed model** (`probe_model="position"`): one boolean per (size, spot)
   instead of one item per building, which removes the identical-building symmetry. On FR17
   it decides skeletons in 0.1–0.3 s that the old model left UNKNOWN after 30 s × 12 threads.

| city | before tonight (600 s, preset) | + objective (item model) | + position model | best known before |
|---|---|---|---|---|
| darkzig | 99 | 90–91 | **88** | 94 |
| FR16 | 77 | 73–74 | **68** | 76 |
| FR17 | 115 | 106–108 | **105** | 115 |

(Final numbers for repeat 1 + FR24 / your city: see "Results" below.)

## Commits (in order)

- docs: the analysis + Codex reviews
- feat: `objective_limit` (in-walk objective) + **bug fix: production never passed
  `fillers` to `prefilter`** (the check documented as shipped on 2026-07-31 was dead)
- fix: objective respects the level-slice deadline (without it, 60 s runs found NOTHING)
- fix(api): reject NaN/inf, booleans and fractional ints in numeric options (Codex P1);
  stale seed-polish texts corrected
- records: darkzig 90/91, FR16 71, FR17 108 (all re-verified by
  `scripts/verify_layout_file.py`)
- feat: `objective_polish` (end of run, all threads), `exact_finish` (exact router on
  the final layout, keep only if smaller)
- feat: BEST_PRESET adopts `objective_limit=30`, then `objective_polish=0.3` +
  `exact_finish` (two A/B rounds, never worse)
- feat: `probe_model="position"` (opt-in, agreement-tested against the item model)

## Results

See `output/objective-ab*.log` (gitignored) and `scripts/_objective_ab*.jsonl`.

## Not done / for you to decide

- **Merge.** Branch only; 592 Python + 41 frontend tests pass.
- **Two-lane roads.** In the game they are 2×2 tiles; the router writes a 1×1 "level-2"
  cell. That affects darkzig's one military building and every darkzig record, old and
  new. I need the rule: must the whole path to the TH be two-lane?
- **Chain buildings** (darkzig's 7 Road-to-Victory pieces) are moved freely. Should
  adjacency be preserved?
- Codex P1 items I did not touch: `onDone` payload dropped by the UI, job admission
  control, split-file `/api/load/raw` dropping `helper_data`.
