# Lessons

## FoE data model

### Road-need detection: `connected` key AND currently road-adjacent (derived from the valid layout)
- **Mistake 1:** Derived "needs a road" from `CityEntities[id].requirements.street_connection_level` → only 16 buildings (Great Buildings/military/Townhall). That field is absent for event buildings.
- **Mistake 2:** Switched to "has `connected` key" → 99 buildings, but this **over-counts by 11**: the Yukitomo residences (`W_MultiAge_WIN24A13` *Yukitomo Impérial*, `W_MultiAge_WIN24A14` *Résidence Céleste Yukitomo*) have `connected=1` yet are buried with no adjacent road, and the player confirmed they do **not** need roads. Event-building defs carry no road/street info at all.
- **Correct rule (player-confirmed):** a building needs a road **iff** it has a `connected` key **AND** is orthogonally adjacent to a road tile in the input layout. Computed once at load, treating the export as a valid layout; then a fixed per-building property. Sample city: **80 consumers + Townhall**.
- **Key data fact:** the 2×2 of (`connected` key) × (road-adjacent) had **0** in the "no key + road-adjacent" cell — roads are placed only where needed, so the rule is unambiguous.
- Road *level* = def `street_connection_level` if present, else default 1.

### Off-grid = footprint anchor outside the buildable region
- **Mistake:** Excluded off-grid by a type list (`off_grid`/`outpost_ship`/`friends_tavern`) + `coords < 200`. This missed the settlement **hub** structures (`hub_main`/`hub_part`: *Port de l'arctique*, *Terminal océanique*) which have in-range coords but sit outside the unlocked region.
- **Correct rule (player-confirmed):** a building is on-grid (movable, optimization-relevant) **iff its footprint anchor `(x,y)` is inside the buildable region** (union of `UnlockedAreas`). Anything else is off-grid, immovable, ignored. One test replaces the type list and catches hubs + the other ~10–13 off-grid buildings.

### Townhall does NOT substitute for a road
- **Mistake:** Assumed a building adjacent to the Townhall footprint counts as connected without a road tile.
- **Reality:** Every road-needing building must be orthogonally adjacent to an actual **road tile**. The Townhall is only the network **origin** — the road network must connect back to it, but touching the Townhall does not satisfy a building's road requirement.

### Building footprint size resolution
- Top-level `width`/`length` exists for ~1446 defs only.
- Multi-age buildings store size in `components.<Age>.placement.size` → `(x, y)`, constant across ages.
- Resolution order: top-level `width`/`length`, else any component's `placement.size`. Resolves 100% of placed buildings.

### FoE omits the x (or y) coordinate when it is 0 — don't require both keys
- **Symptom:** User reported buildings missing on the **left side** and **top line** of the map; building count was 292 but should be 314.
- **Misdiagnosis (avoid repeating):** I first assumed it was a colour-contrast problem (non-road `#555` vs region `#3a3a3a`) and "fixed" the palette. That was wrong — it addressed a real but secondary issue and did NOT restore the buildings. **The count (292 vs 314) was the decisive clue I should have checked first.**
- **Root cause:** `city-user-data.json` **omits the `x` field when x=0 and the `y` field when y=0** (same zero-omission convention as `unlocked_areas`). `build_layout` required both keys present, silently dropping all 22 buildings on the x=0 column (left edge) and y=0 row (top edge) — including 2 Great Buildings.
- **Fix:** `x, y = e.get("x", 0), e.get("y", 0)`, then exclude by region membership. Verified: 0 entities have *neither* coord, edge cells are in-region, result = 314 buildings / 82 road-needing consumers.
- **Lessons:**
  - When a **count** is off, chase the count directly — it localises the bug faster than reasoning about symptoms (rendering, contrast).
  - Apply the zero-omission rule **everywhere** coordinates are read, not just `unlocked_areas`.
  - For a visual bug, render the real output to a PNG and inspect it (this did confirm the buildings once coords were fixed).

### Map contrast (secondary improvement, kept)
- Non-road buildings were `#555` on region `#3a3a3a` (channel distance 81) — low contrast. Hoisted the palette into testable `foeopt/viz.py` constants; non-road buildings are now amber (`#d89b3c`) on darker region (`#262626`). Regression guard measures **channel-sum distance ≥150** (string inequality is useless: `#555` != `#3a3a3a` is "true" yet they look identical).

### Process lesson
- When a derived count "feels off" or contradicts domain knowledge (FoE: most buildings need roads), validate against the live game-state signal before designing around the metadata-derived value.

## Packer config comparisons must use a 0-unplaced budget (2026-06-20)
**Mistake:** Merged "short-side-facing attachment" believing it cut DarkZig roads 165→154, based on a 20s-budget A/B. Those layouts were PARTIAL (unplaced>0). Because `repack` scores by `(unplaced, roads)` — placement first — a short budget returns an incomplete layout whose road count is artificially LOW (fewer buildings = fewer roads). The comparison was meaningless. A clean A/B at a 0-unplaced budget showed short-side is actually WORSE (best 167 vs 159, mean 177 vs 169, and it even left a seed unplaced). Reverted.
**Rule:** When comparing packer/`repack` configurations, ALWAYS use a budget large enough that every seed reaches `unplaced == 0`, and compare only 0-unplaced results. Never compare raw road counts across runs without checking `unplaced` — a lower road number with unplaced>0 is a worse (incomplete) layout, not a better one.

## Proxy-targeting packer heuristics keep hurting the real objective (2026-06-22)
**Pattern:** Twice now, attachment heuristics that improve a *proxy* for road efficiency have made the real objective (0-unplaced road count) WORSE: short-side-facing (improved building-road adjacency 302->273, but roads 162->167 and slower placement) and B1 pairing-bias (targets road-cell sharing 1.79->2.0, but roads 162->191 best and broke placement on 4/8 seeds). Both fight the grow-tree's strength: free, dense, greedy placement.
**Rule:** For the packer, don't trust proxy metrics (adjacencies, sharing, "% facing short side"). Only the measured 0-unplaced road distribution across multiple seeds + budgets counts. Prototype any attachment-heuristic change as a throwaway and A/B it that way BEFORE building. The constructive packer's practical floor on DarkZig is ~158-162 roads; the Σ(min-side)/2 = 114 "estimate" assumes perfect double-row tiling of heterogeneous footprints, which is geometrically unreachable for a greedy constructive packer — reaching it would need a fundamentally different joint placement+routing optimizer, not another attachment tweak.

## Structured double-row packer (lever B) prototyped and lost to the grow-tree (2026-06-22)
**Tried:** a size-bucketed straight-lane double-row packer emulating the user's expert heuristics (group same-size buildings, both-sides roads, straight lanes, TH offset, trunk). Two prototypes: pure lanes (left 25 road-needing unplaced on DarkZig — the odd-sized tail doesn't bucket) and hybrid bands+greedy-tail (DarkZig best 185 vs current 158, and 12/12 partial on the sample city — couldn't fit it at all).
**Conclusion:** the heuristics describe what a GOOD layout looks like (the user hand-builds 142 on their bucket-friendly sample), but AUTOMATICALLY constructing one is the hard part: rigid bands over-reserve and don't conform to the irregular region boundary, and diverse cities (DarkZig/FutureEra) have a long tail of unique-sized road-needing buildings that won't tile. Four structured/biased attempts now (short-side, B1 pairing, lanes, hybrid) have all LOST to the greedy grow-tree. ~158 (0-unplaced, DarkZig) is the practical automatic floor for this architecture; reaching ~142 would need a fundamentally different global optimizer, not another constructive heuristic. Stop relitigating lever B.

## Incremental scoring: memoization + delta free-cells (Task A, 2026-06-23)
**Goal:** evaluate far more candidate moves per time budget without changing any output (the search re-routed the whole tree per candidate). Done in two output-preserving stages; both gated by a *golden corpus* — 400 full `route()` road dicts (sample city + seeded single-move perturbations), sha256-compared before/after every change.
**Stage 1–2 (memoization, exact):** `Footprint.cells()`/`border_cells()` and the consumer→Townhall sort key are pure functions of small ints, recomputed ~200×/route across candidates that differ by one building. Memoized with `functools.lru_cache` (Footprint is `frozen` ⇒ hashable). Result: **route() 5.165 → 1.335 ms/call (3.87×)** on the sample city, road dicts byte-identical.
- **Why returning cached `frozenset`s is output-exact (verified, not assumed):** route() picks a connector via `next(t for t in targets if t in tree)` and seeds the BFS from `th_roots`/`tree` — both iteration-order-sensitive, and `targets`/`th_roots` derive from `border_cells()`. CPython `set` and `frozenset` share one table implementation, so building either by inserting the *same elements in the same order* yields the *same* iteration order; the cached frozensets are constructed identically to the originals. The golden corpus is the proof, not the reasoning.
**Stage 3 (incremental free-cells, exact):** the bottleneck wasn't only `route()` — `random_move`/`move_building`/`swap_buildings`/`free_cells` each rebuilt occupancy from all ~314 buildings *every iteration* (`_cells_except`, `occupied_cells`, `cells()` called ~1.4M times in a 5 s anneal). Fix: maintain the free-cell set for the accepted state and derive each candidate's free set by an **O(footprint) delta** (`(free | old_cells) - new_cells` for a move; unchanged for an equal-footprint swap), then pass it to `route(layout, *, free=...)`. `route(cand, free=F)` is byte-identical to `route(cand)` when `F == free_cells(cand)` — the achievable form of the "incremental agrees with the full route() oracle" requirement.
- **Determinism preserved exactly:** `_random_move_free` draws from the RNG in the identical sequence as `random_move`, and `state_free == free_cells(state)` is an invariant (asserted: `cand_free == free_cells(cand)` over 5000 random candidates), so the SA trajectory is bit-identical to before — not merely reproducible.
- **Measured end-to-end (sample city):** anneal **113 → ~894 candidate evals/s (~7.9×)**, optimize ~1030 evals/s; final road counts unchanged (sample stays 142→142). The never-worse anchor and all golden counts hold.
**Rules:** (1) for any "speedup" touching set/dict geometry, capture a full-output golden corpus and diff it — set iteration order is load-bearing here and string-inequality intuition is useless. (2) incremental scoring that must preserve output = cache/delta the *inputs* to the scorer (free cells, footprint geometry); do NOT approximate the scorer itself (a local road-tree repair cannot match the greedy global `route()` and would break the oracle + determinism gates).

## No-op same-footprint swaps are 72% of the hill-climber's swap candidates (2026-06-23)
**Observation:** `same_footprint_swaps` pairs every equal-size non-Townhall building, but a swap can only change the road count if the two buildings differ in `(needs_road, road_level)` — otherwise they are interchangeable to `route()` (occupancy and the road-requirement set are unchanged) and the swap is a *strict* no-op (measured: 0/300 random no-op swaps changed the count; 5913 of 8193 swap candidates on the sample city are no-ops). The hill-climber would only evaluate and reject them.
**Fix:** filter swaps to differing-`(needs_road, road_level)` pairs in `_candidate_moves` (the only consumer; `random_move`/anneal builds its own groups and is untouched). Output-preserving for `optimize` — a no-op swap yields `roads == best`, never `< best`, so the first *improving* move is unchanged — proven by capturing optimize's full output (positions+roads+moves) on the sparse and a mixed fixture before/after: identical, with `evaluated` dropping 43→28, 16→12, and bundled-city 5356→2354 in a fixed budget (so a no-improvement pass can now actually *complete* instead of timing out mid-scan).
**Note:** swaps still matter — in a *dense* city they are the only way to drop a road-needing building into a good spot that is currently occupied by a filler (a "move" needs an empty target). Only the same-relevance pairs are dead weight.

## Placement-quality checker: two player-stated rules, measured not enforced (2026-06-23)
**Rules (player-stated):** (1) a building that does NOT need a road must never be orthogonally adjacent to a road tile — except the Townhall, which is always road-adjacent because the network roots at its border; (2) every road tile should be adjacent to >=2 buildings (the double-row ideal), the sole exception being a junction tile whose other 3 orthogonal neighbours are all roads (3 roads + 1 building). `foeopt/quality.py` grades a layout against both; surfaced in the `roads`/`layout`/`improve` CLI output and tested.
**Measured (the point of measuring first):** the bundled hand-tuned city scores **0 violations on both rules** (0/231 fillers touch a road, 0/142 roads are under-used) — independent confirmation the rules match real expert play, and a clean regression anchor. The from-scratch constructive packer's re-pack of the same city scores **59/105 (~56%) under-used roads** — a concrete number for the road-inefficiency lessons.md keeps describing qualitatively.
**Why a checker, not packer enforcement:** these are exactly the adjacency proxies that regressed the real road count in 4 prior packer attempts (see the lever-B entries above). The rule is "measure first": the checker is the metric any future enforcement must be A/B'd against — do NOT bake these into `build_candidate`/the search objective without showing the 0-unplaced road distribution doesn't get worse.

## Packer experiment with the new metric: unplaced are 100% consumers; multi-trunk loses (2026-06-23, attempt #5)
Used `quality.py` + a throwaway harness to take a disciplined run at the packer. Three findings, all reinforcing "stop relitigating lever B":
- **The bundled city is a 97%-full perfect-packing puzzle** (building area 4079 + 142 roads ≈ 4224 region cells, 3 spare). A greedy constructive packer cannot solve that; not a tuning issue.
- **The unplaced buildings are 100% consumers, 0% fillers** (every seed). This kills the review's suggested Task-B fix (a better *filler* packer like skyline/BLF): fillers already place perfectly, so a filler packer helps *nothing*. The whole failure is road-needing co-design. Stranded consumers include the *common* sizes (25× 4×4, 13× 6×4), not just the odd tail. **More trials don't help** — best unplaced is stable at 20 from 4 trials (10 s) to 10 trials (40 s); it's a structural floor, not a multi-start floor.
- **Multi-trunk road growth loses to the bottom-left corridor.** A/B on the real city (same configs): baseline min/mean unplaced 60/75 vs horizontal 64/76, spread 71/78, vertical spine 67/67. The `spine` variant is *more consistent* (tight 67) but never reaches the baseline's lucky lows — and a multi-start packer keeps the best trial, so consistency is worthless; high-variance bottom-left growth is what occasionally reaches 20. Nothing integrated (all strictly worse, violating the measure-first guard).
**Bottom line:** the constructive grow-tree + multi-start is genuinely hard to beat on placement; the road inefficiency it does have (single-row corridors) is inherent to greedy placement, and every structural fix tried (now 5: short-side, B1 pairing, lanes, hybrid, multi-trunk) has lost. Beating it needs a fundamentally different optimizer (e.g., CP-SAT on sub-regions, a heavy non-stdlib dependency), not another growth heuristic.

## CP-SAT (OR-Tools) scoped and a hybrid tiler prototyped — both dead ends (2026-06-23, attempt #6)
Followed the "CP-SAT on sub-regions" idea above to its conclusion with throwaway prototypes (ortools via `uv run --with`, never added to the repo deps).
- **The joint placement+routing CP-SAT model works and is a useful *oracle*.** On a fair, roomy 11×11 instance (TH + 10 buildings, 33% fill) it proves the optimum is **5 roads, all placed**, vs the constructive packer's **11 roads + 1 stranded** — i.e., the greedy packer is ~2× off optimal on fair inputs. This is the principled baseline the 97%-full bundled city cannot provide (that city is near-unbeatable by construction, so it must NOT be used as a packer baseline — use small roomy instances with CP-SAT optima instead).
- **But CP-SAT does not scale.** Provable optimality holds only to ~11×11 / 6 buildings (8 s); 13×13/8 already times out at 30 s unproven; 18×18 returns junk (51 roads). A city *quarter* (~32×32, ~80 buildings) is ~30× past the ceiling, so "solve quarters and tile" is not viable.
- **Hybrid tiler (decompose → CP-SAT each ~11×11 tile → global route()) fails on correctness.** On a 22×22/20-building instance it *does* place all buildings (CP-SAT tiles pack fully, beating the greedy packer's stranding) — but **5 of 6 runs produce non-routable layouts**: per-tile road-adjacency does not compose into global connectivity ("cannot reach b15"), and CP-SAT packs buildings flush against the Townhall ("no free cell to root"). Connectivity to the Townhall is inherently **global**, so tiling breaks exactly what it was meant to sidestep. Roads were also inefficient (61–70 vs ~20 estimate) and CP-SAT's multi-worker solve is non-deterministic (violates the determinism gate).
**Bottom line (attempt #6):** the packing+routing problem is globally coupled (TH connectivity is global) AND the joint form is NP-hard (CP-SAT ceiling ~11×11), so neither decomposition nor exact solving cracks the real city. The grow-tree is a reasonable heuristic for a genuinely hard problem; `route()` is already near-optimal for *fixed* placement. **Packer replacement is closed** — the durable wins are elsewhere (router speed, the quality metric, anneal refinement on a given placement).

## Realistic benchmark: darkzig (90% fill, badly-built) — the pipeline DOES work (2026-06-23)
**Earlier packer conclusions were skewed by a bad benchmark.** `city-user-data.json` is 97%-full and hand-tuned — a perfect-packing puzzle where the constructive packer can *never* reach 0-unplaced, which made it look useless. `darkzig.json` (player-pushed, gitignored locally: 224 buildings, 63 road-needing, **90% fill, deliberately badly optimized**) is realistic for what the tool is actually used on. Benchmark the packer HERE, not on the bundled city.
Full pipeline on darkzig (target Σ(min-side)/2 = **114**):
- input **250** roads (63 Rule-1 violations — fillers touching roads — vs 0 on the tuned bundled city; the metric tracks real waste)
- Phase-1 `route()` (fixed positions): **236**
- Phase-2 `repack` 120 s / 99 trials: **169**, 0-unplaced (Rule-1 10, Rule-2 9). **More trials help here** (30 s→196, 120 s→169), unlike the bundled city where unplaced is structurally stuck — so budget matters when the city has slack.
- `polish` (repack 60 s + the Task-A-accelerated anneal 60 s): **158**, 0-unplaced, clean (Rule-1 8, Rule-2 7). The anneal finisher saves 169→158.
**So the tool cuts a badly-built city 250→158 (−37%), fully placed, clean quality** — the genuine value the bundled city hid completely. The remaining 158-vs-114 gap (~38%) is the real target for the advanced methods (LNS+CP-SAT etc.), and darkzig's repack/polish output is exactly the valid 0-unplaced *start* those methods refine.
**Rules:** (1) benchmark the packer on a high-slack realistic city (darkzig), never the 97%-full bundled fixture; (2) compare only 0-unplaced results; (3) on a slack city, more trials / budget genuinely lower roads.

## LNS+CP-SAT validated on darkzig, doesn't beat the polish plateau (2026-06-23, attempt #7)
Built a deterministic LNS+CP-SAT (ruin-and-recreate: free a window of buildings, re-solve placement+roads with CP-SAT single-worker+`random_seed`, fixed surroundings supply global connectivity, accept on global `route()` improvement) and validated on darkzig BEFORE productionizing.
- **Naive random windows:** 169→164 — only **2 of 7756 windows accepted**. The repack start is already a good local optimum; almost no small window yields a global road reduction.
- **Targeted (windows around under-used roads / spurs, via `quality.py`) + lateral-move acceptance:** 169→162 (3 improving, 2762 lateral), then `+anneal` → **157**. So the full LNS+CP-SAT+anneal pipeline reaches **157 vs the existing repack+anneal polish's 158** — a **1-road (0.6%) gain** for a heavy ortools dependency + ~180 s. The LNS barely moves (169→162); the anneal does most of the work.
**Verdict: NOT productionized** (no repo code; scratchpad only). Root cause is the recurring one — global coupling + CP-SAT's ~11×11 window ceiling means local re-optimization can only make small local fixes, which the Task-A-accelerated anneal already does more cheaply. **~158 is the practical floor for local methods on darkzig.** Reaching the Σ/2=114 target needs a *global* method (an amortized ML/RL solver — the chip-floorplanning playbook), not more local search. Measure-before-build paid off: a 1-road win does not justify the dependency.

## RL placement (M2-M4) archived: the gate failed by its own rule (2026-07-02)
**Evidence (training logs, ROCm GPU):** curriculum stages learn, but at moderate
fill the policy places 80-86% of episodes with mean_roads ~3x target; at
darkzig-like fill 0.7-0.9 success is 0% everywhere (training_bridge.log,
training_m4.log); every greedy darkzig eval ends stuck/unroutable. The designated
rescue lever - imitation warm-start from repack experts (rl/imitate.py, BC top-1
acc 45.8%) - collapsed to 6-12% success under PPO fine-tuning (training_bc_rl.log),
likely catastrophic forgetting. Per the design's fail-fast rule (spec 2026-06-23
section 9.4), that exhausts the track.
**Root cause (same wall as attempts 1-7):** the policy never observes road
structure during an episode (roads are computed only at the terminal step), so at
90% fill it cannot learn to leave road channels; the -100 trap returns as soon as
the fill rises. Fixing that means changing the formulation (roads in the
observation, routability-preserving action masking, DAgger), not the knobs.
**Rule:** don't resume RL training on this formulation. If RL is ever revisited,
it must include the routability mask (foeopt/reach.py, 2026-07-02 spec) and
road-visible observations, and it competes against the Track-A structured
optimizer, not against random rollouts.

## Road-target calibration + A1 composition verdict (2026-07-03)

**BLOCKED — the A1 pessimistic-trunk family model is INFEASIBLE on the
calibration input, so the calibration factor `f` cannot be computed and no
gate verdict was written.** `scripts/exp_lane_composition.py
city-user-data.json city-user-data-foe-helper.json --time-limit 300` (the
brief's Step-1 command, 82 road-needing consumers, real expert answer 142)
returns `status: INFEASIBLE`, `model_optimum: null`. Confirmed this is not a
sizing-knob artifact: re-run with `--lanes 20 --stack-max 300` is still
INFEASIBLE. The binding constraint is the model's own region-area-fit guard
(`total ≤ region_free_cells`), which on the user's city is `145` (4224 region
− 4079 building area; the real 142-road answer leaves only 3 cells of slack)
and is not adjustable from the CLI. Per the calibration spec's own stop rule
(§3.4: "if the model can't get within ~25% of 142... stop and redesign before
reading any darkzig number") and the escalation contract for this task, the
darkzig numbers were **not** used to compute `C*` and no go/kill verdict was
written — this is a harder failure than "`f` outside [0.75, 1.33]": there is
no `f` to be outside anything.

**Root cause, diagnosed against the T2 sharing histogram
(`sharing_histogram`, measured 2026-06/pinned in `tests/test_quality.py`):**
the user's real layout is essentially all double-loaded lane — hist
`{1:1, 2:137, 3:4}`, avg load 2.02, **0 overhead cells** — i.e. the real
network spends only ~5 of 142 cells on anything but a perfect double row.
The A1 pessimistic-trunk formula (`Σ over used lanes of (depthA + 1 +
depthB)`) charges every lane a fully exclusive trunk allocation and credits
*zero* cross-lane trunk sharing. Relaxing the area guard to see the model's
own unconstrained answer for the same 82-item inventory (diagnostic only, not
an official Step-1 run): best-found after 300s is `total=205`
(`proven_bound=166`, `gap=39`, not solved to optimality) with
`trunk_pessimistic=41` (vs the real ~5 overhead cells — an ~8x overcount) and
lane cells ≈164 (vs the real double-loaded portion of 137, a further ~20%
overcount from the rigid uniform-depth-per-lane-side constraint). Both errors
compound on a city with only 3 cells of slack, so the family model can't find
*any* feasible point even though the real solution fits with room to spare.

**Recorded for reference, not used in any gate math:**
`comp-darkzig.json` (300s): `model_optimum=160`, `proven_bound=124`, `gap=36`,
`trunk_pessimistic=32`, `optimistic_total=132`, `stub_cells=0`.
`comp-darkzig-stubs.json` (300s, `--stubs`): `model_optimum=61`,
`proven_bound=41`, `gap=20`, `stub_cells=18` — degenerate: the stub-slot cap
(`stub_cells <= 2*used_lanes`) rewards opening many minimal single-item lanes
purely to unlock stub capacity, matching the design doc's own warning that the
stub scenario is a sensitivity check, not a base-model number. `report_bounds`
(`foeopt/bounds.py`, adjacency bound only): darkzig max=21, user city max=28
(both well below their known-achievable 158/142, i.e. the bound itself is
sound — the composition model's trunk term is the specific defect, not the
bounds).

**Rule:** before trusting any A1 number, fix the trunk-cost term to credit
cross-lane sharing (e.g. shared boundary between adjacent stacked lanes, or an
"optimistic-trunk-minus-sharing" formula actually derived from the geometry
rather than guessed) and re-run calibration on the user's city first — a
composition model whose own best score on the *known-142* input isn't even
region-feasible cannot be trusted to rank a `C*` on darkzig. Do not read or
act on the darkzig `model_optimum`/`C*` numbers above until calibration
passes; they are recorded here only so the next attempt doesn't have to
re-run the 300s solves.

## v2 calibration + A1 gate verdict (2026-07-05)

**Verdict: KILL Track A.** This was the pre-committed one-iteration,
time-boxed retry (spec `docs/superpowers/specs/2026-07-02-road-target-calibration-design.md`
v2 section: "if v2 also fails calibration, Track A is killed per the
pre-committed stop rule — no v3"). v2 fixed v1's INFEASIBLE failure
(2026-07-03 entry above: v1 blew its own area guard, 145 budget vs 166 bound)
by dropping the pessimistic trunk term and adding end-overhangs, and it *does*
now solve — but the resulting `f` is decisively outside the sanity band, in
the opposite direction from v1's failure.

**Runs** (all `nice -n 19 uv run --with ortools python
scripts/exp_lane_composition.py ... --model v2 --time-limit 300`):
- User city (`city-user-data.json` + `city-user-data-foe-helper.json`, 82
  road-needing consumers): `status=FEASIBLE`, `model_optimum=84`,
  `proven_bound=13`, `gap=71`. → `output/comp-user-v2.json`.
- darkzig (63 consumers): `status=FEASIBLE`, `model_optimum=39`,
  `proven_bound=0`, `gap=39`. → `output/comp-darkzig-v2.json`.
- darkzig `--connectors` sensitivity (charges `n_used_lanes−1`): `model_optimum=50`
  (delta **+11** over the no-connectors run, consistent with the reported 12
  used lanes), `trunk_pessimistic=11`, `proven_bound=0`, `gap=50`. →
  `output/comp-darkzig-v2-conn.json`.

**f = 142 / 84 = 1.69** — outside the sanity band `[0.75, 1.33]` (above the
upper edge). **No re-run at `--time-limit 900`:** the gap (71) does not
straddle the band edge. `model_optimum=84` is a CP-SAT feasible incumbent for
a *minimization* problem, i.e. a valid upper bound on the true model optimum
— more solve time can only find an equal-or-lower optimum, which can only
*increase* `f` further (already 1.69 > 1.33), never bring it back down into
band. So the failure is decisive, not an artifact of an unconverged solve;
extra compute cannot rescue it. (Self-test sanity: `v2_optimum ≤ v1_optimum`
holds on darkzig, 39 ≤ 160; `v2_optimum ≥ ⌈n/3⌉` holds both cities, 84≥28 and
39≥21 — the model itself is internally consistent, it's just badly miscalibrated
against the real 142.)

Because `f` is outside the band, **`C*` was not computed** (per spec §"Calibration
criterion" and the brief's step 2 — a band failure is a kill on its own, no
gate arithmetic needed). For the record only (not used in any verdict): darkzig
local-method floor is 158; darkzig Σ/2 estimate 114 (not a bound); adjacency
bounds darkzig 21 / user city 28; v1 quarantined numbers darkzig 160
pessimistic / `optimistic_total` 132.

**Root cause (opposite direction from v1):** v1 was too pessimistic (INFEASIBLE,
overcounted trunk ~8× and lane frontage ~20%, couldn't even reach 142's slack).
v2 over-corrected: dropping the trunk term entirely and allowing 2 free-overhang
buildings per lane side lets the model claim connectivity is nearly free, so its
82-consumer user-city optimum (84) sits *below* even a generous read of the real
network's productive cells — the model is now too optimistic to anchor a
calibration factor anywhere near 1. Both v1 and v2 sit on either side of the
real 142 by roughly the same kind of error (trunk/connectivity accounting),
just with the sign flipped.

**Pre-committed-stop-rule context:** this was explicitly scoped in the spec
as "a one-iteration, time-boxed retry" for Track A's go/no-go gate — not an
open-ended tuning loop. Per that rule, Track A (the composition-solver-driven
global optimizer for O2, "A1 → A2/A3") is now **killed**; there is no v3.
Track A's supporting artifacts (`foeopt/quality.py` sharing metrics,
`foeopt/bounds.py` adjacency bound, `scripts/exp_lane_composition.py` itself)
are sound and stay in the repo as reference/diagnostic tooling — only the
"build a global lane/stub composition optimizer and use its output as the
road target" bet is closed. Per the plan's own ordering (`todo.md`: "Order &
why this can reach the objective"), remaining live paths are Track B
(structured LNS on the existing 158-road plateau) and Track D
(productionize the winner) — Track A is out of the loop for both.

## Safe-placements mask A/B (2026-07-05)

Task C1's routability-preserving action mask (`foeopt/reach.py`
`placement_is_safe`/`ReachChecker`, flag-gated `safe_placements` in
`repack`/`build_candidate`, `--safe-placements` CLI flag) was A/B-measured
per the plan's Task 5 / spec §5 gates: 8 seeds, 120s budget/run, darkzig +
`make_real_like_city` at fill 0.5/0.7/0.9 (`scripts/exp_safe_ab.py`, output
`output/safe-ab.txt`):

- darkzig: off unplaced 0/0.0/0 (all 8 seeds), roads `[159,160,162,162,167,
  168,169,170]`, 205 trials/run. On unplaced 0/5.1/10 (only 1/8 seeds
  reach 0), roads `[184]` (n=1), 55 trials/run.
- fill 0.5: off unplaced all-0, roads `[115,115,115,115,115,115,116,116]`,
  242 trials/run. On unplaced all-0, roads `[115,115,115,116,116,116,116,
  119]`, 67 trials/run.
- fill 0.7: off unplaced all-0, roads `[152,152,152,152,154,154,154,156]`,
  266 trials/run. On unplaced all-0, roads `[152,154,154,156,156,158,159,
  161]`, 76 trials/run.
- fill 0.9: off unplaced 0/0.6/4 (6/8 seeds at 0), roads `[180,188,192,193,
  198,211]`, 132 trials/run. On unplaced 11/12.6/15, roads NONE at 0, 44
  trials/run.

**Gate 1 (unplaced strictly no worse everywhere, better in the tails)
— FAILS.** darkzig: 0/0/0 → 0/5.1/10, worse on mean and max (min tied at 0)
(the tail the mask exists to fix). fill 0.5/0.7: tied (both all-0), no
violation but no improvement either. fill 0.9: 0/0.6/4 → 11/12.6/15, a
catastrophic tail regression — precisely the high-fill regime the mask
targeted, and the one place a routability guarantee should have paid off.

**Gate 2 (0-unplaced road distribution not worse AND throughput regression
< ~30%) — FAILS on both clauses, every scenario.** Throughput: darkzig
205→55 (−73.2%), fill 0.5 242→67 (−72.3%), fill 0.7 266→76 (−71.4%), fill 0.9
132→44 (−66.7%) — a 3-4x drop in trials/run everywhere, 2-2.4x past the ~30%
budget. Road counts: fill 0.5 mean 115.25→116.0 and fill 0.7 mean
153.25→156.25, both slightly worse (not better, as required); darkzig's "on"
side has only 1 of 8 seeds even reaching 0-unplaced, so its 184-road point
is not a distribution to compare, just evidence the mask rarely gets there
at all; fill 0.9's "on" side never reaches 0-unplaced. Both gates fail
decisively — no borderline call needed.

**Verdict: do NOT flip the default.** `safe_placements`/`--safe-placements`
stays an opt-in experimental flag (default off, byte-identical to
pre-mask behavior when unused).

**Mechanistic interpretation.** The project's placement failures were never
routing failures — `route()` already doesn't fail for grow-tree candidates
(the packer's own RouteError path says "should not happen"); unplaced
buildings are a packing/co-design problem, not a connectivity one (100% of
unplaced are consumers — a structural floor, 2026-06-23 attempt #5 entry
above). Guaranteed routability was a fix for a failure mode this project
doesn't have. Applied as a per-anchor search mask, it makes packing strictly
*harder*: it forbids exactly the tight endgame placements dense layouts
need — sealing the last pocket, filling a guarded border cell down to its
last free neighbor — which is normal, necessary behavior in a
tightly-packed grow-tree, not a bug the mask should suppress. It also cuts
trial count 3-4x, starving the multi-start restart loop the packer actually
relies on to escape local optima. Both effects point the same direction:
worse tails, fewer trials, at equal wall-clock.

**Rule for future search-mask work:** never guard a search with a
per-candidate exactness check when the observed failure mode is a packing
limit, not a validity violation — the check's overhead buys correctness the
search didn't need, and its cost (search-space narrowing, throughput) comes
out of the budget that was actually solving the problem. Measure any such
mask at *equal wall-clock*, trials-normalized, before considering it for a
default — an A/B that only equalizes seed count and budget-per-run (not
trials reached) will hide a throughput collapse like this one.

`foeopt/reach.py` stays in the repo as verified infrastructure, not dead
code: it is the pre-registered prerequisite for any RL revisit (RL M2-M4
archived-track entry, 2026-07-02, on `unroutable` evals) and a candidate
one-shot validity check inside future Track-B destroy-repair moves (checked
once per repair, not searched per-anchor) — the exactness that hurt as a
per-anchor filter is exactly what a single pre-commit check wants. Full
numbers and gate arithmetic: `.superpowers/sdd/p2-task-5b-report.md`.

## TH-stub constructor template A/B (2026-07-06)

The TH-stub template (commits 2bbb4a6/82af61e, flag `th_stub_template`,
default off) replicates the user's expert pattern — offset Townhall + two
flank road cells, each serving 3 buildings — as a constructive seed
alternative to the packer's corner-style start. A/B'd per the harness
docstring gates (`scripts/exp_th_ab.py`, 8 seeds, 120 s budget/run, darkzig +
`make_real_like_city` fill 0.5/0.7/0.9, `output/th-ab.txt`):

- darkzig: off unplaced all-0, roads `[159,160,162,162,167,168,169,170]`
  (mean **164.6**, recomputed from the list), 207 trials/run. On unplaced
  all-0, roads `[160,162,165,167,169,174,179,183]` (mean **169.9**,
  recomputed), 301 trials/run — worse mean despite ~45% more trials.
- fill 0.5: off and on roads identical, `[115,115,115,115,115,115,116,116]`
  both arms; trials 248 (off) vs 325 (on).
- fill 0.7: off roads `[152,152,152,152,154,154,154,156]` (mean **153.25**),
  269 trials/run. On roads `[151,152,152,153,154,154,156,158]` (mean
  **153.75**), 334 trials/run — near-neutral, min 151 (on) vs 152 (off),
  mean 0.5 worse on.
- fill 0.9: off unplaced 0/0.6/4 (6/8 seeds reach 0), roads
  `[180,188,192,193,198,211]`, 134 trials/run. On unplaced 0/5.5/13 (only
  1/8 seeds reach 0), roads `[188]` (n=1), 169 trials/run — a severe tail
  regression in exactly the regime a good structural template should help
  most.

**Gate evaluation (harness docstring: 0-unplaced road distribution not
worse — ideally better — AND unplaced distribution no worse) — FAILS.**
darkzig and fill-0.9 both show the on-arm road/unplaced distribution
strictly worse despite more trials; fill 0.5 ties; fill 0.7 is a wash
(one seed better, mean fractionally worse). No scenario shows a clean
improvement, and the two scenarios that matter most (darkzig gate city,
fill-0.9 high-fill tail) are the ones that regress hardest.

**Verdict: gates FAIL — do not flip the default.** `th_stub_template`
stays opt-in (default off, byte-identical to pre-template behavior when
unused).

**Three observations for the record:**
1. **Portfolio dilution.** With the flag on, each trial coin-flips
   corner-style vs stub-style start, so roughly half the corner-style
   trials that used to run are lost to stub-style trials instead. On
   darkzig and fill-0.9 the corner style is what carries the result at
   120 s budget, and halving its sample is a pure loss that the stub
   trials don't repay in the same wall-clock. Also note the flag changes
   the master RNG draw sequence, so the two arms are different random
   samples end-to-end, not "off plus extra stub trials" — part of why
   the on-arm trial *counts* differ from the off-arm too.
2. **Fast-start, not asymptotic.** An earlier 10 s/2-seed smoke run showed
   the opposite ranking (on: 162-167 roads vs off: 199-217 on darkzig,
   with a higher trial rate at that budget) — the pre-packed pinwheel
   template reaches a good layout in very few trials, but the 120 s
   multi-start loop gives the corner-style constructor enough restarts to
   overtake it. Worth flagging as a possible salvage (NOT pursued now, per
   the measure-first/no-relitigating discipline): use the stub style only
   as a first-trials seed, or restrict it to low-budget contexts; or
   redesign the A/B so stub trials are added on top of the corner-style
   budget rather than splitting it.
3. **Consistent with the standing lesson.** This is another instance of
   "expert heuristics bolted onto the greedy constructor don't survive an
   equal-wall-clock A/B" (cf. short-side-facing, B1 pairing, structured
   lanes, multi-trunk — all lost previously). The offset-TH template saves
   ~4 cells locally when it fires, but it costs boundary-packing space at
   high fill and the multi-start variance swamps the local gain. The
   flag-gated, measure-first discipline worked exactly as designed here:
   zero cost to the default path, a clean negative result recorded instead
   of a merged regression.

## Track B corridor-LNS A/B + TH-offset probe (2026-07-06)

Corridor-granularity destroy-repair (`--lns`, arm B `lns_polish(60, 30, 30)`)
A/B'd against plain `polish(60, 60)` at equal wall-clock, 8 seeds, darkzig +
`make_real_like_city` fill 0.5/0.7/0.9 (`output/lns-ab.txt`), per the
pre-committed gate in spec §1.1/§8: on darkzig, 0-unplaced rows only,
`mean(B) <= mean(A) - 2 AND max(B) <= max(A)` -> pass; else fail -> flag
stays opt-in, Track B closes (no tuning marathon; revisit needs new
evidence). A parallel TH-offset probe (pure-style arms, corner-only vs
offset-only repack, 8 seeds, `output/th-offset-ab.txt`) ran alongside as a
diagnostic only, no gate.

**Summary lines (verbatim) + accepted-rewrites lines, `output/lns-ab.txt`:**
```
city lns=off: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [153, 154, 155, 157, 158, 165, 169, 175] | trials/run mean 102
city lns=on : unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [155, 155, 155, 156, 158, 164, 172, 175] | trials/run mean 102
  lns accepted rewrites per seed: [0, 0, 1, 0, 0, 1, 0, 0]
real-like fill=0.5 lns=off: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [115, 115, 115, 115, 116, 116, 116, 116] | trials/run mean 121
real-like fill=0.5 lns=on : unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [105, 107, 107, 107, 108, 108, 108, 115] | trials/run mean 122
  lns accepted rewrites per seed: [1, 2, 0, 1, 1, 1, 1, 1]
real-like fill=0.7 lns=off: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [144, 150, 152, 152, 154, 154, 154, 165] | trials/run mean 134
real-like fill=0.7 lns=on : unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [144, 150, 152, 152, 152, 152, 154, 174] | trials/run mean 136
  lns accepted rewrites per seed: [1, 0, 1, 0, 0, 0, 0, 1]
real-like fill=0.9 lns=off: unplaced min/mean/max 0/3.0/10 | 0-unplaced roads [180, 190] | trials/run mean 64
real-like fill=0.9 lns=on : unplaced min/mean/max 0/3.0/10 | 0-unplaced roads [180, 190] | trials/run mean 64
  lns accepted rewrites per seed: [0, 0, 0, 0, 0, 1, 1, 0]
```

**Summary lines (verbatim), `output/th-offset-ab.txt`:**
```
city th=corner: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [159, 160, 162, 162, 167, 168, 169, 170] | trials/run mean 205
city th=offset: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [162, 165, 165, 166, 166, 167, 171, 174] | trials/run mean 210
real-like fill=0.5 th=corner: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [115, 115, 115, 115, 115, 115, 116, 116] | trials/run mean 243
real-like fill=0.5 th=offset: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [115, 115, 115, 115, 115, 115, 115, 116] | trials/run mean 244
real-like fill=0.7 th=corner: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [152, 152, 152, 152, 154, 154, 154, 156] | trials/run mean 266
real-like fill=0.7 th=offset: unplaced min/mean/max 0/0.0/0 | 0-unplaced roads [151, 151, 153, 153, 153, 153, 154, 155] | trials/run mean 244
real-like fill=0.9 th=corner: unplaced min/mean/max 0/0.6/4 | 0-unplaced roads [180, 188, 192, 193, 198, 211] | trials/run mean 133
real-like fill=0.9 th=offset: unplaced min/mean/max 0/1.6/4 | 0-unplaced roads [190, 195, 219] | trials/run mean 135
```

**Gate arithmetic (recomputed from the raw lists above, darkzig, 0-unplaced only):**
- off (A): sum 153+154+155+157+158+165+169+175 = 1286, mean **160.75**, max **175**.
- on (B): sum 155+155+155+156+158+164+172+175 = 1290, mean **161.25**, max **175**.
- `mean(B) <= mean(A) - 2` -> 161.25 <= 158.75 -> **FALSE** (B is 0.5 roads *worse* on
  mean, not 2 better). `max(B) <= max(A)` -> 175 <= 175 -> true, but the AND fails
  on the mean clause alone. **GATE FAILS.**

**Secondary fill-level readings (not gated, diagnostic):**
- fill 0.5: off mean 924/8=115.5, on mean 865/8=**108.125** -> B wins by **7.375**
  roads mean at equal wall-clock; accepted-rewrites-per-seed `[1,2,0,1,1,1,1,1]`
  (7/8 seeds with >=1 accepted rewrite) — this is the headline secondary finding:
  the corridor-rebuild mechanism *works* where slack exists. Darkzig's accepted
  rewrites are `[0,0,1,0,0,1,0,0]` (0-1 per seed) — at 97%-dense era layouts and
  60 s polish there is essentially no room for the double-row template to fire.
- fill 0.7: off mean 1225/8=153.125, on mean 1230/8=153.75 — a wash (0.625 worse
  mean, and worse max: on 174 vs off 165).
- fill 0.9: off and on distributions identical (`[180, 190]` both arms, mean
  185, accepted rewrites 0-1 per seed) — no effect, most seeds don't even reach
  0-unplaced (unplaced mean 3.0 both arms).

**TH-offset probe reading (diagnostic only, no gate — `output/th-offset-ab.txt`):**
- darkzig: corner sum 1317/8=**164.625**, offset sum 1336/8=**167.0** — offset is
  ~2.4 roads *worse* on mean.
- fill 0.5: corner mean 922/8=115.25, offset mean 921/8=115.125 — effectively
  identical.
- fill 0.7: corner mean 1226/8=153.25, offset mean 1223/8=**152.875** — offset
  marginally *better* here (0.375 roads mean).
- fill 0.9: corner unplaced 0/0.6/4 (6/8 seeds reach 0-unplaced), offset unplaced
  0/1.6/4 (only 3/8 reach 0-unplaced) — offset is worse on placement at high
  density.
- Reading: per-trial offset-TH is neutral-to-worse on the darkzig gate city and
  the high-fill tail, marginally better only at fill 0.7, and worse where
  density matters overall. Corner-seeking is **not** a measurable cause of the
  darkzig plateau via this constructor alone — the expert city's offset-TH
  advantage evidently comes from the coordinated surrounding structure the
  player builds around it, not from the placement choice in isolation.

**Verdict: GATE FAILS -> `--lns` stays opt-in (default off). Track B CLOSES**
per the pre-committed rule (no tuning marathon; revisiting needs new evidence).

**Interpretation:**
1. The mechanism is validated, the target was wrong. Corridor rebuilds convert
   single-loaded corridors into double rows wherever free space allows
   re-arrangement: fill 0.5 shows a **-7.4 roads mean win at equal wall-clock**
   — the first structural method in this project's history to beat plain polish at its own game
   *anywhere*. On darkzig-density cities there is no slack for the template to
   use: repairs can't fit the two-row pattern into the freed cells, so almost
   nothing is accepted (rounds spin, accepted 0-1 per seed) — per the earlier
   RL/T5 framing, that means "converged, no room," not "broken."
2. Rule for the record: destroy-repair value scales with free-space slack;
   density is the binding constraint, and the darkzig plateau (~158-165 roads,
   0-unplaced) remains unbeaten by every method tried so far in this project
   (structured packers x4, CP-SAT, LNS+CP-SAT, RL M2-M4, safe-placements mask,
   TH-stub template, and now corridor-LNS). Any future attempt must explain how
   it *creates* slack (e.g. cross-region coordinated moves that free cells
   somewhere else first) rather than how it *uses* slack that isn't there.
3. Probe: no follow-up TH-placement investigation is warranted by these numbers
   alone — noting the user's standing interest (memory-flagged,
   `foe-layout-heuristics.md`) as deferred, with this probe as its first
   data point.
4. Fill-0.5 salvage option, noted but NOT pursued: `--lns` is a legitimate
   opt-in win for players whose cities have overhead-cell slack; a "recommend
   `--lns` when overhead cells > X" heuristic could be a Track D item if the
   project reaches productionization. See `output/lns/<stamp>/` HTML folders
   for visual before/after inspection of the accepted corridor rewrites.

## Dependency policy: gated solver extras (2026-07-06)
**Rule:** any solver-dependent method that passes its pre-registered A/B gate is productionized as a
`[solver]` optional extra in pyproject.toml (stdlib core keeps working without it — same pattern as the
existing `rl` extra), rather than being penalized for the dependency. Experiments keep using
`uv run --with <lib>` throwaway scripts; `foeopt/` core stays pure-stdlib.
**Why:** a full audit (2026-07-06) found the stdlib constraint cost exactly one measured road across the
project's history (attempt #7's 157-vs-158 LNS+CP-SAT, rejected as "not worth the dependency") — every
other dead track died on evidence about the problem, not on library access. But methods were carrying an
unspoken extra bar. Pre-committing the promotion rule removes the distortion without giving up the
zero-dependency core install.

