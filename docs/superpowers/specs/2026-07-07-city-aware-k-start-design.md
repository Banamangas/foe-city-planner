# City-Aware k_start Heuristic — Design

**Date:** 2026-07-07
**Status:** Approved (brainstorm 2026-07-07; user decisions §2)
**Origin:** user request after the 2026-07-07 full-TH-sampling test: the `--k-start 152` default is
hardcoded and city-blind. "Not all cities are like Darkzig's city… how should we determine the right
k_start (not too big so that it never finds a solution cause impossible for lack of available space,
not too small either)?" Refined against the five-city test set (darkzig, the user's city, and three
new CityMap-Born-FRxx cities added 2026-07-07).

## 1. Why this and why now

The roads-first k-walk (spec `docs/superpowers/specs/2026-07-06-roads-first-feasibility-design.md`
§2.2) starts at a fixed `--k-start 152` and walks down in steps of −4. Two city-blind defaults are
hardcoded in `scripts/exp_roads_first.py`:

- `--k-start` default `152` (line 663) — picked as a round number above darkzig's classical-pipeline
  158, no city-awareness.
- The upward fallback cap `while st != "FEASIBLE" and k < 168` (line 604) — a hardcoded 168, no
  city-awareness.

Both are wrong for every city except darkzig-class. The five-city test set (measured 2026-07-07)
shows the spread:

| city | region | bldg area | k_current | σ/2 | efficiency | k_max (area ceiling) |
|---|---|---|---|---|---|---|
| darkzig | 2720 | 2437 | 158 | 114.5 | 72.5% | 283 |
| user city | 4224 | 4079 | 142 | 157.0 | 110.6% | 145 |
| FR16 | 1232 | 1026 | 92 | 88.0 | 95.7% | 206 |
| FR17 | 1600 | 1407 | 127 | 121.0 | 95.3% | 193 |
| FR24 | 2736 | 2468 | 232 | 238.0 | 102.6% | 268 |

`efficiency = σ/2 / k_current` (the road-efficiency metric established 2026-07-07; 100% = every road
cell serves the double-row ideal of 2 buildings; >100% = stubs/junctions serving 3, beating the
double-row-tiling estimate). `k_max = region_cells − building_area` is the hard area ceiling: above
it, 0 free cells exist and no placement is possible by simple area accounting, so no probe is needed.

The hardcoded defaults fail three ways:

1. **Too low for cities with k_current > 152.** FR24 (k_current 232): starting at 152 probes a road
   budget far below the existing 232 — almost certainly infeasible for the comb family at that k,
   triggering the upward fallback, which then climbs 152→156→…→? Until it finds a feasible k near
   ~240. Wastes the entire 152→236 climb on probes that were never going to work.
2. **Too high for cities with k_max < 152.** The user's city (k_max 145): starting at 152 is
   *above the area ceiling* — every probe is area-infeasible before CP-SAT even runs. The fallback
   then climbs toward 168 (its cap), all area-infeasible. The walk dies with `FAMILY_TOO_WEAK`
   having probed nothing useful.
3. **The 168 fallback cap is city-blind.** For the user's city (k_max 145) the cap should be 145
   (probing 146–168 is area-impossible). For FR24 (k_current 232) the cap should be 268 (stopping
   at 168 would cut off the feasible region). One hardcoded number can't serve both.

## 2. Locked decisions (user, 2026-07-07)

1. **Single rule: `k_start = min(k_max, ceil(σ/2) + 8)`.** No efficiency conditional, no
   k_current branch. The optimum sits at or below σ/2 (stubs/junctions beat the double-row-tiling
   estimate — every recent roads-first result is >100% efficiency, per the 2026-07-07 metric entry),
   so σ/2 + 8 is almost always feasible for the comb family while skipping the slack above σ/2.
   Margin 8 is a constant, not a flag — keep it simple. If σ/2 + 8 is infeasible, the existing
   upward fallback kicks in (now capped at k_max).
2. **Fallback cap: `k < k_max`** (replaces the hardcoded `168`). The upward fallback walks up in
   steps of +4 until FEASIBLE or `k >= k_max`; if it reaches k_max without feasibility, the verdict
   is `FAMILY_TOO_WEAK` (honest: the comb family can't represent this city at any road budget that
   fits the area).
3. **`bound_adjacency` is NOT a walk-down stop signal.** Per user correction: the bound
   (`ceil(n_consumers / 3)`, `foeopt/bounds.py:17`) assumes all roads are load-3, which is
   geometrically unreachable — roads chain to the TH in straight lanes (load 2 max along the lane),
   and load-3 only happens at lane ends, which are rare relative to lane length. The bound is loose
   and informational only. The walk-down keeps stopping at the first INCONCLUSIVE/INFEASIBLE level,
   as today. `bound_adjacency` stays in `foeopt/bounds.py` unchanged.
