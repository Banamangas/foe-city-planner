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

## Step 5 — skeleton-generation RL: reopened on headroom, **CLOSED AGAIN on mechanism (2026-07-31)**

Step 4 passed, so RL finally has what it always lacked: free feasibility and a validated
in-distribution reward (`mean_free_adjacency`, rho **+0.825** *within* the grammar it would
operate in). The case still fails, because both places it could search were measured and
neither holds enough to justify training anything.

- [x] **Outside comb/lane — almost nothing is feasible.** OOD check: 21 generators, ~54,000
      novel candidates. Only `scatter` is feasible at all (best 103 vs record 95); the corrected
      in-band generator returned 0 SAT / 240. The binding constraint is **spatial coverage**, and
      comb/lane are near-optimal solutions to it. See the OOD entry in `tasks/lessons.md`.
- [x] **Inside the grammar — the headroom is ~1 road.** Test 1 (`exp_nonuniform_lanes.py`):
      lifting uniform pitch + balanced growth gives 229 SAT / 234 probes (97.9%), best 97,
      polished to **96** — against a 95 baseline the cheap pipeline already reaches in ~11
      core-hours with no training. Verdict SATURATED.
- [x] **Perturbation/diffusion around good skeletons is dead:** 0-for-64.
- [x] **The one open door — RUN, and it overturned the closure:** test 1's arms were unmatched — the 95 used the
      `mean_free_adjacency` quality filter, the non-uniform run did not. A matched re-run
      (non-uniform + `--quality-top`) is one screen. If it dips below 95, headroom returns and
      guided search over per-branch parameters becomes interesting again. Until then: closed.

~~**Recommendation: RL stays closed.**~~ **SUPERSEDED 2026-07-31.** The matched re-run (the
"open door" item below, which I should have run before committing the closure) reached **94** —
a new record, verified. So headroom inside the grammar is real, and all four conditions for a
guided search now hold simultaneously: ~10^19 space, 47% SAT feasibility, rho +0.825 in-grammar
reward, and measured headroom. **RL was reopened** on that evidence — then closed again on mechanism, measured rather than
argued: **within the productive band nothing predicts `achieved`** (106 in-band SATs, all
|rho| < 0.22 across nine features). `mean_free_adjacency`'s rho +0.825 was the *band* effect; it
is a **classifier, not a gradient**, and is flat (-0.147) inside the band. There is no surface for
a bandit/CEM/policy to climb — the residual variance is CP-SAT seed luck, which `seed_polish`
already exploits. **The learnable structure is a filter, and it is now one integer test
(`losses - 2c in {3,4}`) shipped in `foeopt.roads_first.quality_index`.**
See the two 2026-07-31 entries in `tasks/lessons.md`.

## Multi-city generalisation (2026-07-30) — it transfers, with a measurable boundary

- [x] **FR16: NEW RECORD 76 roads (was 79)**, six distinct layouts, verified
      (`exact_route`=76 OPTIMAL, 89/89, rotated=0, 116% efficiency). Found in **14 probes**;
      the old 2h comb run needed its full budget for 79 and left k=84 INCONCLUSIVE — this
      grammar produced 47 SATs at that k. `docs/records/fr16-76-roads-nonuniform-k84.json`.
