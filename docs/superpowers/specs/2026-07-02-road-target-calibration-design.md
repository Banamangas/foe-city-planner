# Road-Target Calibration + Lane/Stub Composition Go/No-Go — Design

Status: **approved design, not yet implemented.** First of two specs from the
2026-07-02 road-objective review (`tasks/todo.md`); companion spec:
`2026-07-02-routability-mask-design.md`.

## 1. Context and purpose

Every local method plateaus at ~**158** roads on darkzig vs the Σ(short-side)/2 =
**114** estimate. The RL M4 bet failed at its own gate (0% success at 0.9 fill,
BC rescue collapsed, every darkzig eval stuck/unroutable) and is **archived** —
see the lessons.md entry accompanying this spec.

Two facts reshape the target:
- **Validity needs ONE road-adjacent border cell** (`foeopt/validate.py:35-38`),
  not a full short side. Σ/2 is therefore an *estimate*, not a bound in either
  direction — the user's own city routes 142 < its Σ/2 = 157.
- Truly *provable* placement-independent lower bounds are weak: buildings are
  movable, so border-based arguments don't apply. The cheap provable bound is
  adjacency capacity — a connected road cell serves ≤ 3 consumers — giving
  roads ≥ ⌈63/3⌉ = 21 on darkzig. Honest, but far below anything informative.

**Purpose of this project:** produce (a) an evidence-based **target band** for
darkzig roads, and (b) a **go/kill verdict** on the Track-A lane/stub
decomposition *before any geometry work*. Deliverable is a written verdict
backed by numbers, not a road-count improvement.

**The band is anchored as: [max proven bound, A1 family-optimum]**, where the
family-optimum is the minimal road cost achievable *within the expert layout
family* (parallel double-loaded lanes + trunk + capped stubs/junctions) for the
city's exact building inventory. That is what "a perfect expert" could do — the
honest target for any automatic method.

## 2. Decisions locked during brainstorming

- **Decomposition:** gate-respecting. This spec covers Track 0 + A1 only.
  Track A2/A3 (geometry + repair) and Track B (corridor LNS) get their own
  specs only after this project's verdict, with real numbers in hand.
- **Dependency stance:** prototype-first. The composition solver is a throwaway
  script run via `uv run --with ortools`, committed under `scripts/`. OR-Tools
  becomes an optional extra only if the gate passes and the full A-track ships.
  `foeopt/` stays pure-stdlib.
- **Objective anchoring:** re-anchored to evidence. Success for the eventual
  road objective = reaching this project's target band, not a hard 114.
- **RL:** archived (pending `rl/` changes + `rl/imitate.py` committed as-is with
  a lessons entry; GPU runs stop). The routability mask (companion spec) is
  classical-first infrastructure, not an RL rescue.

## 3. Components

### 3.1 `foeopt/quality.py` extension (production, stdlib, tested)

New measurements, surfaced in the `roads`/`layout`/`improve` CLI report next to
the existing Rule-1/Rule-2 grades:

- `road_cell_load(layout) -> dict[cell, int]` — number of road-needing
  buildings orthogonally adjacent to each road cell.