4. **Scope: k_start heuristic only.** No warm-start-from-classical integration, no road-efficiency
   metric in CLI output, no richer pattern family, no objective-augmented CP-SAT. All separate
   specs. This is a single self-contained change to `scripts/exp_roads_first.py` + a small new
   pure function in `foeopt/bounds.py`.

## 3. Deliverable

One pure function `pick_k_start(layout: Layout) -> int` in `foeopt/bounds.py` (same family as
`bound_adjacency` / `report_bounds` — placement-independent city metrics). The script calls it when
`--k-start auto`. Unit-testable in isolation (no CP-SAT, no ortools). The script changes:
`argparse` default `"auto"` (string, not int — resolves to the computed value); the `k < 168` cap
becomes `k < k_max` where `k_max = len(region) − sum(building area)`.

`ortools` stays a throwaway `uv run --with` dependency; no change to `foeopt/` core beyond the new
function in `foeopt/bounds.py` (which is pure-stdlib, no ortools import). Per the 2026-07-06
gated-solver-extras policy.

## 4. The heuristic

```python
def pick_k_start(layout: Layout) -> int:
    """City-aware k_start for the roads-first k-walk.

    k_start = min(k_max, ceil(sigma_half) + 8) where:
      k_max      = region_cells - building_area  (hard area ceiling; above it
                   no placement is possible by simple area accounting)
      sigma_half = sum(min(w, l) for each road-needing consumer) / 2
                   (the 100%-efficiency anchor; optima sit at or below it via
                   stubs/junctions serving 3 buildings per road cell)

    Margin 8 keeps the first probe almost always feasible for the comb family
    while skipping the slack above sigma_half. If sigma_half + 8 is infeasible
    the upward fallback walks up (capped at k_max). Never exceeds k_max.

    Not a bound — a starting guess. The walk-down stops at the first
    INCONCLUSIVE/INFEASIBLE level, as today (bound_adjacency is unreachable
    in practice and is not used as a stop signal)."""
    region_cells = len(layout.region.cells)
    building_area = sum(b.footprint.width * b.footprint.length for b in layout.buildings)
    k_max = region_cells - building_area
    sigma_half = sum(min(b.footprint.width, b.footprint.length)
                     for b in layout.road_needing()) / 2
    return min(k_max, math.ceil(sigma_half) + 8)
```

**Per-city k_start (computed from the measured numbers):**

| city | k_max | ceil(σ/2)+8 | **k_start (auto)** | old default (152) | old fallback cap (168) |
|---|---|---|---|---|---|
| darkzig | 283 | 123 | **123** | 152 | 168 |
| user city | 145 | 165 → clamp 145 | **145** | 152 (above k_max!) | 168 (above k_max!) |
| FR16 | 206 | 96 | **96** | 152 | 168 |
| FR17 | 193 | 129 | **129** | 152 | 168 |
| FR24 | 268 | 246 | **246** | 152 (far below k_current 232) | 168 (cuts off feasible region) |

Every city gets a sensible k_start. darkzig skips 29 roads of slack (123 vs 152) — the targeted
run proved this saves ~1.5h. FR16/FR17 start near σ/2 (96/129 vs 152). FR24 starts at 246 (above
its k_current 232 — the comb family needs the road budget to be feasible; the walk descends through
232 territory on the way down). The user's city clamps to k_max=145 (σ/2+8=165 would exceed the area
ceiling); the comb family is almost certainly infeasible at 145 (3 free cells, 110.6% efficient), so
the walk fast-dies with `FAMILY_TOO_WEAK` — the honest outcome for a near-optimal tight city the
comb family can't represent.

## 5. CLI and backward compatibility

**`--k-start` accepts `auto` (string) or an integer.** Default `"auto"`.

- `--k-start auto` (new default): calls `pick_k_start(layout)`, uses the result.
- `--k-start 152` (integer): uses 152 exactly as today. Existing scripts/CI that pass an explicit
  integer are unaffected.
