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

## Track B — Structured LNS on the 158 plateau (cheap, parallel) — CLOSED at the gate (2026-07-06)

Local search plateaus because single moves/swaps can't perform the coordinated
multi-building rearrangement that turns a grow-tree corridor into a double row.
Change the *move set*, not the search:

- [x] Corridor-granularity destroy-repair: pick an under-used corridor via
      `quality.py`, free its buildings + road cells, rebuild as a balanced double
      row using A1's balancer; add row-shift and junction/stub-promotion moves
      — descoped to v2-if-gate-passes per spec §1.3; never built (gate failed).
      Built (`--lns` flag, `lns_polish`), default off.
- [x] Run inside the existing anneal/polish harness; same A/B discipline.
      **RESULT (2026-07-06): GATE FAILS on darkzig** — `lns_polish(60,30,30)`
      vs `polish(60,60)`, equal wall-clock, 8 seeds: mean 161.25 vs 160.75
      (0.5 *worse*, gate needs `<= -2`), max tied 175=175. Pre-committed gate
      (spec §1.1/§8) fails -> `--lns` stays opt-in, **Track B closes** (no
      tuning marathon). Secondary finding: on slack cities (real-like
      fill 0.5) the same mechanism wins by **-7.4 roads mean** at equal
      wall-clock — the mechanism works, darkzig just has no slack to use it
      on. A parallel TH-offset probe (diagnostic only, no gate) found
      offset-TH placement alone is neutral-to-worse, not a fix for the
      darkzig plateau. Full numbers: `tasks/lessons.md` 2026-07-06 entry,
      `.superpowers/sdd/task-8-report.md`.

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

## Track E — Roads-first fixed-skeleton CP-SAT feasibility search — 106 VERIFIED LEGAL, gate WIN (2026-07-07)

**The void "127-road WIN" below (T4 v1) has been superseded by the de-rotated re-run: 106 roads,
independently verified legal.** The v1 127 was invalid (19/33 non-square consumers placed ROTATED, which
FoE forbids) — fixed 2026-07-07: `rotated_buildings` guard in `foeopt/validate.py`; rotation removed from
`scripts/exp_roads_first.py` + `foeopt/lns.py`. The de-rotated re-run (`--probe-limit 30`, 200 patterns,
k-start=152, 6h box) returned **106 ≤ 148 → decisive WIN**, with `rotated_buildings`=0 confirmed by
independent re-derivation. See the 2026-07-07 entries in `tasks/lessons.md` (RETRACTION + de-rotated
re-run). T1–T3 stand; T4 v1's verdict is void, T4 v2 below is the live verdict.

