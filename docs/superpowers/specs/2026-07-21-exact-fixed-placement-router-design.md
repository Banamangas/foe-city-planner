# Exact fixed-placement router — design

_2026-07-21. Track: R&D (beat the roads-first floor / test a load-bearing assumption). Status: spec, not yet planned._

## 1. Motivation

The road count of any layout is produced by `route()` (`foeopt/router.py:132`), a **greedy**
heuristic: it connects each consumer to the growing tree by a shortest BFS path (in
Townhall-distance order), then greedily removes non-articulation road cells (`_prune`,
`:185`). It is a good heuristic with **no optimality guarantee**. The project's lessons
*assert* "route() is already near-optimal for fixed placement" (2026-06-23, attempt #6) but
never measured it.

Two independent sources of slack determine the achieved road count:

- **Placement slack** — which consumer placement you pick. The 2026-07-21 placement-objective
  study measured this (~4.8 roads of `oracle_gap`) and found it hard to capture with a proxy.
- **Routing slack** — how close `route()` gets to the *minimum* road network **for a fixed
  placement**. This has never been measured.

This spec attacks the second. An **exact router** — the minimum connected road-cover for a
fixed placement — recovers routing slack directly, on *any* placement including the current
all-time best. Applied to the 102-road layout, if `route()` left even one cell on the table,
the exact solve is a new all-time best. And a null result ("route() really is optimal")
settles the unproven assumption with certainty.

**Why this is tractable where `minroads` was not.** The joint `minroads` model
(`foeopt/minroads.py`) blew up to 3.9 GB because it optimized placement *and* roads together
(224-rectangle no-overlap × connectivity). **Fixing the placement deletes the placement
variables entirely** — what remains is selecting road cells from the free-cell set (~100–270
cells on darkzig), which is the slice that never exploded.

## 2. Grounding facts (from `router.py` / `validate.py`)

- **Validity is cover + connect only** (`validate.py:29`–`45`): a layout is valid iff every
  road-needing consumer has an orthogonally-adjacent, TH-connected road cell whose level ≥ the
  consumer's `road_level`. There is **no** constraint forbidding a road cell from touching a
  non-consumer ("rule 1" is a *quality metric, measured not enforced*). So the exact model
  needs no anti-adjacency constraints.
- **Road level does not affect the cell-count objective.** A level-N street still occupies one
  tile; any road cell can be any level at no extra tile cost; connectivity is level-agnostic
  (`validate.py` checks the *covering* cell's level and TH-connectivity separately). So level
  is a **post-hoc per-cell assignment** (`level(c) = max road_level over adjacent consumers`),
  never a decision variable in the min-cells model.
- **Roads occupy free cells** = `region − (all building footprints)`. The exact router selects
  a subset of those.

## 3. The model

For a fixed `Layout` (all buildings + TH placed): let `free = region − occupied`, and for each
consumer `i`, `border_free(i) = i.border_cells() ∩ free`; `th_roots = TH.border_cells() ∩ free`.

- **Decision:** `r_c ∈ {0,1}` for every `c ∈ free` (is `c` a road).
- **Cover:** for each consumer `i`, `Σ_{c ∈ border_free(i)} r_c ≥ 1`.
- **Connect (single-commodity flow):** a virtual source feeds the `th_roots`; each *selected*
  cell consumes 1 unit; flow may enter a cell only if that cell is selected. Concretely, over
  the directed graph on orthogonally-adjacent free cells:
  - node balance: `inflow(c) − outflow(c) = r_c` for every `c ∈ free`, where `inflow` of a
    `th_root` includes its source arc (the source supplies `Σ r_c` total);
  - gating (internal edges): `f(u→v) ≤ M·r_u` and `f(u→v) ≤ M·r_v`;
  - gating (source arcs): `f(S→root) ≤ M·r_root` — an unselected root carries no source flow;
  - `M = |free|`.
  This forces every selected cell to receive flow from a *selected* `th_root` through selected
  cells ⇒ the road set is one component reaching the Townhall.
- **Objective:** `minimize Σ_c r_c`.

The optimum's road *count* is deterministic (single-worker CP-SAT, fixed seed, proven
optimal); the specific cells may vary, which is fine.

## 4. Hypothesis and success criterion

**Hypothesis.** `route()` leaves ≥1 road cell of slack on real fixed placements, and the exact
model recovers it within a tractable budget.

**Headline success.** Exact solve returns **< 102** on the current best 102-road placement — a
new all-time best, valid and verified.

**Gate success (decides go/kill).** See §5 Stage-0 gate.

## 5. Design by stage

### Stage 0 — de-risk spike (cheap, no productionization)

Build the model as a throwaway and run it on the existing `output/roads-first/best-k*.json`
layouts (at minimum the **102**-road `best-k110-a102.json`; also e.g. `best-k112-a105`,
`best-k119-a108`). For each: reconstruct the fixed placement, solve the exact model
(single-worker, seed 0, per-layout time limit e.g. 300 s), and compare `exact_roads` to
`route()`'s count on the *same* placement. **Verify every exact solution is valid** —
reconstruct a `Layout` with the exact roads and assert `is_valid`, connectivity to TH, all
consumers covered, and `len == objective`.

**Pre-committed Stage-0 gate:**
- **Slack + tractable** (exact proven-optimal `< route()` on ≥1 layout, within budget) →
  **advance to Stage 1.** If it beats the 102 layout, that count is independently re-verified
  and recorded as a new best regardless of Stage 1.
- **Proven-optimal but equal** (`exact == route()` everywhere, solved to optimality) → **null,
  documented:** route() *is* optimal for fixed placement — do not productionize; redirect.
- **Times out** (no proven optimum within budget on darkzig-scale free sets) → the CP-SAT+flow
  encoding is the blocker, not the idea: record the sizes/times and decide whether to escalate
  the encoding (§6 B/C) or shelve. Do **not** claim a null from a timeout.

### Stage 1 — productionize (only if Stage 0 advances)

`foeopt/exact_router.py`: `exact_route(layout, *, time_limit, seed=0) -> dict[cell,int] | None`
returning the minimum road network (levels post-assigned), or `None` if not solved to optimality
within `time_limit` (caller falls back to `route()`). Wire it as **opt-in**:
- a post-hoc "polish any layout to minimum roads" entry (CLI + the roads-first/webapp result path);
- optionally, replace `route()`'s final call inside `validate()` behind a flag.
Per the 2026-07-06 gated-solver-extras policy, `ortools` is already a core dep, so no new
dependency; `route()` stays the default, `exact_route` is the opt-in upgrade.

**Stage-1 gate:** beats `route()` by ≥1 road on the darkzig best layouts **and** solves within a
production-acceptable budget (target: single-digit seconds for a polish step; document the
actual distribution). Fall back to `route()` on timeout so the pipeline never regresses.

## 6. Connectivity encoding — chosen and fallbacks

- **A — CP-SAT + single-commodity flow (chosen for the spike).** No new dependency, simplest to
  build, and the fixed-placement problem is small. Integer flow bounded by `|free|`.
- **B — Lazy connectivity cuts.** Solve cover-only; if the solution has a component not reaching
  the TH, add a cut (its boundary must select a neighbor) and re-solve; iterate. Often the
  fastest exact approach; more machinery (manual re-solve loop in CP-SAT).
- **C — HiGHS / Gurobi MILP + flow.** Flow LP relaxation is strong → fast at scale; a new
  dependency (`highspy` is open-source and light).

Start with **A**; escalate to **B** or **C** only if Stage 0 shows CP-SAT+flow can't prove
optimality within budget. The spike's timing data drives that choice.

## 7. Non-goals (scope fence)

- **No placement changes.** Placement stays fixed; this is orthogonal to the placement objective
  and the other levers. (Combining exact-router with a better placement is a later question.)
- **No joint model.** Deliberately the fixed-placement slice — that is the whole tractability
  argument.
- **Level optimization** is out: levels are post-assigned (§2), not optimized.
- **New pattern families / skeletons** are a different lever, untouched here.

## 8. Risks / open questions

- **route() may already be optimal** → Stage 0 is a null. That is an acceptable, informative
  outcome (settles the assumption), not a failure.
- **CP-SAT+flow tractability** on the largest free-cell sets is unproven; §6 B/C is the
  escalation path, and the spike measures it before any productionization.
- **Determinism:** single-worker + fixed seed for a proven-optimal solve makes the road *count*
  reproducible; note the winning layout itself may differ run-to-run (count is what matters).
- **Free-cell scarcity vs opportunity:** on a 90%-full city the free set is small, which is
  good for tractability but also limits how much rearrangement is possible — the slack may be
  only 1–3 roads. Even 1 road is a real result on a count that four experiments couldn't move.

## 9. Deliverables

- Stage 0: a throwaway spike script + a `tasks/lessons.md` entry with the per-layout
  exact-vs-route() numbers, solve times, validity verification, and the go/kill call.
- Stage 1 (if advanced): `foeopt/exact_router.py` + tests (matches `route()` when route is
  already optimal on a small fixture; strictly ≤ `route()` and valid on a fixture where it
  isn't; falls back to `None` past the time limit) + the opt-in wiring, gated by a real A/B.
