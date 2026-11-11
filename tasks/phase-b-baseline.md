# Phase B baseline: where the time goes (2026-11-11)

BEST_PRESET exactly as shipped (position model, probe_limit 30, objective_limit 30,
objective_polish 0.3, exact_finish, nonuniform + band, 6x2 workers), all game rules on,
strictly sequential. Rows: `scripts/_phase_b_baseline.jsonl` (each has a manifest and a
profile). Shares below are of worker time (wall x 6 workers).

## Results (all legal)

| city | 120 s | 600 s | before |
|---|---|---|---|
| darkzig | 94, 95 | 91, **90** | 90 (legal) |
| FR16 | 68, 68 | 68, 68 | 68 |
| FR17 | 106, 106 | **103, 103** | 105, **new record 103** (`docs/records/fr17-103-roads-preset.json`) |
| user (97% full) | - | none (FAMILY_TOO_WEAK) | none |
| FR24 | - | none (FAMILY_TOO_WEAK) | none |

## Where the time goes

| | darkzig 600 | FR16 600 | FR17 600 | FR16/17 120 | user | FR24 |
|---|---|---|---|---|---|---|
| probe solve, UNKNOWN (30 s timeouts) | 16% | 46% | 61% | 26% | 73% | 44% |
| probe solve, UNSAT / SAT | 0 / 5% | 0 / 2% | 4 / 1% | ~1% | 16 / 0% | 44 / 0% |
| objective solve | 35-38% | 27% | 13% | 17-25% | 1% | 0% |
| model build (probe + objective) | 1.2% | 0.4% | 1.0% | <1% | 8% | 9% |
| validate (route + fillers + repair) | 0.3% | 0% | 0.1% | <0.2% | 0.2% | 0% |
| generation + prefilter | 0.1% | 0.2% | 0.2% | 0.4% | 0.1% | 0.5% |
| workers idle during the walk | (see note) | 24% | 22% | **47-53%** | 9% | 12% |

Note: for darkzig the end-of-run polish runs in the parent with all threads and is
not counted as worker time, so its "idle" (~40%) is mostly that phase, not waste.

## Findings

1. **Model building, routing and filler packing are negligible** (about 1% combined on
   solvable cities). Codex Tasks 2A (geometry reuse) and 3 (faster filler scan): **drop**.
2. **The first layout always appears at ~31 s** on every city and box. The feasibility
   probe finds one in about a second, but the in-walk objective holds that worker for its
   full 30 s limit before reporting. A UX lever: publish the feasible layout first.
3. **UNKNOWN probes are the biggest cost on FR16/FR17** (46-61% at 600 s). Decided
   probes take under a second with the position model, so a 30 s limit mostly buys
   timeouts. A shorter probe limit is a cheap, high-value A/B.
4. **Workers sit idle 47-53% at 120 s on FR16/FR17** (22-24% at 600 s): a level batch
   waits for its slowest probe or objective before the next batch is dispatched.
   Keeping the pool fed across levels is a real speed lever at short boxes.
5. **Runs end early:** FR16/FR17 finish at 0.63-0.69x of the box. Objective polish
   converges almost at once (its share is about 0%), so about 200 s of a 600 s box goes
   unused. Phase C target.
6. **Solver roads vs greedy route (Codex Task 1):** on darkzig, the routed count exceeds
   the objective's own road count in 29-30 of 42 solves (~1.3 roads per solve on
   average). On FR16/FR17 there is essentially no gap. Worth doing, mainly for darkzig-like
   cities (mixed sizes, two-lane tile).
7. **The dense cities fail for different reasons:**
   - **user:** 848 skeletons proven UNSAT and **one** consumer placement found, which
     then failed filler packing. Consistent with "fillers must be in the model" (Phase D).
   - **FR24:** 1685 UNSAT, **zero** consumer placements. Fillers are not the blocker;
     the skeleton families cannot host FR24's 146 consumers at the k tried. Phase D will
     not fix FR24 alone. It needs different skeletons or optional road cells (Codex T5).

## Decision

Next, in order of expected value per effort:
1. **Quick A/Bs on existing knobs:** probe_limit 30 -> 10 (and 5) at 120 s and 600 s.
2. **Publish the feasible layout before the objective** (first result ~31 s -> ~1-2 s).
3. **Phase C:** rebased polish on the accepted network + the solver's road witness
   (T4 + T1), using the leftover ~35% of the box.
4. **Phase D:** fillers in the position model (user city), plus an FR24 skeleton study.
5. Pool feeding across level batches (idle workers at short boxes): after 1-2, since
   a shorter probe limit already shrinks the stragglers.

## Follow-up A/B: probe_limit 30 vs 10 vs 5 (objective_limit and repair clamp with it)

| city | 120 s: 30 / 10 / 5 | 600 s: 30 / 10 |
|---|---|---|
| darkzig | 94,94 / **90,89** / 92,90 | 91,92 / **90,91** |
| FR16 | 68,68 / 68,68 / 68,68 | 68,68 / 68,68 |
| FR17 | 106,106 / 106,**103** / 105,105 | **103,103** / 105,105 |
| first layout | 31 s / 12 s / 7 s | 31 s / 12 s |

Not adopted as-is: FR17 at 600 s is worse in both pairs (rule: never worse). **Why:** with
10 s, FR17's levels 113/109/105/114 end INCONCLUSIVE (every skeleton probed, some UNKNOWN)
quickly, the bisection settles, and the run STOPS at 175 s (0.3x of the box). At 30 s the
same levels end UNDERSAMPLED and the walk also stops early (0.63x). In both arms the walk
treats unknowns as the end and then leaves the box unused. The short limit is not the
problem; the controller's stopping rule is. darkzig 89 (120 s, pl10) is a new legal record
(`docs/records/darkzig-89-roads-pl10.json`, re-verified from file).

**Next:** keep the 10 s first pass (fast first result), and when the walk settles with
budget left, re-probe the unknown levels below the best with an escalating limit
(10 -> 30 -> 90 s) on fresh skeletons until the box is spent (Phase C, "use the
leftover box").
