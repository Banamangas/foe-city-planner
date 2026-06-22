# FoE City Layout Optimizer — Polish Pipeline (repack → anneal) Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming) — ready for implementation planning
**Builds on:** the multi-start packer (`repack`) and true-objective annealing (`anneal`), both merged.

## 1. Purpose

Lower the `layout` engine's road count by **refining** the packer's output with simulated annealing:
run `repack` to get a 0-unplaced base, then `anneal` (building-move SA) to fiddle it lower. Prototyped
and measured: DarkZig **~158 → ~151** (0-unplaced, valid), a consistent improvement on every seed — the
first approach to beat the greedy packer (the constructive heuristics short-side/pairing/lanes all lost).

## 2. Why it works

`anneal`'s `random_move` already performs placement-level moves (same-size swap, relocate-to-free) with
a Metropolis accept and a never-worse anchor. Applied to the packer's strong 0-unplaced layout, it
escapes local optima the constructive pass can't — the automatic analog of hand-fiddling. It is pure
metaheuristic refinement (not a constructive heuristic), so it can only match or beat plain repack.

## 3. Scope

- Add `foeopt/polish.py` `polish(layout, *, repack_budget, anneal_budget, seed=0) -> PackResult`
  (wires `repack` → `anneal`).
- CLI `layout`: add `--polish` (flag) and `--anneal-budget` (seconds, default 120).
- Web UI: a **Polish (anneal)** checkbox + **anneal budget** field on the run panel, for both Re-pack
  and Parallel sweep; backend `run_repack`/`run_sweep` gain an `anneal_budget` argument.
- No change to `improve`/`roads`/`view`, to `repack`/`anneal` internals, or to the optimizer core.
- Out of scope: live anneal progress streaming; auto-split single budget (we use separate budgets);
  new move operators.

## 4. Core — `foeopt/polish.py`

```
polish(layout: Layout, *, repack_budget: float, anneal_budget: float, seed: int = 0) -> PackResult
```
1. `base = repack(layout, budget_seconds=repack_budget, seed=seed)`.
2. `refined = anneal(base.layout, budget_seconds=anneal_budget, seed=seed)` (returns `OptimizeResult`).
3. Ensure the refined layout carries its roads: `roads = route(refined.layout)`; build
   `final = Layout(region, refined.layout.buildings, refined.layout.townhall, roads)`.
4. Return `PackResult(layout=final, unplaced=base.unplaced, trials=base.trials)`.

Properties: `anneal` never drops buildings, so `unplaced` is exactly `base.unplaced`;
`len(final.roads) <= len(base.layout.roads)` (anneal's never-worse anchor); deterministic given
`(seed, repack_budget, anneal_budget)` and the number of iterations each phase completes (same contract
`repack`/`anneal` already have).

## 5. CLI

`layout` subparser gains:
- `--polish` (`store_true`) — run anneal after repack.
- `--anneal-budget` (`float`, default `120.0`) — seconds for the anneal phase.

`_cmd_layout`: when `--polish`, call `polish(current, repack_budget=_resolve_budget(args.budget,
args.thorough), anneal_budget=args.anneal_budget, seed=args.seed)` and print the gain
(`base roads R0 -> polished R1`); otherwise unchanged (`repack(...)`). The estimate and placed/unplaced
lines are printed as today.

## 6. Web UI

- **Run panel** gains a `Polish (anneal)` checkbox and an `anneal budget (s)` number field (default 120,
  shown when polish is checked). Available for both Re-pack and Parallel sweep modes.
- **Backend** (`webapp/runner.py`): `run_repack(layout, *, budget, seed, anneal_budget=0.0)` and
  `run_sweep(layout, *, budget, seeds, workers, anneal_budget=0.0)`. When `anneal_budget > 0`, anneal the
  base (the single repack result, or the sweep's winning base) before building the result dict; the
  result gains `base_roads` (pre-anneal) alongside `roads` (post-anneal).
- `webapp/app.py` `/run` reads `polish`/`anneal_budget` from the request and passes `anneal_budget`
  through (0 when polish is off).
- The page shows `roads R1 (from R0)` when polish ran.

## 7. Testing (TDD)

- **`polish` unit tests:** on a synthetic sparse city, `polish` returns `unplaced == []`, valid, and
  `len(roads) <= len(repack(...).layout.roads)` for the same seed/repack-budget (never worse);
  deterministic — same args twice give the same road count; `unplaced` equals the base's.
- **CLI:** `build_parser()` parses `layout --polish --anneal-budget 0.2`; a tiny-budget
  `polish` end-to-end stays valid (covered by the unit test) — the CLI test asserts arg wiring.
- **Web:** `run_repack(layout, budget=0.3, seed=0, anneal_budget=0.3)` returns a valid result dict with
  `roads <= base_roads`; `/run` with `polish` passes through; the run panel exposes the checkbox
  (served-page assertion).
- **Existing 118 tests stay green** (polish/CLI/web changes are additive).
- **Recorded measurement** (not a fast suite test): DarkZig `polish` (repack 30s + anneal 240s) best
  road count vs the sweep's 158.

## 8. Risk / limitations

- Low: composes two tested engines; anneal's never-worse guarantee means polish ≥ plain repack in
  quality. Determinism preserved. The only cost is the extra (opt-in) anneal time.
- The gain is modest (~4–5%, 158→151) but consistent. Larger gains would need a different optimizer
  class (global search / RL), out of scope here.