Per `docs/superpowers/plans/2026-07-06-roads-first-feasibility.md` /
`docs/superpowers/specs/2026-07-06-roads-first-feasibility-design.md` (the user's own roads-first framing,
refined against the project's evidence base):

- [x] T1 — Spec §5 amendment + comb/TH-stub pattern generator + certificate-safe arithmetic pre-filter.
- [x] T2 — CP-SAT placement-feasibility probe + validation pipeline (`route()` + `is_valid` + filler
      placement) + oracle self-test.
- [x] T3 — k-walk protocol (152 → −4 while feasible, bisect the gap), JSONL probe log, best-layout
      artifacts, smoke mode.
- [x] T4 v1 — ~~Real 6h run + gate verdict: WIN, 127 roads~~ **RETRACTED** (rotated buildings, invalid).
- [x] T4 v2 — De-rotated 6h re-run + gate verdict: **WIN, 106 roads.** Best achieved 106 on darkzig
      (k=118 pattern, independently re-derived: 224/224 buildings, 0 unsatisfied, `route()`=106,
      `is_valid` True, 0 overlaps, **`rotated_buildings`=0**), 106 ≤ gate threshold 148. Configuration:
      `--probe-limit 30` (tuned down from 120s per the 2026-07-06 operational finding — SAT max 28.9s so
      no achievable layout missed, 4x-cheaper UNKNOWNs bought 12 k-levels vs v1's 2). 2189 probes (230
      SAT/1315 UNSAT/642 UNKNOWN/2 filler-fail), `sum_secs`=21557s=5.988h (full 6h accounted). k-walk:
      152→148→144→140→136→132→128→124→120 all FEASIBLE → 116 INCONCLUSIVE → bisect 118 (106) → bisect 117
      (112) → deadline, `walk_complete=TRUE`. **106 is a validated achievable count, not a proven floor**
      — k=116's 60 UNKNOWNs may be feasible with more time. First method to beat the Σ/2 estimate (114)
      and the local-method floor (158) simultaneously. Full numbers, gate arithmetic, mechanism, and the
      probe-limit tuning verdict: `tasks/lessons.md` 2026-07-07 entry ("Roads-first de-rotated re-run").
      Productionization (wiring the k-walk into `polish`/webapp, tuning for lower k) is a separate later
      spec per the gated-solver-extras policy — `ortools` stays a throwaway `uv run --with` dependency,
      `foeopt/` core is unchanged.

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

### Track B — corridor-LNS gate fails on darkzig; mechanism validated on slack cities; TH-offset probe neutral (2026-07-06)

Built the Track B corridor-granularity destroy-repair (`--lns` flag,
`lns_polish`, default off): free an under-used corridor's buildings + road
cells and rebuild it as a balanced double row, inside the existing
anneal/polish harness. A/B'd per the pre-committed gate in spec §1.1/§8 —
darkzig, 0-unplaced rows only, `mean(B) <= mean(A) - 2 AND max(B) <= max(A)`
— against `polish(60,60)` at equal wall-clock (arm B `lns_polish(60,30,30)`),
8 seeds, darkzig + `make_real_like_city` fill 0.5/0.7/0.9
(`scripts/exp_lns_ab.py`, `output/lns-ab.txt`).

**Gate result: FAILS.** darkzig mean(A)=160.75, mean(B)=161.25 — B is 0.5
roads *worse* on mean (gate needed `<= -2`, i.e. `<= 158.75`); max tied at
175=175. The mean clause alone kills the gate. **Verdict: `--lns` stays
opt-in (default off); Track B is closed** per the pre-committed no-tuning-
marathon rule — revisiting needs new evidence, not more knob turns on this
harness.

**Mechanism validated, just not on the gate city.** At real-like fill 0.5
(a slack city) the identical mechanism wins by **-7.4 roads mean** at equal
wall-clock (115.5 -> 108.125), with accepted rewrites in 7/8 seeds — the
first structural method in this project's long history of structural attempts (four
structured packers, CP-SAT, LNS+CP-SAT, RL M2-M4, safe-placements mask,
TH-stub template, corridor-LNS) to beat plain local-search polish at its own
game anywhere. On darkzig (97%-dense era layout at 60 s polish) there's no
free space for the double-row template to land in, so almost nothing gets
accepted (0-1 rewrites/seed) — a slack/density story, not a bug.

**TH-offset probe (diagnostic only, no gate, `output/th-offset-ab.txt`):**
pure-style corner-only vs offset-only repack, 8 seeds. Darkzig: offset mean
167.0 vs corner mean 164.625 (offset ~2.4 *worse*); fill 0.5 near-identical;
fill 0.7 offset marginally better (152.875 vs 153.25); fill 0.9 offset worse
on placement (only 3/8 seeds reach 0-unplaced vs 6/8 for corner). Reading:
offset-TH placement alone is not a measurable fix for the darkzig plateau —
the expert city's advantage from an offset Townhall evidently comes from the
coordinated structure built around it, not the placement in isolation. No
follow-up TH-placement track is warranted by this data alone; noted as the
first data point against the user's standing (memory-flagged) interest.

**Not pursued, noted for the record:** a "recommend `--lns` when a city has
overhead-cell slack above some threshold" heuristic is a legitimate Track D
candidate if this project reaches productionization — `--lns` is a genuine
opt-in win for slack cities, just not for the darkzig gate. Visual before/
after of accepted corridor rewrites: `output/lns/<stamp>/` HTML folders.
Full numbers and gate arithmetic: `tasks/lessons.md` 2026-07-06 entry,
`.superpowers/sdd/task-8-report.md`.

### Track E — Roads-first feasibility search: gate WIN, search truncated by deadline (2026-07-06) — VOID

