# Action plan: reach roads ≤ Σ(short-side)/2 with 100% placement

Written 2026-07-02 after reviewing the specs (`docs/superpowers/specs/`), plans,
`tasks/lessons.md`, the RL M2–M4 code, and all six training logs.

## Where the project actually stands

**Classical pipeline (solid, shipped):** darkzig 250 → 158 roads via repack +
anneal polish, 0-unplaced, quality-clean. Seven structural packer attempts, CP-SAT
(ceiling ~11×11), and LNS+CP-SAT (+1 road) all failed to move it. ~158 is the
proven floor for *local* methods on darkzig; target Σ/2 = 114.

**RL M2–M4 (infrastructure done, bet failing at its own gate):**
- Curriculum stages learn; at moderate fill (`training.log`, stage 4) success is
  80–86% but `mean_roads ≈ 100` vs target ~35 — roads ~3× target even when it places.
- At darkzig-like fill: `training_bridge.log` (bridging fill) and `training_m4.log`
  (0.9) are **0% success across the board**; every darkzig eval is `stuck`/`unroutable`.
- The rescue lever was pulled: BC warm-start (`rl/imitate.py`, acc 45.8%) + RL
  fine-tune collapses to 6–12% success and darkzig eval still `unroutable`
  (`training_bc_rl.log`) — likely catastrophic forgetting, but per the design doc's
  own fail-fast rule (§9.4) the fallback condition is now met.

**Two overlooked facts that reshape the strategy:**
1. **Validity needs ONE road-adjacent border cell** (`foeopt/validate.py:35-38`),
   not a full short side. So Σ(short)/2 is *not* a lower bound — it assumes every
   building spends its whole short side on a double-loaded road. Structures where a
   road cell serves 3 buildings (dead-end stubs, junctions) beat it. The user's own
   city proves it: 142 roads < its Σ/2 = 157.
2. **The two objectives have different bottlenecks.** 100%-placement fails only on
   near-full cities (unplaced are always consumers, never fillers — lessons); the
   road objective fails because no optimizer builds *global* double-row/stub
   structure. Solving the second largely solves the first (roads-first layouts make
   placement an area-accounting problem, not luck).

## Objectives (precise)

- **O1 — 100% placed:** 0-unplaced on any city with slack (darkzig-class),
  deterministic across seeds; never-worse `improve` behavior on near-full cities
  (the 97%-full bundled city is a perfect-packing puzzle — from-scratch 0-unplaced
  there is area-infeasible and stays out of scope).
- **O2 — roads ≤ Σ(short)/2:** ≤114 on darkzig (vs 158 today), and ≤ Σ/2 on the
  real-like benchmark suite.

---

## Track 0 — Calibrate the target (1–2 days, do first)

The 114 number may be a phantom; chasing it uninstrumented violates our own
measure-first lessons.

- [x] Compute honest lower bounds for darkzig roads: (a) adjacency-capacity bound
      (each connected road cell serves ≤3 consumers + must chain to TH), (b) LP
      relaxation of the placement+routing ILP on the real grid (bound only — no
      integral solve needed), (c) per-corridor counting on the free-cell geometry.
      (Shipped: (a) only, `foeopt/bounds.py::bound_adjacency` — 21 on darkzig, 28
      on the user city. (b)/(c) intentionally descoped: (a) is the max/usable
      bound and airtight; adding weaker bounds under it would not move the band.)
- [x] Measure the user's 142-road city: per-building road-cell "contribution"
      histogram + buildings-per-road-cell histogram (extend `foeopt/quality.py`).
      This characterizes *how* an expert beats Σ/2 (stubs? junctions? partial-side?).
      (Measured: hist {1:1, 2:137, 3:4}, avg 2.02, 0 overhead cells — 96.5% of
      road cells at the double-row ideal, essentially no connectivity waste.)