## Roads-first "127" RETRACTED — invalid, buildings were rotated (2026-07-07)
**The 127-road result below is INVALID and the WIN is withdrawn.** The roads-first CP-SAT model gave each
non-square consumer an orientation variable and placed **19 of the 33 non-square consumers ROTATED**
(width/length swapped vs their canonical footprint). **FoE buildings cannot rotate** (hard game
constraint, user-confirmed), so the layout is illegal. The "independent verification" below checked the
wrong invariant: `route()`=127 / `is_valid` / 0-unsatisfied are all true but NONE of them look at
orientation — `is_valid` has no canonical reference and never did.
**Root cause & the real lesson:** verification must check the invariant that *matters*, not the ones that
are easy. Every check I ran passed because none examined orientation. Fixed 2026-07-07:
`foeopt/validate.py` gained `rotated_buildings(layout, canonical_dims(loaded))` (is_valid stays
orientation-blind by necessity — a bare Layout has no canonical reference, so NEW placement methods must
call the guard explicitly); rotation removed from `scripts/exp_roads_first.py` and `foeopt/lns.py`
(the pre-existing packer/anneal/router never rotated — they use same-footprint position moves, so all
prior 250→158→153 results are unaffected). The de-rotated search must be re-run for an honest legal
number ~~which will be HIGHER than 127 (19 buildings lose a degree of freedom) and may land above 153~~
— **prediction was wrong, see the 2026-07-07 de-rotated entry below: actual result is 106, LOWER than
127.** The reasoning (same k is tighter without rotation) was correct in isolation but missed that the
prior run was truncated at 2 k-levels by the 120s probe-limit; tuning the limit to 30s unlocked 12
k-levels (down to k=117), and the lower-k probes more than compensated for the lost rotation degree of
freedom. Lesson: don't predict a re-run's number from a single factor when the run configuration also
changes.
**Rule:** never write placement code that tries both `(w,l)` and `(l,w)`; verify every new placement
method with `rotated_buildings` against the loaded canonical dims. The rest of this entry is kept for
the record but its 127/WIN conclusion is void.

