# Track B — Corridor-Granularity LNS Design

**Date:** 2026-07-06
**Status:** Approved (brainstorm 2026-07-06; user decisions §1)
**Prior art:** `tasks/todo.md` Track B sketch; Track A kill verdict (`tasks/lessons.md` 2026-07-05);
safe-placements + TH-stub A/B verdicts (both: priors inside the constructor lose to trial volume at
equal wall-clock — improvement must come as coarse moves *on top of* the multi-start's best result).

## 1. Goal and locked decisions

Beat the 158-road darkzig plateau with coarse destroy-repair moves the single-building anneal cannot
express. User-locked decisions:

1. **Gate — equal-budget win:** at identical total wall-clock vs plain `polish` (≥8 seeds, darkzig),
   LNS must improve the mean 0-unplaced road count by **≥2** and its worst seed must not be worse than
   the baseline's worst seed. Fail → record verdict, keep flag opt-in, **Track B closes** (no tuning
   marathon; a revisit needs new evidence).
2. **Integration — alternating phases:** new `foeopt/lns.py`; `anneal.py`/`polish.py` untouched.
3. **Move set v1 — corridor rebuild only.** Row-shift and stub-promotion only if the gate passes.
4. **Repair — exact template:** stdlib two-side partition (≤12 buildings → subset enumeration),
   never OR-Tools.
5. **Per-run before/after HTML** (user request): every LNS run can be inspected visually;
   files under `output/lns/` (own folder — many files per A/B run; `output/` is gitignored).

## 2. Core mechanism

Roads are never placed directly: `route()` recomputes the network from building positions (same
contract as every anneal move). A corridor-rebuild move therefore re-places the buildings flanking an
under-used corridor into a double-row formation around a 1-cell-wide gap; routing then has no choice
but to lay one lane through the gap, converting single-loaded corridor cells into double-loaded lane
cells.

## 3. Module: `foeopt/lns.py` (pure stdlib)

```python
@dataclass
class LNSResult:
    final: PackResult        # never-worse vs base; same unplaced set
    base_layout: Layout      # post-polish, pre-LNS ("before" for viz)
    rounds: int              # corridor attempts made
    accepted: int            # improvements accepted

def lns_polish(layout: Layout, *, repack_budget: float, anneal_budget: float,
               lns_budget: float, seed: int = 0) -> LNSResult
```

Flow: `base = polish(layout, repack_budget=..., anneal_budget=..., seed=seed)`, then until
`lns_budget` is exhausted: pick a corridor (§4), run repair attempts (§5), accept only strict
improvements (§6), and after each accepted improvement run a short re-anneal slice — fixed at
**2 seconds, drawn from the same `lns_budget`** — to let single-building moves clean up around the
rewrite. All randomness flows through
one `random.Random(seed)`; the result is deterministic for a fixed seed. The library writes no files.

## 4. Destroy: corridor selection

- Compute `road_cell_load` on the current routed layout. Under-used = load ≤ 1, excluding cells that
  qualify as junctions under the existing rule-2 logic (`quality.underused_roads` semantics).
- Corridor = maximal orthogonally-connected run of under-used road cells, flooded from an rng-chosen
  under-used seed cell. No under-used cells → LNS has nothing to do; stop early (report `rounds`).
- Destroy set = the run's road cells (implicitly freed — they are simply free space at the next
  `route()`) plus **all buildings orthogonally adjacent to the run** — consumers and fillers alike
  (fillers are movable putty; evicting them is required to defragment the rebuild area and pushing
  them off-road is itself rule-1-positive).
- **Cap: ≤ 12 destroyed buildings.** Larger runs are truncated: drop run cells from the end farthest
  (by along-run distance) from the rng-chosen seed cell until the adjacent-building count fits. The
  cap bounds the exact partition (§5) at 2^12 subsets.

## 5. Repair: exact double-row template

Freed area = destroyed buildings' footprints ∪ the corridor's road cells ∪ orthogonally adjacent
already-free cells.