- [x] Deliverable: a target band for darkzig (e.g. "optimum plausibly 118–135")
      and a benchmark suite definition: darkzig (gate) + `make_real_like_city`
      seeds at fill 0.5/0.7/0.9 + the user's city for improve-mode regression.
      **BLOCKED (2026-07-03) → KILLED (2026-07-05):** v1 was INFEASIBLE under
      the model's own region-area guard. v2 (embedded trunk + end overhangs)
      fixed that but produced `f = 142/84 = 1.69`, outside the sanity band
      `[0.75, 1.33]` on the opposite side. Per the spec's one-iteration
      time-boxed retry rule, no v3 — no target band was ever produced. See
      `tasks/lessons.md` (2026-07-03 and 2026-07-05 entries) and
      `.superpowers/sdd/task-5-report.md` / `v2-task-b-report.md`.

## Track A — Lane/stub decomposition optimizer (the main bet) — KILLED (2026-07-05)

Lessons say beating 158 needs a *fundamentally different global optimizer*. The
expert layout IS a global decomposition: straight double-loaded lanes + trunk + TH
stubs. Four constructive lane attempts failed because they were **greedy, rigid
constructors**. The fix is to optimize the decomposition where it is 1-D and
combinatorial (tractable), and keep the 2-D geometry trivial:

- [x] **A1 — Composition solver (go/no-go gate, ~2 days, throwaway):** assign the
      63 road-needing darkzig buildings to *modules* — double-loaded lane segments
      (cost = max(Σ along-road extents side A, side B)), dead-end stubs (1 road
      cell, up to 3 buildings), junction cells — minimizing total road cells +
      trunk overhead. Pure 1-D bin-packing/balancing over ≤82 items: **CP-SAT is
      in its element here** (no spatial grid). Depth-bucket rows to keep outer
      edges straight; price mixed-depth raggedness explicitly; odd-size tail goes
      to lane end-caps and stubs instead of "leftover greedy".
      **Gate:** if the *optimal composition* already costs ≥~150 road cells before
      geometry, the whole track dies cheaply. If it's ~115–130, proceed.
      **RESULT (2026-07-05): KILL.** v2 calibration gave `f = 1.69`, outside the
      sanity band `[0.75, 1.33]` (v1 failed the other way: INFEASIBLE/too
      pessimistic; v2 over-corrected to too optimistic). Pre-committed
      one-iteration retry rule fires — no v3, A2/A3 do not proceed. See
      `tasks/lessons.md` 2026-07-05 entry.
