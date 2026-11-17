# Q4: rebased polish iterated to a fixed point (2026-11-17)

Branch `feat/q4-iterated-rebase` (from `feat/backlog-2026-11`). Option `rebase_iterate`
(bool, off by default). Code: `foeopt/incumbent_polish.py`, plus a solution-trail hook
in `_minimize_needed_position` (`foeopt/roads_first.py`, 14 lines). Tests:
`tests/roads_first/test_rebase_iterate.py` (8).

## 1. Measurement: what the polish actually did on FR24

FR24 never gets a skeleton (FAMILY_TOO_WEAK). The walk runs to about 350-410 s and finds
nothing, so the seed (232) gets rebased polish with whatever is left (about 180-240 s).
Old bench rows plus an instrumented direct run (`polish_rebased` on the seed, 200 s
window, per-solve telemetry now in the report):

| run | solves | what happened | result |
|---|---|---|---|
| q3 qe / qeroot | 1 | fast (consumer-only) solve -> SAT_FILLER_FAIL, model-filler retry ate the rest | 229 |
| q3 qemix | 2 | fast 82 s -> 220 OK; 2nd fast 10 s -> 219; **stopped by MAX_SOLVES=2 with 86 s unused** | 219 |
| instr. A | 1 | fast 62 s OPTIMAL 220, fillers fail; model-filler 134 s FEASIBLE 230 (bound 57) | 230 |
| instr. B | 1 | fast solve **used the whole 197 s** (FEASIBLE 221), fillers fail, no time to retry | 232 |
| instr. C (3 seeds) | 4 | 3 fast solves with new seeds all reach the 220 optimum, all fail fillers; model-filler 57 s | 229 |

Findings:
- The consumer-only optimum is about 220 every time. Whether the fillers then fit is luck,
  and so is the 219-229 spread. A new seed lands on the same tight optimum (0/3).
- The model-filler solve is slow and weak (232 -> 229/230, bound about 50).
- Two structural stops: MAX_SOLVES=2 cuts a chain that is still improving, and an
  unbounded fast solve can eat the whole window.
- User city: fast solve 140, fillers fail; model-filler gives 142 (= input).

## 2. Design (`rebase_iterate=True`)

- Loop until a solve gains nothing, the network repeats, or the deadline (no MAX_SOLVES cap).
- Cap each consumer-only solve at `ITER_SLICE_S` = 60 s.
- On SAT_FILLER_FAIL, validate the solve's **trail** first: the earlier improving solutions
  CP-SAT found on its way down, one per objective value, best first. Earlier solutions
  are closer to the incumbent, so the fillers fit more often. If none fits, run the
  model-filler retry with the rest of the window, as before.
- Report: per-solve rows (status, objective, bound, time), `stop` reason, `unused_s`.
- Off: behaviour unchanged (one unbounded fast solve, model-filler retry, MAX_SOLVES).
- Q2 union alternation was not added. Union members come from objective polish, and FR24
  and the user city have none (no skeleton SAT), so a union could not run where Q4 matters.
  N1 also found qeu identical to qe.

## 3. A/B (pinned worktree `/home/born/Github/foe-bench-q4` @ 729c391, 600 s)

`output/bench/q4-iter.jsonl` (in the pinned worktree), all layouts verified legal:

| city | rep | preset | iter |
|---|---|---|---|
| FR24 | 0 | 229 | **219** |
| FR24 | 1 | 229 | **219** |
| user | 0 | 142 | 142 |
| user | 1 | 142 | 142 |

`bench.py report --base preset`: iter better 2, worse 0, tie 2 -> ADOPT.

Iterate-arm FR24 chains: rep0 232 -> 224 (trail, 4th solution tried) -> 220 -> 219, then a
filler failure with an empty trail; rep1 232 -> 222 (trail, 1st tried) -> 219. Preset:
fast solve failed fillers, model-filler retry -> 229 both reps.

Never-worse check, darkzig/FR16/FR17, 1 rep (`output/bench/q4-iter-check.jsonl`):

| city | preset | iter |
|---|---|---|
| darkzig | 90 | 89 |
| FR16 | 67 | 67 |
| FR17 | 103 | 103 |

better 1, worse 0, tie 2. The darkzig road is noise, not the iteration. Both arms rebased
once from 90 (preset: no gain; iter: 89, then a proven no-gain solve), so MAX_SOLVES did
not bind. darkzig varies by +-2 at 600 s (N2). On these cities the polish ends after
0.2-5 s solves; the 60 s slice and the trail never come into play.

## Verdict

**Never worse in 7 pairs, better in 3. FR24 229 -> 219 in both reps** (preset hit the
filler-failure path both times, as in the q3 runs; iter rescued the first step from
the trail both times). The user city is unchanged at 142: the trail held only the input
value, and the model-filler solve proves nothing better in 250 s. Recommend adopting
`rebase_iterate=true` in BEST_PRESET. That is a one-line change, left to the
coordinator; it is not made on this branch. No new record: 219 ties
`docs/records/fr24-219-roads-rebased.json`. The direct 200 s measurement reached 218
(232 -> 220 -> 219 -> 218, every step legal) when the first fast solve's fillers fit,
but that layout was not saved, so it is not a record.

## Limits / next

- FR24 still spends about 350-410 s of 600 on a walk that never finds a skeleton. Polish of
  the seed converges in about 60-80 s when the fillers fit, so the walk's time is the
  bigger lever (for example, run the seed's iterated polish before the walk on cities
  where seed_input is legal).
- The fixed point ends when a 60 s fast solve proves no gain, or when a filler failure
  has no usable trail. Then the model-filler solve takes the rest of the window and
  rarely gains anything.
