# Newbie app, plan 1 of 4: backend features — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend everything the newbie wizard needs: machine-sized parallelism, city stats, load-time checks (unconnected buildings, loose chain pieces), chain relinking, "keep these off the road", phase reporting, and every legal layout a run finds.

**Architecture:** New small modules (`foeopt/machine.py`, `foeopt/stats.py`, `webapp/collector.py`) plus narrow hooks in existing code: two optional `run()` callbacks (`on_phase`, `on_layout`) on `RoadsFirstSearch`, an `off_road` id set threaded like `military`, and a relink step in `foeopt/editing.py`. The Flask API exposes them; today's webapp keeps working unchanged (all new fields are additive).

**Tech Stack:** Python 3.12, Flask, OR-Tools CP-SAT, pytest. Run tests with `.venv/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-11-24-newbie-desktop-app-design.md`

The other plans, written after this one lands: 2 building-list pipeline (GitHub job + app update), 3 wizard frontend + French/English, 4 desktop packaging + releases.

## Global Constraints

- Buildings never rotate; every published layout goes through the full legality check (`foeopt.legality.check`).
- Nothing leaves the computer (no network calls in this plan).
- Machine check keeps 6 workers x 2 threads on an 8-core / 16-thread CPU and leaves headroom on smaller ones.
- Road efficiency = Σ over connected road-needing buildings of (shorter side × road level ÷ 2), ÷ built road cells, as a percentage.
- Coverage is a % of the unlocked area: buildings, roads, free (free also as a square count).
- "Buildings with roads" = need a road and are connected; "without roads" = don't need one.
- All new API fields are additive; existing endpoints and tests keep passing.
- City files contain player data: tests use synthetic layouts or the existing `require_data` fixtures, never print city contents.

## Review Focus

1. A city with no roads or no road-needing buildings: road efficiency must be `None`, not a crash or division by zero (Task 2 test).
2. `os.cpu_count()` returning `None` or 1: the machine check must still return a runnable setting and warn (Task 1 test).
3. A loose chain piece whose main building is missing, or whose chain has no free slot: leave it in place and report why, never fail the load (Task 4 test).
4. `keep_unconnected` naming ids that an edit removed, or that don't need a road: ignored, not a 400 (Task 5 test).
5. A run stopped in its first second: the result still has a `layouts` list (possibly just the seeded city), never missing (Task 7 test).

---

### Task 1: Machine check

