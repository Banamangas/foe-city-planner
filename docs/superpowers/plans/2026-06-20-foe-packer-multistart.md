# FoE Optimizer — Budgeted Multi-Start Packer Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `layout` engine's deterministic `repack` into a budgeted randomized multi-start search that tries many randomized packings and keeps the best, finding materially better placements the longer it runs.

**Architecture:** Make `build_candidate` fully determined by a seeded `PackConfig(anchor, seed)` (randomized building order + road-growth tie-break). Rewrite `repack` to loop randomized trials until a wall-clock budget, keeping the best by (unplaced, roads) with early-exit at 0 unplaced. Add `--budget`/`--seed` to the `layout` CLI (mirroring `improve`).

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only (`random`, `time`). Touches `foeopt/packer.py`, `foeopt/cli.py`, and their tests.

## Global Constraints

- Python **3.12**; standard library only; dev dep `pytest`. Test runner: `uv run pytest`.
- **`repack` now defaults to 30s/120s.** Every test that calls `repack` MUST pass an explicit small `budget_seconds` (e.g. `0.3`) so the fast suite never runs a 30s+ search.
- Public types: `PackConfig(anchor: str, seed: int)`, `PackResult(layout, unplaced, trials=0)`, `repack(layout, *, thorough=False, budget_seconds=None, seed=0) -> PackResult`, `build_candidate(layout, config) -> PackResult`.
- **Determinism:** `build_candidate` is deterministic given its `PackConfig`; `repack` is deterministic given `seed` and the number of trials completed (mirrors `improve --anneal`).
- The grow-tree algorithm, `road_target` pre-grow, feasibility-by-construction, conservation, and never-invalid invariants from the A3 packer remain unchanged — only the config source and the order/growth tie-breaks become randomized.
- Budget resolution mirrors the CLI `_resolve_budget`: explicit `budget_seconds` wins, else 120.0 if `thorough` else 30.0.

---

### Task 1: Seed-driven randomization in `build_candidate`

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`

**Interfaces:**
- Produces: `PackConfig(anchor: str, seed: int)`; `build_candidate(layout, config)` uses `random.Random(config.seed)` for building order (area-desc with random tie-break) and road-growth tie-break. `_road_frontier_cell(grid, road, region, rng=None)` — `rng=None` returns the bottom-left cell (unchanged default); with `rng`, picks randomly among the lexicographically smallest few frontier cells.

- [ ] **Step 1: Update existing tests + add a determinism test**

In `tests/test_packer.py`, replace every `PackConfig("bl", "area")` and `PackConfig(anchor="bl", order="area")` with `PackConfig("bl", 0)` (lines ~29, 46, 65, 77, 114). Then add:
```python
def test_build_candidate_deterministic_given_config():
    from foeopt.packer import build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(4)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(12, 12), [th, *cons, *fill], th)
    a = build_candidate(layout, PackConfig("tr", 42))
    b = build_candidate(layout, PackConfig("tr", 42))
    pa = {x.entity_id: (x.footprint.x, x.footprint.y) for x in a.layout.buildings}
    pb = {x.entity_id: (x.footprint.x, x.footprint.y) for x in b.layout.buildings}
    assert pa == pb
    assert a.layout.roads == b.layout.roads
    assert [x.entity_id for x in a.unplaced] == [x.entity_id for x in b.unplaced]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packer.py -k "build_candidate" -v`
Expected: FAIL (`PackConfig` got `order=`/`"area"` where an int seed is now expected, or the new test references unseeded behavior).

- [ ] **Step 3: Implement the randomization**

In `foeopt/packer.py`: add `import random` at the top (with the other imports). Change `PackConfig`:
```python
@dataclass
class PackConfig:
    anchor: str   # Townhall start corner: "bl" | "br" | "tl" | "tr"
    seed: int     # seeds building order + road-growth tie-breaks