1. Enumerate candidate lane placements inside the freed area: both axes; a small set of offsets. The
   candidate SET is a deterministic function of the freed area; the ORDER they are tried in is
   rng-shuffled. A lane candidate is a maximal straight 1-cell-wide segment within the freed area.
2. For each lane candidate, partition the freed **consumers** into two sides exactly (enumerate
   subsets; ≤12 buildings): minimize the longer side's total frontage. Per building, orientation is
   chosen to front the shorter side; the longer side is allowed as a fallback if the short-side
   placement does not fit.
3. Geometric placement: rows flank the lane; ragged backs allowed; every footprint must fit the free
   set; every consumer's footprint must include ≥1 cell orthogonally adjacent to the lane.
4. **Fillers are not templated:** they return last, anywhere free, via the existing gap-fill logic.
5. First fully-placed candidate per lane position is scored with `route()`; the best-scoring
   accepted candidate of the round wins.

The exact partition is the Track-A balancer salvaged where it is actually valid: locally, on ≤12
buildings, with real geometry checked by `grid`-style fit tests — not as a global abstract model.

## 6. Acceptance and invariants

A repair is accepted iff ALL of:
- every destroyed building is re-placed (consumers per template, fillers via gap-fill),
- `route()` succeeds and `is_valid` passes,
- total routed roads **strictly decrease** vs the current best.

Otherwise the move is discarded wholesale; the pre-move layout is never mutated. Invariants:
- `final.unplaced == base.unplaced` (LNS can never lose a building),
- `len(final.layout.roads) ≤ len(base_layout.roads)` (never-worse anchoring, as in anneal),
- determinism for fixed seed.

## 7. CLI

`foeopt layout ... --lns SECONDS` (implies `--polish`; default off). The CLI writes the before/after
HTML via the existing `foeopt.viz.render_comparison(base_layout, final.layout)` to
`output/lns/<city-stem>-<timestamp>.html` and prints the path.

## 8. Measurement: A/B harness and gate

- **First extract `scripts/_ab_common.py`** (run_arm/summary shared by the three existing harnesses —
  the whole-branch review's dedup recommendation lands here, before the fourth copy).
- `scripts/exp_lns_ab.py`: arm A = `polish(repack=R, anneal=N+L)`; arm B =
  `lns_polish(repack=R, anneal=N, lns=L)`. **Identical total wall-clock per seed.** Defaults:
  R=60, N=30, L=30 seconds; ≥8 seeds; darkzig primary; real-like fills 0.7/0.9 secondary.
- Arm B writes `render_comparison(base_layout, final.layout)` per run to
  `output/lns/<run-timestamp>/<city>-seed<N>.html` — one timestamped folder per harness invocation.
- **Gate (pre-committed, §1.1):** darkzig mean 0-unplaced roads ≥2 better in arm B AND
  `max(arm B roads) ≤ max(arm A roads)`; compare only 0-unplaced runs. If any darkzig seed in either
  arm fails to reach 0 unplaced at these budgets (prior data: 8/8 seeds reach 0 at 120 s), that is
  itself a red flag — report it and treat the gate as failed for arm B if the unplaced seed is arm B's.
  Secondary no-regression:
  real-like unplaced distributions must not get worse. Verdict recorded in `tasks/lessons.md` +
  `tasks/todo.md` whatever the outcome.

## 9. Testing

1. Corridor finder: hand layout with a known under-used run → exact run found; junction exclusion.
2. Partition optimality: known instance where greedy two-side split is suboptimal → exact result.
3. End-to-end synthetic: a deliberately wasteful "comb" layout (single-loaded corridor) that the
   template provably converts → roads strictly decrease.
4. Invariants: never-worse, unplaced preserved, fixed-seed determinism (golden run).
5. CLI smoke: `--lns` produces the HTML file; file contains both layouts' road counts.

## 10. Out of scope

Row-shift and stub-promotion moves; polish/webapp default changes; TH relocation moves; RL; any
OR-Tools dependency; flipping any existing experimental flag.
