# FoE City Layout Optimizer — Budgeted Multi-Start Packer Search Design

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the A3 grow-tree-and-attach packer (merged).

## 1. Purpose

Make the `layout` engine place more buildings by turning its deterministic `repack` into a
**budgeted randomized multi-start search**: run many `build_candidate` trials with randomized
configuration and keep the best. The A3 packer is highly sensitive to the start anchor and the
building order, so searching that space finds materially better packings the longer it runs.

## 2. Motivation (measured)

On DarkZig the single deterministic sweep leaves 29 unplaced. The result swings widely with
configuration: the four corner anchors give 56 / 32 / 59 / 29 unplaced, and just shuffling the
building tie-order at the best anchor over 8 random tries gives 41 / 34 / 30 / 32 / 37 / **21** /
39 / 41 — i.e. a random restart already found **21 unplaced, 8 better than the deterministic 29**.
More trials → better best. This is the same lever that turned hill-climbing into `--anneal`:
convert a deterministic constructive into a budgeted stochastic search.

## 3. Scope

- Rewrite `foeopt/packer.py` `repack` into a budgeted multi-start; change `PackConfig` to
  `PackConfig(anchor: str, seed: int)`; make `build_candidate` fully determined by its `PackConfig`.
- Add `--budget` and `--seed` to the `layout` CLI; reuse `improve`'s `_resolve_budget` (explicit
  `--budget`, else 120s with `--thorough`, else 30s). `--thorough` stays.
- Keep `PackResult(layout, unplaced)` and the grow-tree `build_candidate` algorithm (only its config
  source and the order/growth tie-breaks become randomized).
- `improve`/`roads`/`view`/`anneal` untouched.

## 4. `repack` — budgeted multi-start

`repack(layout, *, thorough=False, budget_seconds=None, seed=0) -> PackResult`:

1. Resolve the budget: `budget_seconds` if given, else 120.0 if `thorough` else 30.0 (mirrors the CLI
   `_resolve_budget`; the CLI passes an explicit `budget_seconds`).
2. `master = random.Random(seed)`. Loop until the wall-clock budget is spent:
   - Draw a trial config: `anchor = master.choice(("bl","br","tl","tr"))`,
     `trial_seed = master.randrange(2**32)`; `cfg = PackConfig(anchor, trial_seed)`.
   - `res = build_candidate(layout, cfg)`.
   - Track the best by the key `(len(res.unplaced), len(res.layout.roads))` — fewest unplaced first,
     then fewest roads. Ties keep the earlier (deterministic) result.
   - **Early-exit** when the best reaches `len(unplaced) == 0` (placement is the primary goal;
     `route()` already minimizes roads for a placement) — so sparse cities finish quickly.
3. Always run at least one trial (so a zero/closed budget still returns a result). Return the best.

**Determinism:** deterministic given `seed` and the number of trials completed (which scales with the
budget and machine speed) — the same contract `improve --anneal` already has.

## 5. `build_candidate` randomization

`PackConfig(anchor: str, seed: int)`. `build_candidate` builds `rng = random.Random(config.seed)` and
uses it for:
- **Building order:** area-descending with a randomized tie-break — sort key
  `(-area, rng.random())` for road-needing buildings and, separately, for fillers (keeps the
  "largest first" packing bias; randomizes equal-area ties so different trials explore different
  orders).
- **Road-growth tie-break:** when extending the road, pick uniformly at random among the
  lexicographically-smallest few frontier candidates instead of always the single bottom-left cell
  (so growth direction varies per trial).

The grow-tree algorithm, the `road_target` pre-grow, the feasibility-by-construction invariants
(road grows by adjacency from a free Townhall-border cell; placed consumers always border a road;
road cells never overwritten), conservation, and never-invalid all remain unchanged.

## 6. CLI

`layout` gains `--budget BUDGET` (seconds, overrides default/`--thorough`) and `--seed SEED`
(default 0). It calls `repack(current, budget_seconds=_resolve_budget(args.budget, args.thorough),
seed=args.seed)`. Output adds the number of trials run, alongside the existing placed/unplaced/roads
and the `road_estimate` target.

## 7. Testing (TDD)

- **Determinism:** `repack(layout, budget_seconds=B, seed=S)` twice with the same small budget gives
  identical placed/unplaced counts and identical road count.
- **No-worse-than-single-pass:** on a tight synthetic city, `repack`'s unplaced count is `<=` the
  unplaced count of a single `build_candidate(layout, PackConfig("bl", 0))`.
- **Early-exit on sparse:** a sparse synthetic city returns `unplaced == []` and is valid; the call
  returns promptly (a generous budget is not consumed because 0-unplaced triggers early-exit).
- **`build_candidate` determinism:** same `PackConfig` → identical result (the randomized order/growth
  are seeded).
- **Existing `repack`/`_configs` tests** updated to the new signature; the real-city `layout` golden
  invariant (valid-in-structure; all-placed-and-valid OR non-empty unplaced) still holds.
- **Recorded DarkZig measurement** (not a fast suite test): `repack` at `budget_seconds=30` and `120`,
  best unplaced + roads vs the deterministic 29 / estimate 114.

## 8. Risk / limitations

- Best-effort: at ~90% density it will not reach 0 unplaced (expect high-teens); the `unplaced` report
  remains the honest shortfall.
- `layout` now takes ~30s by default (120s with `--thorough`) — the agreed trade-off for a real
  search. `--budget 0`-ish still returns a valid single-trial result.
- For optimizing an *existing* city, `improve` remains the right tool; `layout` targets
  from-scratch/greenfield arrangements.