- [ ] ~~A2 — Geometric embedding~~ (not started — killed at the A1 gate): pack lane rectangles (length × (depthA + 1 +
      depthB)) + a trunk into the irregular region (strip packing against region
      rows; TH near-edge with two road stubs per the user's heuristic memory).
      Fillers backfill remaining space — fillers already place perfectly (lessons).
- [ ] ~~A3 — Repair + polish~~ (not started — killed at the A1 gate): `route()` to connect/validate; existing anneal as
      finisher; any stranded tail goes through the current greedy into leftover
      pockets.
- [ ] **Discipline:** throwaway prototypes; A/B vs 158 only at 0-unplaced across
      ≥8 seeds (lessons rule); explicit kill criterion at each sub-step.

## Track B — Structured LNS on the 158 plateau (cheap, parallel)

Local search plateaus because single moves/swaps can't perform the coordinated
multi-building rearrangement that turns a grow-tree corridor into a double row.
Change the *move set*, not the search:

- [ ] Corridor-granularity destroy-repair: pick an under-used corridor via
      `quality.py`, free its buildings + road cells, rebuild as a balanced double
      row using A1's balancer; add row-shift and junction/stub-promotion moves.
- [ ] Run inside the existing anneal/polish harness; same A/B discipline.
      Expected: single-digit road gains; also the productionizable fallback if
      Track A dies at its gate.

## Track C — RL: fix-or-fold (time-boxed, ranked last)

Per its own M4 fail-fast rule the RL bet is at the fold point. If continued at
all, change the *problem formulation*, not the knobs:

- [x] **C1 — Routability-preserving action mask:** mask placements that disconnect
      free-space components from the TH frontier (articulation check). Eliminates
      `unroutable` by construction ⇒ dense fills become learnable, and the same
      mask drops into the classical packer to attack stranded consumers (O1) —
      **build C1 regardless; it serves Tracks A/B too.**
      **DONE (2026-07-05), opt-in only:** `foeopt/reach.py` (exact predicate +
      `ReachChecker` fast path, oracle-equivalence tested) built and wired into
      `first_fit`/`first_fit_adjacent`, `repack`/`build_candidate`
      (`safe_placements=`), `PlacementEnv.valid_actions(safe=)`, and
      `--safe-placements` CLI. A/B-measured per spec §5 (8 seeds × 120s,
      darkzig + real-like 0.5/0.7/0.9): **both flip-the-default gates fail** —
      unplaced distribution strictly worse in the tails (darkzig 0/0/0→0/5.1/10,
      fill 0.9 0/0.6/4→11/12.6/15, 0/8 seeds reach 0-unplaced) and throughput
      drops 67-73% everywhere (well past the ~30% budget). Kept as opt-in
      only, zero cost when off. See `tasks/lessons.md` 2026-07-05 entry and
      `.superpowers/sdd/p2-task-5b-report.md`.
- [ ] C2 — Make roads observable: incremental partial-`route()` potential + a road
      channel in `rl/encode.py` (today the policy never sees road structure until
      the terminal step — it cannot learn to leave channels at 90% fill).
- [ ] C3 — DAgger from the repack expert instead of one-shot BC; KL-anchored
      fine-tune (the 45%→6% collapse in `training_bc_rl.log` is forgetting).
- [ ] **Hard gate:** fill-0.9 real-like success ≥50% within a fixed GPU budget
      (e.g. 24 GPU-hours), else archive the track (keep env + tests — they're paid
      for). Note honestly: even passing placement, BC toward repack outputs caps
      road quality at repack level (~169) — RL's upside needs Track A's structure
      anyway.

## Track D — Productionize the winner

- [ ] Fold the winning path into `polish`/webapp; surface quality + lower-bound
      numbers in CLI/report output; update README + lessons.

## Order & why this can reach the objective

`0 → A1 (go/no-go) → {A2/A3 ‖ B} → D`, with C1 built early as shared
infrastructure and the rest of C only on explicit user go.

O1 falls out of C1's mask + Track A's roads-first structure (placement becomes
area accounting). O2 is credible because (a) the expert layout proves Σ/2 is
beatable *on a slack city* with exactly the lane+stub structure Track A optimizes
globally, (b) A1's composition optimum is computable *before* any geometry work —
we learn within days whether ≤114 is geometrically live on darkzig or whether
Track 0's lower bound shows the real optimum sits above it (in which case the
objective is re-anchored to the proven bound, not abandoned on vibes).

## Review

### Track 0 / A1 — BLOCKED at calibration (2026-07-03)

Built per plan: `foeopt/quality.py` sharing metrics, `foeopt/bounds.py`
(adjacency bound only — b/c descoped, see checklist above),
`scripts/exp_lane_composition.py` (throwaway CP-SAT lane/stub composer,
`--selftest` PASS: oracle=1 ≤ family=6).

Calibration (§3.4) could not be completed. Running the composer on the user's
82-consumer inventory with the spec's own region-area-fit guard
(`total ≤ region_free_cells = 145`) returns **INFEASIBLE** — confirmed not a
`--stack-max`/`--lanes` sizing artifact (re-run with `--lanes 20 --stack-max
300` still INFEASIBLE; the binding constraint is the area guard, which isn't
CLI-adjustable). So `model_optimum(user city)` does not exist and
`f = 142 / model_optimum` cannot be computed — a harder failure than "outside
the [0.75, 1.33] sanity band," so per the escalation rule the darkzig number
was **not** used to compute a verdict.

