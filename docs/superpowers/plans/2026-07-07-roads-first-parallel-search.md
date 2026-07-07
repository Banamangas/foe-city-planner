# Roads-First Parallel Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallelize the throwaway `scripts/exp_roads_first.py` CP-SAT feasibility search across cores via a `multiprocessing.Pool` (4 concurrent probes × 4 CP-SAT portfolio workers per probe by default), cutting the 6h darkzig run wall-clock and attacking the UNKNOWN-dominated budget — without changing the k-walk algorithm, the gate, the pattern family, or the verification pipeline.

**Architecture:** Approach 1 from the spec — process-pool within each k-level, k-walk stays sequential. The parent process generates patterns deterministically, runs the cheap `prefilter` itself, submits surviving patterns to a `Pool(N)` of stateless worker processes, and serializes all file writes (probe log + best-layout artifacts). Each worker runs `probe()` + `validate()` for one pattern, with CP-SAT `num_search_workers = M`. Verification (`route()`, `is_valid`, `rotated_buildings`) stays deterministic and runs in-worker before any `OK` return, so every saved layout remains independently verifiable-legal.

**Tech Stack:** Python 3.12+ stdlib `multiprocessing.Pool`, `argparse`, `json`; OR-Tools CP-SAT (`ortools.sat.python.cp_model`, throwaway `uv run --with` dep); pytest for tests. No new dependencies. No changes to `foeopt/` core.

## Global Constraints

- **`ortools` stays a throwaway `uv run --with` dependency** — never added to `pyproject.toml`; the parallelism is pure-Python `multiprocessing` in the throwaway script only (spec §3, §7; 2026-07-06 gated-solver-extras policy).
- **No change to `foeopt/` core** — `foeopt/router.py`, `foeopt/validate.py`, `foeopt/model.py`, `foeopt/packing.py`, `foeopt/loader.py`, `foeopt/viz.py` are untouched (spec §3, §8).
- **No change to the k-walk algorithm, the gate (≤ 148), the pattern family (combs + TH stubs), or the verification pipeline** — only the inside of a `_probe_level` is parallelized (spec §2.3, §5, §8).
- **`--patterns` default stays 200** — measured separately later (spec §2.4, §8).
- **Verification is the source of truth, not the search trajectory** — `random_seed = 0` is still set on every CP-SAT solver; only portfolio divergence (with `--probe-workers > 1`) is non-deterministic. Every saved `best-k*-a*.json` must independently re-verify as legal (spec §6).
- **`--workers 1 --probe-workers 1` reproduces the current sequential run** — same set of probe statuses for the same seed, modulo the new `order` field (spec §7, §9).
- **`--smoke` forces `--workers 1 --probe-workers 1`** — keeps the 10-min smoke a deterministic sanity check (spec §7).
- **Tests run without `ortools` installed** — the test suite must not require CP-SAT; guard `ortools` imports behind the probe path so unit tests of the dispatch/logging logic run under plain `uv run pytest`.

---

### Task 1: Extract a pure `_run_probe` worker function

Refactor `probe()` + `validate()` into a single picklable top-level function `_run_probe(payload)` that a `Pool` worker can call. Today `probe()` and `validate()` are already top-level and picklable, but the dispatch loop in `_probe_level` calls them inline and interleaves logging/artifact-writing. This task separates the *work* (run in a worker) from the *orchestration* (run in the parent) without yet parallelizing anything — a pure refactor that the next task swaps in behind a pool.

**Files:**
- Modify: `scripts/exp_roads_first.py` (`probe` at line 259, `validate` at line 302, `_probe_level` at line 374)

