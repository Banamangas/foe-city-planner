# FoE Optimizer — Polish Pipeline (repack → anneal) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower `layout` road counts by refining the packer's output with annealing — a `polish` (repack → anneal) path exposed in the CLI and web UI (DarkZig ~158 → ~151).

**Architecture:** A pure `foeopt/polish.py` wiring `repack` → `anneal` into a `PackResult`. The CLI `layout` gains `--polish`/`--anneal-budget`; the web runner's `run_repack`/`run_sweep` gain an `anneal_budget` arg; the page gains a polish toggle + anneal-budget field.

**Tech Stack:** Python 3.12, `uv`, `pytest`, Flask (already a dep). Reuses `repack`, `anneal`, `route`, `road_estimate`, `is_valid`, `render_html`.

## Global Constraints

- Python **3.12**; `uv run pytest`. No new dependencies.
- `repack(layout, *, thorough=False, budget_seconds=None, seed=0) -> PackResult(layout, unplaced, trials)`.
- `anneal(layout, *, seed=0, budget_seconds=30.0, max_iters=1_000_000) -> OptimizeResult(layout, moves_applied)`; its `best` is anchored at the input and only replaced by a valid layout with strictly fewer roads (never worse), and it never drops buildings.
- `route(layout) -> dict`; `road_estimate(layout) -> int`; `is_valid(layout) -> bool`.
- Determinism is inherited from `repack`/`anneal` ("deterministic given seed and iterations completed"); time-based budgets make strict cross-run road-equality flaky, so tests assert the robust invariants (valid, unplaced preserved, never-worse) instead.
- Web state is single-user in-memory; jobs run in background threads (existing `JobManager`).

---

### Task 1: `foeopt/polish.py`

**Files:**
- Create: `foeopt/polish.py`
- Test: `tests/test_polish.py`

**Interfaces:**
- Produces: `polish(layout, *, repack_budget: float, anneal_budget: float, seed: int = 0) -> PackResult`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_polish.py`:
```python
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.packer import repack
from foeopt.polish import polish
from foeopt.validate import is_valid


def _sparse_city():
    th = Building(1, "c1", "t", Footprint(0, 0, 2, 2), False, 0, True, None, None, "TH")
    cons = [Building(10 + i, f"r{i}", "t", Footprint(0, 0, 2, 2), True, 1, False, None, None, f"r{i}")
            for i in range(4)]
    fill = [Building(20 + i, f"f{i}", "t", Footprint(0, 0, 1, 1), False, 0, False, None, None, f"f{i}")
            for i in range(4)]
    region = Region(frozenset({(x, y) for x in range(20) for y in range(20)}))
    return Layout(region, [th, *cons, *fill], th)


def test_polish_valid_and_places_all():
    L = _sparse_city()
    res = polish(L, repack_budget=0.3, anneal_budget=0.5, seed=0)
    assert res.unplaced == []
    assert is_valid(res.layout)
    assert len(res.layout.buildings) == len(L.buildings)   # conservation


def test_polish_never_worse_than_repack():
    L = _sparse_city()
    base = repack(L, budget_seconds=0.3, seed=0)
    res = polish(L, repack_budget=0.3, anneal_budget=0.5, seed=0)
    # sparse city -> repack reaches the minimal tree; anneal can only match it
    assert len(res.layout.roads) <= len(base.layout.roads)


def test_polish_preserves_unplaced():
    L = _sparse_city()
    base = repack(L, budget_seconds=0.3, seed=0)
    res = polish(L, repack_budget=0.3, anneal_budget=0.3, seed=0)
    assert len(res.unplaced) == len(base.unplaced)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_polish.py -v`
Expected: FAIL (`No module named 'foeopt.polish'`).

- [ ] **Step 3: Implement `polish`**

Create `foeopt/polish.py`:
```python
from __future__ import annotations

from foeopt.anneal import anneal
from foeopt.model import Layout
from foeopt.packer import PackResult, repack
from foeopt.router import route


