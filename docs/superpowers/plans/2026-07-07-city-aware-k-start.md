# City-Aware k_start Heuristic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `--k-start 152` default and the `k < 168` fallback cap in `scripts/exp_roads_first.py` with a city-aware heuristic (`k_start = min(k_max, ceil(σ/2) + 8)`) computed from the loaded layout, so the roads-first k-walk starts at a sensible road budget for any city instead of a darkzig-specific round number.

**Architecture:** One pure function `pick_k_start(layout: Layout) -> int` added to `foeopt/bounds.py` (same family as `bound_adjacency`/`report_bounds` — placement-independent city metrics, pure-stdlib, no ortools). The throwaway script's argparse gains `--k-start auto` (new default, string-or-int) which resolves to `pick_k_start(layout)` in `run_search`; the hardcoded `k < 168` fallback cap becomes `k < k_max` (city-specific area ceiling). `--smoke` drops its `k_start = 156` override and uses `--k-start auto` like any real run.

**Tech Stack:** Python 3.12+ stdlib (`math`, `argparse`); pytest for tests. No CP-SAT/ortools needed for the unit tests (the heuristic is pure arithmetic on the layout). No new dependencies. The only `foeopt/` change is the new function in `foeopt/bounds.py`.

## Global Constraints

- **`ortools` stays a throwaway `uv run --with` dependency** — never added to `pyproject.toml`; the heuristic is pure-stdlib (spec §3, 2026-07-06 gated-solver-extras policy).
- **The only `foeopt/` change is the new `pick_k_start` function in `foeopt/bounds.py`** — no other `foeopt/` file is touched (spec §3).
- **No change to the k-walk algorithm, the gate (≤ 148), the pattern family, the verification pipeline, the parallel dispatch, or the `--th-anchors` flag** — only the k_start selection and the fallback cap (spec §2, §7).
- **`bound_adjacency` is NOT a walk-down stop signal** — it stays in `foeopt/bounds.py` unchanged, informational only (spec §2.3; user correction: load-3 is geometrically unreachable except at rare lane ends).
- **`--k-start auto` (new default) or an integer** — explicit `--k-start N` still works exactly as today; existing scripts/CI passing an integer are unaffected (spec §5).
- **`--smoke` drops its `k_start = 156` override** — uses `--k-start auto` like any real run; its other overrides (`--workers 1 --probe-workers 1 --patterns 20 --probe-limit 20 --time-box 600`) remain (spec §5, §7).
- **MARGIN = 8 is a constant, not a CLI flag** — keep it simple (spec §2.1).
- **Tests run without `ortools` installed** — the heuristic's unit tests are pure-arithmetic; the existing `tests/test_bounds.py` already runs under plain `uv run pytest`.

---

### Task 1: Add `pick_k_start(layout)` to `foeopt/bounds.py`

Pure function: city-aware k_start heuristic. This is the only `foeopt/` change. Unit-testable in isolation (no CP-SAT, no ortools). Followed TDD: failing test first, then implementation.

**Files:**
- Modify: `foeopt/bounds.py` (add `pick_k_start` after `report_bounds`, ~line 35)
- Test: `tests/test_bounds.py` (add tests at end of file)

**Interfaces:**
- Consumes: `foeopt.model.Layout` (already imported in `bounds.py`), `math` (already imported).
- Produces: `pick_k_start(layout: Layout) -> int` — returns `min(k_max, ceil(σ/2) + 8)` where `k_max = len(region.cells) - sum(building footprint area)` and `σ/2 = sum(min(w, l) for each road-needing consumer) / 2`. Later tasks (Task 2) call this from the script.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bounds.py`:

```python
import math

from foeopt.bounds import pick_k_start