```
Replace `_road_frontier_cell` with an rng-aware version:
```python
def _road_frontier_cell(grid: Grid, road: set, region, rng=None) -> tuple[int, int] | None:
    """A free region cell orthogonally adjacent to the road set. Deterministically
    the bottom-left-most cell; with `rng`, a random pick among the smallest few."""
    cands = set()
    for (rx, ry) in road:
        for dx, dy in _ORTHO:
            n = (rx + dx, ry + dy)
            if n in region and n not in road and grid.is_available(n):
                cands.add(n)
    if not cands:
        return None
    ordered = sorted(cands)
    if rng is None:
        return ordered[0]
    return rng.choice(ordered[:4])
```
In `build_candidate`, right after `def area(...)`, create the rng and use it for ordering + growth. Replace the consumer ordering, the two `_road_frontier_cell(grid, road, region)` calls, and the filler ordering:
```python
    rng = random.Random(config.seed)
```
- consumer order: `remaining = sorted(consumers, key=lambda b: (-area(b), rng.random()))`
- both `_road_frontier_cell(grid, road, region)` calls → `_road_frontier_cell(grid, road, region, rng)`
- filler loop: `for b in sorted(fillers, key=lambda b: (-area(b), rng.random())):`

Also update `_configs` (still present until Task 2) to pass an int seed so it stays valid:
```python
def _configs(layout: Layout, thorough: bool) -> list[PackConfig]:
    if not thorough:
        return [PackConfig("bl", 0)]
    return [PackConfig(anchor, 0) for anchor in ("bl", "br", "tl", "tr")]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packer.py -v`
Expected: PASS (determinism test + the updated build_candidate/repack tests). Then `uv run pytest -q` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat(packer): seed-driven randomized order and road-growth in build_candidate"
```

---

### Task 2: `repack` budgeted multi-start

**Files:**
- Modify: `foeopt/packer.py`
- Test: `tests/test_packer.py`, `tests/test_viz.py`, `tests/test_layout_cli.py`

**Interfaces:**
- Consumes: `build_candidate`, `PackConfig`.
- Produces: `PackResult(layout, unplaced, trials: int = 0)`; `repack(layout, *, thorough=False, budget_seconds=None, seed=0) -> PackResult` — randomized multi-start, best by `(len(unplaced), len(roads))`, early-exit at 0 unplaced, ≥1 trial always, sets `.trials`. `_configs` is removed.

- [ ] **Step 1: Update repack call-sites + add the new tests**

Update every `repack(...)` call in tests to pass a small budget:
- `tests/test_packer.py` lines ~87, 98, 127: `repack(layout, thorough=True)` → `repack(layout, budget_seconds=0.3, seed=0)`.
- `tests/test_viz.py` line ~15: `repack(current, thorough=False)` → `repack(current, budget_seconds=0.3)`.
- `tests/test_layout_cli.py` line ~15: `repack(current, thorough=False)` → `repack(current, budget_seconds=0.3)`.

Delete `test_repack_configs_are_corner_anchors` (it referenced the removed `_configs`) and remove `_configs` from the `from foeopt.packer import ...` line in `tests/test_packer.py`. Add:
```python
def test_repack_deterministic_given_seed():
    from foeopt.packer import repack
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(5)]
    fill = [_b(20 + i, 0, 0, 2, 2, needs=False) for i in range(5)]
    layout = Layout(_full_region(8, 8), [th, *cons, *fill], th)  # tight: not all fit
    a = repack(layout, budget_seconds=0.3, seed=7)
    b = repack(layout, budget_seconds=0.3, seed=7)
    assert len(a.unplaced) == len(b.unplaced)
    assert len(a.layout.roads) == len(b.layout.roads)


def test_repack_no_worse_than_single_pass():
    from foeopt.packer import repack, build_candidate, PackConfig
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(6)]
    fill = [_b(20 + i, 0, 0, 2, 2, needs=False) for i in range(6)]
    layout = Layout(_full_region(8, 8), [th, *cons, *fill], th)  # tight
    single = build_candidate(layout, PackConfig("bl", 0))
    multi = repack(layout, budget_seconds=0.5, seed=0)
    assert len(multi.unplaced) <= len(single.unplaced)


def test_repack_early_exit_on_sparse():
    from foeopt.packer import repack
    from foeopt.validate import is_valid
    th = _b(1, 0, 0, 2, 2, th=True)
    cons = [_b(10 + i, 0, 0, 2, 2, needs=True) for i in range(3)]
    fill = [_b(20 + i, 0, 0, 1, 1, needs=False) for i in range(3)]
    layout = Layout(_full_region(20, 20), [th, *cons, *fill], th)  # very sparse
    res = repack(layout, budget_seconds=10.0, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert res.trials == 1   # first trial places all -> early exit (no 10s spent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packer.py -k "repack" -v`