def polish(layout: Layout, *, repack_budget: float, anneal_budget: float,
           seed: int = 0) -> PackResult:
    """Re-pack, then refine with annealing (building-move SA).

    Anneal never drops a building and never accepts a worse-than-best layout, so
    the result has the same `unplaced` as the repack base and roads <= the base.
    """
    base = repack(layout, budget_seconds=repack_budget, seed=seed)
    refined = anneal(base.layout, budget_seconds=anneal_budget, seed=seed)
    final = Layout(layout.region, refined.layout.buildings,
                   refined.layout.townhall, route(refined.layout))
    return PackResult(layout=final, unplaced=base.unplaced, trials=base.trials)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_polish.py -v`
Expected: PASS (3 tests). Then `uv run pytest -q` — full suite green.

- [ ] **Step 5: Record the DarkZig payoff (not a suite test)**

```bash
uv run python -c "
from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.polish import polish
from foeopt.validate import is_valid
L = load_layout('darkzig.json')
b = repack(L, budget_seconds=30, seed=0)
p = polish(L, repack_budget=30, anneal_budget=240, seed=0)
print('repack', len(b.layout.roads), '-> polish', len(p.layout.roads),
      '| unplaced', len(p.unplaced), '| valid', is_valid(p.layout))
"
```
Expected: polish roads **< repack roads** (≈158→~151), 0 unplaced, valid. Record in the report.

- [ ] **Step 6: Commit**

```bash
git add foeopt/polish.py tests/test_polish.py
git commit -m "feat(polish): repack-then-anneal pipeline"
```

---

### Task 2: CLI `layout --polish`

**Files:**
- Modify: `foeopt/cli.py`
- Test: `tests/test_layout_cli.py`

**Interfaces:**
- Consumes: `polish`, `_resolve_budget`, `repack`, `road_estimate`, `render_comparison`.
- Produces: `layout` accepts `--polish` (flag) and `--anneal-budget` (float, default 120.0); `_cmd_layout` runs polish when set, else repack.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_layout_cli.py`:
```python
def test_layout_cli_accepts_polish_flags():
    from foeopt.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["layout", "city.json", "--polish", "--anneal-budget", "0.2"])
    assert args.polish is True
    assert args.anneal_budget == 0.2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_layout_cli.py::test_layout_cli_accepts_polish_flags -v`
Expected: FAIL (unrecognized `--polish`).

- [ ] **Step 3: Wire the CLI**