## Roads-first feasibility search (2026-07-06) — [see RETRACTION above; 127 is invalid]

**Headline result: 127 roads on darkzig, independently verified.** `output/roads-first/best-k148-a127.json`
(pattern k=148, comb+TH-stub family) was re-derived from scratch outside the probe harness: all 224
buildings placed, all 63 consumers 0-unsatisfied, `route()` returns exactly 127 (matches the 127-entry
`roads` array in the JSON), `is_valid` True, no overlaps. This is a proven achievable count, not a claim.

**Gate arithmetic (spec §2.1, `docs/superpowers/specs/2026-07-06-roads-first-feasibility-design.md` §2):**
best achieved = 127 ≤ 148 → **WIN**. Recomputed independently from `output/roads-first/probes.jsonl`
(348 lines, not trusted from the run summary):

| k | SAT | UNSAT | UNKNOWN | best achieved | solve-time note |
|---|---|---|---|---|---|
| 152 | 54 | 45 | 93 | **128** | SAT mean 9.4s/max 100.5s; UNSAT mean 2.2s/max 48.4s; UNKNOWN pinned at ~120.5-121.3s (probe limit) — 11815.5s (3.28h) of the budget spent at this level |
| 148 | 41 | 36 | 79 | **127** | SAT mean 5.5s/max 20.1s; UNSAT mean 1.1s/max 2.0s; UNKNOWN pinned at ~120.5-120.6s — 9785.4s (2.72h) of the budget spent at this level |
| **total** | **95** | **81** | **172** | — | overall SAT mean 7.7s (max 100.5); UNSAT mean 1.7s (max 48.4); UNKNOWN mean 120.5s (all hit the 120s probe-limit, i.e. truly inconclusive, not slow-SAT/UNSAT) |

Sum of `secs` across all 348 probes = 21600.9s = 6.0002h (the full 6h box, confirming no probe went
unlogged). The 172 UNKNOWNs alone consumed 20727.3s = 5.758h ≈ 5.7h of that 6h — this is the key
operational finding, not a footnote.

**Verdict: DONE, walk_complete = FALSE, deadline_hit = TRUE.** Per the pre-committed k-search (spec §2.2:
start at 152, step −4 while feasible, bisect the gap), only k=152 and k=148 were ever probed before the
6h deadline; nothing below k=148 was attempted. **127 is a validated achievable count, not a proven
floor.** The true within-family floor for the comb+TH-stub pattern is very likely lower than 127 — the
search was truncated by wall-clock, not by exhausting the family. Do not read "WIN" as "127 is optimal";
read it as "127 already clears the win bar with most of the k-space unexplored."

**Operational finding: the 120s per-probe UNKNOWN limit ate the budget.** 172/348 probes (49%) timed out
without CP-SAT reaching SAT or UNSAT, burning 5.7h of 6h while only advancing two k-levels. SAT and UNSAT
probes are both fast (means 7.7s and 1.7s) — the cost is entirely in probes CP-SAT can't resolve either
way within the limit. A follow-up run should tune the probe-limit (shorter, to sample more k-levels per
hour, accepting more UNKNOWNs per level) or the model/solver hints (better bounds, symmetry breaking, a
different search strategy) before spending more wall-clock on this exact configuration.

**Mechanism reading — why roads-first beats every prior method on this project.** Every earlier structural
attempt (four constructive lane/hybrid packers, CP-SAT lane composition, LNS+CP-SAT, RL M2-M4) died on one
of two couplings: greedy inner placement that can't find the overhang/corner-contact assignments a real
optimum needs, or joint placement+routing that blew CP-SAT's ~11×11 window. Roads-first (the user's own
framing) breaks both at once by fixing the road network *before* placement: with the skeleton fixed per
probe, the inner problem is pure 2D rectangle packing with an adjacency side-constraint and zero
connectivity variables — well inside CP-SAT's reach as an exact feasibility check. Because the inner step
is exact rather than greedy, it can find the same overhang/corner placements that let the user's own
142-road city route at 2.02 average cell-sharing, which is exactly the trick no prior constructive
heuristic in this project ever reproduced.