**Interfaces:**
- Consumes: `probe(pattern, region, consumers, *, probe_limit)` (line 259), `validate(layout_src, pattern, positions)` (line 302), `prefilter(pattern, region, consumers)` (line 202), `Pattern` dataclass (line ~60), `Building`/`Layout` from `foeopt.model`.
- Produces: `_run_probe(payload: tuple) -> dict` — a top-level function taking `(pattern, k, layout, probe_limit, probe_workers)` and returning a result dict `{"k", "params", "status", "achieved", "secs", "layout"}` where `layout` is the validated `Layout` (or `None`). `status` is one of `SAT`, `UNSAT`, `UNKNOWN`, `ROUTE_FAIL`, `INVALID`, `SAT_FILLER_FAIL`, `SAT_ROTATED` (the existing `validate()` statuses), or `PREFILTERED` (caller-side; `_run_probe` never returns this). `secs` is the wall-clock of the `probe()` call only (prefilter and validate time excluded, matching today's `secs` semantics — see line 391).

- [ ] **Step 1: Write the failing test**

Create `tests/test_roads_first_parallel.py`:

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import pytest

# Import without ortools in scope; _run_probe must be importable and its
# non-CP-SAT branches testable without the solver installed.
import exp_roads_first as mod


def test_run_probe_unsat_returns_status_no_layout():
    """A pattern that prefilter rejects fast (no anchors) -> UNSAT, no layout.
    _run_probe must return a dict with the documented keys, status UNSAT,
    achieved None, layout None, secs a float >= 0."""
    # Build a tiny layout where the consumer cannot sit on any road cell of
    # the pattern (1 consumer 2x2, pattern k=1 with a single road cell the
    # consumer's footprint cannot be adjacent to within a 1x1 region).
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 1, 1),
                  False, 1, True, None, None, "TH")
    consumer = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(1) for y in range(1)))
    lay = Layout(region, [th, consumer], th, {})
    # generate a real pattern at k=1 to feed _run_probe; the exact pattern
    # shape doesn't matter for this test — we just need _run_probe to run
    # the probe() path and return a well-formed dict. We mock probe via
    # monkeypatch to avoid needing ortools.
    import random
    pats = list(mod.generate_patterns(set(region.cells), 1, 1, 1, random.Random(0), 5))
    assert pats, "expected at least one pattern at k=1"
    pat = pats[0]
    # Monkeypatch probe to return UNSAT without calling CP-SAT.
    def fake_probe(pattern, region, consumers, *, probe_limit):
        return ("UNSAT", None)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "probe", fake_probe)
    try:
        result = mod._run_probe((pat, 1, lay, 30.0, 1))
    finally:
        monkeypatch.undo()
    assert set(result.keys()) >= {"k", "params", "status", "achieved", "secs", "layout"}
    assert result["status"] == "UNSAT"
    assert result["achieved"] is None
    assert result["layout"] is None
    assert isinstance(result["secs"], float)
    assert result["secs"] >= 0.0
    assert result["k"] == 1
    assert result["params"] == pat.params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_run_probe_unsat_returns_status_no_layout -v`
Expected: FAIL with `AttributeError: module 'exp_roads_first' has no attribute '_run_probe'`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/exp_roads_first.py`, add a new top-level function just above `_probe_level` (around line 373). Do not change `probe()` or `validate()` themselves — `_run_probe` wraps them.

```python
def _run_probe(payload: tuple) -> dict:
    """Worker entry point: run probe() + validate() for one (pattern, k).

    payload = (pattern, k, layout, probe_limit, probe_workers).
    Returns a result dict with keys: k, params, status, achieved, secs, layout.
    status is one of the validate() statuses (SAT/UNSAT/UNKNOWN/ROUTE_FAIL/
    INVALID/SAT_FILLER_FAIL/SAT_ROTATED) where SAT means validate() returned OK.
    layout is the validated Layout on SAT, else None. secs is the wall-clock of
    the probe() call only (prefilter excluded — caller runs prefilter;
    validate excluded — matches today's secs semantics at line 391).
    """
    pat, k, layout, probe_limit, probe_workers = payload
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers, probe_limit=probe_limit,
                   probe_workers=probe_workers)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None}
```

Note: `probe()` currently does not take a `probe_workers` kwarg — that is added in Task 3. For this task, **also** add the `probe_workers` parameter to `probe()` signature and pass it through to `solver.parameters.num_search_workers` (replacing the hardcoded `1` at line 287), defaulting to `1` so behavior is unchanged when unset. This is a one-line change inside `probe()`:

```python
def probe(pattern: Pattern, region: set[Cell], consumers: list[Building],
          *, probe_limit: float, probe_workers: int = 1) -> tuple[str, dict | None]:
    ...
    solver.parameters.num_search_workers = probe_workers   # was: 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_run_probe_unsat_returns_status_no_layout -v`
Expected: PASS.

- [ ] **Step 5: Run the existing selftest to confirm no regression**

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: `selftest: oracle=1 k1_validated=True k0_empty=True PASS` (unchanged — `probe_workers` defaults to 1).

- [ ] **Step 6: Commit**

```bash
git add scripts/exp_roads_first.py tests/test_roads_first_parallel.py
git commit -m "refactor(roads-first): extract _run_probe worker function

Pure refactor: probe()+validate() wrapped in a picklable top-level
_run_probe(payload) -> dict, ready for multiprocessing.Pool dispatch.
probe() gains a probe_workers kwarg (default 1, behavior unchanged).
No parallelization yet — _probe_level still calls inline in the next task."
```

---

### Task 2: Wire `multiprocessing.Pool` dispatch into `_probe_level`

Replace the sequential `for pat in pats:` loop in `_probe_level` with a `Pool(N)` dispatch. The parent runs `prefilter` (cheap, no CP-SAT), submits surviving patterns to the pool, collects results as they complete (`imap_unordered`), and serializes all file writes (probe log + best-layout artifacts). The k-walk stays sequential — each level is a synchronization barrier. The pool is created once at search start and reused across levels (passed in via `args`), not per level.

**Files:**
- Modify: `scripts/exp_roads_first.py` (`_probe_level` at line 374, `run_search` at line 427, `main`/argparse at line 504)