In `foeopt/cli.py`: add `from foeopt.polish import polish` to the imports. On the `layout` subparser (next to its `--budget`/`--seed`), add:
```python
    p_layout.add_argument("--polish", action="store_true",
                          help="refine the re-pack with annealing (lower roads)")
    p_layout.add_argument("--anneal-budget", type=float, default=120.0,
                          help="seconds for the anneal phase when --polish (default 120)")
```
In `_cmd_layout`, replace the `res = repack(...)` line with:
```python
    rbudget = _resolve_budget(args.budget, args.thorough)
    if args.polish:
        base = repack(current, budget_seconds=rbudget, seed=args.seed)
        res = polish(current, repack_budget=rbudget, anneal_budget=args.anneal_budget, seed=args.seed)
        print(f"  polished roads: {len(base.layout.roads)} -> {len(res.layout.roads)}")
    else:
        res = repack(current, budget_seconds=rbudget, seed=args.seed)
```
(Keep the existing placed/unplaced/roads/estimate prints and the `render_comparison` write below this.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_layout_cli.py -v` then `uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/test_layout_cli.py
git commit -m "feat(cli): layout --polish/--anneal-budget"
```

---

### Task 3: Web backend — `anneal_budget` in runners + `/run`

**Files:**
- Modify: `webapp/runner.py`, `webapp/app.py`
- Test: `tests/test_runner.py`, `tests/test_webapp.py`

**Interfaces:**
- Produces: `run_repack(layout, *, budget, seed, anneal_budget=0.0) -> dict` and `run_sweep(layout, *, budget, seeds, workers, anneal_budget=0.0) -> dict`, where the dict gains `base_roads` (pre-anneal). `/run` reads `polish`/`anneal_budget` and passes `anneal_budget` through.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_runner.py`:
```python
def test_run_repack_polish_not_worse_and_reports_base():
    from webapp.runner import run_repack
    res = run_repack(_sparse_city(), budget=0.3, seed=0, anneal_budget=0.4)
    assert res["unplaced"] == 0 and res["valid"] is True
    assert "base_roads" in res
    assert res["roads"] <= res["base_roads"]   # anneal never worse
```
(`_sparse_city` already exists in `tests/test_runner.py`.)

Add to `tests/test_webapp.py`:
```python
def test_run_with_polish(client, repo_root):
    import time
    with open(repo_root / CITY, "rb") as cf, open(repo_root / HELPER, "rb") as hf:
        client.post("/load", data={"city": (cf, CITY), "helper": (hf, HELPER)},
                    content_type="multipart/form-data")
    r = client.post("/run", json={"remove_ids": [], "add_specs": [], "mode": "repack",
                                  "budget": 0.3, "seed": 0, "polish": True, "anneal_budget": 0.3})
    jid = r.get_json()["job_id"]
    for _ in range(200):
        st = client.get(f"/status/{jid}").get_json()
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["state"] == "done", st
    assert st["result"]["roads"] <= st["result"]["base_roads"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_runner.py -k polish tests/test_webapp.py -k polish -v`
Expected: FAIL (`run_repack` has no `anneal_budget`; no `base_roads`).

- [ ] **Step 3: Implement**

In `webapp/runner.py`, add imports `from foeopt.anneal import anneal`, `from foeopt.router import route`, `from foeopt.model import Layout`. Add a helper and thread `anneal_budget` through:
```python
def _anneal_base(layout, packed, anneal_budget, seed):
    """Return a PackResult refined by annealing (or the base unchanged)."""
    if anneal_budget <= 0:
        return packed, len(packed.layout.roads)
    base_roads = len(packed.layout.roads)
    refined = anneal(packed.layout, budget_seconds=anneal_budget, seed=seed)
    final = Layout(layout.region, refined.layout.buildings,
                   refined.layout.townhall, route(refined.layout))
    from foeopt.packer import PackResult
    return PackResult(final, packed.unplaced, packed.trials), base_roads


def run_repack(layout, *, budget, seed, anneal_budget=0.0):
    packed, base_roads = _anneal_base(layout, repack(layout, budget_seconds=budget, seed=seed),
                                      anneal_budget, seed)
    d = _result(layout, packed)
    d["base_roads"] = base_roads
    return d
```
For `run_sweep`, after selecting `winner` (the best `PackResult`), apply the same anneal + `base_roads`:
```python
def run_sweep(layout, *, budget, seeds, workers, anneal_budget=0.0):
    tasks = [(layout, budget, s) for s in range(seeds)]
    results = []
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        for r in ex.map(_sweep_one, tasks):
            results.append(r)
    ok = [r for r in results if r[2] == 0]
    winner = min(ok, key=lambda r: r[1]) if ok else min(results, key=lambda r: (r[2], r[1]))
    packed, base_roads = _anneal_base(layout, winner[3], anneal_budget, 0)
    d = _result(layout, packed)
    d["base_roads"] = base_roads
    return d
```
(Keep `_result` unchanged; just attach `base_roads` after. For non-polish calls `base_roads == roads`.)

In `webapp/app.py` `/run`, compute the anneal budget and pass it:
```python
        anneal_budget = float(data.get("anneal_budget", 0)) if data.get("polish") else 0.0
        if mode == "sweep":
            seeds = int(data.get("seeds", 8))
            workers = int(data.get("workers", os.cpu_count() or 1))
            job_id = jobs.submit(lambda: run_sweep(edited, budget=budget, seeds=seeds,
                                                   workers=workers, anneal_budget=anneal_budget))
        else:
            seed = int(data.get("seed", 0))
            job_id = jobs.submit(lambda: run_repack(edited, budget=budget, seed=seed,
                                                    anneal_budget=anneal_budget))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_runner.py tests/test_webapp.py -v` then `uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add webapp/runner.py webapp/app.py tests/test_runner.py tests/test_webapp.py
git commit -m "feat(webapp): optional anneal polish in run_repack/run_sweep"
```

---

### Task 4: Web frontend — polish toggle

**Files:**
- Modify: `webapp/static/index.html`, `webapp/static/app.js`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: the `/run` `polish`/`anneal_budget` fields and the result `base_roads` from Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_webapp.py`:
```python
def test_index_has_polish_control(client):
    assert b'id="polish"' in client.get("/").data
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_webapp.py::test_index_has_polish_control -v`
Expected: FAIL (no polish control yet).

- [ ] **Step 3: Add the controls**

In `webapp/static/index.html`, inside the Run panel (after the seed/seeds spans, before the Run button), add:
```html
    <label><input type="checkbox" id="polish"> polish (anneal)</label>
    <span id="polish-opts" hidden><label>anneal budget (s) <input type="number" id="anneal-budget" value="120" min="1"></label></span>
```

In `webapp/static/app.js`:
- After the `$("mode").onchange` handler, add:
```javascript
$("polish").onchange = () => { $("polish-opts").hidden = !$("polish").checked; };
```
- In the `$("run-btn").onclick` request `body`, add two fields:
```javascript
    polish: $("polish").checked,
    anneal_budget: +$("anneal-budget").value,
```
- In `poll`, when showing the result stats, reflect the polish gain — replace the `$("stats").textContent = ...` line with:
```javascript
  const gain = (res.base_roads != null && res.base_roads !== res.roads) ? ` (from ${res.base_roads})` : "";
  $("stats").textContent = `placed ${res.placed} · unplaced ${res.unplaced} · roads ${res.roads}${gain} (est ${res.estimate}) · ${res.valid ? "valid" : "partial"}`;
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_webapp.py -v` then `uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Manual smoke (record, not a suite test)**

```bash
uv run python -m webapp.app &
sleep 2
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:5000/
kill %1
```
Expected: `GET / -> 200`. Note in the report: open the page, load `darkzig.json`, check **polish (anneal)**, set a short anneal budget, Run, confirm `roads R (from R0)` shows the gain.

- [ ] **Step 6: Commit**

```bash
git add webapp/static/index.html webapp/static/app.js tests/test_webapp.py
git commit -m "feat(webapp): polish (anneal) toggle in the run panel"
```

---

## Self-Review

**Spec coverage:**
- `polish(layout, *, repack_budget, anneal_budget, seed)` wiring repack→anneal, never-worse, unplaced preserved, roads via route() (spec §4) → Task 1. ✓
- CLI `--polish`/`--anneal-budget`, prints the gain (spec §5) → Task 2. ✓
- Web `run_repack`/`run_sweep` gain `anneal_budget`, result `base_roads`, `/run` passthrough (spec §6) → Task 3. ✓
- Web run panel polish checkbox + anneal-budget field + result gain display (spec §6) → Task 4. ✓
- Testing: polish invariants (valid/conservation/never-worse/unplaced), CLI arg wiring, runner polish + base_roads, web /run polish, served-page control, existing green, recorded DarkZig (spec §7) → Tasks 1–4. ✓
- Determinism caveat (time-based budgets → assert invariants not strict equality) honored in the tests. ✓

**Placeholder scan:** No placeholders; all code complete. The two recorded checks (Task 1 Step 5, Task 4 Step 5) are explicit measurements.

**Type consistency:** `polish(...) -> PackResult` (Task 1). `run_repack/run_sweep(..., anneal_budget=0.0) -> dict` with `base_roads` (Task 3) read by the frontend `res.base_roads` (Task 4). `/run` accepts `polish`/`anneal_budget` (Task 3) sent by `app.js` (Task 4). `anneal(layout, *, seed, budget_seconds) -> OptimizeResult(.layout)`, `repack(...) -> PackResult(.layout,.unplaced,.trials)`, `route(layout)->dict` used consistently. `_resolve_budget(args.budget, args.thorough)` reused in `_cmd_layout`.