def test_pick_k_start_synthetic_layout():
    """10x10 region (100 cells), TH 2x2 (4 cells), 4 consumers 2x2 each (16 cells).
    building_area = 4 + 16 = 20. k_max = 100 - 20 = 80.
    sigma_half = sum(min(2,2) for 4 consumers) / 2 = 8/2 = 4.
    k_start = min(80, ceil(4) + 8) = min(80, 12) = 12."""
    th = _b(1, 2, 2, th=True)
    cons = [_b(10 + i, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_region(10, 10), [th, *cons], th, {})
    assert pick_k_start(layout) == 12


def test_pick_k_start_clamps_to_k_max():
    """Tight region where sigma_half + 8 exceeds the area ceiling.
    5x5 region (25 cells), TH 2x2 (4), 4 consumers 2x2 (16). building_area = 20.
    k_max = 25 - 20 = 5. sigma_half = 4. sigma_half + 8 = 12.
    k_start = min(5, 12) = 5 (clamped to the area ceiling)."""
    th = _b(1, 2, 2, th=True)
    cons = [_b(10 + i, 2, 2, needs=True) for i in range(4)]
    layout = Layout(_region(5, 5), [th, *cons], th, {})
    assert pick_k_start(layout) == 5


def test_pick_k_start_on_darkzig(repo_root):
    """darkzig: region=2720, building_area=2437, k_max=283, sigma_half=114.5.
    k_start = min(283, ceil(114.5)+8) = min(283, 123) = 123."""
    path = repo_root / "darkzig.json"
    if not path.exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout(str(path))
    assert pick_k_start(lay) == 123


def test_pick_k_start_on_user_city(repo_root):
    """user city: region=4224, building_area=4079, k_max=145, sigma_half=157.0.
    k_start = min(145, ceil(157)+8) = min(145, 165) = 145 (clamped to k_max)."""
    lay = load_layout(str(repo_root / "city-user-data.json"),
                      str(repo_root / "city-user-data-foe-helper.json"))
    assert pick_k_start(lay) == 145


@pytest.mark.parametrize("name,expected", [
    ("CityMap-Born-FR16-2026-07-07.json", 96),    # k_max=206, sigma/2=88 -> min(206, 96) = 96
    ("CityMap-Born-FR17-2026-07-07.json", 129),   # k_max=193, sigma/2=121 -> min(193, 129) = 129
    ("CityMap-Born-FR24-2026-07-07.json", 246),   # k_max=268, sigma/2=238 -> min(268, 246) = 246
])
def test_pick_k_start_on_fr_cities(repo_root, name, expected):
    """Three CityMap-Born-FRxx cities (added 2026-07-07): k_start = min(k_max, ceil(sigma/2)+8)."""
    path = repo_root / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    lay = load_layout(str(path))
    assert pick_k_start(lay) == expected


def test_pick_k_start_never_exceeds_k_max(repo_root):
    """Airtight invariant: k_start <= k_max for any city (the area ceiling)."""
    import glob, os
    for path in sorted(glob.glob(str(repo_root / "CityMap-Born-FR*.json"))):
        lay = load_layout(path)
        k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                            for b in lay.buildings)
        assert pick_k_start(lay) <= k_max
    # also darkzig and user city
    dz = repo_root / "darkzig.json"
    if dz.exists():
        lay = load_layout(str(dz))
        k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                            for b in lay.buildings)
        assert pick_k_start(lay) <= k_max
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bounds.py -v`
Expected: FAIL — `ImportError: cannot import name 'pick_k_start' from 'foeopt.bounds'` (the 6 new tests fail on the import; the 4 existing `bound_adjacency`/`report_bounds` tests still pass).

- [ ] **Step 3: Write minimal implementation**

Add to `foeopt/bounds.py` (after `report_bounds`, at the end of the file):

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

    Not a bound -- a starting guess. The walk-down stops at the first
    INCONCLUSIVE/INFEASIBLE level, as today (bound_adjacency is unreachable
    in practice and is not used as a stop signal)."""
    region_cells = len(layout.region.cells)
    building_area = sum(b.footprint.width * b.footprint.length for b in layout.buildings)
    k_max = region_cells - building_area
    sigma_half = sum(min(b.footprint.width, b.footprint.length)
                     for b in layout.road_needing()) / 2
    return min(k_max, math.ceil(sigma_half) + 8)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bounds.py -v`