**Strategic implication.** 127 is the first method in this project's history to beat the previous
all-time-best of 153 (this week's polish arm) and the long-standing local-method floor of 158 — by a
decisive margin, with most of the search space still unexplored below k=148. It also sits well above the
Σ(min-side)/2 estimate of 114 (not a bound — assumes perfect double-row tiling, geometrically unreachable
per the 2026-06-23 entry), so there is room for the k-walk to keep improving without approaching that
estimate. Per the 2026-07-06 gated-solver-extras policy, this is a search-time result only: `ortools`
stays a throwaway `uv run --with` dependency, `foeopt/` core is unchanged, and productionizing the pattern
search (continuing the k-walk past 148, wiring it into `polish`/webapp) is a separate, later spec.
Artifacts: `output/roads-first/best-k148-a127.json` / `.html` (the winning layout) and the full
`output/roads-first/best-k*.json` / `.html` set (every improving incumbent found during the walk).

## Roads-first de-rotated re-run — 106 roads, verified LEGAL, gate WIN (2026-07-07)

Re-ran the roads-first CP-SAT feasibility search with the rotation fix in place (`scripts/exp_roads_first.py`
canonical-footprint-only probe + `rotated_buildings` defence-in-depth guard in `validate()`). This is the
honest legal number the RETRACTION demanded; it replaces the void 127 above.

**Configuration change that mattered:** `--probe-limit 30` (down from the prior 120s default), per this
file's own 2026-07-06 operational finding ("tune the probe-limit shorter to sample more k-levels per hour").
The prior 120s run reached only 2 k-levels in 6h (49% UNKNOWN, 5.7h burned at the limit). The de-rotated
smoke run (20 patterns × 20s, 10 min) already returned a verified-legal 123 and showed de-rotated SAT
probes resolve fast (mean 3.0s, max 13.6s) — so 30s catches ~all SATs while giving ~3x the k-coverage.

**Headline result: 106 roads on darkzig, independently verified LEGAL.** `output/roads-first/best-k118-a106.json`
(pattern k=118, comb+TH-stub family) was re-derived from scratch outside the probe harness:
- 224/224 buildings placed; 0 overlapping cells; 0 cells out of region.
- `route()` returns exactly 106 (matches the 106-entry `roads` array, matches `achieved`).
- `is_valid` True, 0 unsatisfied consumers.
- **`rotated_buildings(cand, canonical_dims(loaded))` = 0** — the invariant the prior "verification" never
  checked. Every non-square consumer is in its canonical `(width, length)` orientation.

**Gate arithmetic (spec §2.1): best achieved = 106 ≤ 148 → decisive WIN.** 106 also beats: the void 127
(−21), the prior all-time best 153 (−47), the long-standing local-method floor 158 (−52), and the
Σ(min-side)/2 estimate of 114 (−8 — and 114 was never a bound, just a double-row-tiling estimate the
2026-06-23 entry called "geometrically unreachable for any packer"; 106 clears it via the stubs/junctions
mechanism where a single road cell serves 3 buildings, exactly as the user's own 142-road city does at
avg load 2.02).

**Independent recomputation from `output/roads-first/probes.jsonl` (2189 lines, not trusted from the run
summary):**

| k | SAT | UNSAT | UNKNOWN | filler-fail | best achieved | level secs | mins |
|---|---|---|---|---|---|---|---|
| 152 | 49 | 92 | 50 | 1 | 127 | 1707.8 | 28.5 |
| 148 | 42 | 94 | 56 | 0 | 128 | 1916.3 | 31.9 |
| 144 | 37 | 102 | 53 | 0 | 121 | 1788.7 | 29.8 |
| 140 | 31 | 111 | 49 | 1 | 119 | 1739.3 | 29.0 |
| 136 | 28 | 115 | 49 | 0 | 116 | 1782.1 | 29.7 |
| 132 | 15 | 116 | 61 | 0 | 118 | 2036.3 | 33.9 |
| 128 | 10 | 120 | 62 | 0 | 118 | 2016.3 | 33.6 |
| 124 | 8 | 124 | 60 | 0 | 113 | 1982.2 | 33.0 |
| 120 | 7 | 129 | 56 | 0 | 107 | 1947.1 | 32.5 |
| 118 | 2 | 127 | 63 | 0 | **106** | 2015.1 | 33.6 |
| 117 | 1 | 53 | 23 | 0 | 112 | 734.0 | 12.2 |
| 116 | 0 | 132 | 60 | 0 | — (INCONCLUSIVE) | 1892.0 | 31.5 |
| **total** | **230** | **1315** | **642** | **2** | **106** | **21557.2** | **359.3** |

Overall: SAT mean 4.75s (max 28.9s — all resolved within the 30s limit, confirming the probe-limit tuning);
UNSAT mean 0.76s (max 29.4s); UNKNOWN mean 30.31s (all hit the 30s limit). `sum_secs = 21557.2s = 5.988h`
(the full 6h box, confirms no unlogged probe). UNKNOWN sum_secs = 19460.9s = 5.406h (**90.3% of the budget**)
— still the dominant cost even at 30s; the shorter limit just made each UNKNOWN 4x cheaper, buying 12
k-levels instead of 2.

**k-walk trace (spec §2.2: start 152, step −4 while feasible, bisect the gap):** 152→148→144→140→136→132→
128→124→120 all FEASIBLE → 116 INCONCLUSIVE (0 SAT, 132 UNSAT, 60 UNKNOWN) → bisect 116↔120 → 118 FEASIBLE
(106) → bisect 116↔118 → 117 FEASIBLE (112) → deadline. `walk_complete = TRUE` (the integer bisection
converged: 117 lowest proven-feasible k, 116 INCONCLUSIVE adjacent), `deadline_hit = TRUE`. **106 is a
validated achievable count, not a proven floor** — k=116's 60 UNKNOWNs mean it may be feasible with more
probe time, and even at 117 only 1 of 77 probes SAT'd (the family is sparse there). The true within-family
floor for the comb+TH-stub pattern is very likely at or below 106; do not read 106 as optimal.

**Why 106 is at k=118, not at the lowest feasible k (117→112).** Lower k = tighter road skeleton = fewer
patterns SAT (230 SAT total, but only 1 at k=117, 2 at k=118, 7 at k=120). The best-achieved-at-k does not
monotonically decrease with k — there's a sweet spot (k=118 here) where enough patterns still SAT for one
to route-prune aggressively. Below that, SATs get too rare to find a low-achieved one; above it, the
skeleton has more roads to prune but the starting count is higher. The k-walk records the best across ALL
levels, so 106 stands regardless.

**Probe-limit tuning verdict (the 2026-07-06 operational finding, acted on):** 30s was the right call.
Every SAT resolved within 30s (max 28.9s), so no achievable layout was missed by the shorter limit, and
the 4x-cheaper UNKNOWNs bought 12 k-levels of coverage (vs the prior 120s run's 2 levels) — which is the
entire reason 106 (at k=118) was reachable at all. The prior run's 127 was at k=148; it never probed below
148. **Rule reaffirmed:** when the operational finding says tune a bottleneck, tune it before re-running.

**Strategic implication.** 106 is the first method in this project's history to beat the Σ/2 estimate
(114) and the local-method floor (158) simultaneously, by a wide margin, with a verified-legal layout.
Roads-first (fix the skeleton, then exact-pack) is the project's winning structural idea — the same one
that beat 153 with the invalid 127, now confirmed legal. Per the 2026-07-06 gated-solver-extras policy,
this is a search-time result: `ortools` stays a throwaway `uv run --with` dependency, `foeopt/` core is
unchanged, and productionizing (wiring the k-walk into `polish`/webapp, tuning for lower k or a tighter
family) is a separate, later spec. Artifacts: `output/roads-first/best-k118-a106.json`/`.html` (winning
layout) and the full `best-k*.json`/`.html` set. The void 127 artifacts are in
`output/roads-first/invalid-rotated-2026-07-06/`; smoke artifacts in
`output/roads-first/smoke-derotated-artifacts/`.

## Roads-first parallel re-run — 104 roads in ~2h wall-clock, gate WIN (2026-07-07)

Parallelized the throwaway CP-SAT feasibility search via `multiprocessing.Pool` (spec
`docs/superpowers/specs/2026-07-07-roads-first-parallel-search-design.md`, plan
`docs/superpowers/plans/2026-07-07-roads-first-parallel-search.md`). Default config:
`--workers 4 --probe-workers 4` = 4 concurrent probes × 4 CP-SAT portfolio workers = 16
cores. The k-walk stays sequential (each level is a barrier); only the 200 patterns within
a level dispatch concurrently via `imap_unordered`. Verification (`route()`/`is_valid`/
`rotated_buildings`) stays in-worker and deterministic — every saved layout remains
independently verifiable-legal. `--workers 1 --probe-workers 1` reproduces the sequential
run exactly.

**Headline result: 104 roads on darkzig, independently verified LEGAL, in ~2h wall-clock
(vs the sequential 6h).** `output/roads-first/best-k116-a104.json` re-derived from scratch:
224/224 placed, 0 overlaps, 0 out-of-region, `route()`=104 matches, `is_valid` True,
0 unsatisfied, `rotated_buildings`=0. 104 beats the sequential 106 (−2), the prior
all-time best 153 (−49), the local-method floor 158 (−54), and the Σ/2 estimate 114 (−10).
Gate (spec §2.1): 104 ≤ 148 → decisive WIN (already cleared by 106; this extends it).

**k-walk converged before the deadline:** `walk_complete=TRUE`, `deadline_hit=FALSE` —
the bisection finished at k=115 (INCONCLUSIVE) / k=116 (FEASIBLE, 1 SAT → 104) in ~2h,
leaving ~4h of the 6h box unspent. The sequential run hit the deadline at k=117
(`walk_complete=TRUE` there too, but only after the full 6h). 13 k-levels probed (152→112
in steps of −4, then bisection at 115/114/113-equivalent density).

**Throughput (spec §9 must): ~4x.** 2496 probes in ~2h wall-clock (cumulative probe-time
25505s = 7.085h across 4 workers → 3.9x parallel efficiency). The sequential baseline did
2189 probes in 5.988h wall-clock (6.1 probes/min wall); the parallel run did 2496 probes
in ~2h (~20.8 probes/min wall). This is the reliable, mechanical win — exactly as predicted.

**UNKNOWN rate (spec §9 nice-to-have, NOT a gate): unchanged.** 731/2496 = 29.3% UNKNOWN,
statistically identical to the sequential baseline's 642/2189 = 29.3%. The 4-worker CP-SAT
portfolio did NOT meaningfully flip UNKNOWNs to SAT/UNSAT — the UNKNOWN probes are genuinely
hard (the model is loose at low k), and 4 parallel search strategies don't resolve them
within the 30s probe-limit any better than 1 does. The portfolio win was empirical and
unpromised; the throughput win is what delivered the result. **Lesson: when the operational
finding says the bottleneck is UNKNOWN timeouts, the reliable fix is more k-level coverage
via throughput, not portfolio depth.** UNKNOWNs still consumed 87.7% of cumulative
probe-time — but at 4x cheaper per wall-clock minute, the run reached 13 levels (incl.
bisection) instead of 12, and finished 3x faster.

**Why 104 (at k=116) and not lower.** The k-walk converged: 116 is the lowest
proven-feasible k (1 SAT out of 192 probes there); 112/114/115 all INCONCLUSIVE (0 SAT,
~60 UNKNOWN each — may be feasible with more probe time, but the family is sparse there).
104 is a validated achievable count, not a proven floor — the true within-family floor is
very likely at or below 104. The parallel run's early completion means a follow-up could
spend the remaining ~4h probing harder at k=112–115 (longer probe-limit, more patterns) to
try to flip those INCONCLUSIVE levels to FEASIBLE. That is a separate later spec per the
gated-solver-extras policy.

**Per-level table (independently recomputed from `probes.jsonl`, 2496 lines):**

| k | SAT | UNSAT | UNKNOWN | filler | best |
|---|---|---|---|---|---|
| 152 | 49 | 92 | 50 | 1 | 127 |
| 148 | 42 | 94 | 55 | 1 | 126 |
| 144 | 36 | 104 | 52 | 0 | 121 |
| 140 | 32 | 110 | 49 | 1 | 119 |
| 136 | 27 | 116 | 49 | 0 | 117 |
| 132 | 17 | 114 | 61 | 0 | 115 |
| 128 | 11 | 119 | 62 | 0 | 118 |
| 124 | 9 | 124 | 59 | 0 | 113 |
| 120 | 3 | 128 | 61 | 0 | 112 |
| 116 | 1 | 133 | 58 | 0 | **104** |
| 115 | 0 | 133 | 59 | 0 | — (INCONCLUSIVE) |
| 114 | 0 | 132 | 60 | 0 | — (INCONCLUSIVE) |
| 112 | 0 | 136 | 56 | 0 | — (INCONCLUSIVE) |
| **total** | **227** | **1535** | **731** | **3** | **104** |

SAT mean 6.09s (max 29.9s — all resolved within the 30s limit); UNSAT mean 1.14s; UNKNOWN
mean 30.61s (all hit the 30s limit). `sum_secs` = 25505s = 7.085h cumulative (4 workers ×
~2h wall = ~8h, matching).

**Code change:** pure-Python `multiprocessing` in the throwaway `scripts/exp_roads_first.py`
only — no new dependency, no change to `foeopt/` core (per the gated-solver-extras policy).
New CLI: `--workers N` (default 4), `--probe-workers M` (default 4). Worker initializer
sends the read-only layout once per worker (not per task). `pool.terminate()` on deadline-hit
(worst-case overrun = 0, not `probe_limit` — the final-review fix). Selftest asserts
parallel-equivalence (`par_statuses == seq_statuses` at `--workers 2 --probe-workers 1`).
4 unit tests + selftest all pass; `--workers 1 --probe-workers 1` reproduces the sequential
run exactly. Full implementation: 5 commits on `feat/roads-first-parallel` (d023632..0cd9346),
all per-task reviews + final whole-branch review clean (2 Important findings from final
review — deadline-drain overrun + ortools test gate — both fixed).

**Strategic implication.** The parallel search delivers the same verified-legal road count
(104, beating the sequential 106) in 1/3 the wall-clock, with the k-walk converging early
and ~4h of budget unspent. Roads-first remains the project's winning structural idea; the
parallelism makes it practical to iterate on (a 2h run instead of 6h). The remaining
~4h of budget and the INCONCLUSIVE k=112–115 levels point at the next experiment: spend
more probe-time per pattern at the tightest k-levels (longer `--probe-limit`, more
`--patterns`) to try to flip INCONCLUSIVE to FEASIBLE and push below 104. Productionization
(wiring into `polish`/webapp) remains a separate later spec. Artifacts:
`output/roads-first/best-k116-a104.json`/`.html` and the full `best-k*.json`/`.html` set;
sequential baseline preserved in `output/roads-first/sequential-baseline-2026-07-07/`.

## Pattern-family ceiling correction + full-TH-sampling test (2026-07-07)

**Correction of an earlier misdiagnosis.** After the parallel run delivered 104, a targeted
re-run (`--k-start 116 --probe-limit 60 --patterns 400`) was launched to test whether longer
probe-limits / more patterns at the tight k-levels could flip INCONCLUSIVE→FEASIBLE and push
below 104. Two findings reshaped the understanding:

1. **`--patterns 400` was a no-op.** At k=116 *and* k=120 the generator yielded exactly 192
   patterns — same as every k from 108–152. Initial diagnosis blamed the tight-k exact-k
   discard; that was **wrong**. The real cause: `th_anchor_candidates` is a *deliberate coarse
   heuristic* (~8 TH positions: 4 corner+offset variants + 2 mid-edge), and the parameter grid
   (8 TH × 4 sides × 5 spacings × 2 modes × 2 stubs = 640 combinations) dedupes to ~192
   distinct skeletons. The 192 is an **artifact of the 8-TH sampling**, not a constraint of the
   comb family or of low k. Measured: 0 exact-k discards at k=120; the ceiling is dedup.
   **Lesson: measure before reasoning from code shape.** I gave a confident low-k-supply
   explanation that was empirically false; a 30-line instrumented run would have caught it.

2. **The 104 was portfolio luck, not a robustly reachable result.** The targeted re-run
   probed all 192 patterns at k=116 and got **0 SAT** (132 UNSAT, 60 UNKNOWN) — vs the
   parallel run's 1/192 SAT (→ 104). Same family, fully sampled; the difference is CP-SAT
   portfolio non-determinism (`--probe-workers 4` runs 4 parallel search strategies; whether
   the one hard SAT at k=116 is found is a coin flip). Spec §6 flagged this as the cost of
   relaxing search determinism; the targeted run is the first measurement of it. **The robust
   floor is ~k=118** (108–110 roads): k=117 SAT at 110, k=118 SAT at 110, k=120 SAT at 108.
   k=116's 104 stands as a validated achievable count (independently re-verified LEGAL on
   2026-07-07) but NOT as a reproducible one — report it as "achievable under portfolio
   luck," not "the floor."

**Full-TH-sampling test.** Added `--th-anchors {coarse,full}` flag
(`scripts/exp_roads_first.py:th_anchor_candidates`). `full` enumerates every (x,y) where the
TH footprint fits in-region — **2162 positions on darkzig** vs ~8 coarse. Pattern counts:

| k | coarse | full |
|---|---|---|
| 120 | 192 | 54,806 |
| 116 | 192 | 54,995 |

A ~285x increase in pattern diversity — the comb family was nowhere near exhausted; the TH
sampling was the bottleneck. Quick probe test (`--th-anchors full --k-start 112 --patterns 200
--probe-limit 30 --time-box 1800`, 4 workers): **k=116 confirmed FEASIBLE at 106** (vs 0 SAT
coarse), and **k=112 found a SAT at 105 in just 16 probes** — an INCONCLUSIVE level in the
coarse run (0 SAT, 136 UNSAT, 56 UNKNOWN) flipped to FEASIBLE immediately. Best **105,
independently re-verified LEGAL** (224/224 placed, `route()`=105 matches, `is_valid` True, 0
unsatisfied, `rotated_buildings`=0, 0 overlaps, 0 out-of-region).

**This is the highest-leverage diversity lever found in this project.** It's a one-flag change
to a throwaway script (no `foeopt/` change, no new dep), and it flips the "comb family is
exhausted at 192" diagnosis into "the comb family has 55k instances; we were sampling 0.3% of
it." The verified 105 (109% road efficiency) is a new all-time best for a *robustly reachable*
result (the 104 was luck). Productionization and the richer-pattern-family spec (lanes/stubs)
both build on this.

## Road-efficiency metric + CP-SAT feasibility insight (2026-07-07)

**Road efficiency = Σ(short sides of road-needing buildings)/2 / roads, as a %.** 100% = every
road cell serves the double-row ideal (2 buildings); >100% = some road cells serve 3
(stubs/junctions), beating the Σ/2 estimate. darkzig: 63 consumers, Σ/2 = 114.5.

| run | roads | eff% |
|---|---|---|
| sequential baseline (106) | 106 | 108.0% |
| parallel baseline (104, portfolio luck) | 104 | 110.1% |
| targeted robust floor (108) | 108 | 106.0% |
| full-TH k=112 (105, verified) | 105 | 109.0% |

**Every recent roads-first result clears 100% efficiency — unprecedented for this game.**
The user reports prior tools (one tried years ago) achieved 70–90% and usually had many
unplaced. Roads-first + CP-SAT placement consistently beats the Σ/2 double-row-tiling
estimate via the stubs/junctions mechanism (a single road cell serving 3 buildings), which the
exact placer finds but no greedy constructor in this project ever reproduced.

**CP-SAT returns the *first* feasible placement, not the best.** The probe is a feasibility
problem (`AddNoOverlap2D` + anchor constraints, no objective). Whether CP-SAT finds SAT in
3.2s or 30.3s, it stops at the first placement satisfying all constraints — the `secs` reflects
search difficulty, not result quality. The road count comes from `route()` running on *that
specific placement*; a different valid placement on the same skeleton could route lower. So:
- A SAT at 30.3s (borderline, near the probe-limit) is a **ceiling** on what that skeleton can
  achieve, not the floor. The same skeleton might yield fewer roads with a different placement.
- A 30.4s UNKNOWN is a skeleton CP-SAT couldn't resolve either way in the limit — might be
  placeable with more time, might not.
**Lever identified but not built:** add an *objective* to the CP-SAT model (minimize something
correlated with post-`route()` road count — e.g. maximize shared road-cell adjacency). Then
longer probe-time directly lowers the achieved count rather than just flipping UNKNOWNs. This
is a model change, separate spec. For R&D, not production (longer probes hurt user latency).

**Pool dispatch is queue-based, not batch-based.** `imap_unordered` workers pull the next task
the moment they finish — no per-task waiting. A 4s SAT worker runs ~7 probes while a 30s
UNKNOWN worker runs 1. The only idle is at the **level barrier** (last slow task → other 3
workers idle ~20-30s) — a small tax, measured at 3.9x effective parallelism vs 4x theoretical.
The rejected Approach 2 (speculative next-k) would eliminate this; not worth the complexity
now (the boundary idle is ~5-10 min over 13 levels).

## Productionization analysis + RL verdict (2026-07-07)

The user wants to productionize roads-first; 2h/6h search time is fine for R&D but no user will
wait it. Analysis of how to make it fast for users, roughly in leverage order:

1. **Time-boxed search with graceful degradation (core).** Run the k-walk with a user-facing
   budget (60–120s, not 6h), return the best achieved layout. The data shows strong layouts
   come early (k=152→127 in ~30 min sequential; first SAT at k=116 in ~60s with full-TH
   parallel). A 120s budget lands in k=130–140 territory → ~120–130 roads → ~85–95% efficiency,
   still far better than the old 70–90% tools. Promise a time bound, return the incumbent.
2. **Warm-start from the classical pipeline (high leverage).** The project already has a fast
   classical pipeline (repack + anneal polish → 158 roads in seconds, 0-unplaced). Productionize
   roads-first as a *polish step on top of the classical result*, not a from-scratch search:
   run classical (seconds) → 158, then roads-first `--k-start 158` walk-down with 60–120s budget
   → ~125–135 roads, return whichever is better. User gets a good layout in ~2 min total; roads-
   first only spends time improving. Slots in beside the existing `polish`/`improve` CLI modes.
3. **Smarter k-start from a lower bound.** Today the walk starts at 152 (arbitrary) and steps
   down. With the adjacency bound (`foeopt/bounds.py::bound_adjacency`=21) and Σ/2 (114), start
   at ~130 (just below the classical 158) and step down — skip the easy high-k levels where
   nothing is learned. The targeted run proved this: `--k-start 116` saved ~1.5h.
4. **Any-time / incremental results.** Surface the incumbent layout to the user as it improves
   (the webapp already renders HTML). A user watching 140→130→120 over 60s feels progress; a
   60s spinner feels like nothing. UX lever, not algorithmic, but changes perceived performance.
5. **Cache the pattern family.** `generate_patterns --th-anchors full` takes noticeable time to
   enumerate 55k patterns. Precompute/memoize per region shape for a productionized tool.

**Does NOT help productionization:** longer probe-limits (60–90s, helps R&D optima, hurts user
latency); more patterns (400+, more thorough, slower); objective-augmented CP-SAT (better
placements, more solve time). All are R&D levers.

**Production recipe:** time-boxed (60–120s) + warm-started from the classical pipeline + smart
k-start + any-time UX. That gets a user from 158 → ~125 roads in ~2 min — a ~21% improvement on
the project's own best fast method, at ~110%+ efficiency. Unprecedented for the game.

**RL verdict: NOT revived as the main bet.** Roads-first + CP-SAT is the main bet now and it
works. But the findings open a **narrow, well-defined RL role** for later consideration:
- **RL as skeleton chooser, CP-SAT as placer.** Train a policy to *select a road skeleton* (the
  high-level decision: TH position + side + spacing + mode + stubs — discrete, low-dimensional),
  then use the exact placer to fill buildings around it. The policy never places a building, so
  the M2–M4 `unroutable` failure mode (placement at dense fill) disappears by construction.
- **The roads-first probe *is* the labeler.** Run the probe on 55k patterns → 55k (skeleton →
  achieved_roads) labels → train a policy to predict low-achieving skeletons. This is the BC/
  DAgger setup C3 proposed, but with a much cleaner labeler than "repack outputs" (which capped
  quality at ~169).
- **Hesitations:** (a) CP-SAT is slow per label (~8h to label 55k patterns once on 16 cores;
  DAgger iterates); (b) the policy would inherit the pattern generator's biases — needs the
  richer lane/stub family first (the same next-spec identified 2026-07-02); (c) the productionized
  time-boxed search might be fast enough that RL's marginal value is small — "last 30%" latency
  optimization, not "make it work."
**RL stays off the table for now.** Revisit only if (1) the time-boxed CP-SAT search ships and
60–120s latency is still a user complaint, AND (2) the richer lane/stub pattern family has
shipped (RL needs it to escape the comb bias). The M2–M4 placement-RL track stays archived.

**Recommended next specs, in order:**
1. **Productionization spec (Track D)** — time-boxed roads-first, warm-started from classical,
   any-time UX. Delivers user value; the findings give it a clear recipe.
2. **Richer pattern family spec** — expand TH sampling (proven: 55k patterns, flips INCONCLUSIVE
   to FEASIBLE, verified 105) + add lane/stub topologies (to represent the expert's structure
   and push below 105). R&D track that feeds back into #1 (better patterns → better user results
   in the same time budget).

## Green tests ≠ working server: cross-thread SQLite in the Flask API (2026-07-13)
**Bug:** `webapp/cache.py::CityCache` opened one `sqlite3.connect(db_path)` in the main thread and
reused that connection across all requests. Flask's dev/prod server handles each request on a
**worker thread**, and sqlite3 forbids using a connection from a thread other than the one that
created it → the very first real `/api/load` returned a 400 `"SQLite objects created in a thread
can only be used in that same thread"`. **The full pytest suite (274 tests) was green** because
Flask's `test_client` runs the handler in the *same* thread as the test — so no test ever crossed
a thread boundary, and the entire cache layer looked correct.
**How it was caught:** driving the *real* server end-to-end (start `make_server`, POST over a real
socket), not the test_client — exactly the CLAUDE.md "verify the real flow, not just tests" rule.
The test_client is not a server; it never exercises threading, real SSE streaming, or an on-disk DB.
**Fix:** `sqlite3.connect(db_path, check_same_thread=False)` + a `threading.Lock` guarding every DB
method. `check_same_thread=False` allows cross-thread use of the one shared connection (required so a
`:memory:` DB stays shared — thread-local connections would give each thread its *own empty*
in-memory DB); the lock serializes access so there's no concurrent-transaction corruption. Fine for
this app's traffic. Added a cross-thread regression test (`test_cache_usable_from_other_thread`)
that runs get/store from a spawned thread — it reproduces the ProgrammingError before the fix.
**Rules:**
1. For any Flask/threaded-server feature, smoke the **real** server over a socket before calling it
   done — test_client passing proves route logic, not thread-safety, streaming, or persistence.
2. A shared sqlite connection reused across request threads needs `check_same_thread=False` + a lock.
   Never reach for thread-local connections when `:memory:` must be shared (each connection = its own
   in-memory DB).
3. When a plan hands you code, the plan's *test* is the spec: `test_api_stop_unknown_job` expected 404
   but the plan's `api_stop` returned 200 for unknown jobs (because `is_done` can't tell "unknown"
   from "finished"). Fixed by adding a real `JobManager.exists()` predicate rather than string-matching
   the error message — surface the missing state, don't paper over it.