- `sharing_histogram(layout) -> dict[int, int]` — road cells by load
  (the "avg 2.02, 4 cells serve 3" analysis of the user's city, generalized).
- Per-building road contribution: for each consumer, the count of adjacent
  road cells weighted by 1/load — Σ over consumers ≈ road cells that exist to
  serve consumers; the residual (roads − Σ) is pure connectivity overhead.

These characterize *how* the expert beats the estimate (sharing level, stub and
junction usage, overhead cells) and become the structural targets A1's model
must reproduce.

### 3.2 `foeopt/bounds.py` (production, stdlib, tested, small)

Provable placement-independent lower bounds, each documented with its argument:

- `bound_adjacency(layout)`: ⌈n_consumers / 3⌉ — a road cell has 4 orthogonal
  neighbours and (in any connected network of ≥ 2 cells, or rooted at the TH
  border) at least one must be road or TH, so ≤ 3 consumers per cell.
- Connectivity refinements may be added only if the argument survives review
  (e.g. minimum network extent to reach the region's consumer capacity);
  anything not strictly provable stays out.
- `report_bounds(layout)` returns all bounds + their max.

Tests: each bound ≤ the CP-SAT-proven optimum on the tiny instances from the
attempt-#6 lessons (and `rl/oracle.py` optima); each bound ≤ 142 on the user's
city; each bound ≤ 158 on darkzig (sanity: a bound above a *known achievable*
value is a broken bound).

### 3.3 A1 composition solver (throwaway, `scripts/exp_lane_composition.py`)

CP-SAT assignment model over the road-needing inventory only (fillers backfill
later — they already place perfectly, per lessons):

- **Modules:** K candidate lanes (K bounded by region extent / min lane
  thickness). Each lane has two sides; each side has a depth class. A building
  assigned to a lane side chooses orientation: its extent along the road is one
  dimension, its depth the other; the side's depth class must equal the
  building's depth (uniform-depth rows — the expert heuristic; mixed-depth
  raggedness is excluded from the base model and noted as an optimistic
  sensitivity).
- **Lane cost:** max(Σ extents side A, Σ extents side B) road cells.
- **Trunk cost — computed, not guessed.** Lanes stack along a perpendicular
  trunk: pessimistic trunk = Σ over lanes of (depthA + 1 + depthB) (the full
  stacked height); optimistic trunk = the same minus lane-end sharing and the
  TH two-stub start. The verdict is reported under both.
- **Junctions:** 1 road cell per lane-trunk crossing, counted (load ≤ 1 for
  those cells).
- **Stubs (sensitivity scenario, not the base model):** a dead-end road cell
  serving ≤ 3 consumers, allowed only at lane ends, ≤ 1 per lane end. An
  uncapped stub model collapses to trunk + ⌈N/3⌉ — geometrically meaningless.
- **Feasibility guards:** lane length ≤ region bounding-box max; Σ lane
  thicknesses ≤ region extent; total module area + filler area ≤ region area.
  These are coarse (the region is irregular); geometry proper is A2's problem.
- **Determinism:** single worker, fixed `random_seed` (lessons: multi-worker
  CP-SAT is non-deterministic). On timeout, report objective + proven bound +
  gap; the verdict is "inconclusive" if the gap straddles a threshold.

### 3.4 Model calibration (the key validation)

Run A1 on the **user's city inventory first** (82 road-needing consumers,
known expert answer 142). The ratio expert-real / model-optimum is the
family-model optimism factor; darkzig's verdict uses the calibrated value
(model-optimum × factor). If the model can't get within ~25% of 142 in either
direction, the family model itself is wrong — stop and redesign before reading
any darkzig number.

Cross-check on tiny instances: the lane family is a restriction of the general
problem, so wherever both are computable, family-optimum ≥ the `rl/oracle.py` /
CP-SAT joint optimum. A family number *below* a proven joint optimum means a
modeling bug.

## 4. Data flow

```
darkzig.json / city-user-data.json
  → loader → Layout
  → quality.py histograms + bounds.py           (foeopt, stdlib, tested)
  → scripts/exp_lane_composition.py             (uv run --with ortools)
      reads inventory, emits JSON report:
      {bounds, model_optimum, calibrated, trunk_pessimistic/optimistic,
       stub_scenario, gap, assignment}
  → verdict written to tasks/lessons.md + tasks/todo.md review section
```

## 5. The gate

Let C* = calibrated family-optimum with pessimistic trunk.

- **C* ≥ ~150 → kill Track A.** Even perfect geometry lands at today's polish
  level; the durable wins are Track B (corridor LNS) + productionizing.
- **C* ≤ ~130 → go.** Write the A2/A3 spec (geometric embedding + repair),
  carrying the concrete lane assignment as its input.
- **Between → user decides** with the report in front of them.

## 6. Testing