Expected: PASS — all 10 tests pass (4 existing + 6 new: synthetic, clamp, darkzig, user city, 3 FR cities, k_max invariant).

- [ ] **Step 5: Commit**

```bash
git add foeopt/bounds.py tests/test_bounds.py
git commit -m "feat(bounds): pick_k_start city-aware heuristic for roads-first k-walk

k_start = min(k_max, ceil(sigma/2) + 8). k_max = region - building_area
(hard area ceiling). sigma/2 = sum of consumer short sides / 2 (the
100%-efficiency anchor). Margin 8 keeps the first probe feasible while
skipping the slack above sigma/2. Pure-stdlib, no ortools. Unit-tested
on darkzig (123), user city (145, clamped), FR16 (96), FR17 (129), FR24
(246), plus a synthetic layout and a k_max-invariant sweep."
```

---

### Task 2: Wire `--k-start auto` into the script's argparse and `run_search`

Make `--k-start` accept `"auto"` (new default) or an integer. In `run_search`, resolve `"auto"` to `pick_k_start(layout)`; use an explicit integer as-is. This is the script-side wiring that consumes Task 1's function. No change to the k-walk loop body itself (the walk starts at `args.k_start` as today — only how `args.k_start` is computed changes).

**Files:**
- Modify: `scripts/exp_roads_first.py` (argparse `--k-start` at line 663; `run_search` at line ~570; add `pick_k_start` import)

**Interfaces:**
- Consumes: `pick_k_start(layout: Layout) -> int` from Task 1 (`foeopt.bounds`).
- Produces: `--k-start auto` (default) or integer; `run_search` sees a resolved integer `args.k_start` before the walk begins.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roads_first_parallel.py` (the existing script-test file — keep all roads-first script tests together):

```python
def test_k_start_auto_resolves_to_pick_k_start_value(monkeypatch):
    """--k-start auto should resolve to pick_k_start(layout) inside run_search,
    not stay as the string 'auto' (which would crash the k-walk's integer
    arithmetic). Verify by capturing the k the first level() call probes."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import exp_roads_first as mod
    from foeopt.loader import load_layout
    from foeopt.bounds import pick_k_start

    lay = load_layout("darkzig.json")  # assumes cwd is repo root; skip if absent
    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")

    captured_k = []
    real_probe_level = mod._probe_level
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None):
        captured_k.append(k)
        return ("FEASIBLE", 200)  # short-circuit: one level, then walk stops

    monkeypatch.setattr(mod, "_probe_level", spy_probe_level)
    # Also force an immediate deadline so the walk does one level and exits.
    import time as _t
    class FakeArgs:
        k_start = "auto"
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        workers = 1
        th_anchors = "coarse"
        seed = 0
        time_box = 1.0  # 1 second -> deadline fires immediately after first level
        deadline = _t.monotonic() + 1.0
    args = FakeArgs()
    try:
        mod.run_search(lay, args)
    except Exception:
        pass  # run_search may error on the short-circuit; we only care about captured_k
    monkeypatch.undo()
    expected = pick_k_start(lay)
    assert captured_k, "run_search did not probe any level"
    assert captured_k[0] == expected, (
        f"--k-start auto should probe k={expected} first (pick_k_start), "
        f"got k={captured_k[0]}")


def test_k_start_explicit_integer_overrides_auto(monkeypatch):
    """--k-start 152 (explicit integer) must use 152 exactly, not pick_k_start."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import exp_roads_first as mod
    from foeopt.loader import load_layout

    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")
    lay = load_layout("darkzig.json")

    captured_k = []
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None):
        captured_k.append(k)
        return ("FEASIBLE", 200)
    monkeypatch.setattr(mod, "_probe_level", spy_probe_level)
    import time as _t
    class FakeArgs:
        k_start = 152
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        workers = 1
        th_anchors = "coarse"
        seed = 0
        time_box = 1.0
        deadline = _t.monotonic() + 1.0
    try:
        mod.run_search(lay, FakeArgs())
    except Exception:
        pass
    monkeypatch.undo()
    assert captured_k, "run_search did not probe any level"
    assert captured_k[0] == 152, f"explicit --k-start 152 ignored, got {captured_k[0]}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_k_start_auto_resolves_to_pick_k_start_value tests/test_roads_first_parallel.py::test_k_start_explicit_integer_overrides_auto -v`