Expected: FAIL (`repack` has no `budget_seconds`/`trials`; new tests reference them).

- [ ] **Step 3: Implement the multi-start + remove `_configs`**

In `foeopt/packer.py`: add `import time` at the top. Add `trials` to `PackResult`:
```python
@dataclass
class PackResult:
    layout: Layout
    unplaced: list[Building]
    trials: int = 0
```
Delete the `_configs` function. Replace `repack` with:
```python
def repack(layout: Layout, *, thorough: bool = False,
           budget_seconds: float | None = None, seed: int = 0) -> PackResult:
    """Budgeted randomized multi-start: try many randomized packings, keep the
    best by (fewest unplaced, then fewest roads). Deterministic given `seed` and
    the number of trials completed. Early-exits when a trial places everything."""
    if budget_seconds is None:
        budget_seconds = 120.0 if thorough else 30.0
    master = random.Random(seed)
    anchors = ("bl", "br", "tl", "tr")
    best: PackResult | None = None
    best_key: tuple[int, int] | None = None
    trials = 0
    deadline = time.monotonic() + budget_seconds
    while True:
        cfg = PackConfig(master.choice(anchors), master.randrange(2 ** 32))
        res = build_candidate(layout, cfg)
        trials += 1
        key = (len(res.unplaced), len(res.layout.roads))
        if best_key is None or key < best_key:
            best, best_key = res, key
        if best_key[0] == 0:            # all placed: can't improve on placement
            break
        if time.monotonic() >= deadline:
            break
    assert best is not None             # the loop body always runs at least once
    best.trials = trials
    return best
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packer.py tests/test_viz.py tests/test_layout_cli.py -v`
Expected: PASS. Then `uv run pytest -q` — full suite green.

- [ ] **Step 5: Record the DarkZig outcome (not a suite test)**

Run:
```bash
uv run python -c "
import time
from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
L = load_layout('darkzig.json')
for b in (30.0, 120.0):
    t = time.time(); res = repack(L, budget_seconds=b, seed=0); dt = time.time()-t
    print(f'budget={b:.0f}s: trials={res.trials} unplaced={len(res.unplaced)} '
          f'roads={len(res.layout.roads)} (est {road_estimate(L)}) in {dt:.0f}s')
"
```
Expected: best unplaced **< 29** (the deterministic baseline). **Record both runs in the task report.**

