# Routability-Preserving Placement Mask — Design

Status: **approved design, not yet implemented.** Second of two specs from the
2026-07-02 road-objective review (`tasks/todo.md`); companion spec:
`2026-07-02-road-target-calibration-design.md`. Independent of that spec's
gate — this can be built in parallel.

## 1. Context and purpose

The 100%-placement objective fails in exactly one way: **stranded consumers**.
Lessons: unplaced buildings are always consumers, never fillers; RL episodes on
dense cities end `unroutable` because placements wall off free-space pockets
that later buildings (or the road network) needed.

This spec adds a guarantee: **no placement may disconnect a free-space pocket
from the road-network origin.** Any layout built under the mask always admits a
road network reaching every remaining free region — `unroutable` becomes
impossible by construction, and stranding drops to the residual case (pocket
reachable but too small/mis-shaped).

Built as shared `foeopt` (pure-stdlib) infrastructure, classical-first: the
constructive packer is the customer. `rlenv` gets the same mode for free if RL
is ever revived (the RL track is archived as of this review).

## 2. Interface (one helper, exact semantics)

`foeopt/reach.py`:

```python
def placement_is_safe(free: set[Cell], footprint_cells: frozenset[Cell],
                      sources: set[Cell], guarded: Iterable[frozenset[Cell]] = ()) -> bool
```

True **iff** after removing `footprint_cells` from `free`: (1) every remaining
orthogonally-connected free component contains at least one cell of (or
orthogonally adjacent to) `sources`, AND (2) every cell-set in `guarded` — the
border cells of already-placed road-needing buildings and the Townhall — still
intersects the remaining free set. Condition (2) closes the sealing hole:
free-space connectivity alone cannot stop later placements from occupying every
border cell of a placed consumer; given (1), one surviving free border cell is
automatically a *reachable* one, which is exactly what route() needs.

- In the packer, `sources` = the current road tree (or, before any road exists,
  the free cells bordering the Townhall).
- In `PlacementEnv`, `sources` = free cells bordering the Townhall footprint.

The contract is **exactness**, not heuristic pruning: the helper must be
equivalence-tested against a naive oracle (full BFS over `free −
footprint_cells` from `sources`) across randomized placement episodes — the
same golden-oracle discipline as Task A.

## 3. Implementation strategy

Two tiers, exactness preserved:

1. **Local ring check (fast accept, common case):** examine the free cells
   orthogonally adjacent to the footprint (its ring). If those ring cells form
   a single connected arc *within the ring neighbourhood* (connectivity checked
   locally, allowing steps through ring cells only), removing the footprint
   cannot split the free space, and at most the reachability of that one arc
   needs confirming — which holds if any ring cell was reachable before. This
   accepts most open-space placements in O(perimeter).
2. **Full BFS fallback (exact):** otherwise run BFS from `sources` over
   `free − footprint_cells` and check every remaining component is reached.

**Explicitly rejected:** an articulation-point prefilter. It is *unsound* for
multi-cell footprints — a 2×2 footprint can sever a 2-wide corridor whose
individual cells are not articulation points. (Caught at design time; the
oracle test would also catch it.)

Per-step reuse: within one placement step the packer evaluates many candidate
anchors against the same `free`/`sources`; the BFS-reachability labelling of
the *pre-removal* free set is computed once per step and shared (the ring
check consults it), so the fallback BFS is the only per-candidate cost and
only on suspicious candidates.

## 4. Wiring

- **Packer:** `safe_placements: bool = False` on `build_candidate`/`repack`
  (threaded through the CLI as `--safe-placements`). **Default off** until the
  A/B gate below says it wins — lessons rule: no packer heuristic ships
  enabled without a 0-unplaced-budget A/B.
- **Env:** `PlacementEnv.valid_actions(safe=True)` mode, exercised by tests
  only for now.
- The helper is pure and side-effect-free; both call sites own their
  `sources` definition.

## 5. Measured gates (both must hold to flip the default on)

Benchmark suite: darkzig + `make_real_like_city` seeds at fill 0.5/0.7/0.9,
≥ 8 seeds, budgets large enough for 0-unplaced where achievable (lessons
discipline).

1. **Placement:** the unplaced-count distribution is strictly no worse
   everywhere, and better in the tails (min/mean unplaced on the dense fills).
2. **Roads + throughput:** the 0-unplaced road distribution is not worse, and
   packer throughput (trials per budget) regresses < ~30%. If the BFS fallback
   dominates runtime, the flag stays opt-in and the result is recorded.

## 6. Risk (stated up front)

The mask prunes dead ends **and** some dense completions: a temporarily
walled-off pocket can later be exactly filled by a perfectly-sized building,
which the mask forbids. This is the same shape as the five failed proxy
heuristics — plausible-sounding constraint, unmeasured real effect. Hence
default-off + the §5 gates; the mask is a hypothesis until the numbers land.

## 7. Testing

- `tests/test_reach.py`:
  - hand-built cases: open space (safe), corridor severed by 1-wide footprint
    (unsafe), 2-wide corridor severed by 2×2 (unsafe — the articulation
    counter-example, pinned as a regression), pocket kept reachable around a
    corner (safe), footprint consuming an entire pocket exactly (safe — no
    remaining component).
  - **oracle equivalence:** randomized episodes on synthetic cities comparing
    `placement_is_safe` against the naive BFS oracle for every candidate at
    every step.
- `tests/test_rlenv.py` (append): `valid_actions(safe=True)` ⊆
  `valid_actions()`; an env run under the safe mask never ends `unroutable`.
- Packer A/B is a measurement (per §5), not a unit test; results go to
  `tasks/lessons.md`.

## 8. Out of scope

- Turning the mask on by default (gated on §5).
- Any RL training or RL-specific tuning.
- Guaranteeing zero unplaced (the mask removes the *unroutable* failure mode;
  size/shape mismatch stranding remains and belongs to Track A's roads-first
  structure).