Expected: FAIL — `argparse` rejects `"auto"` as `--k-start` (current type is `int`); `run_search` does not resolve `"auto"` to `pick_k_start(layout)`, so `args.k_start` stays the string `"auto"` and the k-walk's `k = args.k_start` / `k < 168` integer comparison crashes with `TypeError`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/exp_roads_first.py`:

(a) Add the import near the other `foeopt` imports (around line 26-30):

```python
from foeopt.bounds import pick_k_start
```

(b) Add a custom argparse type (top-level function, near the other helpers — e.g. just above `def main`):

```python
def _k_start_type(s: str):
    """argparse type for --k-start: 'auto' or an integer."""
    if s == "auto":
        return "auto"
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("must be 'auto' or an integer")
```

(c) Change the `--k-start` argparse line (line 663) from:

```python
    p.add_argument("--k-start", type=int, default=152)
```
to:

```python
    p.add_argument("--k-start", type=_k_start_type, default="auto",
                   help="k-walk start: 'auto' (city-aware, default) or an integer")
```

(d) In `run_search`, resolve `"auto"` to `pick_k_start(layout)` before the walk begins. Find the line `k = args.k_start` (line 601, at the top of the k-walk) and insert the resolution just before it:

```python
            # Resolve --k-start auto to the city-aware heuristic value.
            if args.k_start == "auto":
                args.k_start = pick_k_start(layout)
                print(f"k_start (auto) = {args.k_start}", flush=True)
            k = args.k_start
```

