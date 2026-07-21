# Roads-first placement objective — design

_2026-07-21. Track: R&D (beat the roads-first floor). Status: spec, not yet planned._

## 1. Motivation

The roads-first inner probe (`foeopt/roads_first.py:406`) is a **pure feasibility check**:
per-consumer anchor vars restricted by a table (`AddAllowedAssignments`), one
`AddNoOverlap2D`, **no objective**. It returns the *first* feasible placement CP-SAT
finds. The actual road count is then computed by `route()` in `validate()` — which
**ignores the skeleton** and greedily re-derives the minimal road network for that
specific consumer placement.

`lessons.md` (2026-07-07, "Road-efficiency metric + CP-SAT feasibility insight") already
identified the consequence and the lever:

> CP-SAT returns the *first* feasible placement, not the best. ... A different valid
> placement on the same skeleton could route lower. **Lever identified but not built:**
> add an *objective* to the CP-SAT model (minimize something correlated with post-`route()`
> road count — e.g. maximize shared road-cell adjacency).

**Why now.** The alternative — a provable lower bound to certify how close 102 is to
optimal — was investigated and rejected in this session as structurally infeasible on a
high-fill city (the connectivity term collapses under Townhall multi-rooting; the real
21→102 gap is filler-packing geometry, which every tractable relaxation removes). No cheap
bound or small-instance calibration can measure the gap. **So the placement objective *is*
the experiment that answers "does 102 have headroom":** if optimizing placement drops the
count, we found and captured room; if it plateaus across seeds, that plateau is the
strongest evidence available that 102 is near the comb family's achievable floor.

## 2. The risk this design exists to manage

Optimizing a **proxy** for the road count is the exact move that has burned this project
before:

- 2026-06-22, "Proxy-targeting packer heuristics keep hurting the real objective": four
  attempts (short-side-facing, B1 pairing-bias, structured lanes, hybrid) improved a proxy
  (adjacency, sharing, "% facing short side") and made the measured `route()` road count
  **worse**. Standing rule: *"don't trust proxy metrics ... only the measured 0-unplaced
  road distribution across seeds counts."*
- 2026-06-22, "Structured double-row packer (lever B)": the size-bucketed straight-lane
  double-row packer — which is essentially the player's own hand-building heuristic
  (same-size clustering, spaced double-loaded lanes) — was prototyped and **lost to the
  greedy grow-tree four times**.

Two things make this attempt different from the killed ones, and the design must preserve
both or it is just lever B again:

1. The objective lives inside the **exact CP-SAT placer**, as a *soft* objective — the
   solver finds the best clustering *that still fits* the irregular boundary, rather than a
   greedy constructor rigidly reserving bands that over-commit.
2. Nothing is trusted on proxy value. Every proxy is **measured against real `route()`
   output before any CP-SAT objective code is written** (Stage 0), and the final decision is
   an **equal-wall-clock A/B on the true road count** (Stage 2).

## 3. Hypothesis and success criterion

**Hypothesis.** For a fixed skeleton, there exist feasible consumer placements that
`route()` scores strictly below the first-feasible placement, and a placement objective can
steer CP-SAT toward them, netting a lower achieved road count **at equal wall-clock** despite
slower per-probe solves.

**Headline success.** Reproducibly beat the robust roads-first floor on darkzig
(~105–108; 102 stands as portfolio-luck) at equal wall-clock.

**Gate success (what actually decides go/kill).** Relative, not absolute: objective-on
lowers mean achieved roads vs. the objective-off (first-feasible) baseline on the same
search, at equal wall-clock, without regressing feasibility (§6).

## 4. Candidate proxies

All four are computed on a *finished placement* — pure Python geometry, needing **no CP-SAT
objective** — so Stage 0 can rank them (running only the existing feasibility model to
*produce* placements) before any objective is encoded. Only the Stage-0 winner is later
expressed as a CP-SAT objective (§5), which is the harder linearization.

Let `a[i,c] = 1` iff consumer `i` sits orthogonally adjacent to skeleton road cell `c`.

- **P1 — Sharing / min touched cells.** `u[c] = OR_i a[i,c]`; minimize `Σ_c u[c]`. Direct
  proxy for the coverage portion of the road count (fewer distinct road cells carrying a
  consumer).