- `--smoke` no longer overrides `k_start` — it uses `--k-start auto` like any real run (on darkzig
  that's 123). The smoke's determinism that matters (single-worker, small budget) is preserved by
  its existing `--workers 1 --probe-workers 1 --patterns 20 --probe-limit 20 --time-box 600`
  overrides; the k_start becomes whatever `pick_k_start(layout)` returns for the loaded city, which
  is the right smoke for that city. A `--smoke` on a tight city (e.g. the user's 145-k_max city)
  fast-dies with `FAMILY_TOO_WEAK` — an honest end-to-end result, not a regression.

**Argparse type:** a custom `k_start_type` function that accepts `"auto"` or any integer string:
```python
def _k_start_type(s):
    if s == "auto":
        return "auto"
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("must be 'auto' or an integer")
```
The `run_search` function resolves `"auto"` to `pick_k_start(layout)` before the walk; an explicit
integer is used as-is.

**No other CLI changes.** `--patterns`, `--probe-limit`, `--time-box`, `--workers`, `--probe-workers`,
`--th-anchors`, `--seed`, `--smoke`, `--selftest`, `--dump-patterns` all unchanged.

## 6. The fallback cap change

In `run_search` (line 604 today): `while st != "FEASIBLE" and k < 168:` → `while st != "FEASIBLE"
and k < k_max:` where `k_max = len(region) - sum(building area)`. `k_max` is computed once at the
top of `run_search` (it can reuse `pick_k_start`'s internal `k_max` or recompute — recompute is
cheap and keeps `pick_k_start` self-contained).

**Behavior per city:**
- darkzig (k_max 283): fallback can climb to 283 if needed (was 168 — would have stopped prematurely
  if 123 had been infeasible).
- user city (k_max 145): fallback capped at 145 (was 168 — would have probed area-impossible
  146–168).
- FR24 (k_max 268): fallback can climb to 268 (was 168 — would have cut off the feasible region
  above 168).

If the fallback reaches `k_max` without feasibility, the verdict is `FAMILY_TOO_WEAK` (unchanged
status, honest message: the comb family can't represent this city at any road budget that fits the
area). The user's city is the expected `FAMILY_TOO_WEAK` case.

## 7. What is NOT in scope

- **No warm-start from the classical pipeline.** The 2026-07-07 productionization analysis proposed
  running repack first and using its road count as k_current; that's a separate Track D spec.
- **No road-efficiency metric in CLI/report output.** The metric is established (2026-07-07 lessons
  entry) and computed internally by `pick_k_start`, but surfacing it to the user is a separate
  productionization concern.
- **No richer pattern family (lanes/stubs).** The 2026-07-07 findings identified this as the next
  R&D spec; separate.
- **No objective-augmented CP-SAT probe.** Candidate R&D spec; separate.
- **No change to `bound_adjacency`** — it stays in `foeopt/bounds.py` as informational only, not a
  walk-down stop signal (per user correction, it's geometrically unreachable).
- **No change to the walk-down stop rule** — first INCONCLUSIVE/INFEASIBLE level, as today.
- **No change to `--smoke`'s other overrides** (`--workers 1 --probe-workers 1 --patterns 20
  --probe-limit 20 --time-box 600`) — only the `k_start = 156` override is dropped (it's now
  `--k-start auto` like any real run).

## 8. Acceptance

- **`pick_k_start(layout)` unit tests** (plain `uv run pytest`, no ortools): for each of the five
  cities, assert `pick_k_start` returns the expected value from the §4 table (darkzig 123, user 145,
  FR16 96, FR17 129, FR24 246). Also assert `pick_k_start <= k_max` for all (the area-ceiling
  invariant).
- **Selftest unchanged.** `uv run --with ortools python scripts/exp_roads_first.py --selftest` →
  `PASS` (the selftest layout is tiny; `pick_k_start` on it returns some small value, but the
  selftest uses its own `k=1` probe path, not `--k-start`, so it's unaffected).
- **Smoke uses `--k-start auto`.** `--smoke` on darkzig now starts at 123 (was 156) and walks down
  a few levels within the 600s box; the smoke result is still a verified-legal layout, just reached
  via the city-aware path.
- **A real run on darkzig with `--k-start auto`** (acceptance, not a gate): should start at 123 and
  walk down, reaching ~104–106 territory in less wall-clock than the 152-start run (fewer high-k
  levels probed). Not a gate because the road-count outcome is already established; the acceptance
  is that the *start* is 123 and the walk proceeds normally.

## 9. Self-test

`foeopt/bounds.py` gains `pick_k_start` + its unit tests in `tests/test_bounds.py` (which already
exists for `bound_adjacency`/`report_bounds`). The script's `--k-start auto` wiring is covered by
the existing selftest (which doesn't use `--k-start`) and by the §8 acceptance run.

No new selftest assertion needed in `scripts/exp_roads_first.py::_selftest` — the selftest layout is
a 6×6 synthetic with 2 consumers, not a real city, so `pick_k_start` on it is meaningless. The
function is tested via `tests/test_bounds.py` on real city fixtures instead.