(The `print` is helpful context in run output — matches the existing `print(f"probing k={k} ...")` style. `args` is a `Namespace`, mutable, so this assignment is fine.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_k_start_auto_resolves_to_pick_k_start_value tests/test_roads_first_parallel.py::test_k_start_explicit_integer_overrides_auto -v`
Expected: PASS — both tests pass.

- [ ] **Step 5: Run the full test file + selftest to confirm no regression**

Run: `uv run pytest tests/test_roads_first_parallel.py tests/test_bounds.py -v`
Expected: PASS — all tests pass (the 4 from earlier tasks + 2 new + 10 bounds tests; 1 skipped where ortools is needed for the parallel-dispatch test).

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: `selftest: parallel_equiv=True (seq=11 par=11)` / `PASS` (unchanged — the selftest uses its own `k=1` probe path, not `--k-start`).

- [ ] **Step 6: Commit**

```bash
git add scripts/exp_roads_first.py tests/test_roads_first_parallel.py
git commit -m "feat(roads-first): --k-start auto (city-aware, default) via pick_k_start

--k-start now accepts 'auto' (new default, resolves to pick_k_start(layout))
or an explicit integer (backward-compatible). Custom argparse type _k_start_type.
run_search resolves 'auto' before the k-walk and prints the chosen k_start.
Selftest unchanged (uses its own k=1 path)."
```

---

### Task 3: Replace the hardcoded `k < 168` fallback cap with `k < k_max`

The upward fallback (when `k_start` itself is infeasible) walks up in steps of +4 until FEASIBLE or a cap. Today the cap is the hardcoded `168`. Replace it with the city-specific area ceiling `k_max = len(region) - sum(building area)`. This is a one-line change in `run_search`, but it changes behavior meaningfully (per-city cap), so it gets its own task + test.

**Files:**
- Modify: `scripts/exp_roads_first.py` (`run_search` fallback loop at line 604)

**Interfaces:**
- Consumes: `layout` (already in scope in `run_search`).
- Produces: the fallback loop caps at `k_max` instead of `168`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roads_first_parallel.py`:

```python
def test_fallback_cap_is_k_max_not_168(monkeypatch):
    """When k_start is infeasible, the upward fallback must walk up to k_max
    (city-specific area ceiling), not the hardcoded 168. Verify on the user's
    city (k_max=145): an infeasible k_start=145 should let the fallback try
    145+4=149 only if 149 <= k_max=145 (it isn't) -> fallback stops at 145,
    FAMILY_TOO_WEAK. If the cap were still 168, the fallback would try
    149,153,...,169 (all area-infeasible above 145) before giving up."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import exp_roads_first as mod
    from foeopt.loader import load_layout

    helper = pathlib.Path("city-user-data-foe-helper.json")
    if not (pathlib.Path("city-user-data.json").exists() and helper.exists()):
        pytest.skip("user city files not present")
    lay = load_layout("city-user-data.json", str(helper))
    k_max = len(lay.region.cells) - sum(b.footprint.width * b.footprint.length
                                        for b in lay.buildings)
    assert k_max == 145  # sanity: the user city's area ceiling

    probed_ks = []
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None):
        probed_ks.append(k)
        return ("INFEASIBLE", None)  # every level infeasible -> fallback climbs
    monkeypatch.setattr(mod, "_probe_level", spy_probe_level)
    import time as _t
    class FakeArgs:
        k_start = 145  # = k_max, infeasible -> fallback should try up
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        workers = 1
        th_anchors = "coarse"
        seed = 0
        time_box = 60.0
        deadline = _t.monotonic() + 60.0
    try:
        result = mod.run_search(lay, FakeArgs())
    except Exception:
        result = None
    monkeypatch.undo()
    # The fallback must NOT probe above k_max=145. If the cap were 168,
    # probed_ks would contain 149, 153, ... up to 168.
    above_kmax = [k for k in probed_ks if k > k_max]
    assert not above_kmax, (
        f"fallback probed above k_max={k_max}: {above_kmax} (cap not respected)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_fallback_cap_is_k_max_not_168 -v`
Expected: FAIL — the fallback climbs past k_max=145 (tries 149, 153, … up to 168) because the cap is still the hardcoded `168`. `above_kmax` is non-empty.

- [ ] **Step 3: Write minimal implementation**

In `scripts/exp_roads_first.py` `run_search` (line 604), change:

```python
                while st != "FEASIBLE" and k < 168:
```
to:

```python
                k_max = len(layout.region.cells) - sum(
                    b.footprint.width * b.footprint.length for b in layout.buildings)
                while st != "FEASIBLE" and k < k_max:
```

(Compute `k_max` inline at the point of use. Alternatively, hoist it to the top of `run_search` — but inline is minimal and keeps the change localized. The `layout` variable is in scope at this point in `run_search`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_fallback_cap_is_k_max_not_168 -v`
Expected: PASS — the fallback stops at k=145 (k_max), never probes 149+.

- [ ] **Step 5: Run the full test file + selftest**

Run: `uv run pytest tests/test_roads_first_parallel.py tests/test_bounds.py -v`
Expected: PASS — all tests green.

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: `PASS` (unchanged).

- [ ] **Step 6: Commit**

```bash
git add scripts/exp_roads_first.py tests/test_roads_first_parallel.py
git commit -m "fix(roads-first): fallback cap k<168 -> k<k_max (city-specific area ceiling)

The upward fallback (when k_start is infeasible) now caps at k_max =
region - building_area, not the hardcoded 168. Fixes two failures: cities
with k_max < 168 (user city: 145) no longer probe area-impossible 146-168;
cities with k_current > 168 (FR24: 232) no longer have the feasible region
cut off at 168. Unit-tested on the user city (k_max=145): fallback stops at
145, never probes above."
```

---

### Task 4: Drop the `--smoke` `k_start = 156` override

Per spec §5: `--smoke` no longer overrides `k_start` — it uses `--k-start auto` like any real run (on darkzig that's 123). Its other overrides (`--workers 1 --probe-workers 1 --patterns 20 --probe-limit 20 --time-box 600`) remain. This is a one-line deletion, but it changes smoke behavior, so it gets its own task + a verification run.

**Files:**
- Modify: `scripts/exp_roads_first.py` (`main` smoke-override block at line 672-673)

**Interfaces:**
- Consumes: Task 2's `--k-start auto` default.
- Produces: `--smoke` uses `--k-start auto` (resolves to `pick_k_start(layout)` in `run_search`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roads_first_parallel.py`:

```python
def test_smoke_does_not_override_k_start(monkeypatch):
    """--smoke must NOT override k_start to 156; it should leave --k-start auto
    (the default) so run_search resolves it to pick_k_start(layout). Verify by
    parsing the smoke args and checking args.k_start == 'auto' (not 156)."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import exp_roads_first as mod

    # main() parses argv and applies smoke overrides but returns before
    # run_search if no city is given. Pass --smoke with no city -> p.error()
    # would fire; instead pass a dummy city path that exists so main proceeds
    # to run_search, which we spy on.
    if not pathlib.Path("darkzig.json").exists():
        pytest.skip("darkzig.json not present")

    captured_args = []
    real_run_search = mod.run_search
    def spy_run_search(layout, args):
        captured_args.append(args)
        return {"verdict": "DONE", "results": {}}  # short-circuit
    monkeypatch.setattr(mod, "run_search", spy_run_search)
    try:
        mod.main(["darkzig.json", "--smoke"])
    except Exception:
        pass
    monkeypatch.undo()
    assert captured_args, "main() did not call run_search"
    args = captured_args[0]
    assert args.k_start == "auto", (
        f"--smoke overrode k_start to {args.k_start!r}; expected 'auto' (the default)")
    # Also confirm the other smoke overrides still apply.
    assert args.workers == 1
    assert args.probe_workers == 1
    assert args.patterns == 20
    assert args.probe_limit == 20.0
    assert args.time_box == 600.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_smoke_does_not_override_k_start -v`
Expected: FAIL — `args.k_start` is `156` (the smoke override at line 673 still runs), not `"auto"`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/exp_roads_first.py` `main` (line 672-677), delete the `args.k_start = 156` line. The block becomes:

```python
    if args.smoke:
        args.patterns = 20
        args.probe_limit = 20.0
        args.time_box = 600.0
        args.workers = 1
        args.probe_workers = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_smoke_does_not_override_k_start -v`
Expected: PASS — `args.k_start == "auto"`, other smoke overrides intact.

- [ ] **Step 5: Run the full test suite + selftest + a real smoke to confirm the city-aware smoke works**

Run: `uv run pytest tests/test_roads_first_parallel.py tests/test_bounds.py -v`
Expected: PASS — all tests green.

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: `PASS` (unchanged — selftest uses its own k=1 path).

Run a real smoke on darkzig (now k_start=123, not 156):
```bash
uv run --with ortools python scripts/exp_roads_first.py darkzig.json --smoke > /tmp/opencode/smoke-kstart-auto.txt 2>&1
echo "EXIT=$?"
head -3 /tmp/opencode/smoke-kstart-auto.txt
tail -8 /tmp/opencode/smoke-kstart-auto.txt
```
Expected: `EXIT=0`, the first output line is `k_start (auto) = 123`, then `probing k=123 ...`, and the smoke completes with a `verdict: DONE` and some `best_achieved` (the exact value depends on the 600s budget; on darkzig it should reach ~115-125 territory, better than the old 156-start smoke which reached ~123-135). Independently verify the best smoke layout is legal (reuse the 2026-07-07 verification script pattern — `rotated_buildings=0`, `route()` matches, `is_valid` True).

- [ ] **Step 6: Commit**

```bash
git add scripts/exp_roads_first.py tests/test_roads_first_parallel.py
git commit -m "feat(roads-first): --smoke uses --k-start auto (drops the 156 override)

--smoke no longer forces k_start=156; it uses the city-aware --k-start auto
default like any real run. On darkzig the smoke now starts at 123 (was 156).
Other smoke overrides (--workers 1 --probe-workers 1 --patterns 20 --probe-limit
20 --time-box 600) remain. A --smoke on a tight city (user city: k_max 145)
fast-dies with FAMILY_TOO_WEAK -- an honest end-to-end result, not a regression."
```

---

## Self-Review (run by the planner, not a subagent)

**1. Spec coverage:**
- §2.1 single rule `min(k_max, ceil(σ/2)+8)` → Task 1 `pick_k_start`.
- §2.2 fallback cap `k < k_max` → Task 3.
- §2.3 `bound_adjacency` not a stop signal → Global Constraints (no change to walk-down; `bound_adjacency` untouched in `foeopt/bounds.py`).
- §2.4 scope k_start only → Global Constraints (no warm-start, no CLI efficiency metric, no richer family, no objective-augmented probe).
- §3 deliverable: `pick_k_start` in `foeopt/bounds.py` + script argparse/run_search changes → Tasks 1, 2.
- §4 the heuristic (full code) → Task 1 Step 3 (verbatim).
- §5 CLI `--k-start auto`/integer, `--smoke` drops 156 override → Tasks 2, 4.
- §6 fallback cap change → Task 3.
- §7 out-of-scope → Global Constraints.
- §8 acceptance: unit tests on 5 cities + selftest unchanged + real darkzig run → Tasks 1 (unit tests), 4 Step 5 (smoke = the real run; the §8 "acceptance run" is the smoke on darkzig with `--k-start auto`, now starting at 123).
- §9 self-test: `pick_k_start` tested via `tests/test_bounds.py` on real fixtures → Task 1.

**2. Placeholder scan:** No "TBD"/"TODO"/"similar to Task N". Every code step shows the actual code. The one "..." in Task 2 Step 3(d) refers to the *unchanged* k-walk body — explicitly labeled "the walk starts at `args.k_start` as today"; the engineer is told not to change it.

**3. Type consistency:** `pick_k_start(layout: Layout) -> int` — consistent across Task 1 (definition), Task 2 (import + call), Task 2 tests, Task 3 tests, Task 4 tests. `_k_start_type(s: str) -> str|int` — defined in Task 2 Step 3(b), used in Task 2 Step 3(c). `args.k_start` is `"auto"` (string) or `int` until `run_search` resolves it to `int` — Task 2 Step 3(d) does the resolution, Task 4 test asserts the pre-resolution value is `"auto"`. The `k_max` computation (`len(region.cells) - sum(building area)`) is identical in Task 1 (`pick_k_start`), Task 3 (inline), and Task 3/4 tests — consistent.

One issue caught and fixed inline: Task 2's tests need `args.deadline` set (the `run_search` deadline check runs before the first probe). Added `deadline = _t.monotonic() + 1.0` to `FakeArgs` in both Task 2 tests and the Task 3/4 tests so the short-circuit spy exits after one level. Also: Task 4's test calls `mod.main([...])` which calls `run_search` — the spy on `run_search` short-circuits before the deadline matters, but `main` also sets `args.deadline = time.monotonic() + args.time_box` (line 680), so `FakeArgs` doesn't need `deadline` for Task 4 (main sets it). Verified: Task 4's `FakeArgs` is not used — main builds its own `args` from argparse. Consistent.