- [ ] **Step 6: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py tests/test_viz.py tests/test_layout_cli.py
git commit -m "feat(packer): budgeted randomized multi-start repack"
```

---

### Task 3: `layout` CLI `--budget`/`--seed`

**Files:**
- Modify: `foeopt/cli.py`
- Test: `tests/test_layout_cli.py`

**Interfaces:**
- Consumes: `repack(layout, *, budget_seconds, seed)`, `_resolve_budget`, `road_estimate`.
- Produces: a module-level `build_parser() -> argparse.ArgumentParser` (extracted from `main`); the `layout` subcommand accepts `--budget BUDGET` (float, default None) and `--seed SEED` (int, default 0); `_cmd_layout` calls `repack(current, budget_seconds=_resolve_budget(args.budget, args.thorough), seed=args.seed)` and prints the trial count.

Note: `cli.py` currently builds the parser inline inside `main()`. This task extracts that construction into a module-level `build_parser()` so the subparser is unit-testable; `main` then calls it.

- [ ] **Step 1: Write the failing test**

In `tests/test_layout_cli.py`, add:
```python
def test_layout_cli_accepts_budget_and_seed():
    from foeopt.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["layout", "city.json", "--budget", "0.2", "--seed", "3"])
    assert args.budget == 0.2
    assert args.seed == 3
    assert args.thorough is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_layout_cli.py::test_layout_cli_accepts_budget_and_seed -v`
Expected: FAIL (`layout` has no `--budget`/`--seed`).

- [ ] **Step 3: Wire up the CLI**

In `foeopt/cli.py`, first extract the parser into a testable factory. `main()` currently does `parser = argparse.ArgumentParser(prog="foeopt")` ... building all subparsers ... then `args = parser.parse_args(argv)`. Move everything from the `ArgumentParser(...)` construction through the last `set_defaults` into a new module-level function, and have `main` call it:
```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foeopt")
    sub = parser.add_subparsers(dest="command", required=True)
    # ... all existing subparser definitions (view/roads/layout/improve) unchanged ...
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
```
Then add the args to the `layout` subparser (next to its existing `--thorough`):
```python
    p_layout.add_argument("--budget", type=float, default=None,
                          help="time budget in seconds (overrides default/--thorough)")
    p_layout.add_argument("--seed", type=int, default=0,
                          help="RNG seed for the multi-start search (deterministic)")
```
Change `_cmd_layout`'s `repack` call + add the trials line:
```python
    budget = _resolve_budget(args.budget, args.thorough)
    res = repack(current, budget_seconds=budget, seed=args.seed)
```
and after the placed/unplaced print line, add:
```python
    print(f"  trials: {res.trials}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_cli.py -v`
Expected: PASS. Then `uv run pytest -q` — full suite green.

- [ ] **Step 5: Record the CLI run (not a suite test)**

Run:
```bash
uv run python -m foeopt.cli layout darkzig.json --budget 30 --seed 0 -o output/darkzig_multistart.html
```
Expected: prints `trials:`, placed/unplaced (unplaced < 29), roads, and the estimate. **Record in the report.**

- [ ] **Step 6: Commit**

```bash
git add foeopt/cli.py tests/test_layout_cli.py
git commit -m "feat(cli): layout --budget/--seed for the multi-start search"
```

---

## Self-Review

**Spec coverage:**
- `repack` budgeted multi-start, best by (unplaced, roads), early-exit at 0 unplaced, ≥1 trial, deterministic given seed+trials (spec §4) → Task 2. ✓
- `PackConfig(anchor, seed)`; `build_candidate` randomized order (area-desc + tie-break) + road-growth tie-break, seeded (spec §5) → Task 1. ✓
- Grow-tree/feasibility/conservation/never-invalid unchanged (spec §5) → Tasks 1–2 keep the algorithm body; only ordering/growth-tie-break/config change. ✓
- CLI `--budget`/`--seed`, `_resolve_budget` reuse, trials in output (spec §6) → Task 3. ✓
- Testing: determinism (build_candidate + repack), no-worse-than-single-pass, early-exit on sparse, existing tests to small budgets, real-city golden holds, recorded DarkZig (spec §7) → Tasks 1–3. ✓
- Risk/limitations are behavioral (best-effort; 30s default) — no code obligation. ✓

**Placeholder scan:** No placeholders; all code steps complete. The two "record, not a suite test" steps (Task 2 Step 5, Task 3 Step 5) are explicit measurements with expected outcomes. One named uncertainty: Task 3's parser factory name (`build_parser`) — the implementer confirms the actual name in `cli.py` and uses it.

**Type consistency:** `PackConfig(anchor: str, seed: int)` (Task 1) used by `repack` (Task 2) and tests. `PackResult(layout, unplaced, trials=0)` (Task 2) read by the CLI (Task 3). `repack(layout, *, thorough=False, budget_seconds=None, seed=0)` consistent across Task 2 + CLI + all updated test call-sites. `_road_frontier_cell(grid, road, region, rng=None)` (Task 1) called with `rng` inside `build_candidate`. `build_candidate(layout, config) -> PackResult` unchanged in shape.