- [x] **FR24: 0 SAT / 135**, all UNKNOWN, 11.3 core-h. Probed k=205/220/235 (never tried; the
      old run's k=246-266 leaves 2-22 free cells for 76 fillers). Undecided, not refuted.
- [x] **The limit is ROAD PRESSURE = Sigma(short)/2 / (region − building_area)**, not fill or
      slack: darkzig 0.40 and FR16 0.43 work; FR24 0.89 does not — despite darkzig (89.6% fill)
      and FR24 (90.2%) being nearly identical on fill and region size. Computable in
      microseconds *before* any solver time.
- [x] **New failure mode: `SAT_FILLER_FAIL`** — 34% of FR16 probes place every consumer and then
      cannot fit the filler buildings. Worsens with k. "Consumers place" != "usable layout".
- [ ] **Confounded at n=3:** FR24 has both 0.89 pressure and 2.3x the consumers; probe time
      scales 36s -> 95s -> 301s, which smells like CP-SAT model size. Separating them needs a
      synthesised city via `make_real_like_city` (many consumers + low pressure, or the reverse).

**Practical boundary on current evidence:** ~60-80 road-needing buildings, road pressure <= ~0.5.
That is whether it WORKS; whether it is WORTH running is a separate axis — darkzig went 250 -> 95
(46% -> 121% efficiency) precisely because it started badly built.


## Track F productionisation (2026-07-31) — shipped, opt-in, defaults unchanged

- [x] **`generate_nonuniform_patterns`** in `foeopt/roads_first.py`: the family holding the
      records on both cities (darkzig 94, FR16 76). Its space is ~10^19 so it SAMPLES rather than
      enumerates — documented, and the band filter is applied *during* generation.
- [x] **`quality_index()`** — `losses - 2c`, the derived k-normalised band filter. Replaces the
      bottom-slice cut: SAT rate 46.7% -> 69.6% at equal quality, and the screen alone reached 94
      where the bottom cut needed a 496-solve polish pass.
- [x] **`RoadsFirstSearch`** accepts `pattern_family="nonuniform"`, `quality_index_band`,
      `lane_pitches`. **`webapp/params.py`** exposes all three; `runner.py` translates the UI
      strings. Defaults unchanged (`comb` / `off` / `off`) — zero behaviour change when unused.
- [x] **Time-box question resolved by measurement:** `opts_total` needs 239 s for a 160k
      population and cannot fit a 60-120 s budget; the band predicate needs 15 s materialised and
      is effectively free applied during generation. **Production uses the band, not the scorer.**
- [x] **`road_pressure()` / `screen_city()`** in `foeopt/bounds.py` — microsecond instance screen,
      explicitly marked heuristic-not-bound. Would have declined FR24 before 13 core-hours.
- [ ] **Not done:** `screen_city` is not surfaced in the webapp UI; no end-to-end timing run of
      the nonuniform family inside a real 60-120 s box; `SAT_FILLER_FAIL` (34% of FR16 probes)
      still untreated.

---

# Overnight plan — 2026-08-01 02:35 → ~09:00

Autonomous run while the user sleeps. No blocking questions are possible, so
every judgement call is recorded here with its reasoning.

## Governing constraints

1. **Serialize everything.** CP-SAT budgets are wall-clock, not CPU time, so two
   experiments running at once inflate each other's UNKNOWN rate and understate
   SAT rates. Measured earlier this session: FR16 went 2.7-3.1 -> 4.2 probes/min
   simply by killing the competing job. One driver, one experiment at a time.
2. **All code and tests land BEFORE the first measurement.** The suite is 74 s
   multi-core; running it mid-experiment would bias that experiment. After
   launch: monitoring only.
3. **Smoke-test every experiment at a tiny budget first.** Four filler
   experiments were wasted earlier this session by launching before checking the
   harness. Not repeating that.
4. **Equal wall-clock A/B.** Arms differing in budget are not comparable.

## Phase 1 — code, tests, commit (02:35-03:30)

- [ ] 1a. `modes` lever for the comb family. `generate_patterns` hardcodes
      `for mode in ("both", "alternate")`; there is no way to select one, so the
      9/9-vs-0/528 lead is currently untestable. Opt-in, byte-identical when
      unset (same shape as `lane_pitches`).
- [ ] 1b. `SAT_FILLER_FAIL` visibility. `_place_fillers` already returns the
      unplaced list and never exits early, so "placed N of M" exists and is
      thrown away. Surface it so such a run stops looking like "found nothing".
- [ ] 1c. Overnight driver `scripts/run_overnight.sh` — strictly sequential.
- [ ] 1d. Smoke-test each experiment at ~30 s budgets.
- [ ] 1e. Full suite + commit.

## Phase 2 — measurements, strictly serial (03:30-09:00)

| # | experiment | why | budget |
|---|---|---|---|
| E1 | `alternate` vs `both`, comb, FR16 + FR17 | 9/9 vs 0/528 in existing logs, never exploited | 4 x 600 s |
| E2 | family x city: {comb, nonuniform, nonuniform+band} x {darkzig, FR16, FR17} | BEST_PRESET hard-codes `nonuniform` on n=2 and FR17 contradicts it -- the biggest live correctness risk in what shipped | 9 x 900 s |
| E3 | `k_start` margin sweep, nonuniform, FR16 + FR17 | `K_START_MARGIN["nonuniform"] = -4` is calibrated on two cities, its sign reverses on the third, and it decides where the whole budget is spent | 8 x 600 s |
| E4 | box sweep 30/45/60 s on darkzig, 3 repeats | 60 s already reached the same 101 as 120 s; the default box may be longer than needed | ~20 min |
| E5 | polish path end-to-end at a 600 s box | only "correctly does nothing at 120 s" is verified end to end; the reserve arithmetic is unit-tested but never exercised | 2 x 600 s |

Total ~5 h 15 plus overhead.

**FR24 deliberately excluded**: 0 SAT in 1182 probes across two prior campaigns,
so its expected value per hour is far below everything above. Stays open in
`remaining-work.md`.

## Decisions made without being able to ask

- **Cities**: darkzig, FR16, FR17. The user's own city is excluded -- it screens
  UNLIKELY (road pressure 1.08) and the search cannot produce layouts for it.
- **E2 at 900 s not 600 s**: FR17 needed 600 s to produce its negative result at
  all; 900 s lets each arm be beaten fairly rather than by budget starvation.
- **On error the driver logs and continues** to the next experiment rather than
  aborting the night.
- **No default changes while the user sleeps.** The runs produce evidence; the
  decisions wait for them.

## Review

(filled in as results land)

---

# Level budget allocation — 2026-08-03 (overnight, autonomous)

## Diagnosis: three defects, not one

**D1 — no per-level budget cap.** `level(k)` probes every surviving pattern with
no bound but the walk deadline. Measured on FR17 at k_start=117: the first level
probed 35/35 patterns at probe_limit=90 across 6 workers = **up to 525 s of a
600 s box on one level**, which then came back INCONCLUSIVE. Everything after it
got 1 probe or zero.

**D2 — batch payloads are grouped by level.**
`[(pat, k, idx) for k in ks for idx, pat in ...]` hands the pool all of k1's
patterns, then all of k2's. `imap_unordered` consumes roughly in order, so a
"concurrent" batch still drains level by level — contradicting the function's own
docstring ("instead of draining one level's ~200 patterns before the next
level's are even generated"). Generation was made concurrent; probing was not.

**D3 — UNDERSAMPLED is treated as a refutation by the control flow.** Descent
`break`s when no level is FEASIBLE; ascent jumps to `max(batch_ks)`. Both discard
levels that were never probed. Currently masked because UNDERSAMPLED only arises
at the deadline (so the run is ending anyway) — but it becomes live the moment D1
is fixed, because then levels stop early with budget still on the clock.

## What I will and will not do

**Do:** D2 unconditionally (it is a bug against stated intent, no policy in it).
D1 + D3 behind `level_slice_frac`, default None = today's behaviour exactly.

**Not do:** a bidirectional walk, and any re-tuning of `K_START_MARGIN`. Both are
separate changes and would confound this measurement.

**Arbitration on the risk:** capping the first level is NOT free. At record k
feasibility is ~1%, so fewer probes at a genuinely feasible level can lose the
SAT that produces the good road count. This must therefore be measured on cities
where k_start is RIGHT (does it hurt?) as well as where it is WRONG (does it
rescue?). A change that only ever helps the broken case is not worth shipping if
it degrades the healthy one.

## Overnight A/B

Arms (equal 600 s boxes, per-city probe_limit as calibrated 2026-08-01):
  baseline            — current behaviour
  interleave          — D2 only
  slice0.35 / slice0.5— D2 + D1 + D3 at two fractions

Cells: {darkzig, FR16, FR17} x {default k_start, deliberately-wrong k_start}.
The wrong-start arm is the point: robustness to a bad start is what this buys.

Adopt only if: no city regresses at its default start, AND at least one
wrong-start case improves.

# Placement objective — 2026-11-11 (overnight, autonomous)

Evidence: `tasks/analysis-2026-11-11.md`. A hinted objective (minimize the skeleton cells
actually needed) beat every stored record in 120 s per skeleton (darkzig 90, FR16 71).
The 2026-07-21 study that closed this lever used a degenerate proxy (P2 == k).

- [ ] `probe(..., objective_limit=)`: after a SAT, re-solve the one-hot objective model hinted
      from the SAT placement; return both placements; default 0 = byte-identical behaviour
- [ ] `_run_probe`: validate both, keep the better LEGAL layout; clamp objective_limit to
      probe_limit (budget-defect class, lessons 2026-07-31)
- [ ] `RoadsFirstSearch(objective_limit=)` + webapp option + CLI flag (off by default)
- [ ] pass `fillers=` to `prefilter` in production (shipped-but-dead check)
- [ ] tests: needed-closure correctness on a toy, objective never worse than feasibility,
      off == unchanged
- [ ] A/B at equal 600 s boxes, strictly sequential: {darkzig, FR16, FR17} x {off, on} x 2
- [ ] Regenerate + verify any record (exact_route, is_valid, rotated 0, all placed), docs/records
- [ ] Adopt in BEST_PRESET only if: no city worse at either repeat, and >= 1 city better

## 2026-11-11: game rules confirmed by the user (two-lane roads, chains)

Rules (also in memory `foe-game-rules-roads-chains`):
- A `road_level == 2` building needs a two-lane path **all the way to the TH**, and two-lane
  tiles are 2x2. It may also be left unconnected (to be offered as an option).
- Chain buildings must sit at the catalog `linkPositions` (an offset rectangle from the
  previous building's top-left). darkzig: Statue d'honneur 4x3 plus 6 Route vers la victoire
  2x3 in a straight row to the right, which makes a rigid 16x3 block where only the statue
  needs a road. The serpent statue chain has its link *behind* (y-2).

Every darkzig record breaks both rules. FR16/17/24 and the user city have no level-2 consumers
and no chains (the FR exports DO carry the catalog, so this is real, not undetected).

Plan (check in before building):
- [x] **Validator first.** `is_valid` / verify fail on (a) a level-2 consumer without a
      2x2-tile two-lane path to the TH, and (b) a chain not at its linkPositions. Re-score
      every record and mark the darkzig ones as non-compliant.
- [x] **Chains as composite blocks.** In the loader, merge each linked chain into one rigid
      composite footprint: road border only on the parts that need a road, and parts
      unpacked on output. The position model treats a composite as one more size class
      with a custom border. No new solver machinery is needed.
- [x] **Two-lane path.** Pick the military building's spot and a 2-wide road corridor to
      the TH as part of the skeleton: one skeleton branch is drawn 2 wide, and the level-2
      building's anchors are restricted to that branch. The router emits the 2x2 tiles.
      Option `military: connect | unconnected`. With unconnected, it is treated as a filler.
- [x] A/B darkzig with the rules on, then publish the new compliant baseline record.

### Review (2026-11-11)
darkzig, BEST_PRESET verbatim, 600 s, 3 sequential reps, all rules on: **92 / 90 / 92**, every
result `valid` under `foeopt/legality.check` with the count matching the saved network. Record:
`docs/records/darkzig-90-roads-legal-rules.json` (tile at (35,44) touching the TH, chain intact).
This is the first legal darkzig baseline. The legacy 87 broke both rules, so the two are not
comparable. Also done: the review's shared-incumbent/deadline fix, a verifier that checks the
saved network, the webapp legality verdict, and roads serialized with their levels.

## 2026-11-11 (evening): plan after Codex's next-model-speed-quality review

Source: `docs/superpowers/plans/2026-11-11-next-model-speed-quality.md`, plus the open items
of the follow-up / app reviews. Its prerequisites (one incumbent, a shared deadline, a
legality gate, a verifier that checks the saved network) are done and merged. Its "no
tests / no heavy CPU" restriction was an instruction to Codex, not to this repo, so the
measurements below get run.

**Assessment of Codex's tasks**
- T0 profiling: yes, and first. Since the position model, the time split is unknown
  (probes went from 30 s to under a second), so T2A/T3 are guesses until measured.
- T1 road witness: cheap, but expect a small gain. `exact_finish` already reroutes the
  final layout optimally over all free cells, which is a superset of the witness. The
  witness can only help BEFORE filler packing (a smaller network leaves more room).
  T0 will log objective value against greedy route() to size it first.
- T2A geometry reuse / T3 filler scan: only if T0 shows construction or packing is a
  real share of the time.
- T2B complete hints / bound: a cheap flag, but measure it alone.
- **T4 rebased polish: the most promising quality lever.** On the legal darkzig 90 the
  skeleton had k=115, so about 25 skeleton cells sit unused yet still block consumers.
  Polishing on the accepted network frees them, from a known feasible start.
- T5 optional-road neighbourhood: high potential, high risk. Only once T4 plateaus,
  under Codex's caps.
- **Missing from the Codex plan:** the cities that still FAIL (the user's 97%-full city
  and FR24) need fillers inside the model plus the k_max boundary fix. For the user,
  that is worth more than −2 roads on darkzig.

**Plan (one change per commit, each A/B'd before it becomes a default)**

Phase A: correctness and app (small, low risk)
- [x] App P1s: city/job identity (city A cannot update or save into B), job admission
      control, final report and errors reach the UI, split upload keeps helper_data,
      the best-preset button resets to defaults before applying, OverflowError in
      numeric parsing.
- [x] Walk: k_start == k_max with an UNDERSAMPLED level keeps probing (bounded retries
      and descent) instead of FAMILY_TOO_WEAK at 0.3x the box. Fake-level test.

Phase A result: done on `fix/phase-a`. Live server check: a second submit gets 409, an
unknown stream 404, every improvement carries its legality verdict and two-lane cells,
and the final envelope is `done`/98/valid. User city: wall 90 s -> 241 s of a 300 s box,
still no layout (at k=145, 65/200 skeletons probed, none placed the road-needing
buildings). That moves Phase D ahead of C for this city.

Phase B: measure (T0)
- [ ] Per-phase timing: generation, anchors, model build, solve, route, fillers, repair,
      objective, validate. Also time to first valid incumbent, objective value against
      route() count, and a manifest (git rev, input hash, effective options, rules version).
- [ ] Baseline: literal BEST_PRESET at 120 s and 600 s on darkzig, FR16, FR17, 2 reps,
      plus user/FR24 at 600 s. Sequential.
- [ ] Decide T2A/T3/T1 from the numbers.

Phase C: quality (T4, with T1 as its building block)
- [ ] T1: return the objective's selected roads; witness checker; evaluate witness and
      greedy route as two candidates (greedy first, witness on capped remaining time).
- [ ] T4: polish on the accepted network (pattern = actual roads + TH, max 2 solves inside
      the objective-polish reserve; strict improvement after full legality). Two-lane
      tiles and chain composites stay frozen at first.
- [ ] A/B against the current preset, 4 paired reps, 120 s and 600 s.

Phase D: dense cities (the user's city, FR24)
- [ ] Fillers as position classes without road contact (behind a flag), first on toy and
      exact cases, then the user city and FR24 at 600 s, against exact repair at equal budget.

Phase E (only if C plateaus): T5 bounded optional-road spike under Codex's caps.

Adoption rule as before: no validity regression, no city worse in any pair, failures
counted, and long-run-only wins become a long-run profile rather than the default.

## 2026-11-11 (night): "use the leftover box" deepening -- PAUSED (user restart)

Branch `feat/deepening` (from `exp/probe-limit`, not merged, not pushed).
`deepen=True` (off by default; A/B arm `deep10` = probe_limit 10 + deepen):
after the k-walk settles, each round re-solves the best-roads level and the
bound, then sweeps INCONCLUSIVE/UNDERSAMPLED levels below (plus a newly opened
k-1) on fresh skeletons, limit x3 per round (10 -> 30 -> 90 s cap).

| FR17 600 s | result | note |
|---|---|---|
| preset | 103, 103 | the bar (rule: never worse in any pair) |
| v1 a2baaac | 105, 105 | slice sized by base 10 s limit -> every 90 s round UNDERSAMPLED |
| v2 c661699 | 104, 104 | slice fixed + re-solve best/bound; still improving at walk end, ended 0.70x |
| v3 5191759 | 104, 105 | borrows the objective-polish reserve (keeps 30 s); box now used (0.94x) but no gain -> more time alone does not reach 103 |

v1 at 120 s was never worse than the preset (darkzig 91,90 vs 94,94; FR16 68;
FR17 106,103 vs 106,106); v1 at 600 s darkzig 91,90 (preset 91,92), FR16 68.
Data: `scripts/_deepen_ab.jsonl` (v1), `_deepen_ab_v2.jsonl`, `_deepen_ab_v3.jsonl`.

Next when resuming:
- [x] v3 did NOT reach 103 (104, 105). Deepening is not adopted; keep it off by default.
- [ ] Next idea: give the re-solve of the best level a longer objective limit than the
      probe limit, or re-solve the best level's recorded SAT candidates (objective polish
      seeds) with 90 s instead of fresh skeletons.

## 2026-11-12 overnight: using the leftover box -- results

All runs legal, strictly sequential, 2 reps, branch `feat/deepening` (not merged).
Preset reference (BEST_PRESET, earlier today): 600 s darkzig 91,92 / FR16 68 / FR17 103,103;
120 s darkzig 94,94 / FR16 68 / FR17 106,106.

| arm (600 s) | darkzig | FR16 | FR17 | 120 s darkzig / FR17 |
|---|---|---|---|---|
| deep10 v1-v3 (10 s walk + deepening) | 91,90 | 68 | 105 / 104 / 104-105 | 91,90 / 106,103 |
| deep30 (preset + v3 deepening) | 90 (rep1 killed) | 68 | **106,106** | - |
| deep10r (retry timed-out skeletons) | 90,91 | 68 | 105,105 | 93,91 / 106 |
| fill (polish more stored candidates) | 91,90 | 68 | 103,103 | **92,92** / 106 |
| fillw (fill, store 40) | 91,90 | 68 | 103,103 | 96,92 / 106 |
| pl10fw (10 s walk + fillw) | 91,92 | 68 | 105,105 | 92,91 / 106 |
| harvest (fillw + fresh skeletons at the best levels, each polished) | 92 (v1), 91, 91 | 68,68 | 103,103 | - |

Findings:
1. **FR17's 103 is made by objective polish**, not by the walk (k=116 skeleton 106 -> 103
   in ~70 s, all threads). Phase B's "polish ~0%" was a profiling blind spot (corrected in
   phase-b-baseline.md, lesson added). Borrowing the polish reserve (deep30) cost 3 roads.
2. **Deepening is dropped** (4 variants): no variant reaches 103 on FR17 at 600 s.
   The 10 s walk never visits FR17's good k=116 skeletons.
3. **A 600 s FR17 run finds only ~10 distinct SAT skeletons**; each polish solve is proven
   optimal in < 1 s. The leftover box can only help by producing MORE SAT skeletons near
   the best levels -> `objective_polish_harvest`.
4. darkzig 120 s varies by +-2 between identical arms (fillw 96 vs 92), so single darkzig
   pairs at 120 s are not evidence either way.
5. **Harvest uses the whole box (0.98x) but gains nothing**: one round per run (3 levels x
   ~200 skeletons at 30 s), 3-8 new SAT skeletons, none better than the incumbent. v1 crashed
   on 3/6 runs ("Pool not running": the walk can leave the pool dead) -- fixed in 5ce20ba,
   v2 clean.

**Verdict.** Nothing tonight beats the preset at 600 s. FR16 (68) and FR17 (103) look like
plateaus for these skeleton families; darkzig moves only within its run-to-run noise.
"Use the leftover box" is not worth more effort: the time is idle because the search has
nothing useful left to try, not because the controller stops too early.
- `fill` is free and never worse (could be switched on; not adopted, no clear gain).
- deepening / deepen_retry / harvest stay in the code OFF by default (documented knobs),
  or can be removed before merging -- the user's call.

**Next (higher expected value):** the walk's skeletons, not its time: Codex T1 (keep the
solver's road witness; darkzig routes ~1.3 roads above the objective in 70% of solves),
Phase D (fillers in the model, user city), and an FR24 skeleton-family study.

**Decision (2026-11-12, user: "go with your recommendation"):** the null-result knobs
(deepen, deepen_retry, objective_polish_fill/keep, harvest) were removed before merging; their
code stays in history at 5ce20ba for reference. Kept: polish rows' `solve_s`, the A/B rows'
level statuses, all data, the docs corrections and the lesson.

## 2026-11-12: Codex T4 -- rebase polish on the accepted road network

**Hypothesis.** Objective polish makes FR17's record, but it re-solves on the ORIGINAL
skeleton, whose every cell blocks consumers -- including cells the accepted network no
longer uses (k=116 skeleton vs ~103 kept roads). Re-solving on the incumbent's actual roads
frees those cells as consumer anchors and starts from a known-feasible placement.

**Design** (`foeopt/incumbent_polish.py`, off by default, `rebase_s=0`):
- [ ] `rebase_pattern(incumbent)`: Pattern(th = incumbent TH, roads = its saved road cells).
- [ ] `incumbent_positions(search_layout, incumbent)`: consumer + composite-chain positions
      (composite = member position - offset) and the two-lane tile ("lane2:0").
- [ ] `hint_is_feasible`: every consumer has contact with a TH-reachable road, no overlap.
- [ ] `polish_rebased(...)`: position-model minimize_needed on the rebased pattern (all
      threads), validate (fillers repacked), accept only a strictly better routed count;
      rebase again after an acceptance, at most 2 solves, stop on a repeated road set.
- [ ] Budget: `rebase_s` seconds are taken from the END of the objective-polish window
      (plus whatever polish leaves unused); runs before exact finish. Same deadline, no
      extra time.
- [ ] Report in result["rebased_polish"]: attempts, per-solve before/after, solve_s.
- [ ] Tests: rebased pattern = incumbent roads; vacated skeleton cells become anchors;
      composite/lane hints; never publishes worse; no-op when no time.
- [ ] A/B arm `rebase` (preset + rebase_s=60) vs preset, 600 s then 120 s, 2 reps,
      darkzig/FR16/FR17. Adopt only if never worse in any pair and better in one.

**Result (2026-11-12): ADOPTED** -- BEST_PRESET `rebase_s: 20`. 12-cell A/B, all legal:

| | preset | preset + rebase_s=20 |
|---|---|---|
| darkzig 600 s | 91, 92 | **89, 89** |
| FR16 600 s | 68, 68 | **67, 67** |
| FR17 600 s | 103, 103 | 103, 103 |
| darkzig 120 s | 94, 94 | **88, 91** |
| FR16 120 s | 68, 68 | **67, 67** |
| FR17 120 s | 106, 106 | 106, 106 |

Never worse, better in 8/12. Each rebase solve 0.3-14 s; it ran before exact finish and
never skipped for lack of time. Records: darkzig 88 and FR16 67 (rebased from the saved
records, verified from file). FR17 does not move: its rebased solve proves the same 103.
Data: `scripts/_rebase_ab.jsonl`. Exposed as option `rebase_s` (webapp, CLI `--rebase-s`).

~~Observed: darkzig's verify re-route sometimes beats the accepted count.~~ **Not real**
(checked 2026-11-12): the verify re-routes ignored the 2x2 two-lane tile, which is illegal
(`two_lane_not_2x2`). With the tile kept, exact_route proves the delivered count optimal
(darkzig 88, FR16 67). Both verify scripts now keep the tile. Next: Codex T1.

## 2026-11-12: Codex T1 -- keep the objective's road witness

**Hypothesis.** `minimize_needed` selects a TH-closed road forest (`needed[c]`) but returns
positions only; `validate` then greedy-routes. Phase B saw darkzig route ~1.3 roads above the
objective in 70% of solves. Caveat to check first: the objective omits 2x2 tile cells that lie on
the skeleton but are not `needed`, so part of that gap may be counting, not routing.

- [x] Measure first (36 objective solves, 10 s each, same placement for both networks):
      darkzig 2/20 smaller (by 3 and 2), FR17 1/8 (by 1), FR16 0/8; the witness is NEVER larger
      and always legal. Mean gain 0.25 roads/solve on darkzig, not 1.3: most of the Phase B gap
      was the objective not counting the 2x2 tile cells that sit on the skeleton.
- [x] `minimize_needed` puts the selected cells in `diag["witness"]` (both models; only on SAT).
- [x] `validate(..., witness=)`: legal pruned witness network as a second candidate; try the
      smaller network first, fall back to the other if fillers fail; greedy wins ties.
- [x] Wire into worker objective, objective polish, rebased polish (flag `road_witness`).
- [x] Tests (tests/roads_first/test_road_witness.py, 9 tests); 648 passed.
- [x] A/B `witness` vs `rebase` (current preset): 600 s witness-only against this morning's
      `rebase` rows (identical code with the flag off), 120 s both arms paired; 2 reps,
      darkzig/FR16/FR17. Data `scripts/_witness_ab.jsonl`.

**Result (2026-11-12): ADOPTED** -- BEST_PRESET `road_witness: True`. All 18 runs legal.

| | preset (rebase) | + road_witness |
|---|---|---|
| darkzig 600 s | 89, 89 | **88, 88** |
| FR16 600 s | 67, 67 | 67, 67 |
| FR17 600 s | 103, 103 | 103, 103 |
| darkzig 120 s (paired) | 89, 91 | 89, **89** |
| FR16 120 s (paired) | 67, 67 | 67, 67 |
| FR17 120 s (paired) | 106, 106 | 106, 106 |

Never worse, better in 3 of 10 pairs, all darkzig. Small, as the measurement predicted; darkzig's
120 s pair is within noise, the 600 s pair is consistent (88 = the record). No new record.

## 2026-11-13: next items after T1 (user: "merge it and proceed to the next items")

T1 merged to main (743c9b4). Order chosen: the dense cities first (FR24, user), since they
still get NO layout, which is worth more than a road on darkzig.

**Finding.** FR24's uploaded city is game-legal with 232 roads (user city: 142). Every
skeleton family has failed on FR24, but the uploaded city is a known feasible start. Rebased
polish from it:
- consumers only (fillers repacked): SAT_FILLER_FAIL, even with a 120 s exact repair;
- **fillers placed by the position model, hinted from where they stand: 232 -> 227, legal**
  (one 300 s solve, not proven optimal);
- user city: 142 -> 142 in 300 s (an expert layout; the rebase can only drop road cells).

**Phase D, built on `feat/fillers-in-model` (bce86a7), both off by default:**
- [x] `fillers_in_model`: filler size classes in `_position_model` (any anchor off roads/TH,
      no contact, the same per-cell at-most-one); probe, minimize_needed, objective polish
      and rebased polish pass them; validate keeps model-placed fillers and packs the rest.
- [x] `seed_input`: a legal uploaded city is the first incumbent (k = its road count) and gets
      rebased polish + exact finish, also on the FAMILY_TOO_WEAK path.
- [x] Tests: tests/roads_first/test_fillers_in_model.py (10); 657 passed.
- [x] A/B (`scripts/_phased_ab.jsonl`), 600 s, all legal:

| | preset (witness) | fill | seed | fillseed |
|---|---|---|---|---|
| darkzig | 88, 88 | **94, 94** | | |
| FR16 | 67, 67 | 67, 67 (0.98x box) | | |
| FR17 | 103, 103 | **105, 104** | | |
| FR24 | none | | **220** | 227 |
| user | none | | 142 (= input) | 142 |

  `fill` in the walk is REJECTED: bigger models, slower probes, worse on darkzig/FR17.
  `seed` alone: FR24 232 -> 220 in a 16 s solve, then its 2nd solve failed filler packing;
  `fillseed` is reliable but slow (one 176 s solve, 227).
- [x] Hybrid (e2edefb): rebased polish tries the fast solve first; on SAT_FILLER_FAIL it re-solves
      with fillers placed by the model. 658 passed.
- [x] A/B `seed` (preset + seed_input, with the retry) on all 5 cities, 600 s x2
      (`scripts/_seed_ab.jsonl`), all legal: darkzig 89,89 (witness arm 88,88), FR16 67,67,
      FR17 103,103, FR24 228,220 (rep0's fast solve failed fillers, retry ate the box),
      user 142,142 (= input). darkzig walk levels identical; the gap is in rebased polish
      (91->89 / 90->89 vs 90->88). Seed is a 250-road no-op there, so suspected noise.
      FR24 220 re-verified legal -> `docs/records/fr24-220-roads-seed-input.json`.
- [x] Paired darkzig witness vs seed, 600 s x2 (`scripts/_seed_pair_darkzig.jsonl`):
      witness 90,89 vs seed 89,88 -- the gap was noise. seed_input ADOPTED in BEST_PRESET.

# Optimization backlog for agents — 2026-11-16 (project review)

Source: a full review on 2026-11-16 (history docs, `foeopt/roads_first.py` audit, infra audit).
Nothing below is implemented or measured yet; every "expected" is a hypothesis.

**Where we stand (all legal):** darkzig 88, FR16 67, FR17 103, FR24 220 (seed only; no
skeleton family ever hosts it), user city 142 (= input). No useful lower bound exists
(`bound_adjacency` gives 21 on darkzig), so the optimality gap is unknown.

**What the evidence says about where the gap is:** incumbents are locally optimal (T5
windows up to 20x20: 0 gains, mostly proven), the leftover box has nothing to spend on
(deepening / fill / harvest: null), and solver-parameter portfolios sit at the noise floor.
The remaining quality is in **global skeleton topology** (what road networks the objective
is allowed to choose from). The remaining speed is in **scheduling** (idle workers,
killed in-flight work, sequential polish) and in **UNKNOWN probes** (46-61% of worker time
on FR16/FR17).

## Rules for every agent picking up an item

- [ ] Grep `tasks/lessons.md` for the lever first and quote the prior result in your notes.
- [ ] One item = one branch (`feat/<id>-...`) in its own worktree; new behaviour behind an
      option that is OFF by default; BEST_PRESET changes only after the gate.
- [ ] **Benchmarks are strictly serial on this machine** (16 cores, CP-SAT limits are
      wall-clock). Code and unit tests may proceed in parallel; timed runs must hold the
      bench lock from I1. Never run two timed runs at once.
- [ ] Gate: darkzig, FR16, FR17 at 120 s and 600 s, >= 2 paired reps, adopt only if never
      worse in any pair and better in at least one. darkzig is +-2 noise: paired runs only.
- [ ] Every result must pass `legality.check` (no rotation, two-lane tiles, chains) and be
      re-verified from the saved file; records go to `docs/records/` with provenance.
- [ ] Before calling a result negative: check the budget could detect the effect, and that
      treatment differs from control (set difference of skeletons / solutions).
- [ ] Write the verdict (adopted / null / refuted, with numbers) back under the item here,
      and a lesson in `tasks/lessons.md` if something was surprising.

## Suggested order

I1 -> (S1, S2, S3, C1 in parallel as code; benchmarks queued) -> Q1 -> Q2 -> Q3 -> Q4 -> rest.
I1 comes first because every other item needs its lock and its paired-run table.

---

## I — Infrastructure (unblocks parallel agents)

### I1. One benchmark harness with a machine lock  [S, do first]
- [ ] `scripts/bench.py --arm name=opt1,opt2 --cities darkzig,fr16,fr17 --box 120,600 --reps 2`:
      paired, sequential, takes `flock` on a lock file for the whole run, writes one JSONL
      row per run (commit hash, dirty flag, full options, seed, profile incl. parent phases,
      roads, legality) under `output/bench/<date>-<name>/`, and prints the paired table plus
      the never-worse verdict.
- [ ] Replace `scripts/_ab_common.py` callers gradually; do not port the 30 `exp_*.py`.
- [ ] Done when a preset-vs-preset run reproduces 88-90 / 67 / 103 and a second concurrent
      invocation blocks on the lock.

### I2. Seeds as a first-class option  [S]
`random.Random(0)` (roads_first.py:2020) and probe seed 0 are hardcoded, so repeat runs
differ only by timing noise and sample the same skeletons every time.
- [ ] Add a `seed` option (skeleton rng + CP-SAT seed); default 0 keeps today's behaviour.
- [ ] Measure true run-to-run spread: preset x 4 seeds x 3 cities at 600 s. This is the
      noise floor every later gate should be judged against, and a free record-hunting lever
      (best-of-N seeds).

### I3. Hygiene  [S]
- [ ] `tests/test_rl_anneal.py`, `tests/test_rl_gate.py`: `pytest.importorskip("torch")`
      (plain `pytest -x` aborts at collection today; 658 pass otherwise in 75 s).
- [ ] `.gitignore`: `agrou-city.json` (48 MB, untracked, not ignored), `webapp/cities.db`.
- [ ] Add `agrou-city.json` as a benchmark city (report consumers, Σ/2, input roads, whether
      any family hosts it). More cities = less tuning on three.
- [ ] README: lead with roads-first + presets + records; move layout/improve/anneal to "legacy".

---

## S — Speed

### S1. Continuous work queue instead of level batches  [M, highest speed value]
Today a level batch drains fully before the next is generated, generation + prefilter run
serially in the parent while the pool waits, and a slice expiry calls `pool.terminate()`
(roads_first.py:1746), discarding in-flight SAT+objective work and rebuilding the pool.
Measured: workers idle 47-53% at 120 s, 22-24% at 600 s on FR16/FR17.
- [x] Persistent workers pulling `(k, pattern)` tasks from a queue the parent keeps topped
      up across levels; the walk controller consumes results as they arrive.
- [x] Cooperative cancel: a shared deadline / level-cancel flag checked in a CP-SAT solution
      callback and before each phase (no terminate, nothing lost).
- [ ] Gate: idle share < 10% at 120 s; roads never worse; first-result time not worse.
- Prior: `concurrent_levels` was a small win; "keep the pool fed" is open from Phase B.
- **Implemented** on `feat/s1s3-work-queue` as `scheduler="queue"` (default "batch";
  `foeopt/work_queue.py`). Walk controller unchanged; a level answers when its
  classification is final (FEASIBLE at the first validated SAT, else all tasks back or
  deadline), the rest of a FEASIBLE level stays queued and is booked late. Cancel = every
  solve clamped to the level deadline + a stop Event -> `CpSolver.stop_search()` from a
  watcher thread; a cut task is CANCELLED (not counted -> UNDERSAMPLED, as before).
  New profile fields: `profile.walk.idle_share` (both schedulers), `profile.info.queue`.
  Smoke (FR16, 60 s, 1 run each, correctness only): batch wall 62.8 s (walk ran to 62.8 s,
  into the polish reserve), idle 59.5%; queue wall 40.3 s (walk ended at its 39 s
  deadline), idle 3.0%, same level classifications. **Verdict pending the serial A/B.**

### S2. Parallel polish  [S]
Objective polish solves the top-3 skeletons sequentially with all threads; rebased polish
and exact finish are sequential too, while the pool idles. FR17's record is made here.
- [x] Run the polish candidates concurrently (3 x 4 threads), then widen to top-6 at the
      same wall-clock. Use all 16 cores (preset uses 6x2).
      -> branch `feat/s2-parallel-polish`: `polish_parallel=N` (threads; CP-SAT releases
      the GIL in Solve), `polish_threads` (default workers x probe_workers), `polish_top`
      (renamed from `objective_polish_top`). All OFF by default.
- [x] `exact_route`: hint from the current roads and give it > 1 worker (exact_router.py:100).
      -> `exact_finish_workers=N` (0 = historical). The hint (roads + BFS-tree flow) is a
      complete feasible solution on the darkzig 88 / FR16 67 / FR17 103 records (verified
      with fix_variables_to_their_hinted_value). Exact finish already takes 0.03-0.08 s and
      is OPTIMAL there, so expect no gain from it on these cities.
- [ ] Gate: same or better roads at 600 s with polish wall-clock down >= 2x, or better roads
      at equal wall-clock. Never shrink the polish reserve (lesson 2026-11-12).
      Not run yet (code only). Note: at a 60 s box on FR17 the preset runs NO objective
      polish -- rebase_s=20 >= the 18 s reserve takes the whole window -- so S2 can only
      show at 120/600 s.

### S3. Publish the feasible layout before the in-walk objective  [S, UX]
First layout appears at ~31 s because the objective holds the worker for its full limit.
- [x] Emit the validated probe layout as an improvement immediately, then the objective's.
- [ ] Gate: first result < 3 s on darkzig/FR16/FR17; final roads unchanged.
- **Implemented** as `early_publish` (needs `scheduler="queue"`). FR16 60 s smoke: first
  solver layout 27.1 s -> 0.9 s. **Verdict pending the serial A/B.**

### S4. Pattern ledger  [S]
A re-probed UNDERSAMPLED level regenerates a fresh sample and may re-probe known patterns;
nothing is remembered across levels.
- [ ] Hash patterns (roads + TH); skip decided ones; reuse SAT answers as candidates.
- [ ] Exact matches only. Any subset/superset dominance rule must be proven sound first
      (extra roads both add contact and remove free cells, so neither direction is obvious).
- [ ] Report the duplicate rate first; drop the item if it is < 2%.

### S5. Use the objective bound  [S]
Each objective solve reports `objective_bound` (roads_first.py:1063); nothing reads it.
- [ ] Polish: skip or stop a candidate whose bound >= incumbent roads.
- [ ] In-walk objective: A/B a cutoff `Σneeded <= incumbent - 1` (finishes early as
      infeasible when the skeleton cannot beat the incumbent). Prior: T2B was skipped
      because solves "take seconds", yet objective solves are 13-38% of worker time.

### S6. What are the UNKNOWN probes?  [M, diagnostic then decide]
UNKNOWN probes cost 46-61% of worker time on FR16/FR17 and 73% on the user city.
- [ ] Sample 40 UNKNOWN (k, pattern) pairs per city from a preset run; re-solve each with
      300 s x 8 threads. Report the SAT / UNSAT / still-unknown split and time-to-decide.
- [ ] If mostly SAT: cross-skeleton hints (Q5) and longer adaptive limits are the lever.
      If mostly UNSAT: stronger refutation -- LP relaxation of the position model as a
      screen (HiGHS or CP-SAT `linearization_level=2`), class-pair capacity cuts.
- [ ] Also try the pure-boolean model on a SAT solver with cardinality encodings (pysat):
      the position model is only exact-counts + at-most-one per cell.

---

## C — Correctness (cheap, may be hiding results)

### C1. Prefilter counts two-lane consumers against skeleton capacity  [S]
`prefilter` (roads_first.py:469) is documented "sound", but `capacity < len(consumers)`
includes two-lane buildings, which are served by a 2x2 tile, not by skeleton cells.
- [ ] Confirm with a unit test (a pattern feasible only because the military building sits on
      the tile); if real, exclude tile-served consumers from the count.
- [ ] Count how many patterns per city this rejected in a preset run.

### C2. Walk assumes feasibility is monotone in k  [S]
The binary search (roads_first.py:2378) relies on it; the docstring at 2234 says it is not.
- [ ] From existing run rows, list levels where k is infeasible/unknown but k-4 is SAT.
      If frequent, bisect on "best achieved so far" instead of on k.

### C3. `verify_layout_file.py` re-routes instead of checking the saved roads  [S]
- [ ] Verify the roads as saved (legality on the file), and report the re-route separately.

---

## Q — Quality (the real gap: global topology)

### Q1. A lower bound that means something  [M]
- [ ] Side-counting bound, one hour: a connected network of R cells has <= 2R+1 sides
      left for consumers (4R sides, 2(R-1) used by road-road adjacency, 1 by the TH), each
      consumer needs >= 1, so R >= ceil((n-1)/2). Compare with ceil(n/3) on all cities.
- [ ] Geometric strengthening: a side of a straight run of length L hosts at most
      floor-packing of consumer widths; LP over (class, contact-width) with the side budget.
- [ ] LP relaxation of position model + optional road cells on a coarsened grid
      (the joint model OOM'd as CP-SAT; an LP with column generation may not).
- [ ] Deliverable: bound per city, gap to record, and a stop rule proposal. If the gap on
      FR16 is <= 3, stop spending on FR16 and redirect to FR17/FR24.

### Q2. Superset skeletons with DAG connectivity  [L, main quality bet]
`minimize_needed` can only pick a subset of ONE skeleton and keeps it connected through a
single BFS parent per cell (roads_first.py:1019) -- exact only on trees. So the objective
can never mix the good half of skeleton A with the good half of skeleton B, which is
exactly the non-local move T5's windows could not make.
- [ ] Step 1 (enabler): `needed[c] => OR(needed[p] for p in neighbours with dist(p) =
      dist(c)-1)`, dist = BFS distance to the TH border inside the pattern. Still sound
      (every needed cell chains to the TH), identical on trees, strictly looser on cyclic
      patterns. Unit-test connectivity on random cyclic patterns; A/B on rebased polish.
- [ ] Step 2: union pattern = road cells of the top-M (M = 2..4) distinct SAT networks that
      share a TH anchor; hint from the best member; objective picks the subset.
      Watch model size (anchor candidates grow) and cap by literals as T5 did.
- [ ] Step 3: if step 2 gains, put the union pass in polish (after objective polish,
      before rebase) and try the loose-k controller (k_start +4/+8 with the objective on).
- [ ] Gate: any city improves in paired 600 s runs; FR17 is the target (lags at 117%).
- Prior: T5 null (local windows); perturbing good skeletons 0/64 (feasibility only, no
  objective); joint free model OOM. None tested a union with a looser closure.

**Q2 status (2026-11-16, branch `feat/q2-superset-skeletons`): code done, offline evidence
NULL, timed A/B pending.**
- [x] Step 1: `closure="bfs"|"layered"|"flow"` (RoadsFirstSearch / webapp / CLI option,
      default bfs = unchanged) in minimize_needed, objective polish and rebased polish.
      layered is sound and = bfs on trees but still not exact (a route through a
      same-or-farther cell is excluded); flow is exact (single-commodity flow, complete
      flow hint from the hint network). Tests: tests/roads_first/test_closure.py.
- [x] Soft skeleton cells (`soft=True|cells`): an unused cell may hold a building (needed
      for unions: hard union cells cost space and make the best member's hint infeasible).
- [x] Step 2 wired anyway (option `union_polish` s, default 0, `union_m`): objective |
      union | rebase inside the polish window. foeopt/union_polish.py; new cells soft,
      best member's network hard, flow closure, complete hint, validate + legality.
- Offline (`scripts/exp_union_polish.py`, under the bench lock, 12-25 s per solve):
  * Saved rebased/record networks are trees: 0-1 cells (the 2x2 tile) have >1 layered
    predecessor, so **layered changes nothing on rebased polish** (rebase-bfs = rebase-flow:
    darkzig 88, FR16 67 (and 71 -> 67), FR17 103, all proven optimal).
  * Saved same-TH members are near-duplicates (1-9 new cells): no gain anywhere.
  * Fresh same-TH networks (`--generate`, nonuniform family at the incumbent's TH):
    FR17 103 U {105, 112} (51-55 new cells): 103, PROVEN optimal in 0.5-9 s.
    FR16 67 U 12 networks 67-76 (23-44 new cells): 67, proven in 5 of 6 unions.
    darkzig 88 U {93, 96/97} (48-67 new cells, 8-11k anchors): 88, FEASIBLE, bound 0-34.
  * Making ALL union cells soft: 3x anchors, bound collapses (FR17 30-44, darkzig 20),
    no move from the hint in 15-20 s. Layered on unions lost the hint (darkzig 96).
- [ ] A/B (coordinator, serial): `layered:closure=layered`, `union:union_polish=60;union_m=3`.
      Expect null: FR16/FR17 unions are proven at the incumbent; only darkzig is undecided.

### Q3. Fit the skeleton grammar to the expert networks  [M, analysis before code]
The grammar is depth-2: one trunk flush to one TH side, straight perpendicular branches
that stop at the first obstacle. Not expressible: second-level branches, bent branches,
offset or multiple trunks, loops. FR24 has no feasible skeleton at all, yet its uploaded
city is legal at 232 and polishes to 220.
- [x] For each legal network we have (5 uploads + records): tree depth, branch count, bends,
      trunk offset from the TH, TH sides used, loops. Which grammar rule does each violate?
      Done: `docs/reviews/2026-11-16-q3-network-topology.md`. Uploads 72-84% out of grammar
      (agrou 0%); end-on TH spoke + second trunk + depth 3 covers 98% of their OOG cells.
- [ ] Extend the generator only with the features the data shows (likely: depth-3
      branches and a second trunk on another TH side). Judge by **achieved roads after the
      objective**, not by SAT rate in the band.
- [ ] Gate: FR24 gets a non-seed layout, or FR17 improves.
- Prior: 21 out-of-grammar generators gave 0 SAT in 240 (scatter best 103). Those were
  invented shapes judged on feasibility; this item derives shapes from working cities.
  Re-check that study's probe budget before trusting it.

### Q4. Seed from the incumbent more aggressively on dense cities  [M]
`seed_input` took FR24 232 -> 220 in one 16 s solve; then the second solve failed fillers.
- [x] Iterate rebased polish to a fixed point with the model-filler retry, alternating with
      the Q2 union (incumbent network ∪ best partial skeleton).
      DONE 2026-11-17 on `feat/q4-iterated-rebase`, option `rebase_iterate` (off by default).
      Review: docs/reviews/2026-11-17-q4-iterated-rebase.md. Measured: the consumer-only solve
      hits about 220 on FR24 every time, but whether the fillers then fit is luck (the
      219-229 spread). MAX_SOLVES=2 cut a chain that was still improving (86 s unused), and an
      unbounded fast solve could eat the whole window. Fix: loop to a fixed point, 60 s fast
      slices, and on a filler failure validate the solve's trail of earlier solutions
      before the model-filler retry. Union alternation NOT added: no union members on
      FR24/user. A/B 600 s: FR24 229,229 -> **219,219**, user 142 = 142, darkzig 90 -> 89
      (noise), FR16 67 =, FR17 103 = -> never worse, ADOPT recommended (BEST_PRESET untouched).
- [ ] User city (97% full, 142): run Q1's bound first -- it may already be near-optimal.

### Q5. Hints across skeletons for the position probe  [S]
The position probe starts cold; only the objective is hinted. Neighbouring skeletons share
the TH and trunk.
- [ ] Hint every anchor of the nearest SAT answer that is still a candidate.
- [ ] Gate on UNKNOWN rate and time-to-SAT (uses S6's sample), then on roads.
- Prior: warm start from repack was -7, but in the item model with a greedy placement.

### Q6. Let fillers move in the exact finish  [S]
`exact_finish` re-routes with fillers fixed, so a filler cell can never become road.
- [ ] Final solve with fillers in the model (as the rebase fallback already does) on the
      final incumbent only. Expect 0-1 roads; drop quickly if null.

### Q7. TH anchor study from existing logs  [S, data mining only]
User-flagged open thread: TH placement. No new runs.
- [ ] From all stored run rows: best achieved per TH anchor, per city. If the top anchors
      are stable across runs, concentrate sampling there (and it defines the same-TH
      groups Q2 needs).
- Prior: inside the band nothing predicted achieved (|rho| < 0.22); TH-offset alone was
  neutral in the old constructor. Expect a weak result; one afternoon at most.

---

## Explicitly NOT on this list (already refuted or null — do not re-run without a new mechanism)

Leftover-box deepening / fill / harvest; probe_limit 10/5 as-is; fillers in the walk;
CP-SAT parameter portfolios; lex symmetry breaking in the item model; assumption-based
incremental solving (unsupported); skeleton bandit / CEM / RL; CNN scheduling;
depth-matched gaps; T5 optional-road windows <= 20x20; model-build / loader / filler-scan
speedups (~1% of time; a city load is 0.33 s).

## Status 2026-11-16 (session paused at usage limit)
Integration branch `feat/backlog-2026-11` (all new options OFF, full suite 701 passed):
- I1 bench harness + shared machine lock: DONE.
- S1 queue scheduler + S3 early_publish: MERGED (smoke FR16 60 s: walk idle 59% -> 3%, first solver layout 27 s -> 0.9 s). A/B pending.
- S2 parallel polish / hinted exact finish: MERGED. A/B pending.
- Q1 forest bound: DONE (sound, weak: 22/22/32/60 vs 88/67/103/220; no stop rule from counting).
- Q3 analysis: MERGED (docs/reviews/2026-11-16-q3-network-topology.md; two trunks + depth 3 cover 98% of out-of-grammar cells).
- STOPPED mid-work (check their worktree branches under .claude/worktrees/ for partial commits):
  C1 prefilter (`fix/c1-prefilter-two-lane`), Q2 superset skeletons (`feat/q2-superset-skeletons`),
  Q3 rooted generator (`feat/q3-rooted-family`).
Pending A/Bs (serial, scripts/bench.py, darkzig/FR16/FR17, 120+600 s, 2 reps):
  `--arm preset --arm "queue:scheduler=queue" --arm "qe:scheduler=queue;early_publish=true"`
  `--arm preset --arm "par3:polish_parallel=3;polish_threads=16;exact_finish_workers=4" --arm "par6:polish_parallel=6;polish_top=6;polish_threads=16;exact_finish_workers=4"`

### A/B 120 s (2026-11-16, `output/bench/2026-11-16-s1s2-120/`, 2 reps, all legal)
| city | preset | qe (queue+early) | par3 |
|---|---|---|---|
| darkzig | 89, 90 | 90, 88 | 89, 88 |
| FR16 | 67, 67 | 67, 67 | 67, 67 |
| FR17 | 106, 106 | **104, 104** | 106, 106 |
| first solver layout | 27 s | **1-2 s** | 27 s |
| walk idle share | 38-71% | **2-4%** | 38-71% |
- qe: FR17 -2 in both reps; darkzig within the +-2 noise (one pair worse by 1, so the strict
  rule says REJECT at 120 s). Mechanism: under batch, darkzig's walk overruns its deadline and
  objective polish gets 0 s (`tried 0`); the queue leaves the polish window intact.
- par3: the "ADOPT" is spurious -- in the differing pairs polish never ran (`tried 0`), so the
  code was not exercised; where it ran (FR17) it took 12 s vs 5 s for the same roads (5 threads
  per candidate stop proving optimality). Re-test on top of the queue scheduler.
- Decider: 600 s, arms preset / qe / qe+par3 / qe+union_polish=60, pinned worktree at 54032ba
  (`output/bench/s123q2-600.jsonl`).
- C1 merged (sound, zero rejections changed on darkzig/FR16/FR17). Q2 merged, options off:
  offline null (unions with 50+ new cells re-prove FR17 103 and FR16 67 optimal at the
  incumbent's TH; darkzig unsettled), layered closure = bfs on pruned trees.

## Night plan 2026-11-16/17 (user asleep; nothing merged to main)
Machine rule: every CPU-heavy run (bench, probe studies) goes through the shared lock,
`flock output/bench/.lock <cmd>` (same lock as scripts/bench.py), so runs stay strictly serial.
- [x] N1. 600 s A/B (s123q2-600) finishes -> report; if qe is never-worse, set
      scheduler=queue + early_publish in BEST_PRESET on feat/backlog-2026-11 (not main).
      RESULT (600 s, 2 reps): qe better 2 / worse 0 / tie 4 -> ADOPTED (darkzig 89,91 -> 88,88;
      FR16, FR17 tie; first layout 31 s -> 1-2 s). qep (parallel polish) REJECT (worse 2).
      qeu (union polish) identical to qe in every pair -> not adopted (adds nothing).
- [x] N2. Q3 rooted family (`feat/q3-rooted-family`): finish the pre-flight on FR24/FR17
      (remaining k), review, merge into the integration branch (option off), A/B
      `mix:family_mix=0.5` vs qe at 600 s; FR24 `rooted:pattern_family=rooted`.
      Pre-flight (probe 20+20 skeletons/level): FR17 k121 rooted 1 SAT best 111 vs nonuniform
      4 SAT best 111; FR24 k226/k238 0 SAT for both. Merged the integration branch into
      `feat/q3-rooted-family` (full suite 736 passed). A/B queued from pinned worktree
      /home/born/Github/foe-bench-q3: output/bench/q3-600.jsonl, q3-fr24.jsonl.
      RESULT (600 s, base qe): qemix better 3 / worse 2 -> REJECT. FR17 103,103 -> 106,106 (the
      rooted share displaces the nonuniform skeletons that make 103); darkzig 90,90 -> 89,89;
      FR16 67,69 -> 67,68. FR24: every arm FAMILY_TOO_WEAK (no skeleton SAT, best_k 232 = seed);
      qe 229, qemix **219**, qeroot 229 -- all from rebased polish of the seed, so the 219 is
      polish variance, not the family. New legal FR24 record 219, re-verified from file:
      docs/records/fr24-219-roads-rebased.json. Note: this qe control gave darkzig 90,90 vs
      88,88 the night before (same settings) -- darkzig noise is +-2 at 600 s.
      Bench layout files land under the PINNED worktree's output/ (copied back by hand).
- [x] N3. Multi-trunk family (user idea): 1-4 main roads, one per TH side, with TH placement
      filtered by room on every used side (central TH for 3-4 trunks), level-2 combs
      and stubs serving up to 3 buildings. Offline first: achieved roads after the objective
      vs nonuniform at the same TH and k on darkzig/FR16/FR17/FR24/user. Data note: none of
      the 5 uploads uses more than 2 TH sides (Q3 table, `sd` column), so 3-4 trunks are
      untested, not refuted.
      RESULT (branch feat/n3-multi-trunk, docs/reviews/2026-11-17-n3-multi-trunk.md there): NULL.
      Best legal roads after objective, record/central TH pooled -- darkzig nonu 92 vs r2 98,
      r3 99, r4 none (0/32); FR16 70 vs 73/79/none; FR17 105 vs none; FR24 and user: no SAT
      for any arm. Edge-to-edge trunks eat 25-30 cells each that branches need; mean distance
      to road rises (FR17 4.7 -> 6.1). 3-building stubs already occur (~6 per nonuniform
      layout). Next if revisited: length-capped trunks with a coverage pre-check.
- [x] N4. More optimized city layouts: search public sources (FoE Helper exports, city
      planner shares) for optimized layouts in a format the loader accepts; the user can
      supply more on 2026-11-17.
      RESULT: none found. Public layouts are screenshots; foe-helper.com planner links need a
      login; GitHub code search for CityMapData finds nothing. Ask the user for FoE Helper
      exports (Town Overview -> "Download data" = `<world>_citymap_<date>_<id>.json`) from
      road-optimized cities, with era. Checker: `output/n4-layouts/_scripts/check.py`.
- Q3-gen insight (agent report 2026-11-16): the rooted family CAN express the uploads (best
  single-skeleton coverage 0.51-0.63 vs nonuniform 0.26-0.38), but random draws almost never
  land near one (mean coverage 0.04-0.09 for both). The bottleneck is sampling, not grammar.
  Candidate next mechanism: directed skeleton search (mutate the incumbent/best SAT skeleton:
  move/extend/add a trunk or branch, re-probe) instead of more random families.
- [x] N5. Directed skeleton mutation (branch `feat/n5-skeleton-mutation`, review
      docs/reviews/2026-11-17-n5-skeleton-mutation.md there): one-arm mutations of a concrete
      skeleton, judged by roads after the objective (probe + parent-hinted 12-thread solve).
      **New legal records: darkzig 87 (was 88), FR17 102 (was 103; reproduced in 2 of 2
      runs)**; darkzig repeat stayed 88. FR24: evaluator too weak (88/91 mutants UNKNOWN/UNSAT).
      Records re-verified on the integration branch (legality, exact reroute optimal, inventory,
      0 rotated, 0 overlap): docs/records/darkzig-87-roads-n5-mutation.json,
      fr17-102-roads-n5-mutation.json. Not yet shown to beat production at equal wall time.
- [x] N6. Mutation search as an end-of-run phase (option, off by default), paired A/B at
      600 s vs BEST_PRESET on darkzig/FR16/FR17.
      DONE on `feat/n6-mutation-phase` (review docs/reviews/2026-11-17-n6-mutation-phase.md):
      options `mutation_polish`, `mutation_reserve` (s; shifts walk + polish window earlier,
      window length unchanged), `mutation_starts`. Runs after rebase, before seed polish/exact
      finish; N5 operators + evaluator (cold probe + warm hinted solve), legality-gated.
      A/B 600 s x2 (output/bench/n6-mut.jsonl in /home/born/Github/foe-bench-n6):
      mut (leftover) better 2 / worse 0 / tie 4; mutr (reserve 120) better 4 / worse 0 /
      tie 2 -> both ADOPT by the rule. FR17 103 -> 102 (2 runs), darkzig 90 -> 88,
      **FR16 66 new legal record** (docs/records/fr16-66-roads-n6-mutation.json, verified).
      darkzig preset also ends early (~430 s), not at the box. Not yet in BEST_PRESET:
      repeat at 120 s first (reserve takes up to half the box).
- N6 merged into feat/backlog-2026-11 (1cd94b8, suite 756 passed). A/B on its own branch (600 s):
  mut better 2/worse 0, mutr (reserve 120 s) better 4/worse 0 -> both ADOPT candidates;
  FR16 66 new legal record (docs/records/fr16-66-roads-n6-mutation.json), FR17 102 inside a
  normal 600 s run. Confirmation on the MERGED code (now with rebase_iterate in the preset),
  120 + 600 s, pinned /home/born/Github/foe-bench-m1: output/bench/m1.jsonl, m1-fr24.jsonl.

## 2026-11-17: v3 city format + catalog chain fix
- v3 FoE Helper exports load (13 user cities under cities/, gitignored). Bundled catalog
  foeopt/data/catalog.json. Webapp upload worker updated.
- **Chain detection fix changes darkzig and agrou**: component-style chains were invisible.
  darkzig 8 -> 28 chain buildings; ALL darkzig records (87, 88, 89, 90) now fail legality
  (chain_broken: gentiana_windmill, pirates_hideout; 16 links). agrou 0 -> 34 (Breezemill
  + 33 parcels). FR16/FR17/FR24/user unchanged, so their records stand. darkzig numbers in
  every A/B so far were measured under the incomplete chain rule.
- [ ] Re-baseline darkzig under the full chain rule (new legal record), re-run darkzig arms.
- [x] GR25 "Niv. 2" need no road (user-confirmed): loader now uses the catalog rule; FR17 77->74, FR24 146->145 consumers.

### N7. Low-freedom chain blocks placed like the TH  [M, user direction 2026-11-17]
User: chain main buildings do not need to touch each other, only patches (already true: links
are linkPositions slots; heads have no head-sized slot). Big chains fit in very few positions,
so the city's own row/column widths decide where they can go.
Data (empty-grid positions of each composite): agrou Breezemill 34 pieces 71x6 -> 14 positions;
darkzig chains 16x3..16x5 -> ~1750; essay 11x6 -> 1448; vini ~2300. All composable.
- [x] Per composite: feasible anchors from the region shape (excluding TH cells per TH anchor).
- [x] If anchors < threshold (~50): sample one per skeleton (like th_anchors), carve its cells
      from the skeleton generator's region, fix it in the position model at that anchor.
- [ ] Gate: agrou gets a skeleton-made layout (today expected FAMILY_TOO_WEAK -> seed only);
      essay/darkzig not worse. All results pass full legality (chains linked).
- [ ] Re-baseline darkzig under the full chain rule (records 87-90 break component chains).
- [x] N6 ADOPTED (2026-11-17): BEST_PRESET mutation_polish + reserve 120 s for boxes >= 300 s
      (mutation_reserve_min_box). m1 confirmation, darkzig excluded (pre-chain-fix):
      120 s leftover-only better 3/worse 0; 600 s reserve FR16 66,66 FR17 102,102 (4/4 better),
      FR24 tie 219. The leftover-only arm's FR24 220 came from rebased polish BEFORE the climb
      (run-to-run variance), not from the climb.

## E — City edits: remove buildings, add new ones (DONE 2026-11-17, merged into feat/backlog-2026-11; user tried the UI: works)

**Why:** the point of rearranging a city is to make room. The June static UI could do this
(`foeopt/editing.py`: remove by id, add by width x length); the JSON-API rewrite (771a827)
and the React SPA (dae5f3c) dropped the endpoint and the UI. Only `apply_edits` and its
tests survive, uncalled.

**Facts that shape the design (checked in code):**
- Chain links are derived from the positions in the (edited) layout (`chains.linked_groups`,
  `legality.chain_links`). So removing pieces needs no special case in the optimizer, but a new
  chain piece has no position, so no link to keep: it would be placed unlinked.
- `seed_input` publishes the upload only if it passes the full legality check
  (`_seed_from_input`). The upload minus removed buildings stays legal, so the instant result
  and the rebased polish still work. Unplaced additions would fail that check.
- `apply_edits` sets roads={} (made for the old repacker), so it would silently switch off the
  seed even for a removal-only edit. It also creates added buildings as type "custom", with no
  catalog data.

### E1. Backend
- [x] `GET /api/catalog?q=&city_id=`: search the bundled catalog, plus the city's helper
      CityEntities when present, by name or id. Returns id, name, type, w x l, road need and
      level, chain id, head/patch. Hide off-grid types and streets; limit 30 results.
- [x] Rewrite `apply_edits(layout, remove_ids, add)` with catalog-backed additions:
      `{"cityentity_id": id, "count": n}` gives the real size, `needs_road = street_requirement > 0`,
      `road_level`, set/chain ids. Keep `{"width","length","needs_road","name"}` for custom sizes.
      Keep the upload's roads. Townhall: never removable (existing rule).
- [x] Edits are per-city state, sent with `/api/optimize` as `edits: {remove: [...], add: [...]}`.
      They are validated (unknown id or entity -> 400) and echoed back with the options.
- [x] Seed with edits: removal-only keeps `seed_input` (upload minus removed). With
      additions, first try greedy-placing them in free cells of the upload. On success the seed
      stays (the instant result keeps working). Otherwise skip the seed with reason
      "N new buildings not placed".
- [x] Space pre-check in the response: free cells after edits = region minus buildings, and a
      lower bound on roads. If the new buildings cannot fit even with zero roads, return an
      error that names the overflow, not a 10-minute FAMILY_TOO_WEAK.
- [x] Legality: result checked against the EDITED inventory (`check(result, edited)`), still
      no rotation; a run on an unedited city must give byte-identical options and behaviour.

### E2. Frontend
- [x] BuildingsPanel: a "remove" toggle per building, plus "remove all of this type". Click a
      building on the map to toggle it. Removed buildings shown hatched or faded, not hidden.
- [x] Warn when removing a chain piece breaks the chain behind it (later patches lose their
      link). Offer "remove the rest of this chain".
- [x] "Add buildings" panel: catalog search, count, then a list of additions with size and road
      tags; custom size entry for anything missing from the catalog.
- [x] Summary bar: removed n (cells), added m (cells), free cells after edits, and the space
      pre-check warning.
- [x] Edits saved with the city (survive reload) and stored with each saved layout, so a
      result says which edit set it was made for.
- [x] Result view/export: added buildings drawn at their placed position, named from the catalog.

### E3. Verify
- [x] Unit: apply_edits (catalog add, custom add, remove keeps roads, TH protected, bad id).
- [x] API: optimize with edits; unedited run unchanged; space pre-check error.
- [x] End-to-end: FR16, remove 3 buildings + add 2 catalog buildings (one road-needing),
      300 s. Result legal against the edited inventory, nothing rotated, removed ones absent.
      Also a removal-only run: the seed is used and the first result arrives in under 2 s.
- [ ] Browser walkthrough of the UI flow (record a GIF). NOT DONE: Chrome extension not connected.

### Decisions (user, 2026-11-17)
1. Chain buildings are in v1. An added patch links automatically to the chain's main building
   when the city has exactly one of that chain; with several, the UI asks which one. The linked
   set is then composed as one rigid block, like the upload's chains.
2. Removed buildings are listed as "to store" in the export.
3. Keep custom width x height (in case the catalog lags behind the game).
4. Removing a chain piece REATTACHES the pieces behind it (user's choice). In-game the cut-off
   tail stays together but gives nothing, and the game does NOT relink it. The tool assumes the
   player will relink it, so one removed patch does not cost the whole tail. Mechanism: the tail
   piece that sat in the removed piece's slot moves into that freed slot (same slot size), and the
   tail shifts with it. The UI says so ("P2, P3 will be reattached to <main>"), with "remove them
   too" as the alternative.
   Added patches use the same mechanism: they go into a free slot at the end of the chosen chain.
- [x] Re-baseline darkzig under the full chain rule (records 87-90 break component chains).
- 2026-11-17 done on `feat/n7-chain-anchors` (9a211a6; docs/reviews/2026-11-17-n7-chain-anchors.md).
  Option `chain_anchors` (default 0 = off, byte-identical; 50 recommended: anchor counts are
  14 for agrou and >= 1490 everywhere else). Pinned composites get one anchor per nonuniform
  skeleton, carved out of the roads' region, joined to the trunk by a shortest path to the
  contact edge, and fixed in the position model. A/B 600 s x2 (output/bench/2026-11-17-n7 in
  /home/born/Github/foe-bench-n7): agrou 67,67 = 67,67; darkzig 90,88 = 90,88; essay 62,61 ->
  61,61 (noise: nothing is pinned there). Verdict NEUTRAL, keep it off. The agrou gate is NOT
  met: the walk SATs went from 0 to 27, but filler packing fails (fillers + consumers + TH fill
  4293/4368 cells, so k <= 75 with zero slack). Next lever for agrou: pins + fillers_in_model.
  New legal baselines: darkzig 88 (full chain rule), essay 61 (docs/records/).
5. (user, 2026-11-17, during the build) Removing a chain's MAIN building sends its patches to
   store, unless the city has another main of that chain: the UI then offers to attach them to
   it (same picker as for added patches; API `edits.relink = {removed_main: other_main}`).

### Review (2026-11-17, branch feat/e-city-edits)

**Built.** `foeopt/editing.py` rewritten (`apply_edits(layout, remove, add, catalog, relink)` ->
(edited layout, report)); `Catalog.is_chain_head`; `loader.city_catalog_defs`; API
`GET /api/catalog`, `POST /api/edits/preview`, `PUT /api/cities/<id>/edits` (new `cities.edits`
column, upsert keeps edits on re-upload), `/api/optimize` with `edits` (validated, echoed with a
report, space pre-check 400, non-composable chain 400); every published layout of an edited run
carries `to_store` + `added`. Frontend: City edits panel (summary bar, seed note, chain notices
with "remove them too" / "attach them to", Add buildings with catalog search, count, main picker,
custom size), remove / remove-all-of-type in the Buildings list, click-to-toggle on the map
(removed drawn faded + hatched), saved layouts keep their edit set, result shows added names and
the to-store list (in the export too).

**Design choices.**
- Main vs patch: a chain member is a main iff it needs a road, or has the size of a road-needing
  member of its chain. Checked on all 11 bundled chains (every chain has >= 1 main and >= 1
  patch); the only road-less main is gentiana CUP22A10 (5x4 like the mains, patches 1x4).
  darkzig / essay / agrou groups: the detected main is exactly the linked group's road-needing
  root. magicness has 9 unlinked mains and no patches.
- Seed with additions: new buildings (or the chain block an added patch joined, or a relinked
  tail) are greedy-placed in the upload's free cells, road-needing ones touching the upload's own
  connected road of their level; final `legality.check(edited, edited)` decides. Unplaced ones are
  parked outside the region (the search ignores input positions except chain shape), and the
  report says "N new or relinked building(s) do not fit".
- Unedited requests (no `edits`, or empty lists) take the historical code path; test asserts the
  same submit kwargs.

**Measured (BEST_PRESET, under output/bench/.lock).**
| run | box | first result | roads | legality vs edited | notes |
|---|---|---|---|---|---|
| FR16 remove 3 (60 cells) + add Obelisk 2x2 road + Bal macabre 4x3 | 300 s | 0.18 s (seed, 92) | **68** | valid (server + independent recheck) | removed absent, added present, nothing rotated |
| FR16 remove the same 3 only | 60 s | 0.17 s (seed, 92) | 68 | valid | |
| darkzig remove pirate patch 1275 + gentiana patch 3480 | 120 s | 0.18 s (seed, 250 cells) | 88 | valid | both tails reattached; 20/20 chain links kept |
Smoke (not locked, 1 worker): FR16 + a custom 7x7 road building that does not fit the upload ->
seed skipped with the reason, legal 81 in 10 s.

**Tests.** Python 791 passed, 4 skipped (20 apply_edits + 8 API tests new). Frontend 56 passed
(8 edits helpers + 2 store tests new). `npm run build` clean.

**Not done.** Browser walkthrough: the Chrome extension was not connected; checked instead that
the built bundle is served and contains the new panels, and drove /api/catalog and
/api/edits/preview on a live server (darkzig: link_to required with both pirate mains listed).
Tree-shaped chains (Mughals: TH is the main, never removable) and hippodrome (two mains) are
handled generically but untested on real data.

## X — Export the result as a v3 city file (Forge Hammer planner format)  (APPROVED 2026-11-17; BUILT on feat/x-v3-export, awaiting review)

**Today:** "Export" in the result panel downloads the optimizer's internal JSON (`<city>-k<k>.layout.json`:
roads as [x,y,level] + building positions by entity id). The city export (`.city`) is the cached
UPLOAD, not the result. The cache stores a slimmed upload (stripV3 keeps only id/cityentity_id/type/x/y
and mapData), so it can't rebuild a full v3 file either.

**What the v3 format is (measured on the 13 files):**
- `cityData` = the city as it is in-game (with era, level, bonuses per entity).
- `mapBuildings` = the FoE Helper PLANNER layout: `{metaId, x, y, era, custom}` per building INCLUDING
  streets. For 12 cities it mirrors cityData exactly (vini 588/588, sinj 479/479; the gap to cityData is
  off-grid entities). My-City-V2 is a plan in progress: only 17 of 325 entries match the city,
  116 are `custom: true` (not owned yet) and 192 sit in `storedBuildings`.
- `storedBuildings` = the planner's storage, same `{metaId, x, y, era, custom}` shape.
- So the right export is: same file, `cityData` untouched, the optimized layout written into
  `mapBuildings`, removed buildings into `storedBuildings`.

### Plan
- [x] Cache the FULL v3 upload (70-260 KB; stays local in webapp/cities.db, never sent anywhere);
      the optimizer still loads from cityData. Old slim caches: export says "re-upload the file".
- [x] `foeopt/export_v3.py`: `to_v3(original, result_layout, to_store, added)`:
      - mapBuildings: one entry per placed building (metaId = cityentity_id, x/y = new position,
        era = the entity's cityData era, custom = false), plus one per road cell with the street
        metaId the city already uses for that level (level 1 / two-lane read from cityData; two-lane
        tiles are 2x2: one entry per tile, not per cell — verify against an upload).
      - added buildings: custom = true, era = currentEra.
      - storedBuildings: removed buildings (+ whatever was already stored? see question 2).
      - off-grid entities untouched; every other top-level field copied verbatim.
- [x] Round trip: load the exported file's mapBuildings as a city and get the same layout back
      (positions, roads, legality valid); for an unedited, unoptimized city, export == upload's mapBuildings.
- [x] `GET /api/layouts/<id>/export.v3` (and for the live result) + an "Export for FoE Helper" button;
      keep the internal JSON export as "Export (debug)".
- [x] Tests: unit (entries, era, custom, roads per level, stored), API, round trip on 3 real cities.

### Decisions (user, 2026-11-17)
1. Target: the Forge Hammer city planner. The v3 files ARE its export/import format.
2. storedBuildings: REPLACE with exactly our removed buildings (user: yes). (My-City-V2 has 192 = its own plan's storage, 144 of them
   copies of buildings in the actual city). Recommended: REPLACE with exactly our removed buildings,
   since the export replaces the plan.)
3. Always optimize from the actual city (cityData), never from the plan (mapBuildings).

### Review (2026-11-17, branch feat/x-v3-export, NOT merged)
- **Format evidence (13 uploads):** the mapBuildings entries are `{metaId, x, y, era, custom}`, in that
  key order. x/y is the top-left, same as cityData, and a zero coordinate is OMITTED, as in cityData
  (My-City-V2, a plan Forge Hammer edited, writes explicit 0s, so FH reads both). era = the entity's
  cityData era (13/13). Off-grid types (hub_main/part, friends_tavern, outpost_ship, off_grid) are
  not in it. Two-lane: every `*CarStreet*` in the catalog is 2x2 and provides level 2. cityData and
  mapBuildings both store ONE entity per tile, at its top-left (essay: 36 CarStreet2 = 144 cells).
- **Export:** `foeopt/export_v3.py` `to_v3()`. Buildings follow cityData order. Streets: one 1x1
  entity per level-1 cell and one 2x2 entity per two-lane tile (the tiling is unique, greedy
  row-major). A street keeps the metaId/era of the city's street at that cell or tile anchor; a new
  one gets the city's most used street of that level, or a catalog street of that level (same age
  as the other street kind, else currentEra). Cells that cannot be tiled raise a clear error. A
  building added by size only (no catalog id) is left out, with a warning.
- **Unedited export reproduces mapBuildings exactly (as a multiset) on 12/12 mirroring cities**,
  including vini's 3 mixed street types. My-City-V2 differs by design (its plan is replaced).
- **Webapp:** the full v3 file is cached. The city id = hash of the old slim projection (cityData
  keys in JS order), so re-uploading keeps the id, its edits and saved layouts (checked: essay
  and antivol reproduce their cached ids, edits included). Old slim caches: export returns 400
  `reupload: true`. Endpoints: `POST /api/export/v3 {city_id, layout}` and
  `GET /api/layouts/<id>/export.v3`. File name `<upload-name>-optimized.json` (the name is sent with
  /api/load?name=, ASCII-only, falls back to the city id). The result panel has "Export for Forge
  Hammer" (primary) and "Export (debug)".
- **Tests:** 16 unit/round-trip (3 real cities, unedited and edited) + 8 API. Full suite 825
  passed / 4 skipped. Frontend 60 passed, build OK.
- **End to end** (scripts/e2e_export_v3.py, BEST preset, 60 s, under the bench lock; checks: export
  plan reloaded, legality valid, roads/levels equal, positions equal, stored equal, other fields
  untouched): essay 64 roads OK. moune with 2 removed + 1 added: 33 roads, 2 stored, 1 custom, OK.
  durza 66 cells (4 two-lane = 1 CarStreet tile) -> 63 street entities, OK.
- **For the user to check in Forge Hammer:** (1) import one export and check that the streets and
  buildings land where the optimizer drew them (positions have only been checked against our own
  reading of the format). (2) essay's 36 two-lane tiles serve no building, so the optimized city
  has only level-1 roads. (3) storedBuildings are written at their old cityData position, custom=false.

## Plan W: 8x2 workers vs 6x2 (2026-11-24, user: "Try A")
Profile (FR16 300 s): 12 threads configured, 9.6 busy on average; 4 of the 16 logical
CPUs never used (Ryzen 7 9700X: 8 cores / 16 threads). Mutation climb loses 556
thread-s (empty 6th slot + slowest-probe tail); the walk only 42.
- [ ] Paired A/B: `preset` vs `w8:workers=8` (probe_workers stays 2; polish threads
      follow workers x probe_workers = 16), darkzig/FR16/FR17, 120 s and 300 s, 2 reps.
- [ ] Gate: adopt only if never worse in any pair and better in at least one.