**This v1 entry is VOID — the 127-road layout was invalid (rotated buildings). It is kept for the record
only. The live verdict is the v2 de-rotated re-run entry below.**

Ran the pre-committed 6h box (`scripts/exp_roads_first.py darkzig.json`, `output/roads-first/run.txt`),
348 CP-SAT probes logged to `output/roads-first/probes.jsonl` and recomputed independently (not trusted
from the run summary): 95 SAT (mean 7.7s, max 100.5s), 81 UNSAT (mean 1.7s, max 48.4s), 172 UNKNOWN (all
pinned at the 120s probe-limit). Sum of logged `secs` = 21600.9s = 6.0002h, confirming full accounting.

Only two k-levels were reached: k=152 (54 SAT/45 UNSAT/93 UNKNOWN, best achieved 128) and k=148 (41
SAT/36 UNSAT/79 UNKNOWN, best achieved **127**) — the 172 UNKNOWN timeouts consumed 20727.3s (5.758h,
~5.7h of the 6h budget), leaving no time to probe below k=148.

**Gate (spec §2.1): best achieved 127 ≤ 148 → WIN.** ~~Independently re-derived~~ The "verification"
checked `route()`/`is_valid`/0-unsatisfied but NOT orientation — `is_valid` has no canonical reference.
**19/33 non-square consumers were placed ROTATED, so the layout is illegal and the WIN is withdrawn
(2026-07-07 RETRACTION).**

