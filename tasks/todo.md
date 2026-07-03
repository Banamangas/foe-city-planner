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
- [ ] Deliverable: a target band for darkzig (e.g. "optimum plausibly 118–135")
      and a benchmark suite definition: darkzig (gate) + `make_real_like_city`
      seeds at fill 0.5/0.7/0.9 + the user's city for improve-mode regression.
      **BLOCKED (2026-07-03):** calibration on the user city is INFEASIBLE under
      the A1 model's own region-area guard — no target band could be produced.
      See `tasks/lessons.md` and `.superpowers/sdd/task-5-report.md`.

## Track A — Lane/stub decomposition optimizer (the main bet)

Lessons say beating 158 needs a *fundamentally different global optimizer*. The
expert layout IS a global decomposition: straight double-loaded lanes + trunk + TH
stubs. Four constructive lane attempts failed because they were **greedy, rigid
constructors**. The fix is to optimize the decomposition where it is 1-D and
combinatorial (tractable), and keep the 2-D geometry trivial:

- [ ] **A1 — Composition solver (go/no-go gate, ~2 days, throwaway):** assign the
      63 road-needing darkzig buildings to *modules* — double-loaded lane segments
      (cost = max(Σ along-road extents side A, side B)), dead-end stubs (1 road
      cell, up to 3 buildings), junction cells — minimizing total road cells +
      trunk overhead. Pure 1-D bin-packing/balancing over ≤82 items: **CP-SAT is
      in its element here** (no spatial grid). Depth-bucket rows to keep outer
      edges straight; price mixed-depth raggedness explicitly; odd-size tail goes
      to lane end-caps and stubs instead of "leftover greedy".
      **Gate:** if the *optimal composition* already costs ≥~150 road cells before
      geometry, the whole track dies cheaply. If it's ~115–130, proceed.
- [ ] **A2 — Geometric embedding:** pack lane rectangles (length × (depthA + 1 +
      depthB)) + a trunk into the irregular region (strip packing against region
      rows; TH near-edge with two road stubs per the user's heuristic memory).
      Fillers backfill remaining space — fillers already place perfectly (lessons).
- [ ] **A3 — Repair + polish:** `route()` to connect/validate; existing anneal as
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

- [ ] **C1 — Routability-preserving action mask:** mask placements that disconnect
      free-space components from the TH frontier (articulation check). Eliminates
      `unroutable` by construction ⇒ dense fills become learnable, and the same
      mask drops into the classical packer to attack stranded consumers (O1) —
      **build C1 regardless; it serves Tracks A/B too.**
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