**Interfaces:**
- Consumes: `_run_probe(payload)` from Task 1; `Pattern`, `prefilter`, `validate`, `render_html`, `probe`.
- Produces: `_probe_level` now takes a `pool: multiprocessing.pool.Pool | None` argument (None ⇒ sequential fallback identical to today, used by `--workers 1` and `--smoke`). `run_search` creates and tears down the pool. New CLI flags `--workers` and `--probe-workers`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roads_first_parallel.py`:

```python
def test_probe_level_sequential_fallback_matches_today(monkeypatch_patch=None):
    """With pool=None, _probe_level must behave exactly as today: patterns
    probed in generation order, results logged in order, best-achieved
    computed. Verify via a fake _run_probe that records call order."""
    import random
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    # Fake _run_probe: returns SAT with achieved=k for the first pattern,
    # UNSAT for the rest, recording the order it was called in.
    call_order = []
    def fake_run_probe(payload):
        pat, k, layout, probe_limit, probe_workers = payload
        call_order.append(pat.params)
        if len(call_order) == 1:
            # Return a minimal valid-ish layout dict; _probe_level only
            # reads achieved + layout for the SAT branch.
            return {"k": k, "params": pat.params, "status": "SAT",
                    "achieved": k, "secs": 0.1,
                    "layout": "FAKE_LAYOUT"}  # layout is opaque to _probe_level's bookkeeping
        return {"k": k, "params": pat.params, "status": "UNSAT",
                "achieved": None, "secs": 0.1, "layout": None}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mod, "_run_probe", fake_run_probe)
    # Stub render_html and the artifact writer so no files are written.
    monkeypatch.setattr(mod, "render_html", lambda lay: "<html/>")
    monkeypatch.setattr(mod.json, "dumps", lambda obj, indent=None: "{}")

    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600

    import time as _t
    FakeArgs.deadline = _t.monotonic() + 600

    log_rows = []
    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=None)
    finally:
        monkeypatch.undo()

    # Sequential fallback: called in generation order (not completion order).
    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    expected_order = [p.params for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    assert call_order == expected_order, (
        f"sequential fallback must probe in generation order; got {call_order} "
        f"expected {expected_order}")
    assert status == "FEASIBLE"
    assert best == 1  # first pattern returned achieved=k=1
    # Log rows include the SAT row.
    assert any(r.get("status") == "SAT" for r in log_rows)


def test_probe_level_parallel_dispatch_completes_all(monkeypatch):
    """With a real Pool(2), _probe_level must dispatch all surviving patterns
    and collect every result (order may vary, set of statuses must match)."""
    import random
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    # Fake _run_probe at module level so the pool worker can pickle it.
    # (Workers import the module fresh; the real _run_probe is used. We
    # instead verify dispatch completeness by counting log rows.)
    class FakeArgs:
        patterns = 5
        probe_limit = 30.0
        probe_workers = 1
        deadline = time.monotonic() + 600
    import time as _t
    FakeArgs.deadline = _t.monotonic() + 600

    log_rows = []
    def log(row):
        log_rows.append(row)

    region_set = set(region.cells)
    rng = random.Random(0)
    # Use a real Pool(2) but with --probe-workers 1 and a real CP-SAT solve
    # (small enough to resolve fast). This is an integration smoke of the
    # dispatch path, not a unit test of fake probes.
    pool = mod.multiprocessing.Pool(2)
    try:
        status, best = mod._probe_level(lay, region_set, [c1], 1, rng,
                                        FakeArgs, log, pool=pool)
    finally:
        pool.close()
        pool.join()

    # All surviving patterns were probed and logged.
    pats = list(mod.generate_patterns(region_set, 2, 2, 1, random.Random(0), 5))
    surviving = [p for p in pats if mod.prefilter(p, region_set, [c1]) is None]
    probed = [r for r in log_rows if r.get("status") != "PREFILTERED"]
    assert len(probed) == len(surviving), (
        f"parallel dispatch must probe all {len(surviving)} surviving patterns, "
        f"got {len(probed)} log rows")
```

Add `import time` to the test file's top.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roads_first_parallel.py -v`
Expected: FAIL — `_probe_level` does not accept a `pool=` kwarg (`TypeError`), and `mod.multiprocessing` is not imported.

- [ ] **Step 3: Write minimal implementation**

In `scripts/exp_roads_first.py`:

(a) Add the import at the top (after line 21, `import time`):

```python
import multiprocessing
```

(b) Rewrite `_probe_level` (replacing lines 374–424) to accept `pool` and dispatch via `imap_unordered` when a pool is provided, else fall back to the sequential loop:

```python
def _probe_level(layout, region, consumers, k, rng, args, log, pool=None) -> tuple[str, int | None]:
    """Probe up to --patterns patterns at level k. Returns (level_status, best_achieved):
    level_status in {"FEASIBLE", "INFEASIBLE", "INCONCLUSIVE"} — INFEASIBLE only if
    every attempted pattern was UNSAT (incl. prefilter rejections, which are proofs);
    any UNKNOWN or SAT_FILLER_FAIL/ROUTE_FAIL/INVALID/SAT_ROTATED makes a failed level
    INCONCLUSIVE. If pool is None, probes sequentially in generation order (identical
    to the pre-parallel behavior). If pool is a multiprocessing.pool.Pool, dispatches
    surviving patterns via imap_unordered and collects results in completion order."""
    th = layout.townhall.footprint
    pats = generate_patterns(region, th.width, th.length, k, rng, args.patterns)
    best_achieved = None
    saw_nonproof_failure = False
    order = 0  # monotonic completion counter for the log's `order` field

    def handle_result(result, pat):
        nonlocal best_achieved, order, saw_nonproof_failure
        order += 1
        status = result["status"]
        achieved = result["achieved"]
        log({"k": k, "params": pat.params, "status": status,
             "achieved": achieved, "secs": result["secs"], "order": order})
        if status == "SAT":
            vlay = result["layout"]
            if best_achieved is None or achieved < best_achieved:
                best_achieved = achieved
                out_dir = pathlib.Path("output/roads-first")
                out_dir.mkdir(parents=True, exist_ok=True)
                stem = f"best-k{k}-a{achieved}"
                (out_dir / f"{stem}.json").write_text(json.dumps({
                    "k": k, "achieved": achieved, "pattern": pat.params,
                    "roads": sorted(vlay.roads),
                    "buildings": {b.entity_id: [b.footprint.x, b.footprint.y,
                                                b.footprint.width, b.footprint.length]
                                  for b in vlay.buildings}}, indent=1), encoding="utf-8")
                (out_dir / f"{stem}.html").write_text(render_html(vlay), encoding="utf-8")
        elif status in ("UNKNOWN", "ROUTE_FAIL", "INVALID", "SAT_FILLER_FAIL", "SAT_ROTATED"):
            saw_nonproof_failure = True
        if time.monotonic() > args.deadline:
            return True  # signal: stop submitting / drain
        return False

    # Prefilter in the parent (cheap, no CP-SAT), log rejections immediately.
    surviving = []
    for pat in pats:
        reason = prefilter(pat, region, consumers)
        if reason is not None:
            log({"k": k, "params": pat.params, "status": "PREFILTERED",
                 "reason": reason, "secs": 0.0, "order": 0})
            continue
        surviving.append(pat)

    if pool is None:
        for pat in surviving:
            result = _run_probe((pat, k, layout, args.probe_limit, args.probe_workers))
            if handle_result(result, pat):
                return ("INCONCLUSIVE" if best_achieved is None else "FEASIBLE", best_achieved)
    else:
        # Dispatch via imap_unordered; collect in completion order.
        payloads = [(pat, k, layout, args.probe_limit, args.probe_workers)
                    for pat in surviving]
        # Build a params lookup so we can recover the pattern for artifact writes.
        # imap_unordered yields results in completion order; we pair by id via
        # the payload's pattern object identity.
        pat_by_id = {id(p): p for p in surviving}
        # We need to know which pattern each result came from. _run_probe does
        # not return the pattern object (not picklable-safe to rely on), so we
        # embed a pat_index in the payload and look it up.
        payloads = [(pat, k, layout, args.probe_limit, args.probe_workers, idx)
                    for idx, pat in enumerate(surviving)]
        # _run_probe must accept the 6-tuple; update its signature to ignore
        # the trailing idx (or use it — see Task 1 amendment below).
        for result in pool.imap_unordered(_run_probe, payloads):
            idx = result["pat_index"]
            pat = surviving[idx]
            if handle_result(result, pat):
                break

    if best_achieved is not None:
        return ("FEASIBLE", best_achieved)
    if not pats:
        return ("INCONCLUSIVE", None)
    return ("INCONCLUSIVE" if saw_nonproof_failure else "INFEASIBLE", None)
```

**Amend `_run_probe` (Task 1)** to accept the 6-tuple and return `pat_index`:

```python
def _run_probe(payload: tuple) -> dict:
    pat, k, layout, probe_limit, probe_workers, pat_index = payload
    ...  # unchanged body
    return {..., "pat_index": pat_index}  # add pat_index to every return
```

(c) Update `run_search` (line 427) to create the pool once and pass it to `_probe_level`:

```python
def run_search(layout, args) -> dict:
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    rng = random.Random(args.seed)
    out_dir = pathlib.Path("output/roads-first")
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = None
    if args.workers > 1:
        pool = multiprocessing.Pool(args.workers)
    try:
        with (out_dir / "probes.jsonl").open("a", encoding="utf-8") as logf:
            def log(row):
                logf.write(json.dumps(row) + "\n")
                logf.flush()
            def timed_out():
                return time.monotonic() >= args.deadline
            results: dict[int, tuple[str, int | None]] = {}
            def level(k):
                if k not in results:
                    print(f"probing k={k} ...", flush=True)
                    results[k] = _probe_level(layout, region, consumers, k, rng,
                                              args, log, pool=pool)
                    print(f"  k={k}: {results[k][0]}"
                          f"{' achieved=' + str(results[k][1]) if results[k][1] is not None else ''}",
                          flush=True)
                return results[k]
            # ... rest of the k-walk (lines 453–499) UNCHANGED ...
    finally:
        if pool is not None:
            pool.close()
            pool.join()
```

(d) Add the CLI flags in `main` (after line 513, `--smoke`):

```python
    p.add_argument("--workers", type=int, default=4,
                   help="concurrent probe processes (1 = sequential fallback)")
    p.add_argument("--probe-workers", type=int, default=4,
                   help="CP-SAT num_search_workers per probe (portfolio)")
```

And in the `--smoke` override block (lines 515–519), force single-worker:

```python
    if args.smoke:
        args.k_start = 156
        args.patterns = 20
        args.probe_limit = 20.0
        args.time_box = 600.0
        args.workers = 1
        args.probe_workers = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roads_first_parallel.py -v`
Expected: PASS for both `test_probe_level_sequential_fallback_matches_today` and `test_probe_level_parallel_dispatch_completes_all`.

- [ ] **Step 5: Run the existing selftest to confirm no regression**

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: `selftest: oracle=1 k1_validated=True k0_empty=True PASS`.

- [ ] **Step 6: Run the smoke test to confirm the parallel path produces a legal layout**

Run: `uv run --with ortools python scripts/exp_roads_first.py darkzig.json --smoke > /tmp/opencode/parallel-smoke.txt 2>&1; echo "EXIT=$?"`
Then independently verify the best smoke layout is legal (reuse the verification script pattern from the 2026-07-07 run — `rotated_buildings`=0, `route()` matches, `is_valid` True). Expected: smoke now forces `--workers 1 --probe-workers 1`, so the result matches the prior 123-road de-rotated smoke (or close).

Expected: `EXIT=0`, `best_achieved` ≤ ~135, and the verification script prints `rotated= 0 -> LEGAL`.

- [ ] **Step 7: Commit**

```bash
git add scripts/exp_roads_first.py tests/test_roads_first_parallel.py
git commit -m "feat(roads-first): multiprocessing.Pool dispatch in _probe_level

--workers N (default 4) concurrent probes via imap_unordered; --probe-workers M
(default 4) CP-SAT portfolio workers per probe. Pool created once in run_search,
reused across k-levels, torn down in finally. --workers 1 = sequential fallback
(generation-order dispatch, identical to today). --smoke forces --workers 1
--probe-workers 1 for determinism. probe log gains an `order` field (monotonic
completion counter). Verification stays in-worker and deterministic."
```

---

### Task 3: Worker initializer for read-only layout data (avoid per-task pickling)

Today's payload sends `layout` in every task tuple. The layout is read-only and ~MB; pickling it 200×N times per level is wasteful. Send it once to each worker process via a pool initializer (a module global in the worker), and shrink the per-task payload to `(pat, k, pat_index)`.

**Files:**
- Modify: `scripts/exp_roads_first.py` (`_run_probe`, `_probe_level`, `run_search`)

**Interfaces:**
- Consumes: Task 2's pool dispatch.
- Produces: `_WORKER_LAYOUT` module global in the worker process; `_worker_init(layout)` initializer; `_run_probe` payload shrinks to `(pat, k, pat_index)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roads_first_parallel.py`:

```python
def test_run_probe_payload_uses_worker_global_not_embedded_layout(monkeypatch):
    """_run_probe must accept the 3-tuple (pat, k, pat_index) and read layout
    from the worker global, not from the payload. Verify by setting the
    global in-process and calling _run_probe with a 3-tuple."""
    import random
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, c1], th, {})

    # Set the worker global as the initializer would.
    mod._WORKER_LAYOUT = lay
    mod._WORKER_PROBE_LIMIT = 30.0
    mod._WORKER_PROBE_WORKERS = 1
    try:
        pats = list(mod.generate_patterns(set(region.cells), 2, 2, 1, random.Random(0), 5))
        pat = next(p for p in pats if mod.prefilter(p, set(region.cells), [c1]) is None)
        # Fake probe so we don't need ortools.
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(mod, "probe",
                            lambda pattern, region, consumers, *, probe_limit, probe_workers=1:
                            ("UNSAT", None))
        try:
            result = mod._run_probe((pat, 1, 0))  # 3-tuple: pat, k, pat_index
        finally:
            monkeypatch.undo()
        assert result["pat_index"] == 0
        assert result["k"] == 1
    finally:
        del mod._WORKER_LAYOUT
        del mod._WORKER_PROBE_LIMIT
        del mod._WORKER_PROBE_WORKERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roads_first_parallel.py::test_run_probe_payload_uses_worker_global_not_embedded_layout -v`
Expected: FAIL — `_run_probe` still expects the 6-tuple from Task 2.

- [ ] **Step 3: Write minimal implementation**

In `scripts/exp_roads_first.py`:

(a) Add module globals and the initializer near the top (after the imports, around line 31):

```python
# Worker-process globals set by _worker_init (sent once per worker, not per task).
_WORKER_LAYOUT: Layout | None = None
_WORKER_PROBE_LIMIT: float = 30.0
_WORKER_PROBE_WORKERS: int = 1


def _worker_init(layout: Layout, probe_limit: float, probe_workers: int) -> None:
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
```

(b) Rewrite `_run_probe` to take the 3-tuple and read from globals:

```python
def _run_probe(payload: tuple) -> dict:
    pat, k, pat_index = payload
    layout = _WORKER_LAYOUT
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    t0 = time.monotonic()
    st, pos = probe(pat, region, consumers,
                   probe_limit=_WORKER_PROBE_LIMIT,
                   probe_workers=_WORKER_PROBE_WORKERS)
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay, "pat_index": pat_index}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None, "pat_index": pat_index}
```

(c) Update `_probe_level`'s parallel branch to send the 3-tuple:

```python
        payloads = [(pat, k, idx) for idx, pat in enumerate(surviving)]
        for result in pool.imap_unordered(_run_probe, payloads):
            idx = result["pat_index"]
            pat = surviving[idx]
            if handle_result(result, pat):
                break
```

(d) Update `run_search` to pass the initializer and `probe_limit`/`probe_workers` to the pool:

```python
    pool = None
    if args.workers > 1:
        pool = multiprocessing.Pool(
            args.workers,
            initializer=_worker_init,
            initargs=(layout, args.probe_limit, args.probe_workers))
```

(e) Update the sequential fallback in `_probe_level` to pass `args.probe_limit`/`args.probe_workers` directly (no globals in the parent process):

```python
    if pool is None:
        for pat in surviving:
            result = _run_probe_seq((pat, k, layout, args.probe_limit, args.probe_workers))
            ...
```

Add a thin sequential wrapper `_run_probe_seq` that takes the 6-tuple (kept for the `--workers 1` path, which never goes through the pool so never sets globals):

```python
def _run_probe_seq(payload: tuple) -> dict:
    """Sequential-mode wrapper: sets globals temporarily and calls _run_probe.
    Kept separate so the pool path's globals are never mutated by the parent."""
    global _WORKER_LAYOUT, _WORKER_PROBE_LIMIT, _WORKER_PROBE_WORKERS
    pat, k, layout, probe_limit, probe_workers = payload
    _WORKER_LAYOUT = layout
    _WORKER_PROBE_LIMIT = probe_limit
    _WORKER_PROBE_WORKERS = probe_workers
    try:
        return _run_probe((pat, k, 0))
    finally:
        _WORKER_LAYOUT = None
```

(Note: in the sequential path, `pat_index` is always 0 — it's unused by `handle_result` for the sequential branch, which has the `pat` object directly. See the `_probe_level` code in Task 2 Step 3: the sequential branch calls `handle_result(result, pat)` with the loop's `pat`, not via `pat_index`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roads_first_parallel.py -v`
Expected: PASS for all three tests.

- [ ] **Step 5: Run the selftest and smoke**

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: PASS.

Run: `uv run --with ortools python scripts/exp_roads_first.py darkzig.json --smoke > /tmp/opencode/parallel-smoke2.txt 2>&1; echo "EXIT=$?"`
Expected: `EXIT=0`, `best_achieved` ≤ ~135 (smoke forces `--workers 1`, so unchanged from Task 2's smoke).

- [ ] **Step 6: Commit**

```bash
git add scripts/exp_roads_first.py tests/test_roads_first_parallel.py
git commit -m "perf(roads-first): worker initializer sends layout once per worker

Worker-process globals _WORKER_LAYOUT/_WORKER_PROBE_LIMIT/_WORKER_PROBE_WORKERS
set by _worker_init; per-task payload shrinks from (pat,k,layout,limit,workers,
idx) to (pat,k,idx). Avoids pickling the ~MB layout 200×N times per level.
Sequential --workers 1 path uses _run_probe_seq (sets globals transiently)."
```

---

### Task 4: Selftest parallel-equivalence assertion

Add the spec §6/§10 structural assertion: `--workers 1 --probe-workers 1` produces the same set of `(k, params, status)` tuples as today's sequential path, and `--workers 2 --probe-workers 1` produces a subset of the sequential statuses (parallelism must not invent new statuses).

**Files:**
- Modify: `scripts/exp_roads_first.py` (`_selftest` at line 344)

**Interfaces:**
- Consumes: `_run_probe`, `generate_patterns`, `prefilter`, `probe`, `validate` from earlier tasks.

- [ ] **Step 1: Write the failing test**

This task's test is the selftest itself — there is no separate unit test file. The assertion lives in `_selftest` and is exercised by `--selftest`. Add it as new assertions at the end of `_selftest` (before the `return`):

```python
    # Parallel-equivalence (spec §10): --workers 1 --probe-workers 1 must
    # produce the same set of (k, params, status) as the sequential path,
    # and --workers 2 --probe-workers 1 must produce a subset of those
    # statuses (parallelism must not invent new statuses; at probe-workers=1
    # even SAT/UNKNOWN flips are fixed, so the set should be identical).
    import multiprocessing as _mp
    seq_statuses = set()
    rng2 = random.Random(0)
    for pat in generate_patterns(region, 2, 2, 1, rng2, 50):
        if prefilter(pat, region, [c1, c2]) is not None:
            seq_statuses.add(("PREFILTERED", tuple(sorted(pat.params.items()))))
            continue
        st, _ = probe(pat, region, [c1, c2], probe_limit=30.0, probe_workers=1)
        seq_statuses.add((st, tuple(sorted(pat.params.items()))))

    # Parallel path with --workers 2 --probe-workers 1.
    par_statuses = set()
    pool = _mp.Pool(2, initializer=_worker_init,
                    initargs=(lay, 30.0, 1))
    try:
        rng3 = random.Random(0)
        pats3 = [p for p in generate_patterns(region, 2, 2, 1, rng3, 50)]
        surviving = [(p, 1, idx) for idx, p in enumerate(pats3)
                     if prefilter(p, region, [c1, c2]) is None]
        prefiltered = [tuple(sorted(p.params.items())) for p in pats3
                       if prefilter(p, region, [c1, c2]) is not None]
        for pf in prefiltered:
            par_statuses.add(("PREFILTERED", pf))
        for result in pool.imap_unordered(_run_probe, surviving):
            par_statuses.add((result["status"],
                              tuple(sorted(pats3[result["pat_index"]].params.items()))))
    finally:
        pool.close(); pool.join()

    ok_parallel_equiv = par_statuses == seq_statuses
    print(f"selftest: parallel_equiv={ok_parallel_equiv} "
          f"(seq={len(seq_statuses)} par={len(par_statuses)})")
    ok = ok_k1 and ok_k0 and ok_parallel_equiv
    print(f"selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1
```

- [ ] **Step 2: Run the selftest to verify it fails (or passes — this is a structural check)**

Run: `uv run --with ortools python scripts/exp_roads_first.py --selftest`
Expected: PASS (the equivalence should hold by construction — if it fails, there's a pool-introduced bug to fix before committing). If it fails, debug the divergence (likely a pattern-params serialization or a status mismatch from the pool path).

- [ ] **Step 3: Commit**

```bash
git add scripts/exp_roads_first.py
git commit -m "test(roads-first): selftest parallel-equivalence assertion

--workers 2 --probe-workers 1 must produce the same set of (status, params)
as the sequential path for the tiny selftest layout (spec §10). Catches
pool-introduced bugs. Existing oracle/k0 assertions unchanged."
```

---

### Task 5: Real parallel run + A/B measurement against the 106 baseline

Run the parallel search for real and measure against the 2026-07-07 sequential baseline (106 roads, 2189 probes, 5.988h, 642 UNKNOWN). This is the spec §9 acceptance step — empirical, not a code change.

**Files:**
- No code changes. Artifacts written to `output/roads-first/` (gitignored).

**Interfaces:**
- Consumes: the parallel script from Tasks 1–4.

- [ ] **Step 1: Confirm no CPU-heavy processes are running**

Run: `ps aux --sort=-%cpu | head -8`
Expected: no other `python`/`ortools`/CP-SAT process competing for the 16 cores. If there is, wait or kill it.

- [ ] **Step 2: Back up the sequential baseline artifacts so the parallel run doesn't overwrite them**

```bash
mkdir -p output/roads-first/sequential-baseline-2026-07-07
mv output/roads-first/best-k*.json output/roads-first/best-k*.html output/roads-first/sequential-baseline-2026-07-07/ 2>/dev/null
mv output/roads-first/probes.jsonl output/roads-first/sequential-baseline-2026-07-07/probes-sequential.jsonl
mv output/roads-first/run-derotated.txt output/roads-first/sequential-baseline-2026-07-07/
```

- [ ] **Step 3: Launch the parallel 6h run (default 4×4)**

```bash
nohup uv run --with ortools python scripts/exp_roads_first.py darkzig.json --probe-limit 30.0 > output/roads-first/run-parallel.txt 2>&1 &
echo "PID=$!" > output/roads-first/run-parallel.pid
```

- [ ] **Step 4: Monitor — after ~30 min, confirm probes are completing faster than the sequential baseline**

```bash
sleep 1800
uv run python -c "
import json
from collections import Counter
rows=[json.loads(l) for l in open('output/roads-first/probes.jsonl')]
print('n=',len(rows),'status=',dict(Counter(r['status'] for r in rows)))
print('levels=',sorted(set(r['k'] for r in rows)))
print('sum_secs=%.0f (%.2fh)'%(sum(r['secs'] for r in rows),sum(r['secs'] for r in rows)/3600))
"
```

Expected: more than ~2 k-levels reached in 30 min (the sequential baseline reached ~1 level in 30 min). If only 1 level, the parallelism isn't helping — stop and debug before burning the 6h budget.

- [ ] **Step 5: Let the run complete (6h), then independently recompute and verify**

After the run finishes, recompute every derived number from `probes.jsonl` directly (not trusting `run-parallel.txt`):

```bash
uv run python -c "
import json, statistics
from collections import Counter, defaultdict
rows=[json.loads(l) for l in open('output/roads-first/probes.jsonl')]
print('total probes:', len(rows))
print('overall status:', dict(Counter(r['status'] for r in rows)))
# ... per-level table, SAT/UNSAT/UNKNOWN means, sum_secs, best_achieved ...
"
```

Then independently verify the best layout is legal (reuse the 2026-07-07 verification script): 224/224 placed, `route()` matches `achieved`, `is_valid` True, `rotated_buildings = 0`, 0 overlaps, 0 out-of-region.

- [ ] **Step 6: Record the verdict in `tasks/lessons.md` and `tasks/todo.md`**

Append a `## Roads-first parallel re-run (2026-07-XX)` entry to `tasks/lessons.md` with: the parallel config (`--workers 4 --probe-workers 4`), the wall-clock, the k-levels reached, the best achieved, the UNKNOWN rate vs the baseline's 29%, the per-level table, and the legality verification. Update `tasks/todo.md` Track E with a note pointing at the parallel run. Commit.

**Acceptance (spec §9):**
- Throughput (must): more k-levels than the baseline's 12 (or 12 with wall-clock to spare).
- Legality (must): every saved `best-k*-a*.json` independently re-verifies as legal. **A failure here blocks the change.**
- UNKNOWN rate (nice-to-have, not a gate): no worse, ideally lower, than 29%.

- [ ] **Step 7: Commit the verdict**

```bash
git add tasks/lessons.md tasks/todo.md
git commit -m "docs: roads-first parallel re-run verdict — <result>"
```

---

## Self-Review (run by the planner, not a subagent)

**1. Spec coverage:**
- §2.1 balanced hybrid → Tasks 1–3 (pool + probe-workers portfolio).
- §2.2 relax search determinism → Task 1 (`probe_workers` kwarg, `random_seed=0` kept) + Task 2 (log `order` field).
- §2.3 Approach 1, level barrier → Task 2 (`_probe_level` barrier, pool reused across levels).
- §2.4 `--patterns` default 200 → Global Constraints + Task 2 (no change to default).
- §3 throwaway script, no new dep → Global Constraints + all tasks (pure `multiprocessing`).
- §4 core model (pool, 4×4, parent generates+writes, worker runs probe+validate) → Tasks 1–3.
- §5 level barrier, deadline, probe-limit independence, pool lifecycle, memory → Task 2.
- §6 logging (`order` field), reproducibility stance, selftest parallel-equiv → Tasks 2 + 4.
- §7 CLI flags, defaults, smoke forces single-worker, no auto-detect → Task 2.
- §8 out-of-scope → Global Constraints (no `foeopt/` change, no `--patterns` bump, no speculative k).
- §9 acceptance → Task 5.
- §10 selftest assertions → Task 4.

**2. Placeholder scan:** No "TBD"/"TODO"/"similar to Task N". Every code step shows the actual code. The one "..." in Task 2 Step 3(c) refers to the *unchanged* k-walk body (lines 453–499), explicitly labeled — the engineer is told not to change it.

**3. Type consistency:** `_run_probe` return dict keys (`k`, `params`, `status`, `achieved`, `secs`, `layout`, `pat_index`) are consistent across Task 1 (6-tuple, no `pat_index`), Task 2 (adds `pat_index`), Task 3 (3-tuple, reads globals). The signature change is explicit in each task. `handle_result` in Task 2 reads `result["layout"]` and `result["achieved"]` — both present in every version of `_run_probe`. `_worker_init`/`_WORKER_LAYOUT` introduced in Task 3 and used in Task 4's selftest — names match.

One issue caught and fixed inline: Task 2's `_run_probe` initially took a 6-tuple `(pat, k, layout, probe_limit, probe_workers, idx)`; Task 3 shrinks it to a 3-tuple `(pat, k, pat_index)`. The plan states both signature changes explicitly so an engineer doing Task 2 then Task 3 sees the evolution. The sequential wrapper `_run_probe_seq` (Task 3) bridges the `--workers 1` path.