**Files:**
- Create: `foeopt/machine.py`
- Modify: `webapp/app.py` (`api_options`, `api_optimize`)
- Test: `tests/test_machine.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `pick_parallelism(logical_cpus: int | None, mem_gb: float | None = None) -> dict` with keys `workers: int`, `probe_workers: int`, `threads: int`, `logical_cpus: int | None`, `reduced: bool` (threads < 12), `warn: bool`.
- Produces: `machine_info() -> dict` = `pick_parallelism(os.cpu_count(), total_memory_gb())`; `total_memory_gb() -> float | None` (Linux/Mac `os.sysconf`, Windows `ctypes` `GlobalMemoryStatusEx`, `None` on failure).
- Produces: `/api/options` response gains `"machine": machine_info()`.

Rule: `headroom = max(2, n // 4)` if `n > 2` else `1`; `budget = clamp(n - headroom, 1, 12)`; `probe_workers = 2 if budget >= 2 else 1`; `workers = budget // probe_workers`; `warn = n < 4 or (mem_gb is not None and mem_gb < 4)`. `None` CPUs → treat as 2.

- [ ] **Step 1: Write the failing tests** in `tests/test_machine.py`

```python
from foeopt.machine import pick_parallelism

def test_strong_cpu_keeps_today_setting():
    p = pick_parallelism(16)
    assert (p["workers"], p["probe_workers"], p["reduced"], p["warn"]) == (6, 2, False, False)

def test_eight_threads_leaves_headroom():
    assert (pick_parallelism(8)["workers"], pick_parallelism(8)["probe_workers"]) == (3, 2)

def test_four_threads():
    p = pick_parallelism(4)
    assert (p["workers"], p["probe_workers"], p["reduced"], p["warn"]) == (1, 2, True, False)

def test_tiny_or_unknown_machine_still_runs_and_warns():
    for n in (None, 1, 2):
        p = pick_parallelism(n)
        assert p["workers"] >= 1 and p["probe_workers"] >= 1 and p["warn"]

def test_low_memory_warns():
    assert pick_parallelism(16, mem_gb=3.0)["warn"]

def test_never_above_twelve_threads():
    assert pick_parallelism(64)["threads"] == 12
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_machine.py -q` — expected: FAIL (module missing).
- [ ] **Step 3: Implement `foeopt/machine.py`** per the rule above.
- [ ] **Step 4: Add API tests** in `tests/test_api.py`: `GET /api/options` has `machine.workers`; `POST /api/optimize` without `workers`/`probe_workers` submits the machine's values (monkeypatch `foeopt.machine.machine_info` and capture `jobs.submit` kwargs like `test_runner.py` does); a request that sets `workers` explicitly keeps it.
- [ ] **Step 5: Implement in `webapp/app.py`:** after `parse_options`, for each of `workers`, `probe_workers` absent from the request body, use the machine value.
- [ ] **Step 6: Run** `.venv/bin/python -m pytest tests/test_machine.py tests/test_api.py -q` — expected: PASS.
- [ ] **Step 7: Commit** `feat: size the solver to the machine (plan N1 task 1)`.

### Task 2: City stats

**Files:**
- Create: `foeopt/stats.py`
- Modify: `webapp/app.py` (`_parse_and_cache` response), `webapp/runner.py` (`on_improvement` payload)
- Test: `tests/test_stats.py`, `tests/test_api.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `foeopt.validate.unsatisfied(layout) -> list[Building]`, `Layout.occupied_cells()`, `Layout.road_needing()`.
- Produces: `city_stats(layout: Layout) -> dict` with keys `area`, `roads`, `road_efficiency_pct: float | None` (1 decimal), `buildings_pct`, `roads_pct`, `free_pct` (1 decimal each), `free_cells: int`, `with_roads: int`, `without_roads: int`, `unconnected: list[int]` (entity ids, sorted).
- Produces: `/api/load` response gains `"stats"`; every streamed improvement gains `"stats"`.

Definitions: `area = len(region.cells)`; building cells = `occupied_cells() ∩ region`; road cells = `roads ∩ region`; free = area − both. Connected = road-needing and not in `unsatisfied`. Efficiency `None` when roads == 0 or no connected building.

- [ ] **Step 1: Write failing tests** in `tests/test_stats.py` on a hand-built layout (build it with `Building`/`Footprint`/`Region`/`Layout` like `tests/test_editing.py::_city`): a 10×10 region, a 2×3 one-lane building and a 4×4 two-lane-free decoration, 3 road cells connecting the building to the town hall. Assert exact `roads == 3`, `road_efficiency_pct == round(100 * (2*1/2) / 3, 1)`, `free_cells == 100 - occupied - 3`, `with_roads == 1`, `without_roads` counts the decoration, `unconnected == []`. Second test: same city with the roads removed → `road_efficiency_pct is None`, `unconnected == [<building id>]`. Third: a two-lane building counts `min(w,l) * 2 / 2`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_stats.py -q` — expected: FAIL.
- [ ] **Step 3: Implement `city_stats`.**
- [ ] **Step 4: Run** — expected: PASS.
- [ ] **Step 5: Wire it:** `_parse_and_cache` returns `"stats": city_stats(layout)`; runner's `on_improvement` adds `"stats": city_stats(best_layout)`. Add one assertion each to an existing load test in `tests/test_api.py` and to `test_job_manager_submit_and_status` in `tests/test_runner.py` (key present, `roads` is an int).
- [ ] **Step 6: Run** `.venv/bin/python -m pytest tests/test_stats.py tests/test_api.py tests/test_runner.py -q` — PASS.
- [ ] **Step 7: Commit** `feat: city stats (roads, efficiency, coverage, free area)`.

### Task 3: Load-time checks

**Files:**
- Modify: `foeopt/editing.py` (new `loose_chain_pieces`), `webapp/app.py` (`_parse_and_cache`)
- Test: `tests/test_editing.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `city_stats(...)["unconnected"]` (Task 2), `chain_links`, `Catalog.is_chain_head`, `Catalog.chain_id`.
- Produces: `loose_chain_pieces(layout: Layout, catalog: Catalog | None) -> list[int]` — entity ids of non-head chain pieces that are linked to nothing, in a city that also contains a head of the same chain. Empty without a catalog.
- Produces: `/api/load` response gains `"checks": {"unconnected": [ids], "loose_chain_pieces": [ids]}`.

- [ ] **Step 1: Failing tests** in `tests/test_editing.py`, reusing `_city`/`_cat_b`: a patch moved one cell away from its slot is reported; a correctly linked chain reports nothing; a lone patch whose chain has no main in the city is not reported (nothing to link to).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_editing.py -q -k loose` — FAIL.
- [ ] **Step 3: Implement** `loose_chain_pieces`, then add `"checks"` to `_parse_and_cache`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_editing.py tests/test_api.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: report unconnected buildings and loose chain pieces on load`.

### Task 4: Relink loose chain pieces

**Files:**
- Modify: `foeopt/editing.py` (`_Editor.relink_loose`, `apply_edits` parameter), `webapp/app.py` (`_edit_city`, `api_optimize`, `api_edits_preview`)
- Test: `tests/test_editing.py`, `tests/test_api_edits.py`

**Interfaces:**
- Consumes: `loose_chain_pieces` (Task 3); `_Editor.free_slot`, `_Editor.place_for_seed` (the same path `add` uses for a new patch).
- Produces: `apply_edits(layout, remove_ids, add=None, *, relink=None, relink_loose: bool = False)`; the report gains `"relinked": [{"entity_id", "name", "main": <head entity id>}]` and `"relink_failed": [{"entity_id", "name", "reason": "no_free_slot" | "no_main"}]`.
- Produces: `api_optimize` and `api_edits_preview` accept `"relink_chains": bool` (default `true`) and pass it as `relink_loose`; the optimize path must go through `_edit_city` whenever `relink_chains` is true and the city has loose pieces, even with no remove/add edits.

Behavior: each loose piece (ascending entity id) attaches at the free END slot of its chain's main, exactly like an added patch (`add` with `link_to`); several mains of that chain → the lowest entity id with a free slot; the entity id is kept. After relinking, `chains.compose` must see one rigid group.

- [ ] **Step 1: Failing tests** in `tests/test_editing.py`: one loose patch → `relinked` names it, `chain_links(result)` contains its link, `compose(result)` makes one composite; main with no free slot → `relink_failed` reason `no_free_slot` and the piece unchanged; `relink_loose=False` (default) → no change (existing behavior).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_editing.py -q -k relink` — FAIL.
- [ ] **Step 3: Implement** `_Editor.relink_loose()` and the `apply_edits` flag.
- [ ] **Step 4: API tests** in `tests/test_api_edits.py`: preview with `relink_chains` default reports `relinked`; `relink_chains: false` does not.
- [ ] **Step 5: Wire** `webapp/app.py`.
- [ ] **Step 6: Run** `.venv/bin/python -m pytest tests/test_editing.py tests/test_api_edits.py -q` — PASS.
- [ ] **Step 7: Commit** `feat: link loose chain pieces back to their main building`.

### Task 5: Keep chosen buildings off the road

**Files:**
- Modify: `foeopt/legality.py` (`check`), `foeopt/roads_first.py` (`RoadsFirstSearch.__init__`), `webapp/runner.py` (`submit`, `on_improvement`), `webapp/app.py` (`api_optimize`), `foeopt/mutation_polish.py:153`, `foeopt/union_polish.py:158`, `foeopt/roads_first.py:2439` (every `legality_check` call inside the search)
- Test: `tests/test_legality.py`, `tests/test_roads_first_parallel.py` (or a new `tests/test_off_road.py`), `tests/test_api.py`

**Interfaces:**
- Produces: `check(layout, reference, military="connect", off_road: frozenset[int] = frozenset())` — ids in `off_road` are exempt from `no_road` and `two_lane_path`.
- Produces: `RoadsFirstSearch(..., off_road: frozenset[int] = frozenset())` — those buildings get `needs_road=False` before composing, the same way `military="unconnected"` does for two-lane buildings (`roads_first.py` ~2303); stored as `self.off_road` and passed to every internal legality check.
- Produces: `JobManager.submit(..., off_road=frozenset())`; `api_optimize` accepts `"keep_unconnected": [entity ids]`, keeps only ids present in the (edited) city that need a road, passes `off_road`.

- [ ] **Step 1: Failing tests:** legality — an unconnected one-lane building is a `no_road` violation, and valid when its id is in `off_road`; search — a tiny city (see `tests/test_runner.py::_tiny_layout`) with `off_road={id}` returns a layout where that building has no road contact and legality is `valid`; API — `keep_unconnected` with a removed id and a decoration id is accepted (200) and the submitted `off_road` is empty.
- [ ] **Step 2: Run** the three tests — FAIL.
- [ ] **Step 3: Implement** the parameter end to end.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_legality.py tests/test_api.py tests/test_off_road.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: let the player keep chosen buildings off the road`.

### Task 6: Phase reporting

**Files:**
- Modify: `foeopt/roads_first.py` (`run`), `foeopt/profiling.py` (`Profile.timed` gains an optional `on_enter` hook), `webapp/runner.py` (state, `status`)
- Test: `tests/test_profiling.py`, `tests/test_runner.py`

**Interfaces:**
- Produces: `RoadsFirstSearch.run(on_improvement=None, on_status=None, should_stop=None, on_phase=None, on_layout=None)` (`on_layout` is Task 7's). `on_phase(name: str)` is called once when each phase starts, with names from `PHASES = ("seed", "walk", "objective_polish", "union_polish", "rebased_polish", "mutation_polish", "seed_polish", "exact")` exported from `foeopt/roads_first.py`. Hook it where `profile.timed("finish_<name>")` opens (strip the `finish_` prefix) plus `"seed"` before `_seed_from_input` and `"walk"` before the walk.
- Produces: runner status (heartbeat payload) gains `"phase": str | None` and `"layouts_found": int` (Task 7 fills the count; 0 until then).

- [ ] **Step 1: Failing tests:** run a tiny search with `on_phase=seen.append` and assert `seen[0] in ("seed", "walk")`, every name is in `PHASES`, and no name repeats consecutively; runner: a monkeypatched search that calls `on_phase("walk")` then blocks makes `jobs.status(id)["phase"] == "walk"`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_profiling.py tests/test_runner.py -q` — PASS.
- [ ] **Step 5: Commit** `feat: report the current optimizer phase`.

### Task 7: Every legal layout found

**Files:**
- Create: `webapp/collector.py`
- Modify: `foeopt/roads_first.py` (`_result_handler` SAT branch, `_apply_objective_polish`, `_polish_concurrent`, `_apply_exact_finish`, rebased/union/seed polish publish points), `foeopt/mutation_polish.py` (`_Climb.climb` SAT results), `webapp/runner.py`, `webapp/app.py` (`api_stream`)
- Test: `tests/test_collector.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `on_layout` from Task 6's `run()` signature.
- Produces: `on_layout(layout: Layout, k: int | None, achieved: int)` is called for **every** validated layout at the sites listed above, before the strict-improvement test (the search stores it as `self._on_layout`; `polish_mutation` reads it from `search`). The seeded input city is not reported (the UI shows it separately).
- Produces: `LayoutCollector(reference: Layout, *, military: str, off_road: frozenset[int], cap: int = 30)` with `offer(layout, k, achieved) -> dict | None` (returns the stored entry when kept: legal, not a duplicate, and among the `cap` lowest road counts; else `None`), `entries() -> list[dict]` sorted by `(roads, order found)`, `count: int`. Entry = `{"id": int, "k", "achieved", "stats": city_stats(...), "legality": ..., **layout_to_dict(layout)}`. Duplicate = same road cell set and same building positions. Legality is checked only for layouts that would be admitted.
- Produces: SSE event `layout` per kept entry; the `done` result gains `"layouts": entries()`; status `layouts_found = count`.

- [ ] **Step 1: Failing tests** in `tests/test_collector.py`: an illegal layout is refused; the same layout offered twice is stored once; with `cap=2`, offering 5, 3, 4 roads keeps 3 and 4, then offering 6 returns `None`; `entries()` is sorted.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_collector.py -q` — FAIL.
- [ ] **Step 3: Implement `LayoutCollector`.**
- [ ] **Step 4: Runner tests:** a tiny real run's result has `layouts` with at least the final best and every entry's `legality.status == "valid"`; a run stopped immediately (`jobs.stop` right after submit) still has a `layouts` key.
- [ ] **Step 5: Wire** the search hooks, runner and stream.
- [ ] **Step 6: Run** `.venv/bin/python -m pytest tests/test_collector.py tests/test_runner.py tests/test_webapp.py -q` — PASS.
- [ ] **Step 7: Measure** one FR16 120 s run via the bench (`scripts/bench.py run --name n1 --arm preset --cities FR16 --box 120 --reps 1`, holding the bench lock): best roads must be within the usual noise of the preset (66–68) and the run log must show no slowdown from collection (`first=` time and `wall=` unchanged); report `layouts_found`.
- [ ] **Step 8: Commit** `feat: keep every legal layout a run finds`.

### Task 8: Full verification

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` — all pass (known flaky: `test_lns` determinism; rerun alone if it fails).
- [ ] **Step 2:** `cd frontend && npx vitest run && npx tsc --noEmit -p .` — pass (the current webapp ignores the new fields).
- [ ] **Step 3:** Start the webapp, load a city, run 60 s, and confirm the stream carries `phase`, `layouts_found`, `stats`, and the `done` result has `layouts`.
- [ ] **Step 4:** Add a review section to `tasks/todo.md`; commit `docs: plan N1 review`.
