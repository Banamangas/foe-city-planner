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
**Verdict: closed, stays opt-in/off.** `symmetry_breaking=` kept in `foeopt/roads_first.py` as tested,
correct, zero-cost-when-off infrastructure (same policy as `reach.py`/`--lns`/`--safe-placements`), but
the reproducible measurement rules it out as a win. **Lesson for the backlog:** "manually add textbook
symmetry breaking" is not free against a solver (CP-SAT) that already does this automatically in
presolve -- measure before assuming a classic OR technique transfers, same standing pattern as
"expert heuristics bolted onto the greedy constructor lose an equal-wall-clock A/B" (2026-07-06 entry),
now with a CP-SAT-specific instance: don't fight the presolve. Idea #2 (warm-start hints from the
classical packer) is now the top remaining cheap-tier candidate; unlike this idea it doesn't add
constraints, it seeds the search, so it isn't subject to the same presolve-interference risk.
Artifacts: `output/kwalk/symbreak.log`, `output/kwalk/symbreak-2.log`.

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

## Hybrid comb/lane (bounded lane length): hypothesis falsified, monotonically worse (2026-07-17)
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
**A/B result: the hypothesis is falsified, and the trend is the *opposite* of predicted --
capping makes the lane family monotonically WORSE, not better, as the cap shortens.**
| arm | k reached | best_achieved |
|---|---|---|
| comb baseline | 111 | 102 |
| lane, uncapped (idea #5 baseline) | 115 | 109, 112 |
| lane, cap=16 (user follow-up) | 115 | **111, 111** (reproduced exactly) |
| lane, cap=8 | 123 | **119, 119** (reproduced exactly) |
| lane, cap=4 | -- | **FAMILY_TOO_WEAK** (climbed to k=283, `walk_complete=true`, never found a single SAT) |
Cap=8 is worse than uncapped lane on *both* metrics (2 k-levels higher, 7-10 roads worse) despite
having plausible-looking pattern diversity in the sanity pass; cap=4 is a total, decisive failure
-- not a near-miss, not a timeout, the upward-fallback walk exhausted the entire feasible k range
without ever finding one SAT pattern.
**User follow-up (same day): cap=16.** Sanity pass showed healthy pattern counts (150-152,
matching uncapped's 152) -- unsurprising in hindsight, since darkzig's trunk is only ~52 cells and
pitch>=5, so most individual lane fronts rarely need to grow past 16 cells to hit a typical budget
before running into the trunk/region boundary anyway; a cap this large barely restricts anything.
A/B'd 30min x2 (reproduced exactly): **k=115/roads=111 both runs** -- matches uncapped's k-level
exactly, and 111 falls *inside* uncapped's own run-to-run range (109-112), i.e. statistically
indistinguishable from not capping at all. This is the missing large-cap anchor point that
completes the monotonic picture: as the cap shrinks from "effectively unbounded" (16, ≈ uncapped)
through 8 (worse) to 4 (totally infeasible), results get strictly worse -- there is no sweet spot
in between where a moderate cap *beats* uncapped. The best a length cap can do is converge back to
doing nothing; every point where it actually bites, it hurts.
**Why the hypothesis was wrong:** capping a lane's reach doesn't just shrink each individual
`NoOverlap2D` subproblem -- it also means each lane contributes fewer cells to the k budget, so
*more* lanes (more seeds) are needed to hit the same k. But the number of viable seed positions is
bounded by two things this generator doesn't loosen when capping: the trunk's fixed length (set by
the region/TH geometry, not by the cap) and the minimum seed pitch (5, unchanged). Shortening the
cap trades "few long, individually-hard lanes" for "many short lanes that collectively can't reach
the budget without more seeds than the trunk can provide" -- exactly what the sanity pass's shrinking
pattern counts (152 uncapped -> 96-150 at cap=8 -> 18-48 at cap=4 -> near-zero at cap=3) already
hinted at, and what the full A/B confirms decisively. The lane family's structural efficiency and
its solver-decidability aren't a dial you can turn independently with this parametrization --
they're coupled through the same fixed trunk/pitch geometry.
**Verdict: closed, no gain, falsifies the specific hybrid mechanism tried.** `max_lane_len=`/
`--lane-cap` kept as tested, correct, zero-cost-when-unset infrastructure (default None is
byte-identical to today's lane family). This doesn't rule out the *literal* spatially-mixed
hybrid (short teeth vs full lanes chosen by a genuine slack/frontier classification, not a single
global length cap) -- but it does rule out the cheap length-cap proxy for it, and it raises the bar
for any future hybrid: a real spatial-mixing generator would need its own seed/trunk budget that
isn't shared with a global pitch/length constraint, which is a materially bigger build than this
test, not a small follow-up. **Session-wide standing conclusion, now five solver/generator-side
levers deep (pruning, warm-start, symmetry breaking, lane topology, lane-length hybrid):** every
attempt to out-think the comb family's plateau by changing what CP-SAT sees -- reordering,
constraining, hinting, or re-generating the skeleton -- has either regressed or, in the one mixed
case (stub priority), helped only a family that was already worse than comb outright. The comb
family's 102-road result remains the best in this project by a clear margin. Artifacts:
`output/kwalk/lanecap4.log`, `output/kwalk/lanecap8.log`, `output/kwalk/lanecap8-2.log`.
