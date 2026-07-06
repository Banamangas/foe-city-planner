# Roads-First Feasibility Search — Design

**Date:** 2026-07-06
**Status:** Approved (brainstorm 2026-07-06; user decisions §2)
**Origin:** user idea ("build the road trunk/tree first with a set optimal number of roads, then try to
place all road-needing buildings next to the roads; if no solution, rebuild/iterate; if still none,
increase road count by 1"), refined against the project's evidence base (see §1).

## 1. Why this and why now

Every prior structural attempt died for one of two reasons: greedy inner placement (lanes/hybrid,
multi-trunk — attempts #4/#5: rigid structures + greedy attach never admit full placement) or joint
placement+routing coupling (CP-SAT ceiling ~11×11, attempt #6). This design keeps the user's roads-first
framing but fixes both killers at once:

- **The road network is FIXED per probe**, so the placement subproblem has no connectivity variables at
  all — it is pure 2D rectangle packing with an adjacency side-constraint, well within CP-SAT range as a
  *feasibility check* for darkzig's 63 consumers.
- **The inner step is EXACT**, so a failed probe is a proof (UNSAT), not "greedy didn't find it". The
  overhang/corner-contact assignments that greedy attach can never find (the trick by which the user's
  own city routes 142 < its Σ/2 = 157) are inside the solver's reach.
- **Iterative deepening on road count k** turns even a negative outcome into a certificate: "no
  comb-family network at k ≤ X admits full placement" is decisive strategic information about the
  153-road plateau, which no prior attempt produced (they all just lost).

Track B's closing rule ("any future attempt must explain how it creates slack rather than uses it")
is satisfied by construction: roads-first never packs wrong in the first place, so it needs no slack
to repair.

Benchmark: **darkzig only** (2720 region cells, 2437 building area, 283 free; 63 consumers,
Σ min-sides = 229; best-ever 153 roads, 0-unplaced). The user's own city is out of scope — 3 spare
cells put its feasibility boundary out of reach of any pattern family that doesn't reproduce its exact
network.

## 2. Locked decisions (user, 2026-07-06)

1. **Gate:** evaluated on the **achieved road count** (post-`route()`, §7.4) of the best validated
   layout found. ≤ **148** → win (keep the layout; spec productionization of the pattern search next).
   No validated layout below **153** → near-optimality certificate for the plateau within this family;
   the road objective closes with confidence. Best achieved in **149–152** → marginal: record, user
   decides. (The SEARCH iterates on pattern budget k; the GATE reads the achieved count, which can only
   be ≤ the k that produced it.)
2. **k-search:** downward from **152** (steps of −4 while feasible, then bisect the infeasible gap for
   the exact first-feasible k). Rationale: every feasible probe immediately beats the incumbent and
   yields a concrete layout; no budget is burned proving infeasibility at fantasy-low k.
3. **Pattern family:** **combs + TH corner stubs** (trunk × perpendicular branches, plus the user's
   verified 2-cell TH-flank stubs, each serving up to 3 buildings with TH-provided connectivity).
4. **Architecture:** approach C — external pattern enumeration + arithmetic pre-filter; CP-SAT does
   placement feasibility only. (Semi-parametric branch-length-in-model is the recorded fallback if
   probe counts explode; not built now.)

## 3. Deliverable

One throwaway script, `scripts/exp_roads_first.py`, run via `uv run --with ortools` — never a repo
dependency (per the 2026-07-06 gated-solver-extras policy, a gate win routes productionization through a
`[solver]` optional extra later; nothing in `foeopt/` changes now). Determinism: one seeded
`random.Random` for pattern sampling order; CP-SAT `num_search_workers = 1`, `random_seed = 0`.

## 4. Pattern generator (combs + TH stubs)

A **pattern instance** = `(th_footprint, frozenset[road_cells])`, constructed from parameters and
clipped to darkzig's irregular region:

- **TH anchor:** enumerated coarsely — 4 corner-most positions, offset-by-d variants (d ∈ {2, 4, 6}),
  and 2 mid-edge positions. The TH is placed by the pattern, not the solver.
- **Trunk:** axis (horizontal/vertical), line position, extent — a straight 1-wide segment starting
  orthogonally adjacent to the TH border.
- **Branches:** perpendicular 1-wide segments off the trunk; spacing ∈ {3..7}, sides alternating or
  single-sided; lengths distributed so the TOTAL cell count is exactly k after region clipping (trim or
  extend the last branches deterministically).
- **TH corner stubs (optional per instance):** the two flank cells at opposite ends of one TH side
  (the user's measured load-3 pattern); their cells count toward k.
- **Connectivity by construction:** trunk touches the TH border; branches touch the trunk; stubs touch
  the TH. No pattern needs a connectivity check.

Per k: sample up to `--patterns 200` instances (rng-ordered from the deterministic parameter grid),
AFTER the pre-filter (§5). Patterns that clip to fewer than k cells against the region boundary are
discarded (not padded arbitrarily).

## 5. Arithmetic pre-filter (no solver)

Reject a pattern in microseconds when any of these fail:

1. **Frontage capacity:** total free-cell frontage adjacent to the pattern's road cells ≥ Σ over
   consumers of min(w, l) — with per-cell capacity ≤ its free orthogonal neighbours.
2. **Per-branch two-sided capacity:** for each branch, the buildable depth on each side (clipped by
   region/TH) must admit at least the smallest consumer; branches with zero usable frontage are dead
   cells and the pattern wastes k.
3. **Area fit:** consumer area + k + filler area ≤ region cells (always true on darkzig by inventory,
   kept as a guard for other inputs).

## 6. CP-SAT placement feasibility (the core probe)

Roads fixed ⇒ each consumer's legal anchors are **precomputable**: for each orientation (w×l, l×w),
every anchor whose footprint is in-region, overlaps no road/TH cell, and has ≥1 border cell on a road
cell (the exhaustive version of the packer's `first_fit_adjacent` scan).

Model per consumer i: integer vars `(x_i, y_i)` + orientation literal, constrained by
`AddAllowedAssignments` over the precomputed candidate triples; `NoOverlap2D` across all 63 consumers
with orientation-dependent interval sizes. No routing, no connectivity, no fillers, no objective —
**feasibility only**. Outcomes:

- **SAT** → a candidate layout (validated per §7 before being believed);
- **UNSAT** → a proof this pattern admits no full placement;
- **timeout** (per-probe limit, default `--probe-limit 120` s) → **UNKNOWN**, recorded as such.

Fast-fail: any consumer with an empty candidate list ⇒ UNSAT without building the model.

## 7. Validation of every SAT result (acceptance conditions)

1. Build the full `Layout`: consumers at solver positions, roads = the pattern's cells, TH at the
   pattern's position.
2. **Gap-fill all fillers** (first-fit into remaining free cells, both orientations). Filler-fit is an
   explicit acceptance condition — "fillers always fit" was measured on grow-tree layouts and is NOT
   assumed for roads-first geometry. Any unplaced filler ⇒ the probe does not count as feasible
   (recorded distinctly as `SAT_FILLER_FAIL`).
3. `is_valid(layout)` must pass.
4. Run `route()` on the final placement: it may prune unused pattern cells, so the achieved road count
   can come in BELOW k — report both `k` (pattern) and `len(route)` (achieved). The gate is evaluated
   on the **achieved** count of the best validated layout.
5. Persist per accepted layout: JSON (positions + roads), an HTML render
   (`foeopt.viz.render_html`) under `output/roads-first/`, and a summary line.

## 8. Probe protocol and budgets

- Walk k downward from `--k-start 152` in steps of 4 while any pattern at that k validates; on the
  first level with no validated pattern, bisect between the last feasible and first failed k to locate
  first-feasible k exactly. If `--k-start` itself yields no validated pattern, walk UP in steps of 4
  (capped at 168) — a family that can't even match the incumbent's neighbourhood is itself a finding
  (family too weak; report and stop rather than burn the box).
- A k level counts as **infeasible** only if ALL attempted patterns return UNSAT. Any UNKNOWN
  (timeout) at the boundary weakens the certificate and is reported honestly ("first-feasible k is in
  [a, b]; certificate weakened by N timeouts"), never silently treated as UNSAT.
- Budgets: `--probe-limit 120` s per CP-SAT solve, `--patterns 200` per k, `--time-box 21600` s (6 h)
  total — on expiry, report the best validated k found plus the probe log.
- Every probe appends one JSONL row to `output/roads-first/probes.jsonl`: pattern parameters, k,
  status (SAT / SAT_FILLER_FAIL / UNSAT / UNKNOWN / PREFILTERED), solve seconds.

## 9. Gate recording

Whatever the outcome, append a `## Roads-first feasibility search (2026-07-XX)` entry to
`tasks/lessons.md` (probe-log summary, first-feasible k or its interval, the gate arithmetic, the
verdict, one paragraph of mechanism reading) and update `tasks/todo.md`'s Review section. Recompute
every derived number from the raw probe log (three prior entries had derived-number slips). On a win,
the found layout's JSON + HTML are the artifacts; productionization is a SEPARATE later spec through
the `[solver]` optional-extra policy.

## 10. Self-test (built into the script, `--selftest`)

- Tiny synthetic instance (TH + ≤4 consumers on a small region) whose true optimum roads are known via
  `rl.oracle.optimal_roads`: assert the probe pipeline finds a validated placement at some k with
  achieved `route()` count == the oracle optimum, and returns all-UNSAT at k below any feasible
  pattern. (The oracle repositions buildings freely, so family-vs-oracle equality is asserted on the
  tiny instance only where a comb trivially expresses the optimum — a 1-cell stub pattern.)
- Validation-pipeline check: a SAT result round-trips to a `Layout` that passes `is_valid`.

No pytest tests — throwaway-script discipline (same as `exp_lane_composition.py`); the self-test is
the validation gate before any real probe is trusted.

## 11. Out of scope

The user's own city; double-trunk / H patterns (recorded extension if combs stall against the region
boundary); the semi-parametric CP-SAT variant (recorded fallback); any `foeopt/` change; any
dependency change; the fillers-first idea (its region-cleaning insight survives as the §5 area
accounting); productionization of a winning pattern search (separate spec if the gate passes).