## Track C-bis Stage 1: CNN feasibility scheduling has strong AUC but ZERO end-to-end walk benefit (2026-07-15)
**Setup:** Stage 0 corpus (darkzig 1459 + FR16 800 probes; only 42 SAT positives / 1062 labeled).
Trained a small feasibility CNN `(region, skeleton, buildings) -> P(SAT)` and used it to rank/prune
patterns in the roads-first k-walk (opt-in `scorer`, CP-SAT still decides).
**AUC half of G1: PASS, convincingly.** Held-out ROC-AUC **0.999**; and crucially the *within-k-level*
AUC (strips the trivial "SAT lives at higher k" correlation, = the scheduler's real job) is mean
**0.987** across 9 levels. Scorer produces varied discriminative P(SAT) (0.00-0.99 within a level), not
a no-op. So despite only 42 positives, there is real learnable feasibility structure.
**End-to-end half of G1: FAIL (null result).** Baseline vs CNN-guided k-walk on darkzig, 30 min each,
equal config: **identical** — both reached lowest feasible k=111, best_achieved=**102 roads**, both
deadline-limited at the same frontier. The guidance moved nothing.
**Why (the load-bearing lesson):** the k-walk frontier is **decision-limited, not ordering-limited.**
During the easy descent (123->119->115->111) SATs are plentiful so probe order doesn't matter; below
k=111 the walk stalls on **slow UNKNOWN probes CP-SAT cannot decide within the probe-limit**, and
reordering cannot make a hard probe decidable. The scorer even correctly assigns high P(SAT) to some
sub-111 patterns, but CP-SAT still can't prove them fast enough. **A good ranking of a level's patterns
does not help when the barrier is per-probe SAT-proving time, not which pattern you try first.**
**Consequences:** (1) Stage 1 (scheduling) is NOT the lever to beat the baseline; the trained model is a
paid-for asset (good classifier) but doesn't move the walk alone. (2) This is exactly what Stage 1.5
(UNKNOWN autopsy) exists to diagnose: re-solve the frontier UNKNOWNs (sub-111) under a large budget --
if any are actually SAT (feasible-but-hard), **Stage 2 (CP-SAT warm-start from the model's placement)**
is the real lever; if all UNSAT, the pattern family caps out and the fix is better topologies, not ML.
(3) Offline AUC is necessary but NOT sufficient -- always run the end-to-end gate; a classifier that
ranks well can still deliver zero system-level benefit when the bottleneck is elsewhere.
**Aside:** both arms reached 102 validated roads in 30 min (below the earlier 106 benchmark) -- a config
effect (th-anchors full, patterns 200, probe-limit 30), not the CNN's doing.

## Track C-bis Stage 1.5: UNKNOWN autopsy finds no feasible-but-hard frontier -> Stage 2 not justified (2026-07-15)
**Experiment (`scripts/kwalk_autopsy.py`):** re-solved 8 frontier UNKNOWN patterns (4 at k=107, 4 at
k=109 -- the sub-feasible darkzig levels where the k-walk found no SAT; feasible frontier was
k=110/111) at **900s + 12 workers each**, vs the original 30s that produced the UNKNOWNs.
**Result: 0 SAT / 4 UNSAT / 4 UNKNOWN.**
**Read:** achievable SATs historically solve fast (~29s max), so a genuinely-feasible k=107/109
skeleton would very likely be found in 15min x 12 workers. 0/8 SAT + 4 *proven* infeasible is a
discouraging signal for the "feasible-but-hard" thesis -> leans **CASE 2 (pattern family caps out
near k~110-111)**, i.e. the lever is better skeleton *topologies*, not a CP-SAT warm-start. The 4
UNKNOWNs leave residual uncertainty, but there is **no SAT to warm-start toward**, so **Stage 2
(warm-start) is not justified on this evidence.**
**Track C-bis conclusion (Stage 1 null + Stage 1.5 no-go):** the ML-as-k-walk-accelerator thesis does
not pan out on darkzig. The frontier (~k=110, ~102-106 validated roads) is a **pattern-family limit**,
not a scheduling limit (Stage 1: ranking gave 0 benefit) nor a SAT-proving-speed limit (Stage 1.5: no
feasible-but-hard SAT to accelerate). Paid-for assets kept: the Stage-0 corpus engine, the feasibility
CNN (a genuinely good classifier, held-out AUC 0.999), and the opt-in scorer hook. **The remaining
lever to go below ~102 roads is pattern topology (lane/stub skeleton generators -- a separate, non-ML
track), or much more k-walk compute.** Before fully closing, a larger autopsy (more patterns / bigger
budget) could firm up the 4 UNKNOWNs, but 0/8 SAT is already a fairly strong negative.
**Meta-lesson:** a classifier with excellent offline AUC delivered zero system benefit AND its target
sub-problem turned out not to be the bottleneck -- validate the *bottleneck* (autopsy) before, not
after, building the ML pipeline. Here Stage 0 (data engine) + a cheap Stage 1.5 autopsy would have been
a smarter first move than Stage 1 (train+scheduler) in hindsight; the staged gates still caught it
cheaply, which is the point of measure-first.

## next-things-to-try #1: prune-mode k-walk (score-threshold) extends descent depth but does not improve best_achieved (2026-07-16)
**Setup:** `next-things-to-try.md` idea #1 flagged that the Track C-bis G1 gate only tested the CNN
scorer in **rank-only** mode (reordering); the scorer hook also supports **pruning**
(`--score-threshold`, patterns scoring below the threshold are dropped from the probe queue entirely,
not just reordered) and that lever had never been measured. Swept `--score-threshold 0.1/0.2/0.3/0.4`
on darkzig, 30min/arm (`scripts/prune_sweep.sh`), equal wall-clock, same config as the existing G1
baseline (patterns=200, probe-limit=30, workers=6, probe-workers=2, th-anchors=full); reused the
existing `output/kwalk/baseline.log` (30min, no scorer) rather than re-running it.
**Smoke-tested first** (2min budget, threshold 0.3): ran clean, valid JSON, no crash -- proceeded to
the full sweep.
**Result:**
| arm | lowest_feasible_k probed | best_achieved | inconclusive | walk_complete |
|---|---|---|---|---|
| baseline | 111 | 102 | 0 | false |
| threshold 0.1 | 109 | 102 | 1 | false |
| threshold 0.2 | 110 | 102 | 2 | true |
| threshold 0.3 | 110 | 102 | 2 | true |
| threshold 0.4 | 110 | 102 | 2 | true |
Per-k-level sequences (`output/kwalk/prune-{t}.log`) show no false negatives: every k baseline found
FEASIBLE (123/119/115/111) stayed FEASIBLE under every pruning threshold -- the mechanism is safe, the
threshold range 0.1-0.4 never mis-drops a truly-feasible pattern down to INFEASIBLE. Thresholds 0.2-0.4
gave **identical** k-sequences and outcomes (reproducible, not noise), so no repeat-seed runs were
needed to confirm.
**Pruning does free real budget** -- baseline never got past k=111 in 30min; 0.2-0.4 completed the
entire bisection to k=110 (`walk_complete=true`) and 0.1 reached k=109, one level deeper than baseline.
**But `best_achieved` stayed pinned at 102 in every arm, including baseline.** The extra k-levels
reached by pruning were either INCONCLUSIVE or a SAT that didn't beat the existing 102. **Verdict: no
gain from pruning at these thresholds** -- same root cause as the Stage-1 G1 null result
(2026-07-15 entry): the k-walk frontier is **decision-limited, not ordering/volume-limited**. Cutting
the number of patterns probed per level (pruning) lets the walk visit more k-levels within the time
box, but the binding constraint is whether CP-SAT can *prove* SAT/UNSAT on a hard pattern within the
30s probe-limit -- pruning doesn't make a single hard probe decidable faster, it just reaches more
locked doors sooner. Reordering (Stage 1) and now culling (this test) are both volume/order levers on
a problem that's gated by per-probe solve time.
**Consequence for the backlog:** idea #1 is closed, no gain. This sharpens the priority of idea #3
(symmetry breaking in the CP-SAT probe -- directly targets per-probe SAT/UNSAT proving time, the actual
bottleneck both this test and Stage 1.5 point at) and idea #2 (warm-start hints) over further
scheduling-side tweaks. Artifacts: `output/kwalk/prune-0.1.log` .. `prune-0.4.log`,
`scripts/prune_sweep.sh`.

## next-things-to-try #3: CP-SAT symmetry breaking makes the k-walk WORSE, reproducibly (2026-07-16)
**Setup:** idea #3 hypothesized that darkzig's heavy footprint symmetry (13x 2x2, 7x 4x4, 6x 6x4, ...
-- 63 consumers, 21 distinct sizes, 42 "chainable" same-size pairs) wastes CP-SAT time on permutation-
symmetric assignments, since `probe()`'s model has no per-building distinction beyond footprint size
(`_anchor_candidates` only reads `width`/`length`). Implemented `symmetry_breaking=` (opt-in, default
off) in `foeopt/roads_first.py`: for each footprint-size group, chain a lexicographic `(x, y) <=`
ordering across consecutive members via boolean channeling (`_add_symmetry_breaking`, 2 bool vars + 6
constraints per adjacent pair). Threaded through `_run_probe`/`_run_probe_seq`/`_worker_init`/
`RoadsFirstSearch`/CLI (`--symmetry-breaking` on both `exp_roads_first.py` and `kwalk_gate.py`), all
backward-compatible (existing 3-/5-tuple worker-payload call sites still work via defaults). Added
`test_symmetry_breaking_preserves_status_across_patterns` (checks SAT/UNSAT/UNKNOWN status is identical
on/off across every surviving pattern in a toy 3-identical-building case) plus the full suite (301
tests) and the roads-first `--selftest` (`parallel_equiv=True`) all green before measuring.
**Smoke-tested first** (2min budget): ran clean, no crash, valid JSON.
**A/B result (30min/arm, equal wall-clock, same config as the idea-#1 baseline): reproducibly WORSE.**
| arm | lowest_feasible_k | best_achieved | inconclusive |
|---|---|---|---|
| baseline (no symmetry breaking) | 111 | **102** | 0 |
| symmetry-breaking, run 1 | 115 | **105** | 1 (k=111 INCONCLUSIVE) |
| symmetry-breaking, run 2 (repeat) | 115 | **105** | 1 (k=111 INCONCLUSIVE) |
Both symmetry-breaking runs landed on the exact same k-sequence and numbers -- reproducible, not pool-
scheduling noise. The walk stalls a full level earlier than baseline and best_achieved regresses by 3
roads.
**Mechanism check:** timed 6 individual probes at k=115 on/off in isolation (2 UNSAT resolving in
<1s either way, 2 more UNSAT in ~0.75s either way, 2 UNKNOWN pinned at the 15s cap either way) --
**no per-probe slowdown visible on this small sample**, so the 30min regression isn't simple "each
probe takes longer" overhead on the patterns sampled. Most likely explanation (not directly measured):
cumulative per-probe *model-construction* cost (84 extra bool vars + ~250 extra constraints built in
Python on literally every probe, including the ~1300+ fast UNSAT ones from the idea-#1 baseline run)
adds up across the ~2000+ probes run in 30min, and/or the added constraints interfere with CP-SAT's own
automatic symmetry detection during presolve (a built-in feature) rather than complementing it --
manually-added redundant symmetry-breaking constraints are a known way to *slow down* a modern CP-SAT
solver that already detects and exploits this exact kind of interchangeable-item symmetry itself.
> **BOTH of these hypotheses were MEASURED AND REFUTED on 2026-07-22 -- see the amendment at the end
> of this entry. The A/B regression itself still stands; only the explanation was wrong.**
**Verdict: closed, stays opt-in/off.** `symmetry_breaking=` kept in `foeopt/roads_first.py` as tested,
correct, zero-cost-when-off infrastructure (same policy as `reach.py`/`--lns`/`--safe-placements`), but
the reproducible measurement rules it out as a win. **Lesson for the backlog:** "manually add textbook
symmetry breaking" is not free against a solver (CP-SAT) that already does this automatically in
presolve -- measure before assuming a classic OR technique transfers, same standing pattern as
"expert heuristics bolted onto the greedy constructor lose an equal-wall-clock A/B" (2026-07-06 entry),
now with a CP-SAT-specific instance: ~~don't fight the presolve~~.
**The "don't fight the presolve" generalization is WITHDRAWN (2026-07-22 amendment):** it was inferred
from a mechanism nobody had measured, and the branch counts measured later point the opposite way. What
survives is narrower and more durable: *an equal-wall-clock A/B beat the technique and we did not know
why -- so scope the verdict to the regime actually measured.* Idea #2 (warm-start hints from the
classical packer) is now the top remaining cheap-tier candidate; unlike this idea it doesn't add
constraints, it seeds the search, so it isn't subject to the same presolve-interference risk.
Artifacts: `output/kwalk/symbreak.log`, `output/kwalk/symbreak-2.log`.

### AMENDMENT 2026-07-22: the mechanism above is refuted; the A/B result is not
Found while investigating "why are so many richer-skeleton probes UNKNOWN at 300s?" -- that
investigation needed the real per-probe cost model, which forced a measurement of the two mechanisms
this entry had only hypothesized. Both are wrong.

**Hypothesis A -- cumulative model-construction cost -- REFUTED by direct timing.** Built the darkzig
k=105 probe model 20x with and without `_add_symmetry_breaking` (63 consumers, 21 size groups):

| model build | median |
|---|---|
| `symmetry_breaking=False` | 2.8 ms |
| `symmetry_breaking=True` | 3.8 ms |

**1.0 ms of extra Python per probe.** Across the ~2000 probes of a 30min arm that is ~2 seconds out of
1800 -- **0.1%**. It cannot produce a 3-road regression. The "84 extra bool vars + ~250 constraints
adds up" story was plausible-sounding arithmetic that nobody had multiplied out.

**Hypothesis B -- interference with CP-SAT's automatic presolve symmetry detection -- REFUTED by
branch counts.** Re-probed the 4 comb k=105 patterns that this session's diagnostic left UNKNOWN,
on/off, 60s cap, 1 worker:

| pattern | sym=False | sym=True |
|---|---|---|
| pat[2] | UNKNOWN 60s, 1,787,248 branches | **UNSAT in 18.6s**, 456,973 branches |
| pat[3] | UNKNOWN 60s, 1,744,041 | UNKNOWN 60s, 1,155,820 (-34%) |
| pat[5] | UNKNOWN 60s, 1,987,799 | UNKNOWN 60s, 1,387,815 (-30%) |
| pat[7] | UNKNOWN 60s, 1,971,135 | UNKNOWN 60s, 1,564,325 (-21%) |

Branch counts fall 21-34% and one instance *flips to decided*. If the added constraints were fighting
presolve's own symmetry detection, branches would rise. They fall. Soundness cross-check: `pat[2]`'s
UNSAT is independently corroborated -- the un-instrumented 12-worker run refuted the same pattern at
38.1s *without* symmetry breaking, so the flip is a real refutation, not an over-constrained false
UNSAT. (Note the speedup: 18.6s on 1 worker vs 37.6s of solve on 12.)

**So why did the 30min A/B regress?** *Unknown, and now explicitly recorded as unknown.* Not build
cost (0.1%), not presolve interference (branches fall). The regression is real and reproducible; its
cause is unexplained. Do not invent a third mechanism without measuring it.

**Scope correction.** The A/B measured *end-to-end k-walk quality at fixed wall-clock* -- ~2000+ probes
averaging <1s, throughput-dominated, and its own mechanism check pinned its 2 UNKNOWN probes at a
**15s cap**, too short to observe the effect above. That verdict is sound **for the k-walk** and stays.
It should not be read as "symmetry breaking is bad here" in the *big-budget* regime (72 probes x 300s,
e.g. `scripts/exp_richer_skeleton_probe.py`), where 1ms of build cost is noise and branch efficiency is
the whole game. Nobody has measured that regime beyond the n=4 above -- which is far weaker evidence
than the A/B, and is a signal to test, not a result to act on.

**Methodological lesson (the durable one).** This entry said *"Both symmetry-breaking runs landed on the
exact same k-sequence and numbers -- reproducible, not pool-scheduling noise."* That is true and it does
rule out scheduling noise -- but re-running a fixed-seed pipeline demonstrates **determinism, not
independent confirmation**. Same seed -> same patterns -> same trajectory, twice. The evidence was one
trajectory through pattern space, reported in language ("reproducibly", twice-run table) that reads like
two samples. **When a repeat run shares the seed, say "deterministic", not "reproducible" -- and get
independent samples by varying the seed before calling a lever closed.**

## next-things-to-try #2: CP-SAT warm-start hints from the classical packer also make the k-walk WORSE, reproducibly (2026-07-16)
**Setup:** idea #2 hypothesized that hinting `probe()`'s CP-SAT model with the classical repack
packer's building positions (via `AddHint`) could turn slow frontier UNKNOWNs into fast SAT/UNSAT,
without adding any constraints (so, unlike idea #3's symmetry breaking, not subject to a presolve-
interference risk). Implemented `hints=` in `foeopt/roads_first.py`: for each consumer with an
entity_id present in the hint map, `AddHint`s its (x, y) vars to the *nearest valid anchor* in that
building's `opts` for the current pattern (`_nearest_opt`, Manhattan distance) -- never an out-of-
domain value, so the hint is always locally consistent even though it may not be collision-free
globally. Threaded through the same worker-global/`RoadsFirstSearch`/CLI plumbing as idea #3
(`hint_layout=` constructs the entity_id->(x,y) map once from a `Layout`; `--warm-start`
[`--warm-start-budget`, default 30s] on both CLI scripts calls `foeopt.packer.repack()` once and feeds
its output layout in). Added 2 tests (hint status-preservation across patterns incl. an out-of-region
hint that must snap via `_nearest_opt`, not crash; `_nearest_opt` unit test) -- full suite (303 tests)
and roads-first `--selftest` green before measuring.
**Smoke-tested first** (2min budget): ran clean, no crash, valid JSON.
**A/B result (equal *total* wall-clock: 30s repack + 1770s walk = 1800s, matching the 1800s baseline;
2 runs to check reproducibility): reproducibly WORSE**, same pattern as idea #3.
| arm | lowest_feasible_k | best_achieved | inconclusive |
|---|---|---|---|
| baseline (no hints) | 111 | **102** | 0 |
| warm-start, run 1 | 117 | **109** | 1 (k=115 INCONCLUSIVE) |
| warm-start, run 2 (repeat) | 117 | **109** | 1 (k=115 INCONCLUSIVE) |
Both warm-start runs landed on the exact same k-sequence and numbers -- reproducible, not noise. Two
k-levels earlier stall than baseline and best_achieved regresses by 7 roads (worse than idea #3's
regression).
**Mechanism check:** timed 6 individual probes at k=115 on/off in isolation -- again **no per-probe
slowdown visible** (UNSAT resolves in <0.5-1.1s either way, UNKNOWN pinned at the 15s cap either way;
if anything the hinted UNSAT probes were marginally *faster*). The likely explanation is the **quality
of the hint source, not solver mechanics**: `repack()` alone (no anneal polish -- the polish step is
what the project's other results get to the 158-road local-method floor from) landed **199 roads** in
a 15s diagnostic call here, i.e. the hinted building positions come from a layout with far more slack
and a completely different road topology than what a ~102-118-road roads-first pattern needs. The hint
therefore doesn't point CP-SAT toward a good region of the search space for the *tight* skeletons the
k-walk is actually probing at the frontier -- it points toward a loose, road-inefficient one, and
`AddHint`'s repair-from-hint search machinery spends effort reconciling that irrelevant starting point
instead of searching freely. Consistent with idea #3's reading: bolting external structure onto CP-SAT
without accounting for how it interacts with the solver's own search strategy is not free.
**Verdict: closed, stays opt-in/off.** `hints=` kept in `foeopt/roads_first.py` as tested, correct,
zero-cost-when-off infrastructure (same policy as `symmetry_breaking=`/`reach.py`/`--lns`), but not a
win as tested. **Not retested with an annealed/polished hint source (~158 roads, closer in quality to
the k-walk's own frontier) -- that's a plausible but unmeasured follow-up, out of scope for this A/B
since idea #2 as written specified "the existing repack/greedy packer layout".**
**Consequence for the backlog:** all three of the cheap-tier ideas (#1 pruning, #2 warm-start, #3
symmetry breaking) are now closed, all negative, all pointing at the same wall: the k-walk frontier is
gated by raw CP-SAT proving time on hard patterns, and none of these levers (reordering, culling,
constraining, seeding) move that needle on darkzig. The medium-tier idea #5 (lane/stub topology
generator -- attacking the *pattern family* itself, not the solver) is now the strongest remaining
candidate, per the same "pattern-family limit, not a scheduling/solver limit" conclusion Track C-bis
Stage 1.5 already reached from a different angle. Artifacts: `output/kwalk/warmstart.log`,
`output/kwalk/warmstart-2.log`.

## next-things-to-try #5: lane/stub topology generator also regresses the k-walk (2026-07-16)
**Setup:** with all three cheap-tier solver-side levers closed negative, idea #5 targeted the
pattern *family* itself: the comb generator's short, budget-proportional teeth off one trunk
can't represent the user's real city's straight double-loaded lanes + near-zero-overhead trunk
(5/142 cells) + TH stubs. Added `generate_lane_patterns()` to `foeopt/roads_first.py` as a second
family, matching `generate_patterns()`'s signature so it drops into the same k-walk/CP-SAT/
validate pipeline unchanged (opt-in `pattern_family=`/`--pattern-family {comb,lane}`, default
`comb`). Reuses `th_anchor_candidates`/`_trunk`/`_stub_cells`; unlike the comb family (which
commits `budget//2` cells to trunk regardless of need), the trunk is built *minimally* -- only
spanning from the TH-adjacent anchor cell out to the furthest lane seed on each side -- directly
encoding the "almost no overhead" finding. Lanes grow as full straight runs (not single-step
teeth) from seeds spaced at a `pitch` (5-11) along that trunk.
**Found and fixed a real bug before any timed run:** `_trunk()`'s returned cell list has the
TH-adjacent anchor cell at index 0 only when the TH sits at a region corner -- for TH placements
away from a corner (confirmed empirically on darkzig: anchor at index 23 of 52 for a mid-region
TH), the anchor sits in the *middle* of the list. A naive `trunk[:n]` prefix (which is what the
comb family already does, and works there mainly because its trunk_len -- `budget//2` -- is
usually large enough to reach past the anchor by luck) would silently produce a **disconnected**
lane pattern for non-corner TH placements. Fixed by explicitly computing the anchor's index and
slicing symmetrically around it (`_th_anchor_cell()` + `trunk_raw[lo:hi+1]`). Caught via a
dedicated regression test (`test_generate_lane_patterns_th_off_corner_anchor_mid_trunk`) plus a
direct `_check_pattern` sweep across k=8/20/40 before any CP-SAT time was spent -- all patterns
connected, exact-k, in-region.
**Also found a monkeypatch-breaking bug during testing:** the first implementation dispatched
families via a module-level `_PATTERN_GENERATORS = {"comb": generate_patterns, ...}` dict built
once at import time, which silently broke two pre-existing tests
(`test_probe_level_records_each_probe`, `test_scorer_orders_and_prunes_patterns`) that
monkeypatch `rf.generate_patterns` directly -- the dict had already captured the original
function object, so patching the module attribute had no effect on dispatch. Fixed by resolving
the family via a plain function (`_pattern_generator(family)`) that does a live name lookup
against module globals on every call, restoring monkeypatch-ability. Full suite green (310
tests) before any timed run.
**Sanity pass** (`--dump-patterns`, no CP-SAT time): lane family produces a healthy, comparable
pattern count to comb across the whole relevant k range (152 vs comb's 192 at k=60-150, both
100% prefilter survival) -- not degenerate, not near-empty.
**Smoke-tested first** (2min budget): ran clean, no crash, valid JSON.
**A/B result (equal 1800s wall-clock, 2 runs): reproducibly WORSE**, same direction as ideas
#2/#3, though (unlike those) not bit-identical across the two runs:
| arm | lowest_feasible_k | best_achieved |
|---|---|---|
| baseline (comb) | 111 | **102** |
| lane family, run 1 | 115 | **109** |
| lane family, run 2 (repeat) | 115 | **112** |
Both lane-family runs plateau at k=115 (never reaching k=111 or below) -- a full k-level worse
than baseline in both runs, with `best_achieved` 7-10 roads worse. The exact `best_achieved`
differed between runs (109 vs 112, unlike ideas #1-3's bit-identical repeats) -- explained below.
**Mechanism check (this time a clear signal, unlike ideas #2/#3's inconclusive per-probe timing):**
timed 6 individual probes at k=115 for each family in isolation. **Comb: 4/6 fast UNSAT (0.7-1.6s),
2/6 UNKNOWN (10s cap). Lane: 6/6 UNKNOWN (10s cap) -- zero fast resolutions.** The lane family's
long straight corridors with wide parallel building rows create geometrically harder
`NoOverlap2D` decision problems for CP-SAT than the comb's shorter, more locally-constrained
teeth -- even though the lane topology is structurally closer to the user's real (efficient) city,
it is *harder for the solver to arbitrate*, which starves the walk of the fast SAT/UNSAT
resolutions it needs to make k-walk progress within a fixed probe-limit. This also explains the
run-to-run variance: with almost every probe pinned at the timeout, which few probes happen to
finish (parallel-pool race) has an outsized effect on the result, unlike the comb family where
most probes resolve fast and the outcome is dominated by exhaustive coverage rather than luck.
**Verdict: closed, stays opt-in/off.** `pattern_family=`/`generate_lane_patterns()` kept as
tested, correct (including a real connectivity bug fixed pre-flight), zero-cost-when-unused
infrastructure -- not a win as implemented. **This closes all four next-things-to-try levers
tried so far (pruning, warm-start, symmetry breaking, lane topology), all negative, and sharpens
the diagnosis further: it is not enough for a richer topology to structurally resemble the
expert city -- it must also be easy for CP-SAT to *decide* quickly, and the two pull in opposite
directions here (wider/straighter geometry -> harder packing subproblems).** A follow-up (not
built) worth flagging for later: a *hybrid* family (short comb teeth near the frontier /
hard-to-decide region, full lanes only where slack is generous) might recover the lane family's
structural advantage without its solver-hardness cost -- unmeasured, out of scope for this A/B.
Artifacts: `output/kwalk/lanefamily.log`, `output/kwalk/lanefamily-2.log`.

## Stub priority hint: hurts the comb family, helps and stabilizes the lane family (2026-07-17)
**Setup:** user follow-up question after the roads-first work above -- does the model require the
*biggest* buildings to sit next to the TH stub cells, matching the expert-city heuristic
(`memory/foe-layout-heuristics`: "puts ~3 big buildings next to each stub", each stub cell reaching
load-3 "for free" via the TH edge)? No: `probe()` has zero objective, so CP-SAT seats whichever
building fits first, with no size preference. **Diagnostic first (before building):** inspected
3 existing solved layouts (`best-k110-a102.json`, `best-k111-a102.json`, `best-k115-a105.json`) --
every one had at least one stub-adjacent cell hosting a genuinely tiny building (area 1 or 4)
alongside bigger ones (16-49), confirming real headroom for a size-aware nudge.
**Implementation:** `stub_priority=`/`--stub-priority` (opt-in, default off) added to `probe()`.
`_th_stub_cells_in_pattern(th, roads)` finds whichever of the 4 candidate TH-flank cells are road
cells in the *given* pattern (family-agnostic -- works whether they're comb stubs, lane stubs, or
incidental trunk cells); `_stub_priority_hints()` then `AddHint`s the largest buildings (by area,
top-3 per stub cell, matching the load-3 ceiling) toward their own valid anchor options that touch
that cell -- a soft nudge (not a hard constraint), and every hint is drawn from the pattern's own
already-computed `opts`, so (unlike the failed idea #2 warm-start) it's always in-domain by
construction. Verified the selection logic on a controlled 6-building case (only the 3 largest of
6 candidates get hinted) and confirmed real coverage on darkzig (177/200 sampled patterns had at
least one stub cell present, and the top-6-by-area selection matched expectations on inspection).
Added a SAT/UNSAT-preservation equivalence test (mirrors the `symmetry_breaking`/`hints` tests).
315-test suite and `--selftest` green before any timed run.
**A/B result (30min/arm, equal wall-clock, x2 per family/arm for reproducibility) -- a genuinely
mixed, family-dependent result, the first non-uniformly-negative one in this whole run of
experiments:**
| family | arm | k reached | best_achieved |
|---|---|---|---|
| comb (production default) | baseline | 111 | 102 |
| comb | + stub_priority | 111 | **105, 105** (worse, reproduced x2) |
| lane | baseline | 115 | 109, 112 (variable across runs) |
| lane | + stub_priority | 115 | **108, 108** (better than *both* baseline runs, reproduced x2) |
`stub_priority` **hurts** the comb family by 3 roads (same k-walk depth, reproducibly worse
`achieved`) but **helps and stabilizes** the lane family -- not only does it land at 108 (better
than both 109 and 112), it eliminates the lane baseline's own run-to-run variance (bit-identical
across both repeats, unlike the baseline's own two runs disagreeing by 3).
**Mechanism check:** per-probe SAT/UNSAT/UNKNOWN status comparison (5 patterns each, lane k=115 and
comb k=111, on/off) showed **zero status flips** -- consistent with the equivalence tests: the
hint never changes whether a pattern is feasible. The likely explanation for a `best_achieved`
shift despite unchanged decidability: `achieved` is computed by `route()` on whichever *specific*
building placement CP-SAT actually returns for a SAT pattern, not from the road-skeleton budget
`k` itself -- so a hint that changes *which* feasible placement is found (without changing whether
one is found) can still shift the final routed road count. This is inferred from the reproducible
net effect, not directly proven by a per-probe trace (the small sample above didn't happen to catch
a shifted-solution case) -- flagged honestly as the best available explanation, not a certainty.
**Verdict: mixed, stays opt-in/off by default everywhere.** Since comb is the production default
and current best method (102, still far ahead of lane+stub_priority's 108), `stub_priority` must
NOT flip to default-on there -- it would regress the project's best result. It's a genuine,
reproducible win specifically for the *lane* family, which is itself still closed/opt-in from the
next-things-to-try #5 entry above (lane alone regresses vs comb; lane+stub_priority narrows that
gap from -7/-10 to -6, but doesn't close it). Kept as tested, correct, zero-cost-when-unused
infrastructure, available for revisiting if the lane family (or a future hybrid family per #5's
follow-up note) is ever picked back up. **Standing pattern across this session's four solver-side
levers (symmetry breaking, warm-start, lane topology, stub priority):** every added
constraint/hint/hint-like nudge either regressed or was neutral on the comb family specifically --
comb's search is already fast and decisive (mostly quick UNSAT, per the idea #5 mechanism check),
and redirecting an already-efficient search seems to cost more than it buys. The one place a hint
helped (lane + stub_priority) is exactly the one place the baseline search was already struggling
(lane's per-probe check showed 6/6 UNKNOWN at a comparable k) -- weak but consistent evidence that
these levers pay off only when the underlying search has room to be steered, not when it's already
efficient. Artifacts: `output/kwalk/stubpriority-comb.log`, `output/kwalk/stubpriority-comb-2.log`,
`output/kwalk/stubpriority-lane.log`, `output/kwalk/stubpriority-lane-2.log`.

## Hybrid comb/lane (bounded lane length): non-monotonic, cap=24 is a real win (2026-07-17, revised)
**Setup:** idea #5's flagged follow-up -- "a hybrid family (short comb teeth near the frontier /
hard-to-decide region, full lanes only where slack is generous) might recover the lane family's
structural advantage without its solver-hardness cost." Rather than building a second from-scratch
generator with a spatial teeth-vs-lanes classification rule (no obvious cheap proxy for "frontier"
vs "slack"), tested the same underlying hypothesis -- that *lane length*, not lane-ness itself,
drives the decidability cost idea #5 found (6/6 UNKNOWN for uncapped lane probes vs comb's 4/6 fast
UNSAT) -- via a much cheaper single-parameter dial: `max_lane_len` added to
`generate_lane_patterns()` (`foeopt/roads_first.py`), capping how far each lane grows from its
seed before stopping. Cap=None (default) preserves today's exact uncapped behavior (verified via a
dedicated backward-compat test comparing full pattern output, plus a test confirming the cap
actually bounds growth by re-deriving each pattern's trunk/seeds and walking its fronts). Wired as
`--lane-cap N` alongside the existing `--pattern-family`/`--stub-priority` flags. 318-test suite
and `--selftest` green before any timed run. Sanity pass (`--dump-patterns`) across caps 3-12
showed cap=3 nearly empty at the relevant k range (0-18 patterns at k>=110) -- dropped; caps 4 and
8 chosen as short/medium representatives with healthy-looking pattern counts (18-151 across
k=100-120).
**First pass (caps 4, 8) looked monotonically negative:**
| arm | k reached | best_achieved |
|---|---|---|
| comb baseline | 111 | 102 |
| lane, uncapped (idea #5 baseline) | 115 | 109, 112 |
| lane, cap=8 | 123 | **119, 119** (reproduced exactly) |
| lane, cap=4 | -- | **FAMILY_TOO_WEAK** (climbed to k=283, `walk_complete=true`, never found a single SAT) |
Cap=8 is worse than uncapped lane on *both* metrics (2 k-levels higher, 7-10 roads worse) despite
having plausible-looking pattern diversity in the sanity pass; cap=4 is a total, decisive failure
-- not a near-miss, not a timeout, the upward-fallback walk exhausted the entire feasible k range
without ever finding one SAT pattern. Based on these two points the entry originally concluded
"capping is monotonically worse, no sweet spot" -- **that conclusion was wrong; see cap=24 below.**
**User follow-up 1: cap=16.** A/B'd 30min x2 (reproduced exactly): **k=115/roads=111 both runs**
-- matches uncapped's k-level exactly, and 111 falls inside uncapped's own run-to-run range
(109-112), statistically indistinguishable from not capping at all.
**User follow-up 2: cap=24 -- overturns the "no sweet spot" conclusion.** While sanity-checking
this cap, found and fixed a real, pre-existing bug (present since the original `--dump-patterns`
implementation, long before this session): `scripts/exp_roads_first.py`'s dump-patterns path never
threaded `th_mode` through to the generator, so every `--dump-patterns --th-anchors full` sanity
check run in this whole investigation (caps 3/4/6/8/12/16) was silently using the default `coarse`
TH-anchor mode instead -- **the real 30-min A/B runs were unaffected** (`kwalk_gate.py walk`
correctly threads `th_anchors` through `RoadsFirstSearch`/`_probe_level` throughout), only the
informal pre-flight pattern-count diagnostics were inaccurate. Fixed with a one-line addition
(`gen_kwargs = {"th_mode": args.th_anchors}`); doesn't change any previously-reported hard number,
only the (now corrected) diagnostic counts. With the fix, cap=24 shows 200/200/200 patterns
(hitting the `max_patterns` cap) at k=100/110/120, and a direct comparison confirmed cap=24's
pattern set is *not* identical to uncapped's (so it's not a no-op, unlike what the buggy coarse-
mode reading of cap=16 suggested). A/B'd 30min x2 (reproduced exactly): **k=115/roads=106 both
runs** -- better than *every* other lane-family result tried, including plain uncapped (109-112)
and cap=16 (111), and the closest the lane family has come to comb's 102.
| cap | k reached | best_achieved |
|---|---|---|
| comb baseline | 111 | 102 |
| **24** | 115 | **106, 106** (reproduced -- best lane-family result) |
| uncapped | 115 | 109, 112 |
| 16 | 115 | 111, 111 |
| 8 | 123 | 119, 119 |
| 4 | -- | FAMILY_TOO_WEAK |
**Not monotonic.** The relationship between cap size and result quality has a real optimum
somewhere near cap=24, not a smooth "smaller is worse" gradient bottoming out at "uncapped is
best." **Why (best available explanation, not fully confirmed):** a cap set well above the
"typical" productive lane length but below the *longest* outlier lengths the uncapped family
occasionally grows may selectively remove only the rare, most-NoOverlap2D-costly long lanes from
the candidate pool, while leaving the bulk of productive, moderate-length lane patterns untouched
-- a soft outlier filter rather than a uniform restriction. Cap=16 apparently sits below that
"productive ceiling" often enough to matter (statistically indistinguishable from uncapped);
cap=24 sits closer to it; cap=8 cuts well into the productive range and hurts; cap=4 removes it
entirely. This is inferred from the shape of the data, not directly measured (would need a
per-pattern length-distribution histogram to confirm) -- flagged honestly as the best current
reading, not a certainty.
**Bracketing the sweet spot (same day): cap=24 is a genuine, isolated local optimum, not part of
a wider plateau.** Ran cap=20 and cap=28 (one run each, since the question was the *shape* of the
curve around an already-double-reproduced anchor point, not a new headline number needing its own
reproduction):
| cap | best_achieved |
|---|---|
| 16 | 111, 111 |
| 20 | 110 |
| **24** | **106, 106** (reproduced) |
| 28 | 111 |
| uncapped | 109, 112 |
Both immediate neighbors (20, 28) are clearly worse than 24 and land close to 16/uncapped's range
-- a narrow, isolated dip centered exactly at 24, not a gradual gradient or a wide plateau. No
further bracketing (e.g. finer steps between 20-24 or 24-28) was needed to see the shape.
**Layering `stub_priority` on top of cap=24 -- does not stack, makes it worse.** `stub_priority`
independently improved the *uncapped* lane family (108 vs 109/112, see the 2026-07-17 stub-priority
entry). Tried combining it with the now-winning cap=24. A/B'd 30min x2 (reproduced exactly):
**cap=24 + stub_priority -> k=115/roads=110, both runs** -- worse than cap=24 alone (106) and
roughly back to the cap=20/uncapped range. The two levers don't compose additively; whatever makes
cap=24 work well on its own is disturbed by also biasing the search toward big-buildings-at-stubs.
Consistent with this session's broader pattern: levers that help a *struggling* search (stub
priority helped uncapped lane, which was UNKNOWN-dominated per idea #5's mechanism check) tend to
hurt an *already-tuned* one (cap=24's own search is evidently already landing in a better regime,
and the extra hint disturbs rather than improves it) -- the same "helps weak search, hurts strong
search" reading first proposed for comb vs lane now shows up *within* the lane family itself,
between cap=24 (strong, for a lane variant) and uncapped (comparatively weak).
**Final verdict: cap=24 *alone* (no `stub_priority`) is the best-performing lever variant found in
this entire next-things-to-try line, and the closest any of it has come to comb.** 106 vs comb's
102 -- still short, but a real, reproduced, bracketed, isolated-optimum result, not a lucky draw.
`max_lane_len=`/`--lane-cap` and `stub_priority` both kept as tested, correct, zero-cost-when-unset
infrastructure. If this thread is picked up again, the natural next step is understanding *why*
cap=24 specifically works (a per-pattern lane-length histogram against the uncapped family's own
distribution would confirm or refute the "outlier filter" theory above) rather than more blind
parameter search -- the bracket here was cheap and conclusive, further probing without a mechanism
hypothesis would not be. Artifacts: `output/kwalk/lanecap4.log`, `output/kwalk/lanecap8.log`,
`output/kwalk/lanecap16.log`, `output/kwalk/lanecap16-2.log`, `output/kwalk/lanecap20.log`,
`output/kwalk/lanecap24.log`, `output/kwalk/lanecap24-2.log`, `output/kwalk/lanecap28.log`,
`output/kwalk/lanecap24-stubpriority.log`, `output/kwalk/lanecap24-stubpriority-2.log`.

## next-things-to-try #4: tightened UNSAT prefilter -- sound improvement, but null at the k-walk's real operating range (2026-07-17)
**Setup:** `prefilter()` (`foeopt/roads_first.py`) already has an adjacency-capacity check
(`bound_adjacency`'s "<=3 consumers per road cell" argument) but applied it loosely: any road cell
with *at least one* free orthogonal neighbor got a flat capacity of 3, regardless of whether it
actually had 1, 2, or 3 free neighbors after this specific pattern's own roads/TH occupy some of
them. Tightened to `min(3, actual free orthogonal neighbor count)` -- strictly tighter, still 100%
sound (a more accurate count of the same provably-necessary quantity, never risks the `reach.py`
false-reject failure mode from 2026-07-05, since it only ever rejects patterns the *old* check
would also have needed to reject given perfect information). Explicitly avoided the backlog's
alternative suggestion ("fast greedy first-fit whose hard failure flags likely-UNSAT") since that's
a heuristic, not a certificate -- using it as a hard reject risks exactly the `reach.py` regression;
using it only to reorder the probe queue would just be idea #1 (pruning) again, already measured
null this session. Added 2 unit tests (a controlled case with a road cell that has exactly 1 true
free neighbor: old check accepts, new check correctly rejects; and a matching case where 1
consumer's demand is genuinely satisfiable, confirming the tightened check doesn't over-reject).
320-test suite and `--selftest` green.
**Diagnostic before any A/B (per the project's measure-first rule):** compared old-vs-new rejection
counts on darkzig across both pattern families. At the k-walk's actual operating range (k~93-123,
where every real run this session has probed), **zero additional patterns rejected by either
family at any tested k** (102/106/111/115/120 comb; 80/100/115/120 lane) -- the bound is tighter in
the abstract but never actually bites there. It *does* catch substantially more at k far below that
range (k=25: 200/200 newly rejected; k=30: 97/200; k=40: ~1-4/200) -- but the k-walk's own
`pick_k_start`/descent logic never probes k that low in practice (trivially area/adjacency-
infeasible territory the walk would never reach from its k_start ~150+ descending only to ~93-123).
**Verdict: sound, correct, real improvement to a provable bound -- but a null result for the
production k-walk, so no real A/B run was spent on it** (per the plan's own "if it rejects ~0 more,
report as null without a 30min run" rule). Kept as a permanent, zero-risk tightening (not opt-in --
it's strictly more correct than the old flat-3 check with no downside, unlike every other
opt-in/off lever this session). Consistent with the session's broader finding that the k-walk's
real bottleneck is per-probe CP-SAT decision time on patterns that *pass* every cheap prefilter,
not on patterns a cheap filter could have caught -- there's no low-hanging fruit left in the
prefilter itself at this city's actual difficulty range.

## next-things-to-try #6: joint minimize-roads CP-SAT -- correct at toy scale, memory-catastrophic at real scale (2026-07-17)
**Setup:** every prior lever this session worked *within* the two-stage architecture (propose a
road skeleton, then `probe()` places buildings on it, bisecting a fixed `k`). Idea #6 asked whether
removing the two-stage split -- making road-cell selection itself a CP-SAT decision variable with
an explicit `Minimize(sum(roads))` objective, solved jointly with placement -- could beat the
k-walk's best achieved (102, comb). Built `foeopt/minroads.py`: a standalone model (does not touch
`roads_first.py`/`probe()`) with connectivity enforced as a BFS-tree constraint (`dist_c` IntVar per
candidate cell, reified parent-link BoolVars proving reachability from a TH-adjacent root by
strictly-increasing integer distance -- CP-SAT's Python API has no lazy-cut support, so this
distance-labeling encoding is the standard substitute for "roads form a tree rooted at TH") and
building placement as one-hot `NewOptionalFixedSizeIntervalVar`s per (building, valid (x,y))
channeled to the road-selection BoolVars, since `AddAllowedAssignments` against a precomputed
position list no longer applies once the road set itself is a variable.
**Toy-scale correctness gate:** 4 tests in `tests/test_minroads.py` compare `solve_min_roads`
against `rl.oracle.optimal_roads` (the project's existing exact brute-force oracle) on 2/3/4-building
toy layouts -- exact match on road count every time, plus one test that independently re-validates
the model's own chosen positions through the *real* `route()`/`is_valid()` pipeline rather than
trusting the model's internal claims. All 4 pass. Model is provably correct at small scale.
**Real-city tractability gate (the actual point of the plan's gating structure):** ran
`scripts/exp_minroads.py darkzig.json` at increasing time budgets.
- `--time-limit 60`: completed cleanly in 65.2s wall time (model construction itself is fast, a few
  seconds -- the 65.2s is dominated by the 60s solve budget), but returned `status=UNKNOWN,
  roads=None` -- CP-SAT could not find *any* feasible solution, let alone prove optimality, within
  60s on darkzig's real scale (2720 region cells, 63 consumers).
- `--time-limit 300`: killed by the OS at exit 137 (SIGKILL) -- not the process itself failing,
  the *system* intervening. Re-ran under direct process monitoring (`ps -o rss`) to confirm: RSS
  hit ~3.9GB within 17 CPU-seconds of the solve starting and kept climbing. A second monitoring
  attempt exhausted the machine's 30GB RAM + swap badly enough that **it crashed the user's
  terminal** (confirmed directly by the user: "Process keeps crashing the terminal"). Force-killed
  via `pkill -9 -f exp_minroads.py`; memory recovered once dead.
**Verdict: decisive kill, worse than the plan's own worst-case expectation.** The plan anticipated
"may not even reach a first feasible solution in reasonable time" as the likely negative outcome
and treated that as sufficient to stop (no long-box escalation, per the project's "no tuning
marathon" rule). What actually happened is a level below that: the one-hot placement encoding
(`O(buildings x positions-per-building)` boolean variables, replacing the fixed model's `O(buildings)`
IntVars) combined with the BFS-tree connectivity encoding (one IntVar + up to 4 reified parent-link
BoolVars *per candidate road cell*, ~2720 of them) blows up CP-SAT's internal memory footprint
catastrophically before it can even finish a first search pass -- not merely slow, actively
dangerous to run unbounded on a real workstation. **Do not re-attempt this model at real-city scale
without a hard memory ulimit and much smaller instances first** (e.g. bound the road-candidate
region to a bounding box around a partial city, not the full 2720-cell darkzig region) if this
direction is ever revisited. The two-stage roads-first architecture's separation of concerns --
fixed, pre-verified-connected skeleton with only `O(buildings)` placement variables -- isn't just
an implementation convenience, it's load-bearing for tractability at this problem size. Confirms by
contrast that this session's real wins (idea #5 lane topology, stub priority, the cap=24 hybrid,
idea #4's prefilter) all worked by improving the two-stage split rather than replacing it, and that
was the right place to have spent the compute.
**Kept as a documented, gated negative/throwaway result** (`foeopt/minroads.py`,
`tests/test_minroads.py`, `scripts/exp_minroads.py`), not productionized, not imported by any
production code path -- same posture as every other closed experiment this session.

## next-things-to-try #7: concurrent k-levels -- workers-count bump backfires, cross-level batching is a real (small) win (2026-07-19/20)
**Setup:** unlike #1-6, this was explicitly a "same result, less compute" idea -- the k-walk
(`RoadsFirstSearch.run()`) leaves cores idle per the backlog's own note ("16 cores available; runs
use ~12"). Split into two independently-testable mechanisms before writing any concurrency code,
per the project's measure-first rule: (1) `kwalk_gate.py`'s defaults are `--workers 6
--probe-workers 2` = 12 of 16 cores -- nothing stops running `--workers 8` = 16 cores today, zero
code required; (2) independent of worker count, `run()`'s ascent/descent phases call `level(k)`
one at a time, and `_probe_level` blocks until that level's ~200 patterns fully drain before the
*next* level is even generated -- a synchronization barrier that idles workers near each level's
tail regardless of pool size.
**Phase 0 (free diagnostic, no code change): `--workers 8` reproducibly makes it WORSE, not
better.** Equal wall-clock (1800s) vs the existing `baseline.log` (workers=6): baseline reached
k=111/best_achieved=102, 0 inconclusive. `--workers 8` (`output/kwalk/workers8.log` + `-2.log`,
byte-identical both runs) only reached k=113/best_achieved=105 with 1 INCONCLUSIVE level -- a full
level worse, reproducibly. Mechanism: 8 workers x 2 probe-threads = 16 concurrent CP-SAT threads on
a 16-core machine leaves zero headroom for OS/scheduling overhead, so individual probes run slower
under contention. This is a genuinely different, useful negative result on its own (the "obvious"
fix -- just add more workers -- is actively counterproductive here), and importantly doesn't
implicate the barrier hypothesis: Phase 1 below doesn't touch worker count at all, so it can't
reintroduce this same contention.
**Phase 1: cross-level batched dispatch.** Added `_probe_levels_batch(layout, region, consumers,
ks, ...)` (`foeopt/roads_first.py`) which generates+prefilters patterns for a *list* of k's (in
order, against the same shared `rng`, preserving byte-identical pattern content vs sequential
per-k calls -- verified by a dedicated determinism test) and submits all their surviving patterns
into **one** `pool.imap_unordered` call instead of one call per level, eliminating the per-level
drain barrier. `_probe_level(k)` is now a one-line wrapper (`_probe_levels_batch(..., [k], ...)[k]`)
-- kept every existing call site and the full `test_probe_level.py`/`test_search.py` suite passing
unmodified (324 tests, zero changes needed), proving batch-of-1 degenerates to exactly today's
code path. Two pre-existing tail-classification quirks (a mid-level deadline hit in the `pool=None`
branch returns a conservative 2-way INCONCLUSIVE/FEASIBLE; the same in the pooled branch falls
through to the standard 3-way logic and can mis-classify a never-tested level as INFEASIBLE) were
identified and **deliberately preserved bit-for-bit**, not fixed -- this was scoped as a pure speed
change, and "fixing" either quirk would make batch-of-1 diverge from today's `_probe_level`,
violating the whole point of the backward-compat wrapper. New opt-in `RoadsFirstSearch(...,
concurrent_levels=N)` (default 1 = today's behavior exactly) batches the ascent phase (`[k+4,
k+8, ..., k+4N]`, take the smallest FEASIBLE) and fine-descent phase (`[lo-4, ..., lo-4N]`, take
the smallest still-feasible under the walk's existing monotonicity assumption) into single
dispatches; bisection stays sequential (already the most information-dense phase, out of scope).
8 new tests for `_probe_levels_batch` (SAT tracking, both interruption-classification quirks,
the merged-single-`imap_unordered`-call mechanism itself, the rng-determinism invariant) + 4 new
`RoadsFirstSearch` tests (ascent/descent batch construction, concurrent_levels=1 never touches the
new function, concurrent_levels=1 vs 4 reach identical verdict/best_achieved on a fake truth
table). 333 total tests green, `--selftest` PASS.
**A/B result (equal wall-clock 1800s x2, reproduced, `concurrent_levels=4` vs baseline's
`concurrent_levels=1`, both workers=6/probe-workers=2, comb family):** identical
`best_achieved=102` both arms (confirms the determinism invariant held in practice, not just in
unit tests) but `concurrent_levels=4` reproducibly reached **one level further** in the walk --
resolved `k=107: INFEASIBLE` (narrowing the bisection bracket to [107,111]), which sequential
baseline's 1800s budget never got to test (`output/kwalk/concurrent4.log` + `-2.log`, byte-identical
both runs, vs `baseline.log`). A real, reproducible, if modest, speed win with no downside
observed -- exactly the "same result, faster" shape idea #7 was scoped for, unlike every lever in
#1-6 which traded search-quality for search-quality.
**Verdict:** Phase 0 alone would have been actively harmful if shipped as "the fix" (a naive
`--workers` bump). Phase 1's actual mechanism (barrier removal, not core-count increase) is the
real lever, and it works, cheaply, without the contention risk Phase 0 exposed. Kept as an opt-in
`concurrent_levels` parameter (default 1, zero risk to any existing call site) rather than changing
the default -- consistent with every other lever this session (`pattern_family`, `stub_priority`,
`lane_cap`) being explicit opt-in.

## next-things-to-try #8: CP-SAT parameter portfolio for the hard frontier -- clean null across every candidate, closed (2026-07-20/21)
**Setup:** the last untested item. Backlog: "the autopsy's 4/8 UNKNOWNs stayed undecided at 15
min... try alternate CP-SAT strategies... small tuning study." Reframed the question precisely
before building anything: the Stage 1.5 autopsy (2026-07-15) already showed more *time* (900s vs
30s) and more *workers* (12 vs 2) only decides half of a hard sample -- idea #8 asks whether
switching *search strategy* decides more of them within the walk's own real 30s/probe_workers=2
budget, which the autopsy never varied. Reused `output/corpus/darkzig/instances.jsonl` (663
UNKNOWN records, k=107-127, confirmed recorded at ~30s each) rather than generating new data --
exactly the frontier population idea #8 needs, spanning the walk's real operating range.
**Built:** `probe()` (`foeopt/roads_first.py`) gained an opt-in `solver_overrides: dict | None =
None` hook, applied via `setattr(solver.parameters, k, v)` right before `solver.Solve()` -- a
generic pass-through (not named presets), since the candidates span unrelated CP-SAT parameters.
Threaded through `_run_probe`/`_run_probe_seq`/`_worker_init`/`_WORKER_*` globals exactly like
every prior opt-in lever (`symmetry_breaking`, `hints`, `stub_priority`). Default `None` is a true
no-op -- full existing suite (338 tests after adding this session's own new coverage) passes
unmodified. New tests prove the hook actually reaches the real solver (an invalid parameter name
raises `AttributeError`, since a stub could never do that; a valid override --
`max_time_in_seconds` set near zero -- observably starves a normally-decidable pattern into
`UNKNOWN`) plus worker-global plumbing tests mirroring the existing `symmetry_breaking`/
`stub_priority` coverage.
**API surprise:** `search_branching` is a pybind-native enum on this ortools version
(9.15.6755), not a plain int-settable protobuf field -- `setattr(params, "search_branching", 2)`
raises `TypeError` (wrong argument type), even though the same int is what
`sat_parameters_pb2.SatParameters.PORTFOLIO_SEARCH` returns. The working value has to come from
the parameter object's own class (`cp_model_helper.SatParameters.PORTFOLIO_SEARCH`, a typed enum
instance), discovered empirically since neither ortools' own enum module nor `dir()` on a fresh
`CpSolver().parameters` made this obvious ahead of time -- worth remembering if this hook is ever
reused for another enum-typed parameter.
**Diagnostic (`scripts/exp_frontier_portfolio.py`, smoke-tested N=4 first, then real N=20):**
5 candidates (`portfolio_search`, `lp_search`, `linearization_max`, `more_probe_workers_4` --
the literal "longer-but-fewer" lever, giving each probe 4 internal threads instead of 2 at the
same 30s wall-clock -- and `use_lns_only`) plus a `default_reconfirm` control (the same config as
recording time, re-solved fresh), each re-solving the same 20 sampled frontier patterns
sequentially (no outer parallelism, per idea #7 Phase 0's contention lesson).
**Result -- and an important calibration finding from the control arm itself:**
| config | decided / 20 |
|---|---|
| default_reconfirm (control) | 1 (5%) |
| portfolio_search | 0 (0%) |
| lp_search | 0 (0%) |
| linearization_max | 1 (5%) |
| more_probe_workers_4 | 0 (0%) |
| lns_only | 0 (0%) |
The `default_reconfirm` control -- re-solving with *no* override at all, the exact same config
these patterns were originally recorded UNKNOWN under -- itself flipped 1/20 to a decided status.
CP-SAT's parallel portfolio is **not perfectly reproducible run-to-run even with a fixed
`random_seed`**, because real-time thread-scheduling races between workers aren't controlled by
the logical seed. This sets a ~5% noise floor that any real candidate needs to clear to claim
signal -- `linearization_max` merely matched it (not evidence of a real effect), and every other
candidate landed at or below it. **No candidate showed real signal.** `use_lns_only=True` ran
without error on this no-objective feasibility model (worth noting since LNS is documented as an
incumbent-improvement strategy needing an objective) but produced no observable difference either.
**Verdict: clean, decisive null across the whole small candidate set -- closed, no real k-walk A/B
warranted** (per the plan's own gate: nothing cleared the noise floor). Consistent with, and
reinforcing, the Stage 1.5 autopsy's reading: this frontier is genuinely hard for CP-SAT at this
problem size, not an artifact of the *particular* search strategy in use -- neither more time,
more workers, nor a different strategy shakes it loose. `solver_overrides` is kept as a tested,
harmless, opt-in-only primitive (zero risk, zero behavior change by default) in case a future,
more targeted parameter is worth trying, but this closes next-things-to-try.md item #8 and,
with it, every item in the document except #9 (assumption-based incremental solving, the one
remaining unexplored Speed-tier idea).

## next-things-to-try #9: assumption-based incremental solving -- CP-SAT doesn't support it, confirmed by the maintainer, closed with zero code (2026-07-21)
**Setup:** the last item in the document. Backlog: "Patterns at one k share region + building set;
only the road skeleton differs. Explore CP-SAT assumptions / clause reuse to amortize solving
across a level's patterns." Unlike every other idea this session, checked the *premise* against
the real solver capability before writing any code or entering plan mode -- if the underlying
mechanism doesn't exist, no model redesign or toy-scale gate can rescue it.
**What exists in the API:** `CpModel.add_assumption(s)` and `CpSolver.sufficient_assumptions_for_infeasibility()`
are real, present methods (confirmed by inspecting the installed ortools 9.15.6755 package
directly). But their purpose is **minimal-unsatisfiable-subset (MUS) extraction within a single
`Solve()` call** -- "which of these assumed-true literals, if I could drop some, would let the
rest be jointly feasible" -- not carrying learned clauses or search-tree state *across* separate
`Solve()` calls the way incremental SAT solvers with assumption interfaces classically do.
**Confirmed authoritatively, not guessed:** GitHub issue google/or-tools#2014 ("Incremental
solving using CP-SAT solver," filed 2020, closed 2021-12-07) is exactly this feature request.
Laurent Perron (CP-SAT's lead maintainer) closed it with **"no plan for more than `AddHint()`"**
-- i.e. the solution-hint mechanism (already used in this codebase for `hints=`/`stub_priority=`)
is, and is intended to remain, the *only* supported way to carry information from one solve to
another; there is no clause-database or search-tree reuse across calls. A separate
`or-tools-discuss` thread specifically asking about assumptions for this purpose got the same
answer from Perron directly: real assumption-based incremental solving "will not happen soon" and
early attempts to force it (`ResetAndSolveWithGivenAssumptions()`) crashed the SAT propagation
layer, "not designed for this use case." Searched for anything more recent superseding this --
found nothing (no evidence this changed by the 9.15.x version installed here or any 2025 release
note).
**Why this matters for this specific idea, not just as a general limitation:** even if CP-SAT DID
support cross-call reuse, achieving it here would require restructuring `probe()`'s model so road
cells are themselves boolean *variables* that differ only in their *assumed* values between
patterns (today they're baked directly into each building's `AddAllowedAssignments` candidate
list, which differs in *structure*, not just assumed truth values, between patterns) -- i.e. the
same one-hot road-selection encoding idea #6 (`foeopt/minroads.py`) already found
memory-catastrophic at real-city scale. So this idea would have inherited idea #6's fatal flaw on
top of not being supported by the solver at all -- a second, independent reason not to pursue it.
**The one actually-supported adjacent mechanism (`AddHint()`, transferring a sibling pattern's
solved positions as a hint for the next pattern at the same k) was not built or tested** --
idea #2 already found hints (from an external classical-packer solution, a different source but
the same mechanism) reproducibly make the walk *worse* (`tasks/lessons.md` 2026-07-16), which is
a strong, directly relevant prior against a same-mechanism variant helping here. Building and
testing it anyway, purely to re-confirm a strong existing prior with a different hint *source*,
would not be measure-first discipline -- reported as a considered-but-not-pursued follow-up
rather than built.
**Verdict: closed as infeasible by design, not by experiment.** No code, no toy gate, no A/B --
the premise doesn't hold, confirmed from the tool's own lead maintainer across two independent,
directly-on-point sources. This is the cheapest possible closure this session produced: a null
result reached entirely through research, at zero compute cost, rather than through a diagnostic
run.
**This closes `next-things-to-try.md` in its entirety.** Every item (#1-9) has now been tried,
tested, or (for #9 alone) researched to a decisive close. Final scoreboard: one clear win (#5's
cap=24 hybrid follow-up, 106 roads), one mixed result (#10 stub priority), one small reproducible
speed win (#7 concurrent k-levels), one permanent zero-risk tightening kept unconditionally (#4's
prefilter bound), and the rest (#1, #2, #3, #5-as-originally-proposed, #6, #8, #9) negative or
null. The project's best validated result remains **102 roads** (plain comb family, no levers),
achieved early in this line and never beaten by any of the eight subsequent ideas tested against
it.

## Exact fixed-placement router — Stage 0 (2026-07-21)

**Verdict: route() is near-optimal for fixed placement — MEASURED, not assumed. The exact
router does NOT beat 102; a marginal 1-road slack exists on 1/11 layouts. Near-null for the
goal (beat 102); kept as a tested reference + a cheap never-hurts opt-in polish.**

The assumption "route() is already near-optimal for fixed placement" (2026-06-23 attempt #6)
was asserted but never measured. Built an exact router — `foeopt/exact_router.py`, minimum
connected road-cover via CP-SAT + single-commodity flow (the tractable slice of
`foeopt/minroads.py` with placement fixed: no rectangle-placement variables) — and compared
its proven optimum to `route()` on every darkzig best-k layout.
Harness `scripts/exp_exact_router.py`; command
`uv run python scripts/exp_exact_router.py darkzig.json output/roads-first/best-k*.json --time-limit 60`.

**Results (11 darkzig best-k layouts, achieved 102–120):**

| layout | route() | exact (all proven OPTIMAL) | slack | solve |
|---|---|---|---|---|
| best-k110-a102 | 102 | 102 | 0 | 0.03s |
| best-k111-a102 | 102 | 102 | 0 | 0.04s |
| best-k115-a105 | 105 | 105 | 0 | 0.03s |
| best-k115-a107 | 107 | 107 | 0 | 0.03s |
| best-k119-a108 | 108 | 108 | 0 | 0.04s |
| **best-k119-a110** | **110** | **109** | **1** | 0.07s |
| best-k119-a112 | 112 | 112 | 0 | 0.04s |
| best-k123-a109 | 109 | 109 | 0 | 0.03s |
| best-k123-a111 | 111 | 111 | 0 | 0.03s |
| best-k123-a115 | 115 | 115 | 0 | 0.02s |
| best-k127-a120 | 120 | 120 | 0 | 0.07s |

- **10 of 11 layouts: exact == route(), proven optimal.** route()'s greedy SPH +
  articulation-prune hits the global minimum for the fixed placement.
- **1 of 11 (best-k119-a110): 1 road of slack** (110 → 109). route() is not *perfectly*
  optimal, but the gap is a single road on a non-best layout.
- **The 102 layout is already route()-optimal (slack 0)** → the exact router does **not** beat
  the all-time best. The lone win (110 → 109) is still above 102.
- **Trivially tractable: every solve 0.02–0.07s.** Tractability was never the question — the
  fixed-placement model is tiny (~100–270 free cells). An exact router is a viable drop-in.

**Gate.** The pre-committed gate ("OPTIMAL slack ≥ 1 → advance") is met by the *letter* (1
layout, 1 road), but the *substance* is a near-null for the goal: route() is near-optimal, the
exact router doesn't beat 102, and a 1-road-on-9%-of-layouts gain doesn't justify a full
production wiring on its own.

**Strategic conclusion.** route() is **not** where the roads are hiding — the darkzig road
count is limited by placement/skeleton, not by route()'s greediness. This settles a
load-bearing assumption with hard data and redirects future effort toward the
placement/skeleton levers. `foeopt/exact_router.py` is kept as a tested reference and a cheap
never-hurts opt-in polish (`res.roads if res.optimal else route()`), available should a layout
ever carry slack, but it is not a path below 102.

**Excluded:** `best-k93/94/96` (achieved 86–90) are a *different* 89-building city (1/89 entity
overlap with darkzig) — `KeyError` on reconstruct, correctly rejected; their counts are
unrelated to darkzig. Assets: `foeopt/exact_router.py` (5 tests), `scripts/exp_exact_router.py`.
## Roads-first placement objective — Stage 0 correlation study (2026-07-21)

**Verdict: the oracle_gap is REAL, but no proxy captures it → do NOT advance to Stage 1
with P1–P4.** Per the pre-committed Stage-0 gate (spec
`docs/superpowers/specs/2026-07-21-roads-first-placement-objective-design.md` §5),
documented and closed before any CP-SAT objective code. The measure-first gate did its
job: it caught that the four natural placement proxies don't predict route()'s road count —
one (P1) is actively counterproductive — so an objective built on them would have been
built on sand (and P1 would have made results *worse*).

**Question.** The roads-first probe returns the *first* feasible placement; route() then
rebuilds the road network on it. Does a better placement on the same skeleton route lower,
and can a placement-level proxy steer CP-SAT toward it?

**Method (after a methodology fix — see below).** Reuse the 34 known-SAT skeletons in
`output/corpus/darkzig/instances.jsonl`; for each, collect distinct placements by re-running
`probe()` under `random_seed` 0–7 (single-worker, no objective — the real first-feasible
model); score every placement with route() and the four proxies (`foeopt/placement_proxies.py`).
22 of 34 skeletons yielded ≥2 distinct placements. Harness: `scripts/exp_placement_objective.py`;
raw: `output/stage0-placement.json`.

**Results (22 skeletons, k 110–127).**
- **mean_oracle_gap = 4.77 roads (max 19); frontier k≤118: 5.0 (n=3, underpowered).**
  Placement choice genuinely matters — the first-feasible placement leaves ~5 roads on the
  table on average, and the gap persists at the tight frontier. An *oracle* objective would
  help; the headroom is real (far above the 1.0 KILL floor).
- **No proxy predicts the good placement.** Gate needs mean rank-corr ≥ 0.4 AND mean realized
  reduction ≥ 50% of the gap (≥ 2.39):

  | proxy | mean Spearman | mean realized reduction |
  |---|---|---|
  | P1 touched cells | **−0.279** | 0.91 |
  | P2 subtree | −0.05 | 1.09 |
  | P3 double-loaded | 0.15 | 1.68 |
  | P4 same-size | 0.16 | 0.73 |

  Every proxy fails both bars. P3 is closest (captures ~35% of the gap) but its correlation
  (0.15) is far below 0.4. **P1 is negatively correlated**: minimizing the road cells
  consumers touch (more skeleton-sharing) reliably picks *worse* placements.

**Gate arithmetic.** mean_oracle_gap 4.77 ≥ 1.0 → not killed. No proxy clears rank-corr ≥ 0.4
(best 0.16) or realized ≥ 2.39 (best 1.68). → spec's third branch: **large gap, no qualifying
proxy → document, stop before Stage 1.**

**Mechanism (best read).** route() *discards the skeleton* and rebuilds the network from the
consumer placement. So the three skeleton-relative proxies (P1/P2/P3 — sharing / subtree /
double-loading measured against `pattern.roads`) score structure route() then throws away;
the one placement-intrinsic proxy (P4, same-size alignment, no skeleton reference) is the
least-bad (weak +0.16). Read: a useful placement objective must predict route()'s output from
the *placement geometry itself*, not from its relationship to the scaffold skeleton — or it
must optimize route() directly (which reintroduces the routing cost the two-stage split exists
to avoid). This is the same proxy-divergence that sank four prior packer heuristics
(2026-06-22), caught this time *before* the build.

**Not disproven, but not these proxies.** The ~5-road headroom is real; reviving the lever
needs a placement-intrinsic proxy that actually correlates with route() (or a route()-in-the-loop
objective) — a new spec, not this build. Caveat: `first_roads` here is seed-0's placement (an
arbitrary first-feasible); the production multi-worker probe may already start better, so the
gap *vs the real baseline* could be smaller — but the proxy failure is a rank correlation,
independent of the baseline, so "don't advance" is robust.

**Methodology defect found + fixed (reusable lesson).** Stage 0 as originally planned (randomly
generate skeletons + `enumerate_all_solutions` pool) does not work at real scale: feasible
skeletons are ~2% at the frontier (34 SAT / 1459 corpus probes), so random sampling returns 0
usable skeletons, and `enumerate_all_solutions` + single worker is too slow to first-solution on
a 63-rectangle packing. The toy selftest passed anyway (trivial instance), hiding it. Fix: reuse
corpus SATs + multi-seed `probe()`. **Lesson: when a study needs feasible instances of a problem
whose feasibility is rare, reuse the corpus of known-feasible ones — don't sample blind.**

**Assets kept.** `foeopt/placement_proxies.py` (four proxies, unit-tested) and
`scripts/exp_placement_objective.py` (corpus-driven correlation harness) stay as reference
tooling — any future placement-proxy idea A/Bs through the same harness.

## Richer-skeleton feasibility diagnostic — PARTIAL (2026-07-22)

**Verdict: no family is feasible at k ≤ 104, and lane/hybrid are indistinguishable from the comb
control there. But the run did NOT test the decisive band (k ≈ 105–109), so it does NOT settle
whether a richer family can beat 102. Partial result; corrected re-run specified below.**

`scripts/exp_richer_skeleton_probe.py`, 108 probes = 3 families (comb control, lane,
hybrid cap=24) × k ∈ {96, 100, 104} × 12 full-TH patterns, **300 s budget, 12 workers, 3.85 h**:

| family | n | SAT | UNSAT | UNKNOWN | min achieved |
|---|---|---|---|---|---|
| comb (control) | 36 | **0** | 21 | 15 | — |
| lane | 36 | **0** | 21 | 15 | — |
| hybrid (cap 24) | 36 | **0** | 22 | 14 | — |

Every (family, k) cell is 0 SAT (UNSAT 5–9, UNKNOWN 3–7 of 12).

**What this establishes.**
- **Zero SAT anywhere** at k ≤ 104 even at 300 s / 12 workers — nothing breaks 102 in this range.
- **Richer ≡ comb here:** lane/hybrid show the same UNSAT/UNKNOWN mix as the control, i.e. no
  evidence the structurally-better families pack tighter at tight k.
- The control behaves exactly as known results predict, which **validates the harness**.

**What it does NOT establish — the k-range was misaimed (spec error).**
The spec chose k ∈ {96,100,104} reasoning "below the 102 floor," **conflating the achieved count
with k**. Measured on the known-good darkzig layouts, **achieved ≈ k − 9** (range 7–14: k110→102,
k115→105, k119→110, k123→109, k127→120). Therefore:
- comb's *feasibility* floor is **k ≈ 110**, not 102 — and the k-walk already records
  **k=107 INFEASIBLE**. At k ≤ 104 *nothing* fits, for any family. We measured a foregone
  conclusion.
- Beating 102 requires feasibility at **k ≈ 105–109** (where achieved would land ~95–101). This
  run touched only k=104, the top edge, and never probed 105–109.
So "0 SAT at k ≤ 104" cannot distinguish "richer families are no better than comb" from "richer
families are better, but not by 6+ cells of k."

**Also: 40% UNKNOWN is not "decided."** `classify_verdict` returned FEASIBILITY_WALL only because
the richer UNKNOWN fraction (29/72 = 40%) fell under the 0.5 threshold — a mechanical call. 40%
undecided at 300 s is evidence, not proof.

**Corrected follow-up (the actual test).** Re-run the *same harness* at **k ∈ {105, 107, 109}**
for comb vs lane vs hybrid, to locate each family's **feasibility floor**. The real question is
whether a richer family is feasible at a k where comb is not — e.g. a lane SAT at k=106 would
achieve ~97 and beat 102. No new code; corrected k-levels only.

**Lesson (generalizable).** When a search reports two coupled numbers (here the skeleton budget
`k` and the achieved `route()` count), pin the empirical relationship between them *before*
choosing the sweep range. A one-line check against existing artifacts (`achieved ≈ k − 9`) would
have caught this before spending 3.85 h probing a range where the answer was foreordained.

**Assets:** `scripts/exp_richer_skeleton_probe.py` (6 tests, harness validated by the control),
`output/richer-skeleton.json`.

## Corrected richer-skeleton run: lane reaches 103 (1 off comb) — and `hybrid` was never a family (2026-07-22)
**Setup.** The corrected follow-up from the entry above: same harness (`exp_richer_skeleton_probe.py`),
k ∈ {105,107,109}, families lane + hybrid(cap=24), n=12, **300 s × 12 workers**, seed 0.
72 probes, **2.96 h**. (comb had been run separately as the control: 0 SAT at k=105/107, corroborating
the k-walk's existing "k=107 INFEASIBLE".)

**Result: 4 legal SATs; minimum achieved = 103.**
| family | k | achieved | legal | secs |
|---|---|---|---|---|
| lane | 107 | **103** | yes | 272.7 |
| hybrid | 107 | **103** | yes | 59.1 |
| lane | 109 | 105 | yes | 161.0 |
| hybrid | 109 | 108 | yes | 97.9 |

Per family: 36 probes each, 2 SAT / 18 UNSAT / 16 UNKNOWN. Verdict fired **FEASIBILITY_WALL**
("no legal SAT < 102; 32/72 UNKNOWN").

**The real finding is 103, not the verdict.** The prior record for a non-comb family was **106**
(lessons: lane/stub/hybrid "all lost to comb"). Lane now lands at **103 — one road off comb's 102**,
with `rotated_buildings == 0`. Richer families are *not* structurally hopeless here; they are one road
short. That is the result that justifies sampling the family properly rather than closing the track.

**Three caveats, all against over-reading the verdict.**
- **Knife-edge.** 32/72 = 44.4 % UNKNOWN against a pre-committed 50 % threshold: four more UNKNOWNs
  and the same data reads DECIDABILITY_WALL. A verdict that flips on 4 of 72 probes is a mechanical
  call, not a conclusion — the identical criticism the previous entry made of its own 40 %.
- **90 % of the 2.96 h went into UNKNOWN probes** (2.67 h). "Decided" overstates what was bought.
- **The 103 layout is unrecoverable.** `probe_pattern` discards `validate`'s layout and the row schema
  carries no pattern identity, so a legal 103 exists that we cannot reproduce or inspect. **Any run
  that can produce a near-record must persist the artifact**; this one couldn't.

**Bug found: `hybrid` is not a family — it is a strict subset of `lane`.**
`max_lane_len` cannot generate a topology the uncapped generator doesn't already produce. Measured
across every cap and k tried:
| k | \|lane\| | \|hybrid(24)\| | novel (in hybrid, not lane) |
|---|---|---|---|
| 105 | 67,308 | 67,308 | **0** |
| 107 | 67,298 | 67,259 | **0** |
| 109 | 67,285 | 67,225 | **0** |
Also 0 novel at caps 3/4/6/8/12 (k=105) and at k=120/140. **Mechanism:** fronts grow round-robin
(`generate_lane_patterns`, roads_first.py:239-253), so lanes come out balanced; a cap either sits above
the natural lane length (inert) or starves growth so the budget can't be spent and
`if remaining != 0: continue` rejects the pattern. The cap is a **filter, never a shape knob**.
At k≈105 it is doubly inert: the trunk consumes ~46 of 105 cells, leaving ~59 across 10-20 fronts, so
lanes are ~3-6 cells and a cap of 24 is unreachable. (cap=24 came from the earlier k≈115 work and was
carried into a k-range where it cannot bind.) **Cost: half of this 2.96 h run bought correlated
samples**, and `classify_verdict`'s `RICHER = ("lane","hybrid")` counted them as independent.
Locked by `test_max_lane_len_only_filters_never_creates_new_topologies`.

**Lesson (generalizable).** Before spending compute on an "arm B" of an experiment, prove it is
*distinguishable from arm A* — one set-difference over the generated populations (seconds) would have
caught this before 1.5 h went into it. A knob that only ever *removes* candidates is a sampling filter,
not a treatment, and must not be counted as an independent family.

**Assets:** `output/richer-skeleton-lane-hybrid.json`,
`docs/superpowers/specs/2026-07-22-wide-shallow-skeleton-screen-design.md` (the replacement method).

## Process: check `lessons.md` before proposing a lever, not after (2026-07-22)
**What happened.** While diagnosing the UNKNOWN-heavy probes I measured that CP-SAT symmetry breaking
resolved 1 of 4 stuck patterns and cut branches 21-34 %, and recommended enabling it — as if it were an
untried idea sitting unused in the codebase. The user asked *"So symmetry-breaking existed but was never
actually used?"* It had been implemented, wired to CLI flags on two scripts, A/B'd twice, and **closed
as a reproducible negative** eight days earlier (lessons.md:1039). A single `grep -rn symmetry` would
have surfaced that before I proposed re-running a closed experiment.
**Why it matters.** The measurement was still worth having — it refuted the recorded *mechanism* (see
the 2026-07-22 amendment on that entry). But framing it as "this exists and was never used" inverted
the burden of proof: the honest framing was "this was closed for the k-walk; here is why that verdict
may not transfer to a different regime," which is a much narrower and more defensible claim.
**Rule.** Before recommending any lever, `grep` `tasks/lessons.md` + `tasks/next-things-to-try.md` for
it. If it was tried: state the prior result first, then argue specifically what is different now.
Never present a previously-closed lever as new.

## Measured `d`: the wide screen's 30s budget would have found NOTHING — and a lane skeleton TIES 102 (2026-07-22)
**Why measured.** The wide-shallow screen spec justified a 30 s probe budget with "all 34 corpus SATs
finished within 29.2 s". A whole-branch review challenged that. Checking where those SATs live:
`corpus SAT k-values = {123:20, 119:6, 127:3, 115:3, 111:1, 110:1}` -- **zero in the 105-107 band the
screen targets.** The statistic came entirely from the loose-k regime.

**Direct measurement of `d`** (detection probability on patterns KNOWN to be feasible). The 4 legal SATs
from the completed deep run are regenerable (seed 0, one shared rng across the family/k loop); the
replay was verified by reproducing the recorded per-index status vector.

| arm | setting | found |
|---|---|---|
| the screen | 30 s x 1 worker | **0 / 4** |
| the screen, more threads | 30 s x 12 workers | **0 / 4** |
| the recheck arm | 300 s x 1 worker | **4 / 4** (102-170 s) |

**Budget is the binding axis, not parallelism.** 30 s misses every known-feasible pattern even at 12
threads; 300 s on one worker finds all four. Had the 8.3 h screen run, it would have reported
"0 SATs in 15,000 patterns, feasibility < 0.06%" while structurally unable to detect four patterns we
already knew were feasible. **`rule_of_three` bounds `p*d`, not `p` -- with `d = 0` the bound is
vacuous, and the spec's gloss ("feasibility below 0.06%") would have been simply false.**

**Refined `d` at the usable budget: 0.77**, not 1.0 -- across 96 re-solves of known-feasible patterns at
300 s x 1, only 74 resolved SAT. A feasible pattern is still missed ~23% of the time per attempt.

**Second finding: `achieved` is luck-of-the-solution, worth up to 10 roads.** `probe()` is pure
feasibility with no objective, so it returns an arbitrary satisfying placement and the `route()` count
depends on which one CP-SAT lands on. Re-solving each known-feasible pattern across 24 CP-SAT seeds
(`solver_overrides={"random_seed": s}`), 300 s x 1, 26 min total:

| pattern | SAT/24 | achieved min / median / max |
|---|---|---|
| lane k=107 i5 | 21 | **102** / 103 / 106 |
| lane k=109 i10 | 17 | 105 / 105 / 108 |
| hybrid k=107 i11 | 15 | 103 / 104 / **112** |
| hybrid k=109 i4 | 21 | 103 / 105 / 107 |

**A lane skeleton reached 102 -- TYING the all-time best**, which until now only the comb family had
produced. Verified end-to-end: reproduced deterministically (gen seed 0, pattern index 5, CP-SAT seed
15), `validate -> OK`, and independently re-routed from the persisted artifact via
`exp_exact_router.reconstruct_fixed` -> `route() == 102`, `is_valid True`, `rotated_buildings 0`.
Artifact: `output/spread/TIE-lane-k107-i5-s15-a102.json`.

**But the seed lever's tail is thin.** 74 achieved samples, minimum 102, hit **once**. The same skeleton
that yields 102 yields 103 eleven times. Re-solving buys ~1 road over the median and then plateaus;
it is not a route to 101 on its own.

**Lessons.**
1. **A budget justified by a censored distribution is not justified.** The 30 s figure was the cap of
   the corpus that produced it -- and worse, that corpus had no observations at all in the target band.
   Before trusting a "resolves fast" statistic, check *where the observations live*, not just their max.
2. **When a null result's bound is on a product (`p*d`), measure the other factor before spending the
   compute.** One 26-minute measurement invalidated an 8.3-hour run.
3. This is the **same failure mode** as the k-range error two entries above -- committing hours to a
   configuration where the answer was foreordained -- caught this time by the branch's own artifacts.
   The pattern to internalize: *the recorded results of the previous experiment are the cheapest
   available critique of the next one.*
4. **Persist the notable artifact, not just the record-breaking one.** The 102 tie was nearly lost
   because the script only persisted `achieved < 102`; it was recoverable only because the seed was
   logged. Persist anything at or near the frontier.

## NEW RECORD: 98 roads on darkzig (was 102) — the wide screen at the corrected budget (2026-07-23)
**The result.** The wide-shallow lane screen at the *measured* settings (300 s budget, 12x1-worker,
k=105/106, 700 patterns/level, 1400 probes, ~7.7 h) found a legal layout at **98 roads** — four under
the standing record of 102, which until now only the comb family had reached (and lane had only tied,
at 102, earlier the same day). Verdict fired **BREAK_FLOOR**.

**Independently verified** (the standing rule after the retracted-127 incident): reconstructed the
persisted artifact via `exp_exact_router.reconstruct_fixed`, then
- `route()` from the placement = **98**,
- `exact_route()` = **OPTIMAL 98** (greedy and exact agree — no undercounting),
- `is_valid` True, `rotated_buildings` **0**, all **224** buildings placed.
Record layout preserved (with provenance) at `docs/records/darkzig-98-roads-lane-k105.json`
(the `output/` artifacts are gitignored). Provenance: family lane, skeleton k=105, gen seed 0,
pattern index 542, CP-SAT seed 0.

**Full frontier (all legal, all independently re-verified):**
| roads | k | idx | source |
|---|---|---|---|
| **98** | 105 | 542 | base screen |
| 99 | 105 | 368 | polish (102 -> 99, seed 9) |
| 99 | 106 | 660 | polish (102 -> 99, seed 6) |
| 101 | 105 | 432 | base screen |
| 101 | 105 | 633 | base screen |
| 101 | 106 | 167 | base screen |

**What actually broke the floor: statistical power, not a new idea.** Feasibility at these k is
~1.1 % (k=105: 8 SAT/700) to ~1.7 % (k=106: 12 SAT/700), and detection is capped at d~0.77 with an
UNKNOWN majority. The 98 is the extreme left tail of the k=105 achieved distribution
`[98,101,101,102,105,106,106,108]`. n=12 (the old deep run) had ~zero chance of sampling it; n=700 did.
The lever that worked was **screening ~120x more patterns at the budget where feasible patterns are
actually detectable** — the whole point of measuring d first.

**Stage-2 seed-polish: real but secondary.** Re-solving the 11 SATs achieving <=104 across 12 CP-SAT
seeds improved 4 of them (two 102->99, two 103->102), confirming `achieved` is luck-of-the-solution —
but it did **not** beat the base screen's 98. Polish tightens the frontier; the screen finds it. Both
matter, in that order.

**The decisive lesson, restated.** This record exists because the 8.3 h run was *halted* before
launch, `d` was measured directly (0/4 known-feasible patterns found at the spec'd 30 s, 4/4 at 300 s),
and the experiment was retargeted onto the winnable band. Had the original spec run as written, it
would have burned 8 h and reported "feasibility < 0.06 %" — while a 98-road layout sat undiscovered in
the exact population it was sampling. *Measure the thing the conclusion depends on before spending the
compute.* The whole-branch review that forced the d-measurement paid for itself many times over.

## NEW RECORD: 95 roads on darkzig (was 98) — a truncated parameter range plus two free filters (2026-07-30)

**The result: 98 -> 97 -> 95 in one session.** Three legal layouts under the standing record,
from two independently-configured screens plus a seed-polish pass. **95 roads is the all-time
best — 120% road efficiency vs the Sigma/2 = 114 estimate.** Preserved with provenance at
`docs/records/darkzig-95-roads-lane-k105.json` (plus the two 97s: `…-97-…-k106.json` and
`…-97-…-k105-alt.json`, distinct skeletons AND placements).

The 95 was found by the screen at **99** and improved to **95 by seed-polish** — a 4-road jump
on a fixed skeleton from CP-SAT seed variation alone. Polish improved **6 of 12** targets
(99->95, 100->97, 100->98, 99->98, 100->99, 98->97), against 4-of-11 historically: the quality
filter hands it a far better target set than it has ever had.

**Independently verified** (the standing rule after the retracted-127 incident), for the 95 and
both 97s: reconstructed via `exp_exact_router.reconstruct_fixed`, then for the 95 — `route()`
from the placement = **95** (matches the artifact's 95-entry roads array and the claimed
`achieved`), **`exact_route()` = 95 OPTIMAL** (greedy and exact agree, no undercounting),
`is_valid` True, **`rotated_buildings` = 0**, 0 overlapping cells, 0 out-of-region, **0
unsatisfied consumers**, **224/224** buildings placed.
Provenance of the 95: family lane, **k=105, pitch 14**, stubs=True, trunk_len 29, TH (21,28),
gen seed 1, pattern index 25, `--prefilter-top 0.10 --quality-top 0.40`,
`mean_free_adjacency` 1.9698.

**What broke the floor: pitch 17 — six steps outside the generator's hardcoded ceiling of 11.**
`generate_lane_patterns` enumerated `for pitch in (5,…,11)`. Measured SAT rate on darkzig rises
monotonically across that whole range (0/0/0/0/1.0/3.2/**6.2**%), i.e. **the range was truncated
at exactly its best value and the entire default family sat on the rising flank.** FR16's comb
analogue (`spacing`, capped at 7) shows the same shape. Widening to 12–24 exposes **93,284
patterns per k** on darkzig — more than the entire previously-enumerated population (67,308) —
none of which had ever been probed. `pitches=` is opt-in and byte-identical when unset.

**Two free filters, both computable before probing, both from data the code already had.**
1. **`opts_total` (feasibility).** `probe()` enumerates each consumer's road-adjacent anchor
   options *before building the CP-SAT model*, records the total into `diag`, and discards it.
   That number separates SAT from non-SAT at **ROC-AUC 0.990** (0.993 within the strongest
   parameter bucket). `foeopt/skeleton_score.py` recomputes it with per-row integer bitmasks —
   **507x faster** (0.71 ms vs 359 ms), so scoring a 160k population costs 1.9 min instead of
   16 core-hours. Oracle-equivalence tested against `_anchor_candidates` (the `reach.py` rule).
2. **`mean_free_adjacency` (quality).** Average free cells orthogonally adjacent to each road
   cell. **The project's first measured quality predictor**: Spearman **+0.76** vs `achieved` on
   the 20 SATs of the 98-road baseline run and **+0.64** on held-out SATs of the widened-pitch
   screen — two independent datasets, different pitch ranges, different sampling. Lower is
   better; mechanism is double-loading (a road cell in open ground makes `route()` rebuild a
   bigger network). Deciles are monotone: lowest → median 102 / 85% at ≤102; highest → median
   106 / 0%.

**Measured arms (equal-wall-clock design; arm A is the recorded 98-road run, not re-run):**

| arm | config | probes | SAT | SAT% | core-h | SAT/core-h | best |
|---|---|---|---|---|---|---|---|
| A baseline | default pitch, no filter | 1400 | 20 | 1.4% | 72.8 | 0.27 | 98 |
| B1 | + `opts_total` top 10% | 300 | 51 | 17.0% | 22.5 | 2.26 (8.4x) | 98 |
| B2 | + pitch 12-18 | 300 | **242** | **80.7%** | 8.6 | **28.2 (104x)** | 97 |
| C | + `mean_free_adjacency` lowest 40% | 300 | 224 | 74.7% | 10.9 | **20.6 (76x)** | **97 -> 95 after polish** |

B2 and C returned **zero UNSAT** in 300 probes each — every probe was SAT or UNKNOWN. Gate
(>=3x SAT/core-h AND min achieved <= 98): **PASS on all three arms.**
**C is the configuration to keep:** the quality filter costs ~27% of the SAT rate and buys 3
roads of median (102 vs 105) — **129 layouts at <=102, against 7 in the entire 1400-probe
baseline** — and its frontier is what let seed-polish reach 95.

**The trade-off that matters for tuning: feasibility and quality pull apart, and both proxies
have interior optima.** `opts_total` is an excellent *feasibility* ranker but among SATs it
correlates with `achieved` at **+0.50 — the wrong sign**; a top-5% rank-and-take would have
missed the 98 (rank 26/320). And the *tightest* skeletons are genuinely harder to pack:
by `mean_free_adjacency` quintile, SAT rate is 36% / 93% / 98% / 84% / 100% while median
`achieved` is 102 / 102 / 104 / 106 / 106 — **quintile 2 is the sweet spot** (near-full SAT rate
*and* the best road counts; the 97 came from it). Both filters must therefore keep a *loose*
cut and sample **uniformly inside** the survivors, never rank-and-take.
Widening pitch is a **feasibility** lever only — `achieved` is flat across pitch 12–18
(median 102–105), so there is no sharper sub-range to find.

**Lessons.**
1. **When every measured knob's optimum sits at the boundary of its hardcoded range, the range
   is the bug.** Three cities and two families all said "more pitch/spacing is better" right up
   to the cap. One `for pitch in (...)` tuple was costing more than every search-strategy idea
   in `next-things-to-try.md` combined (nine ideas, one small win).
2. **Check what the hot path already computes and throws away before building a model.** The
   feasibility signal was inside `probe()` all along; C-bis trained a CNN (AUC 0.999) to
   predict the same thing and delivered zero end-to-end benefit.
3. **A ranker only helps where it selects the sample, not where it reorders one that will be
   consumed in full.** C-bis Stage 1 and next-things #1 both ranked inside an already-sampled
   200 that `_probe_levels_batch` then probed entirely — a no-op by construction. Same models,
   applied to the 160k population instead, are the difference between 0.27 and 19 SAT/core-h.
4. **Existing artifacts answered the "does it generalise" question for free.** The planned 2 h
   FR16 screen was unnecessary: `output/roads-first/FR{16,17,24}/probes.jsonl` already held
   2,444 labelled probes with full params. Stratifying within k-level (so "SAT lives at loose k"
   can't fake a signal) confirmed the structure on two other cities in minutes.
5. **`mode` is a third free bit, never recorded:** pooled FR16+FR17, `mode=alternate` holds
   **9 of 9 SATs**, `mode=both` is **0 SAT / 528**. Consistent with the same mechanism — fewer,
   longer branches. Untested on darkzig/lane (lane has no `mode`); a comb-family lever.