- **P2 — Subtree.** As P1, plus tree-closure toward the Townhall on the skeleton
  (`u[c] ⇒ u[parent(c)]`, parent = next cell toward TH on the pattern's spanning tree);
  minimize `Σ_c u[c]`. Counts coverage cells **plus** the connectors/trunk linking them —
  closer to what `route()` actually emits. Connectivity here is over the ~110 fixed
  skeleton cells (cheap ancestor-closure on a tree), **not** the 2720-cell region that made
  `minroads.py` memory-catastrophic. `route()` may still beat any skeleton subtree (it
  ignores the skeleton), so P2 is an upper proxy `route()` can only improve on.
- **P3 — Double-loaded contiguity.** `dbl[c] = 1` iff `c` has consumers on both
  perpendicular sides; reward `Σ_c dbl[c]` and reward adjacent runs
  (`Σ dbl[c]·dbl[next(c)]`). Encodes the player's straight double-loaded rows.
- **P4 — Same-size lane clustering.** Reward same-footprint consumers sharing a lane /
  aligned on the trunk-perpendicular axis. The player's #1 heuristic, as a *road* proxy: a
  lane of equal-depth buildings double-loads cleanly (every road cell serves exactly 2, no
  ragged frontage), where mixed sizes waste part of a cell's length. `O(same-size-pairs)`
  reward terms.

The objective ships with the **fewest terms that predict best** — every extra term enlarges
the model and slows the probe, and slower probes lose the equal-wall-clock A/B. That tension
is the whole reason to measure first.

## 5. Design by stage

### Stage 0 — proxy correlation study (cheap, no objective code)

Answers two questions before committing: **(a) is there any room** (can a better placement
beat first-feasible at all?), and **(b) which proxy captures it**.

Protocol:

1. Sample `M ≥ 30` comb skeletons via full-TH generation at k-levels spanning the frontier
   (e.g. `k ∈ {112, 118, 125}`).
2. For each skeleton, collect `N ≥ 20` distinct feasible placements — CP-SAT solution pool
   (`CpSolverSolutionCallback`) or `N` re-solves under varied `random_seed`. No objective;
   this is the existing feasibility model.
3. For each placement `p`: record `route()` roads `r_p` and every proxy value.
4. Per skeleton compute:
   - `oracle_gap = r(first_feasible) − min_p r_p` — the road reduction available purely by
     choosing a better placement on that skeleton (a conservative floor: only over sampled
     placements).
   - Per proxy: Spearman rank-correlation between proxy and `r_p` across the `N` placements,
     and `r` of the placement the proxy would select.
5. Aggregate across skeletons: mean `oracle_gap`; per proxy, mean realized reduction
   (`r(first_feasible) − r(proxy-selected)`) and mean rank-corr.

**Pre-committed Stage-0 gate:**
- If mean `oracle_gap < 1.0` road → **KILL the whole lever.** First-feasible is already ~best
  on each skeleton; no objective, on any proxy, can help. (This would itself answer the
  headroom question: 102 is placement-optimal for the comb family.)
- Else advance every proxy that (i) captures `≥ 50%` of `oracle_gap` in mean realized
  reduction and (ii) has mean rank-corr `≥ 0.4`. If several qualify, prefer the cheapest
  CP-SAT encoding (P1 is cheapest — a plain `Σ u[c]`; P4 the most expensive — `O(pairs)`
  terms).
- If `oracle_gap` is large but no proxy captures it → the signal exists but our proxies miss
  it; document and stop before Stage 1 (a new proxy is a new spec, not a tuning loop here).

### Stage 1 — CP-SAT integration (only if Stage 0 advances a proxy)

Add the winning proxy as an **opt-in** objective on `probe()`, default off, byte-identical
to today when off (the project's standard flag pattern; same discipline as
`symmetry_breaking`, `stub_priority`).

Two changes to manage:

- **Adjacency variables.** The proxies need `a[i,c]`, which the current integer-anchor +
  `AddAllowedAssignments` table doesn't expose. Introduce per-option one-hot selectors (or an
  equivalent channelling) so adjacency is linear in the placement. This is the model-growth
  cost the equal-wall-clock A/B will weigh.