**Mechanism:** roads-first (the user's own framing) fixes the road skeleton before placement, so the
inner problem has zero connectivity variables — pure rectangle packing CP-SAT can solve exactly, finding
the overhang/corner assignments greedy attach could never reach (the same trick behind the user's own
142-road city's 2.02 average cell-sharing). This is why it beats every one of this project's prior
structural attempts (four lane/hybrid packers, CP-SAT composition, LNS+CP-SAT, RL M2-M4). **Mechanism
reading stands; only the rotated-layout verdict is void.**

**Operational finding (acted on in v2):** the 120s per-probe UNKNOWN limit is the bottleneck, not solve
quality — SAT/UNSAT resolve fast (means 7.7s/1.7s) but 49% of probes hit the timeout and ate most of the
budget. A follow-up should tune the probe-limit or solver hints before spending more wall-clock at this
configuration. **v2 used `--probe-limit 30` — see entry below.**

### Track E v2 — De-rotated re-run: 106 roads, VERIFIED LEGAL, decisive gate WIN (2026-07-07)

Ran the de-rotated 6h box (`scripts/exp_roads_first.py darkzig.json --probe-limit 30`,
`output/roads-first/run-derotated.txt`), 2189 CP-SAT probes logged to `output/roads-first/probes.jsonl`
and recomputed independently (not trusted from the run summary): 230 SAT (mean 4.75s, **max 28.9s — all
resolved within the 30s limit, confirming the probe-limit tuning**), 1315 UNSAT (mean 0.76s, max 29.4s),
642 UNKNOWN (all pinned at the 30s probe-limit), 2 SAT_FILLER_FAIL. Sum of logged `secs` = 21557.2s =
5.988h, confirming full accounting of the 6h box.

12 k-levels reached (vs v1's 2): k=152 (best 127) → 148 (128) → 144 (121) → 140 (119) → 136 (116) →
132 (118) → 128 (118) → 124 (113) → 120 (107) → 118 (**106**) → 116 (INCONCLUSIVE, 0 SAT) → bisect 117
(112) → deadline. The 642 UNKNOWNs consumed 19460.9s = 5.406h (90.3% of the budget) — still the dominant
cost, but at 30s each (4x cheaper than v1's 120s) they bought 12 k-levels of coverage instead of 2.

**Gate (spec §2.1): best achieved 106 ≤ 148 → decisive WIN.** Independently re-derived
`output/roads-first/best-k118-a106.json` from scratch: 224/224 buildings placed, 0 unsatisfied,
`route()` returns exactly 106 (matches the JSON's 106-entry `roads` array, matches `achieved`), `is_valid`
True, 0 overlapping cells, 0 cells out of region, **`rotated_buildings(cand, canonical_dims(loaded))` = 0
— the invariant v1 never checked.** 106 also beats the void 127 (−21), the prior all-time best 153 (−47),
the local-method floor 158 (−52), and the Σ/2 estimate 114 (−8 — 114 was never a bound, just a
double-row-tiling estimate; 106 clears it via the stubs/junctions mechanism).

**`walk_complete = TRUE`, `deadline_hit = TRUE`.** 117 is the lowest proven-feasible k (1 SAT); 116 is
INCONCLUSIVE (0 SAT, 132 UNSAT, 60 UNKNOWN — may be feasible with more probe time, so 106 is a validated
achievable count, not a proven floor). 106 sits at k=118, not at the lowest feasible k (117→112), because
lower k = tighter skeleton = fewer patterns SAT (230 SAT total: 49 at k=152 down to 1 at k=117) — there's
a sweet spot where enough patterns still SAT for one to route-prune aggressively.

**Verdict: WIN, with the truncation/INCONCLUSIVE caveats stated explicitly.** Productionization (wiring
the k-walk into `polish`/webapp, tuning for lower k or a tighter pattern family) is a separate later spec
per the gated-solver-extras policy; `ortools` stays a throwaway `uv run --with` dependency and `foeopt/`
core is unchanged. Full numbers, per-level table, mechanism, and probe-limit tuning verdict:
`tasks/lessons.md` 2026-07-07 entry ("Roads-first de-rotated re-run"). Artifacts:
`output/roads-first/best-k118-a106.json`/`.html` (winning layout) and the full `best-k*.json`/`.html` set.
Void v1 artifacts: `output/roads-first/invalid-rotated-2026-07-06/`. Full v1 report (void):
`.superpowers/sdd/task-4-report.md`.

### Track E v3 — Parallel re-run: 104 roads in ~2h, VERIFIED LEGAL, gate WIN (2026-07-07)

Parallelized the search via `multiprocessing.Pool` (4 probes × 4 CP-SAT portfolio workers,
default). `scripts/exp_roads_first.py` throwaway-only; no new dep, no `foeopt/` change.
Spec: `docs/superpowers/specs/2026-07-07-roads-first-parallel-search-design.md`; plan:
`docs/superpowers/plans/2026-07-07-roads-first-parallel-search.md`; 5 commits on
`feat/roads-first-parallel` (d023632..0cd9346), all reviews clean.

**Result: 104 roads at k=116, independently verified LEGAL** (224/224 placed, `route()`=104
matches, `is_valid` True, 0 unsatisfied, `rotated_buildings`=0, 0 overlaps, 0 out-of-region).
Beats the sequential v2 106 (−2), prior all-time best 153 (−49), local floor 158 (−54),
Σ/2 estimate 114 (−10). Gate 104 ≤ 148 → decisive WIN.

**~4x throughput, ~1/3 wall-clock:** 2496 probes in ~2h wall (cumulative 7.085h across 4
workers = 3.9x parallel efficiency) vs the sequential 2189 probes in 5.988h. `walk_complete
= TRUE`, `deadline_hit = FALSE` — the k-walk converged at k=116 (1 SAT → 104) with k=112/
114/115 INCONCLUSIVE, leaving ~4h of the 6h box unspent. 13 k-levels probed. UNKNOWN rate
29.3% — unchanged from the sequential (the 4-worker portfolio did NOT flip UNKNOWNs; the
throughput win is what delivered the result). Lesson: the reliable fix for UNKNOWN-dominated
budget is more k-coverage via throughput, not portfolio depth.

104 is a validated achievable count, not a proven floor — k=112–115 are INCONCLUSIVE (60
UNKNOWNs each, may be feasible with more probe-time). The early completion + unspent ~4h
point at the next experiment: longer `--probe-limit` / more `--patterns` at the tightest
k-levels to flip INCONCLUSIVE→FEASIBLE. Separate later spec per the gated-solver-extras
policy. Full numbers, per-level table, mechanism, and code-change summary:
`tasks/lessons.md` 2026-07-07 entry ("Roads-first parallel re-run"). Artifacts:
`output/roads-first/best-k116-a104.json`/`.html`; sequential baseline preserved in
`output/roads-first/sequential-baseline-2026-07-07/`.

### Track E v4 — Pattern-ceiling correction + full-TH-sampling + productionization analysis (2026-07-07)

Targeted re-run + full-TH test reshaped the understanding (see `tasks/lessons.md` 2026-07-07
entries: "Pattern-family ceiling correction", "Road-efficiency metric + CP-SAT feasibility
insight", "Productionization analysis + RL verdict"):

- **The 192-per-k ceiling was an artifact of the 8-TH coarse heuristic**, NOT a comb-family or
  low-k constraint. `--th-anchors full` enumerates 2162 TH positions → ~55k distinct patterns
  per k (285x). Highest-leverage diversity lever found; one-flag throwaway-script change.
- **The parallel 104 was portfolio luck** (targeted re-run got 0 SAT at k=116 across all 192
  coarse patterns). Robust floor is ~k=118 (108–110 roads). Report 104 as "achievable under
  portfolio luck," not "the floor."
- **Full-TH test: 105 roads at k=112, independently verified LEGAL** (109.0% road efficiency),
  in just 16 probes at k=112 — flips INCONCLUSIVE→FEASIBLE. New all-time best for a *robustly
  reachable* result. `--th-anchors` flag shipped (commit 4655b51).
- **Road efficiency metric established:** Σ(short)/2 / roads as %. Every recent roads-first
  result >100% (106→108%, 104→110%, 105→109%) — unprecedented for the game (prior tools 70–90%
  with many unplaced).
- **CP-SAT returns first feasible placement, not best** (no objective) — a SAT at 30.3s is a
  ceiling on that skeleton, not the floor. Objective-augmented probe is a candidate R&D spec.
- **Productionization recipe:** time-boxed (60–120s) + warm-started from classical (158) +
  smart k-start + any-time UX → ~125 roads in ~2 min, ~110%+ efficiency. Track D.
- **RL NOT revived as main bet.** Narrow role as skeleton-chooser (CP-SAT as placer) possible
  later, off the table until productionization ships AND the richer lane/stub family ships.

**Next specs, in order:** (1) Productionization (Track D) — time-boxed roads-first warm-started
from classical; (2) Richer pattern family — full-TH sampling (shipped) + lane/stub topologies
to push below 105. Artifacts: `output/roads-first/best-k112-a105.json`/`.html` (verified 105);
targeted baseline in `output/roads-first/targeted-baseline-2026-07-07/`.

---

# Track F — Population-level skeleton selection (opened 2026-07-30)

Follows `tasks/rl-situation-report.md` §8. The user approved the recommended sequence.
Discipline: A/B at equal wall-clock, ≥2 repeats (the #8 noise floor), independently
re-verify any near-record artifact (the retracted-127 rule), state prior results before
proposing a lever.

## Step 1 — Confirm the pitch/stubs structure off darkzig — **DONE for free (2026-07-30)**

- [x] Planned as a 2 h FR16 screen. **Not needed** — `output/roads-first/FR16|FR17|FR24-2026-07-07/probes.jsonl`
      (2,444 comb-family probes, 3 cities) already carry full `params`. Stratified
      *within-k-level* so "SAT lives at loose k" can't fake a signal:
      - **FR16:** `spacing` 3–4 → **0 SAT / 292**; `spacing` 5–7 → **7 SAT / 308**.
        `stubs=True` 1.68 % vs `False` 0.41 % (same 4× direction as darkzig's 2.8 %/0.6 %).
      - **FR17:** `spacing` 3–5 → **0 SAT / 189**; `spacing` 6 → 2 SAT / 52. Same direction,
        n=2 SATs (weak). `stubs` null here (1 vs 1).
      - **FR24:** 0 SAT at any k in 1,047 probes → uninformative, excluded.
      **Verdict: the structure generalises across cities AND across families** (comb `spacing`
      is the analogue of lane `pitch`). Gate passed on zero compute.
- [x] **Unplanned finding A — `mode` is a third free bit.** Pooled FR16+FR17:
      `mode=alternate` holds **9 of 9 SATs** (7/250 and 2/117); `mode=both` is **0 SAT / 528**.
      Never recorded before. Comb-only parameter.
- [x] **Unplanned finding B (the important one) — every knob's best value is the boundary of
      its hardcoded range.** darkzig lane SAT rate rises monotonically with pitch
      (0/0/0/0/1.0/3.2/**6.2** % for pitch 5→11) and `generate_lane_patterns` stops at 11.
      Comb `spacing` stops at 7, where FR16 sits at 93 % UNKNOWN. Coherent mechanism across
      both families and 3 cities: **the productive skeletons have FEW, LONG branches** —
      ↑pitch, ↑spacing and `alternate` (which halves the branch count) all do the same thing.
      Measured: extending pitch to 12–24 yields **93,284 additional patterns per k** on darkzig
      — more than the entire currently-enumerated population (67,308) — in a range never probed.

## Step 1b — Unlock the truncated pitch range (NEW, cheapest lever, do with Step 2)

- [x] `foeopt/roads_first.py`: `generate_lane_patterns(..., pitches=None)`, default `None` →
      today's exact `LANE_PITCHES = (5,…,11)`. Opt-in, byte-identical when unset (the
      `reach.py`/`--lns` precedent). 3 tests: default output identical with/without the kwarg,
      restriction to the requested values, and — the `max_lane_len` lesson — that widened
      pitches produce topologies the default range **cannot** (`novel_total > 0`), so this is a
      real treatment and not another sampling filter.
- [x] **Pre-flight scoring of the widened population** (no CP-SAT, 2 min): the new range is
      where the anchor-rich skeletons live. Fraction of patterns scoring above the 98-road
      record's own `opts_total` (12,578), k=105: pitch 10 → **3.6 %**, pitch 11 → 11.2 %,
      pitch 12 → **22.6 %**, pitch 15 → 18.3 %, pitch 16 → **20.6 %**, decaying to 0 % by 24.
      Max score reachable rises from 13,755 (pitch 11) to **14,129** (pitch 15) — the widened
      range contains skeletons strictly more anchor-rich than anything ever probed. The curve
      is unimodal with an interior peak at 15–17, so **the default range sat entirely on the
      rising flank.** `prefilter()` rejects **0** of the top-2000, so none of this is
      arithmetically dead.

## Step 2 — `opts_tot` population prefilter + uniform sampling inside survivors

- [ ] `foeopt/skeleton_score.py`: pure-stdlib bitset scorer for
      `opts_tot = Σ_b |road-adjacent, all-free anchor positions|` — the quantity `probe()`
      already computes and discards. Python-int row bitmasks + shift/AND, grouped by distinct
      footprint size. Target ≥100× faster than the 0.37 s/pattern reference loop, since the
      population is ~160 k patterns per k, not 700.
- [ ] **Oracle-equivalence test** against `sum(len(_anchor_candidates(...)))` on random
      patterns/regions — the `reach.py` discipline. A scorer that disagrees with the thing it
      approximates is worthless.
- [ ] `scripts/exp_wide_skeleton_screen.py`: `--pitches`, `--prefilter-top Q` (score the whole
      population, keep the top Q fraction, then **sample uniformly inside it**).
      ⚠️ **Not rank-and-take-the-top:** among SATs, `opts_tot` correlates with `achieved` at
      Spearman **+0.50** (wrong sign) and a top-5 % cut would have missed the 98-road record
      (rank 26/320 = top 8.1 %). Loose cut + uniform sampling inside is the measured-safe design.
- [ ] Prior art stated: next-things #1 (score-threshold pruning) and Track C-bis Stage 1 both
      closed null, but both ranked *inside an already-uniformly-sampled 200*, which
      `_probe_levels_batch` then probes in full — a no-op by construction. This lever changes
      **which patterns are drawn from the 160 k population**. Different lever, never tested.

## Step 2 gate — **PASSED; record 98 -> 95 (2026-07-30)**

Gate was: SATs/core-hour >= 3x baseline AND `min(achieved) <= 98`, vs the recorded 98-road run
(1400 probes / 72.8 core-h / 20 SATs / min 98), which was reused rather than re-run.

| arm | config | probes | SAT | SAT% | SAT/core-h | best achieved |
|---|---|---|---|---|---|---|
| A (recorded baseline) | default pitch, no filter | 1400 | 20 | 1.4% | 0.27 | 98 |
| B1 | + `opts_total` top 10% | 300 | ~25 | ~8% | ~1.1 | 98 |
| B2 | + pitch 12-18 | 300 | **242** | **80.7%** | **~19** | **97 (NEW RECORD)** |

- [x] **97 roads, independently verified LEGAL** — `route()`=97, `exact_route()`=**97 OPTIMAL**,
      `is_valid` True, `rotated_buildings`=0, 0 overlaps, 224/224 placed. Preserved at
      `docs/records/darkzig-97-roads-lane-k106.json`. From **pitch 17** — six steps outside the
      generator's old ceiling of 11. B2 returned **zero UNSAT** in 300 probes.
- [x] Both arms independently re-found 98 as well (different k, different pitch ranges), so the
      record is reproducible rather than a single lucky draw.

## Step 3 — quality filter + seed-polish

- [x] **`mean_free_adjacency` shipped in `foeopt/skeleton_score.py`** with `--quality-top`
      (applied after `--prefilter-top`, uniform sampling inside the survivors).
- [x] **Tuning measured, and it has an interior optimum** — by mfa quintile: SAT rate
      36/93/98/84/100 %, median achieved 102/102/104/106/106. The *tightest* skeletons are
      harder to pack, so the bottom decile is the wrong cut; **quintile 2 is the sweet spot**
      and is where the 97 came from (mfa 1.9717). Run C uses `--quality-top 0.4`.
- [x] Run C: 300 probes, 224 SAT (74.7%), 0 UNSAT, median 102, **129 layouts at <=102**
      (baseline had 7 in 1400 probes). Best 97 from the screen.
- [x] **Seed-polish on C's 12 sub-100 targets: 6 improved, best 99 -> 95.** New all-time record,
      verified (`route()`=95, `exact_route()`=95 OPTIMAL, `is_valid`, rotated=0, 224/224,
      0 unsatisfied). `docs/records/darkzig-95-roads-lane-k105.json`. **120% road efficiency**
      vs the Sigma/2=114 estimate.

## Step 4 — quality model: **PASSED (2026-07-30)**

`scripts/exp_quality_model.py`, pre-committed bar |rho| >= 0.4 on held-out SATs:

| feature | rho(train) | rho(holdout) | |
|---|---|---|---|
| **mean_free_adj** | +0.711 | **+0.639** | PASS |
| th_x | +0.396 | +0.413 | PASS (one-city artifact — no mechanism, do not ship) |
| opts_total | +0.156 | +0.073 | |
| pitch / stubs / trunk_len / deg* | | all < 0.28 | |

Independently re-confirmed on the **baseline** run (default pitch, no prefilter, the dataset that
produced the 98): rho = **+0.760**, with a near-perfect split — lower half by mfa
`[98,99,99,101,101,101,102,102,102,103]`, upper half `[103,105,105,106,106,106,106,107,108,108]`.
**This was the gate that decided whether RL on the real objective is possible at all. It passed.**

## Step 5 — skeleton-generation RL: unblocked, but the case for it is now WEAKER

Step 4 passed, so a real objective surrogate exists — the precondition RL was gated on. But the
same finding cuts against it: if a single microsecond geometric statistic captures the objective
at rho 0.76, the cheap move is to **filter and sample with it** (done, Step 3) rather than train
a policy to rediscover it. RL's remaining distinct value is **escaping the comb/lane families
entirely** via cell-by-cell skeleton generation — searching *within* the family is now handled.

- [ ] Decide only after run C + seed-polish report how far the two-filter screen goes on its own.
- [ ] If pursued: cell-by-cell MDP (every partial state a valid connected skeleton, so M2-M4's
      invalid-action trap cannot recur), reward = `mean_free_adjacency` surrogate, CP-SAT
      verifying the top-N proposals only. GFlowNet preferred over PPO (want diverse
      high-reward samples to feed CP-SAT, not one mode).
- [ ] Hazard to respect: the surrogate is fitted **only on comb/lane skeletons**, so it is
      out-of-distribution on exactly the novel topologies RL would exist to find.
