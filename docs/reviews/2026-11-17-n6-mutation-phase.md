# N6: skeleton mutation as an end-of-run phase (2026-11-17)

Branch `feat/n6-mutation-phase` (from `feat/backlog-2026-11`, N5 merged in). Code:
`foeopt/mutation_polish.py`, wiring in `RoadsFirstSearch.run` (`foeopt/roads_first.py`),
webapp options (`webapp/params.py`, `webapp/runner.py`), tests
`tests/roads_first/test_mutation_polish.py`. Bench pinned at `2efc22a`
(`/home/born/Github/foe-bench-n6`).

## Design

- Options, all off by default: `mutation_polish` (bool), `mutation_reserve` (s, only with
  the switch, capped at half the box), `mutation_starts` (1 = incumbent only).
- Phase order: walk | objective polish | union | rebase | **mutation** | seed polish |
  exact finish. The climb runs until `deadline - seed_polish_reserve`.
- Leftover mode (`reserve = 0`): no deadline changes. The climb only uses time the run
  would have left unused. The polish window is never borrowed.
- Reserve mode: `walk_deadline` and `polish_deadline` both move earlier by R seconds. The
  objective-polish window keeps its length (`time_box * objective_polish`); only the
  walk gets shorter.
- Climb: N5's (1+lambda) hill climb, lambda = workers (6). Each mutant gets 1 move (70%)
  or 2 moves (30%), plus the parent's pruned network, with tabu on seen cell sets. The
  best SAT mutant replaces the parent if it is no worse (ties accepted).
- Start: the incumbent's own road network, hinted with `incumbent_positions`.
  `mutation_starts > 1` adds the original skeletons of the next-best layouts that
  objective polish validated (`solved_networks`); the time is split evenly across starts.
- Evaluator: N5's two halves, unchanged.
  * Cold: `_run_probe` in a fresh worker pool. It runs only when a whole probe plus repair
    fits before the end, because the batch pool does not clamp the probe.
  * Warm: `minimize_needed` hinted from the parent placement and the mutant's cells,
    10 s, all threads, sequential. It now lives in `mutation_polish.warm_solve`, and the
    N5 script imports it from there.
- Safety: every result goes through `validate`. A mutant that would be accepted must also
  pass `legality.check` (military policy, chains, inventory). Only strict improvements
  reach `on_improvement`. The operators touch road cells only, so buildings never rotate.

## Tests

- 10 new tests:
  * the climb improves a 4-road incumbent, and every published layout is legal, strictly
    decreasing, and unrotated;
  * no publish when the incumbent is optimal;
  * no time means no generation;
  * the stop flag ends the phase;
  * the cold half runs the production `_run_probe` through an in-process pool;
  * `plan_starts` orders and dedupes the starts;
  * wiring: mutation runs last and ends at the box;
  * the reserve moves the polish window 20 s earlier without shrinking it;
  * the option is off by default, and the reserve does nothing without the switch.
- Full suite: 712 passed, 38 skipped (`tests/test_api.py::test_old_routes_still_served`
  deselected, because webapp/dist is missing in worktrees).

## A/B (600 s, 2 reps, `output/bench/n6-mut.jsonl` in the pinned worktree)

| city | rep | preset | mut (leftover) | mutr (+120 s reserve) |
|---|---|---|---|---|
| FR16 | 0 | 67 | 67 | 67 |
| FR16 | 1 | 67 | 67 | **66** |
| FR17 | 0 | 103 | **102** | **102** |
| FR17 | 1 | 103 | 103 | 103 |
| darkzig | 0 | 90 | 90 | **88** |
| darkzig | 1 | 90 | **89** | **88** |

`bench.py report --base preset`:
- mut: better 2, worse 0, tie 4 -> ADOPT.
- mutr: better 4, worse 0, tie 2 -> ADOPT.

All 18 layouts verified (`accepted: true`).

Where each gain came from (time of the last improvement against the phase boundaries):
- The mutation phase itself made 4 gains: FR17 mut r0 (103 -> 102 at 526 s), FR17 mutr r0
  (103 -> 102 at 432 s), FR16 mutr r1 (67 -> 66 at 495 s), and darkzig mutr r1
  (89 -> 88 at 534 s).
- darkzig mut r1 89 and darkzig mutr r0 88 came from rebased polish before the climb
  started. That is walk/polish variance (darkzig is +-2 at 600 s), not the phase.
- Wall time: preset 339-438 s (0.57-0.73x of the box), mut/mutr 580-583 s (0.97x). The
  climb took 146-243 s in mut and 237-365 s in mutr.
- Correction to the brief: darkzig did NOT use its whole box in this preset either
  (438 / 420 s). Its leftover is smaller (about 150 s), so the leftover-only arm
  gets about 1-2 generations there.
- The reserve shortens the walk (walk end 337 -> 212 s on FR16/FR17, 369 -> 274 s on
  darkzig) and lost nothing in these 6 pairs. On FR16/FR17 the walk's best layout before
  polish was the same (103 / 67-68 after rebase in every arm).

## Records

- **FR16 66 (was 67), new legal record**: `docs/records/fr16-66-roads-n6-mutation.json`.
  `verify_layout_file.py --military connect --reroute` passed on the saved file: valid,
  count matches, greedy and exact reroute both 66, exact proven optimal. 0 rotated,
  inventory ok, 0 overlap (bench verify).
- FR17 102 equals the N5 record, now reached by the production pipeline in 600 s (in 2 of
  4 mutation runs). darkzig 88 is short of the 87 record.

## Verdict

- Both arms pass the paired never-worse rule. `mutr` (reserve 120 s) is the stronger one:
  better in 4 of 6 pairs.
- This is n=2 per city, and darkzig noise is +-2. The FR17 and FR16 gains are clean
  attributions: they came inside the phase, from incumbents the other arms also reached.
- Not adopted into BEST_PRESET here, per the brief (no merge). Recommendation: adopt
  `mutation_polish=true, mutation_reserve=120` on the integration branch after a repeat
  at 120 s boxes, since the reserve caps at half the box and a 120 s box would lose 60 s
  of walk. Also consider recording the phase report in bench rows (bench.py does not save
  `mutation_polish` yet; the attribution above comes from improvement timestamps and the
  profile).