- `tests/test_quality_sharing.py`: histogram/load/contribution on hand-built
  fixtures + regression values on the bundled city (known: avg 2.02, 137/4
  split) — pinning the user-city numbers guards the loader too.
- `tests/test_bounds.py`: bound ≤ known optima (tiny instances), ≤ 142 (user
  city), ≤ 158 (darkzig-achievable).
- The composition script is throwaway: validated by the §3.4 calibration and
  tiny-instance cross-checks it prints, not by pytest.

## 7. Out of scope

- Any geometry/embedding work (A2), repair/polish integration (A3), corridor
  LNS (Track B) — later specs, gated on §5.
- Making OR-Tools a repo dependency.
- Any RL training.

## v2 model (2026-07-05): embedded trunk + end overhangs

v1 was falsified on the user city: `scripts/exp_lane_composition.py` returned
`status: INFEASIBLE` under its own area guard, with a relaxed (unconstrained)
run proving a bound of 166 — above the area budget of 145, itself above the
real expert answer of 142. See the 2026-07-03 `tasks/lessons.md` entry for the
full diagnosis. Two root causes were identified there:

1. The pessimistic trunk term `Σ over used lanes of (depthA + 1 + depthB)`
   charges every lane a fully exclusive trunk allocation, crediting zero
   cross-lane sharing. The real city's sharing histogram (`{1:1, 2:137, 3:4}`,
   avg load 2.02) has **zero load-0 overhead cells** — every connector cell is
   embedded inside a double-loaded lane, not a separate trunk structure. The
   pessimistic term overcounts this connectivity overhead by ~8×.
2. Full-frontage lane loading (every building's whole extent counted against
   its lane side) overcounts real cell usage by ~20%: the real city's measured
   Σ cell-loads is 287 against a Σ min-sides of 314, because buildings
   overhang the ends of a lane run — an end building needs only ≥ 1 adjacent
   road cell, not a full-width allocation.

**v2 changes:**

- **(a) Trunk term dropped.** Connectors are modeled as embedded in lanes,
  matching the measured zero-overhead-cell reality. An optional
  `--connectors` sensitivity flag charges `n_used_lanes − 1` extra cells (a
  minimal "each additional lane needs one more junction cell to reach it"
  approximation), off by default.
- **(b) Per-lane-side end overhangs.** Up to 2 buildings per lane side (the
  two ends of the row) may be marked as "end" placements: an end building
  contributes 1 frontage cell to the side load instead of its full extent,
  modeling the overhang the real layout exploits.
- **(c) Depth classes and stack-max dropped.** Both existed only to feed the
  now-removed trunk term; v2 has no notion of per-side depth class or a
  cross-lane stacking budget.

**Status: v2 is a RELAXATION of v1, not a restriction of the real problem.**
Its optimum is an *optimistic* estimator (every v1-feasible solution maps to a
v2 solution of ≤ cost, since v2 permits everything v1 permits plus overhangs
and cheaper connectivity) — so, unlike v1, v2's model-optimum is not
guaranteed to sit above the true joint optimum. The calibration factor
`f = 142 / model_optimum(user city)` exists precisely to correct for this
optimism; it is expected to land below 1. Consequently the self-test
invariant changes from "family ≥ oracle" to two relaxation/capacity
invariants instead:

- `v2_optimum ≤ v1_optimum` — provable, since every v1 solution (a full-load
  assignment with a pessimistic trunk) maps to a valid v2 solution (the same
  assignment, zero ends used, trunk dropped) of no greater cost.
- `v2_optimum ≥ ⌈n_items / 3⌉` — the adjacency-capacity bound from §1/§3.2
  still holds: no road cell, however placed, serves more than 3 consumers,
  even when every consumer is served by a stub.

Calibration criterion is otherwise unchanged from §5/§3.4: `f` must land in
`[0.75, 1.33]`; darkzig `C* = f × darkzig v2 optimum`; gate thresholds
unchanged (`~130` go / `~150` kill / between → user decides). This is a
**one-iteration, time-boxed retry**: if v2 also fails calibration, Track A is
killed per the pre-committed stop rule — no v3.