- **Feasibility must not regress.** With an objective, CP-SAT may reach *first feasible*
  slower and, under a tight per-probe cap, return UNKNOWN where the pure-feasibility model
  returned SAT fast — the documented "added structure hurts an already-efficient search"
  pattern. **Required mitigation:** the objective probe must seed from a first-feasible
  solution (solve feasibility fast → `AddHint` that incumbent → optimize with remaining
  budget), so an objective probe is never worse than first-feasible on feasibility and its
  road count is monotonically ≤ first-feasible. The k-walk's SAT/UNSAT/UNKNOWN accounting and
  "best `route()` over probes" logic are otherwise unchanged.

### Stage 2 — equal-wall-clock A/B gate (the real decision)

The project's standard A/B, objective-on vs objective-off, on the **true** road count:

- darkzig, `≥ 3` seeds, equal total wall-clock per arm (e.g. `1800s ×2`, reproduced), report
  the 0-unplaced achieved-roads distribution per arm and per-probe SAT/UNSAT/UNKNOWN mix.
- **Win** (pre-committed): `mean(on) ≤ mean(off) − 2` **AND** `max(on) ≤ max(off)` **AND**
  feasibility not regressed (objective-on UNKNOWN-rate not materially higher at equal
  budget). Matches the Track-B gate arithmetic (2026-07-06).
- **Kill** (pre-committed): otherwise the flag stays opt-in/off, the lever is closed with a
  documented null in `lessons.md`. **No tuning marathon** — revisiting needs new evidence,
  same rule as every prior closed lever.

## 6. Explicit non-goals (scope fence)

Kept out to keep this one clean, isolated experiment (and because some are known dead ends):

- **Filler packer upgrade.** The player's same-size / gap-filling expertise maps most
  directly onto `validate()`'s greedy first-fit filler step (`:489`) — the crude packer that
  strands the unusable 1×1/2×1 gaps they avoid by hand. It affects *feasibility* (SAT
  acceptance at tight k), not the road count directly. Real weakness, strong follow-up, but
  it is lever B's home turf and a scope expansion — **not this experiment.**
- **Lane spacing matched to the consumer depth histogram.** A cheap pattern-generator tweak
  (replace the blind `{3,4,5,6,7}` spacing sweep with sizes derived from the actual
  inventory). Separate spec.
- **Large-neighborhood same-shape swap moves** (the player's 2×1↔3×1 reconfiguration). A
  local-search lever; a small version (same-footprint swaps) already exists in the
  hill-climber. Not the objective.
- **Production latency.** The objective makes probes slower; this is an R&D floor-finding
  lever. If it wins, productionization (lightweight objective, warm-started) is a later spec.
  Per the 2026-07-06 gated-solver-extras policy, `ortools` stays as-is; `foeopt/` core keeps
  working with the flag off.

## 7. Risks / open questions

- **The objective may be redundant with skeleton tightness.** The current k-walk already
  forces sharing implicitly (a tight skeleton leaves few anchor options). If tightness alone
  is near-optimal, `oracle_gap` will be small — Stage 0 catches this before we build
  anything. (A follow-up, out of scope: a *generous* skeleton + explicit objective, which
  inverts the walk direction — only worth it if Stage 0 shows large `oracle_gap`.)
- **Encoding cost may swamp the gain.** The one-hot adjacency channelling could slow probes
  enough that the equal-wall-clock A/B loses even with a good proxy. That is the honest
  question Stage 2 exists to answer; it is not pre-judged.
- **`route()` is a moving target.** Because `route()` re-derives roads independently of the
  skeleton, a proxy can only ever be correlated, never exact. Stage 0 measures how strong
  that correlation actually is rather than assuming it.

## 8. Deliverables

- Stage 0: a throwaway study script + a written correlation report (`oracle_gap`, per-proxy
  rank-corr and realized reduction) → a `lessons.md` entry with the go/kill call.
- Stage 1 (if advanced): opt-in objective in `probe()` + tests (off = byte-identical;
  on = correct proxy value; feasibility-not-regressed on a fixture).
- Stage 2: the A/B numbers + a `lessons.md` entry with the pre-committed verdict.