Root cause (diagnosed against the T2 sharing histogram): the user's real
layout is nearly all double-loaded lane (137/142 cells at load 2, only 5
"overhead"/junction cells total, avg load 2.02) — i.e. real trunk overhead is
tiny. The model's pessimistic-trunk formula (`Σ over lanes of depthA+1+depthB`,
crediting zero cross-lane trunk sharing) cannot reproduce that: relaxing the
area guard to see the model's own unconstrained answer, its best-found
solution after 300s needs `trunk_pessimistic=41` (vs the real ~5) and
`lane cells≈164` (vs the real double-loaded 137, from the rigid
uniform-depth-per-lane-side constraint) — total 205, not even proven optimal
(bound 166). Both numbers are big overcounts on a city with only 3 free cells
of slack (4224 region − 4079 buildings − 142 real roads), so the family model
blows the budget before any feasible point exists.

**Darkzig numbers were computed (Step 1 ran all three commands per the brief)
but are NOT a verdict:** `comp-darkzig.json` model_optimum=160 (proven_bound
124, gap 36); `comp-darkzig-stubs.json` model_optimum=61 (proven_bound 41,
gap 20 — degenerate, stub cap lets the solver open many minimal lanes purely
to unlock stub slots; matches the design doc's own warning that the stub
scenario is a sensitivity check, not a base-model number). `report_bounds`:
darkzig max=21, user-city max=28.

**Gate decision: none — BLOCKED, calibration itself failed** (this is not the
"C* between thresholds" case; it is escalated separately per the brief's
sanity-range rule, generalized to "model_optimum doesn't exist"). Not a
go/kill on Track A itself — the A1 solver and its
`--selftest` restriction-property check are sound; the pessimistic-trunk cost
term is the specific defect (its own reported total on the user city is
already ~1.17–1.44× the real 142 (proven bound 166, best-found incumbent 205), before the area guard even fires). Two
unblocking options for the user: (1) fix the trunk formula to credit
cross-lane sharing and re-calibrate, or (2) accept the adjacency-bound-only
target band (`[21, C*]` unknown) and route to Track B/D on the existing
158-road plateau without a calibrated Track-A ceiling. Full numbers, the two
CLI probes, and the diagnostic run are in `.superpowers/sdd/task-5-report.md`.

### Track A — KILLED at the v2 retry (2026-07-05)

Per the spec's own escalation path, option (1) above was taken: `--model v2`
(embedded trunk + end-overhangs, dropping the pessimistic trunk term and
crediting up to 2 free-overhang buildings per lane side) was built and its
`--selftest` passed. It fixed the *feasibility* problem — v2 solves both
cities — but the calibration factor still fails the sanity band, now from the
opposite side:

- User city: `status=FEASIBLE`, `model_optimum=84` (`proven_bound=13`, `gap=71`).
  `f = 142/84 = 1.69`, above the upper sanity edge `1.33`. Decisive, not a
  convergence artifact: `model_optimum` is a feasible incumbent (valid upper
  bound on the true model optimum) for a minimization problem, so more solve
  time can only lower it further and push `f` even higher — never back under
  1.33. No re-run at 900 s was needed for that reason.
- darkzig: `model_optimum=39` (`proven_bound=0`, `gap=39`);
  `--connectors` sensitivity `model_optimum=50` (`+11`, matching
  `n_used_lanes−1` for the reported 12 lanes).
- Because `f` is outside the band, **`C*` was not computed** — a band miss is
  its own verdict per the brief's step 2, independent of the darkzig numbers.

This was the pre-committed **one-iteration, time-boxed retry**
(`docs/superpowers/specs/2026-07-02-road-target-calibration-design.md`, v2
section): "if v2 also fails calibration, Track A is killed... no v3." It
failed, so **Track A (A1/A2/A3 — the global lane/stub composition optimizer
for O2) is killed.** A1's checklist item above is checked off with this
result; A2/A3 are marked not-started/killed rather than deleted, for the
record. `foeopt/quality.py`, `foeopt/bounds.py`, and
`scripts/exp_lane_composition.py` remain in the repo as sound diagnostic
tooling (their self-tests pass); only the "use this solver's output as the
calibrated road target" bet is closed.

**Remaining live paths per the plan's own ordering:** Track B (structured LNS
on the existing 158-road darkzig plateau — cheap, parallel, was always the
productionizable fallback if Track A died at its gate) and Track D
(productionize whichever path wins). Full numbers, commands, and arithmetic:
`tasks/lessons.md` 2026-07-05 entry and `.superpowers/sdd/v2-task-b-report.md`.

### Track C1 — routability mask built and A/B-measured; stays opt-in (2026-07-05)

`foeopt/reach.py` (exact `placement_is_safe` oracle + `ReachChecker`
accelerator, per-anchor filter in `first_fit`/`first_fit_adjacent`,
`safe_placements=` on `repack`/`build_candidate`, `safe=` on
`PlacementEnv.valid_actions`, `--safe-placements` CLI flag) is complete and
tested. The A/B harness (`scripts/exp_safe_ab.py`, 8 seeds × 120s budget,
darkzig + real-like fill 0.5/0.7/0.9, `output/safe-ab.txt`) shows **both
spec §5 flip-the-default gates fail**:

- Gate 1 (unplaced no worse anywhere, better in tails): darkzig 0/0/0 →
  0/5.1/10 (only 1/8 seeds reach 0-unplaced); fill 0.9 0/0.6/4 → 11/12.6/15
  (0/8 seeds reach 0-unplaced) — worse in exactly the tails the mask targeted.
  fill 0.5/0.7 tie (both all-0), no gain.
- Gate 2 (0-unplaced roads not worse AND throughput regression < ~30%):
  throughput drops 66.7-73.2% in every scenario (darkzig 205→55, fill 0.5
  242→67, fill 0.7 266→76, fill 0.9 132→44) — 2-2.4x past budget; road
  counts at fill 0.5/0.7 are also slightly worse, not better.

**Verdict: do not flip the default.** `safe_placements` stays opt-in
(default off, zero cost/byte-identical when unused). Mechanistically, the
project's unplaced failures were never routing failures (`route()` already
doesn't fail for grow-tree candidates; unplaced are a packing/co-design
problem — 100% consumers, a structural floor per the 2026-06-23 attempt #5
entry) — so a guaranteed-routability mask solves a problem repack doesn't
have, while forbidding the tight endgame placements dense packing needs and
starving the multi-start loop of trials. Rule: never guard a search with a
per-candidate exactness check when the failure mode is packing, not
validity — measure any such mask at equal wall-clock (trials-normalized)
before considering a default flip. `foeopt/reach.py` stays as verified
infrastructure: pre-registered prerequisite for any RL revisit, and a
candidate one-shot validity check inside future Track-B destroy-repair
moves. Full numbers: `tasks/lessons.md` 2026-07-05 entry,
`.superpowers/sdd/p2-task-5b-report.md`.

### TH-stub constructor template A/B — gates fail, stays opt-in (2026-07-06)

User-requested experiment outside the original track list: a constructive
seed template (`th_stub_template` flag, commits 2bbb4a6/82af61e) replicating
the user's expert offset-TH + two-flank-stub pattern (each stub road cell
serving 3 buildings). A/B'd 8 seeds x 120s on darkzig + real-like
fill 0.5/0.7/0.9 (`scripts/exp_th_ab.py`, `output/th-ab.txt`). Both
harness gates (0-unplaced roads not worse, ideally better; unplaced no
worse) fail: darkzig mean roads worsens 164.6 to 169.9 despite ~45% more
trials, fill-0.9 collapses from 6/8 seeds reaching 0-unplaced to 1/8, and
fill 0.5/0.7 are essentially a wash. Root cause: the flag halves the
corner-style trial share (coin-flip start style per trial) at exactly the
budget where corner-style carries the result, and an earlier 10s/2-seed
smoke run had shown the opposite ranking - the template wins fast but the
120s multi-start loop lets the corner constructor overtake it. Verdict:
`th_stub_template` stays default-off/opt-in; another instance of the
standing "expert heuristics bolted onto the greedy constructor lose an
equal-wall-clock A/B" pattern. Full numbers: `tasks/lessons.md`
2026-07-06 entry, `.superpowers/sdd/tht-task-c-report.md`.
