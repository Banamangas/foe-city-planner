# FoE Optimizer — Articulation-Aware Prune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `router._prune` ~6× faster by replacing the per-trial connectivity BFS (O(roads²)) with a single Tarjan articulation-point pass (O(roads)), producing the same road network.

**Architecture:** Add `_articulation_points(roads, th_border)` (iterative Tarjan over the road graph + a virtual Townhall root) to `foeopt/router.py`, then rewrite `_prune` to remove only non-articulation cells whose removal keeps every adjacent consumer covered. `route()`'s signature and output are unchanged; this is a pure internal speedup verified to produce identical cells on the real cities.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Touches only `foeopt/router.py` and its tests.

## Global Constraints

- Python **3.12**; standard library only; dev dep `pytest`. Test runner: `uv run pytest`.
- **Behavior-preserving + guard:** the new prune must produce the same result as the current one where it matters. Guards: existing `tests/test_router.py` small-grid tests stay green; real-city golden counts stay green (`route(darkzig)` == 236, `route(sample)` == 142); a validity property test; and a one-time set-equality verification vs the old prune on both real cities (recorded, before removing old code). If a future input ever differs, the result must still be valid with road count ≤ the old prune's.
- No change to `route()`'s signature/output, `validate`, or any public API.
- Coordinates are `(x, y)` int tuples; `_ORTHO` and `deque` already exist in `router.py`.

---

### Task 1: `_articulation_points` (Tarjan over roads + virtual Townhall root)

**Files:**
- Modify: `foeopt/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Produces: `_articulation_points(roads: dict[tuple[int,int],int], th_border: set[tuple[int,int]]) -> set[tuple[int,int]]` — the set of road cells whose removal would disconnect another road cell from the Townhall. Uses a virtual root connected to the road cells in `th_border`. The virtual root is never returned. `{}`/single-cell inputs return `set()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_router.py`:
```python
from foeopt.router import _articulation_points


def test_articulation_midchain_is_cut_vertex():
    # townhall root borders (0,0); chain (0,0)-(1,0)-(2,0). Removing (1,0)
    # disconnects (2,0) from the root -> (1,0) is an articulation point.
    roads = {(0, 0): 1, (1, 0): 1, (2, 0): 1}
    th_border = {(0, 0)}      # a road at (0,0) is the rooted entry
    art = _articulation_points(roads, th_border)
    assert (1, 0) in art
    assert (2, 0) not in art   # leaf, not a cut vertex
    assert (0, 0) in art       # removing it disconnects (1,0),(2,0)


def test_articulation_leaf_not_cut():
    # star-ish: (0,0) root, (1,0) hub, (2,0) and (1,1) leaves off the hub
    roads = {(0, 0): 1, (1, 0): 1, (2, 0): 1, (1, 1): 1}
    art = _articulation_points(roads, {(0, 0)})
    assert (2, 0) not in art and (1, 1) not in art   # leaves
    assert (1, 0) in art                              # hub is a cut vertex


def test_articulation_cycle_no_cut():
    # a 2x2 loop of roads, all rooted via (0,0); no single removal disconnects.
    roads = {(0, 0): 1, (1, 0): 1, (0, 1): 1, (1, 1): 1}
    art = _articulation_points(roads, {(0, 0)})
    assert art == set()


def test_articulation_empty():
    assert _articulation_points({}, set()) == set()
    assert _articulation_points({(0, 0): 1}, {(0, 0)}) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_router.py -k articulation -v`
Expected: FAIL (`cannot import name '_articulation_points'`).

- [ ] **Step 3: Write the implementation**

Add to `foeopt/router.py` (after `_bfs_path`, before `route`):
```python
def _articulation_points(
    roads: dict[tuple[int, int], int], th_border: set[tuple[int, int]]
) -> set[tuple[int, int]]:
    """Road cells whose removal disconnects another road cell from the Townhall.

    Iterative Tarjan over the road graph plus a virtual root connected to the
    road cells bordering the Townhall. The virtual root is never returned.
    """
    if len(roads) <= 1:
        return set()

    root = ("__townhall_root__",)  # sentinel distinct from any (x, y) cell
    adj: dict[object, list[object]] = {}
    for c in roads:
        cx, cy = c
        adj[c] = [(cx + dx, cy + dy) for dx, dy in _ORTHO
                  if (cx + dx, cy + dy) in roads]
    roots = [c for c in roads if c in th_border]
    adj[root] = list(roots)
    for c in roots:
        adj[c] = adj[c] + [root]

    disc: dict[object, int] = {}
    low: dict[object, int] = {}
    art: set[tuple[int, int]] = set()
    timer = 0
    root_children = 0

    stack: list[tuple[object, object, object]] = [(root, None, iter(adj[root]))]
    disc[root] = low[root] = timer
    timer += 1
    while stack:
        node, parent, it = stack[-1]
        advanced = False
        for nb in it:
            if nb == parent:
                continue
            if nb in disc:
                low[node] = min(low[node], disc[nb])
            else:
                if node == root:
                    root_children += 1
                disc[nb] = low[nb] = timer
                timer += 1
                stack.append((nb, node, iter(adj[nb])))
                advanced = True
                break
        if not advanced:
            stack.pop()
            if stack:
                p = stack[-1][0]
                low[p] = min(low[p], low[node])
                if p != root and stack[-1][1] is not None and low[node] >= disc[p]:
                    art.add(p)
    if root_children > 1:
        art.add(root)
    art.discard(root)
    return art
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_router.py -k articulation -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add foeopt/router.py tests/test_router.py
git commit -m "feat(router): articulation-point detection over road graph"
```

---

### Task 2: Rewrite `_prune` to use articulation points

**Files:**
- Modify: `foeopt/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `_articulation_points`, `deque`, `_ORTHO`, `layout.road_needing()`, `Footprint.border_cells()`.
- Produces: `_prune(layout, roads)` — same signature and result as before, faster. A cell is removable iff it is not an articulation point AND no consumer adjacent to it loses its only connected, sufficient-level road. Deterministic removal order (`sorted(roads, reverse=True)`, first removable, restart pass).

- [ ] **Step 1: Capture the current route() output for the set-equality verification**

Before changing `_prune`, record the exact pruned road sets so the rewrite can be checked against them. Run this scratch (writes to `/tmp`; not committed):
```bash
uv run python -c "
import json
from foeopt.loader import load_layout
from foeopt.router import route
for name, L in [('darkzig', load_layout('darkzig.json')),
                ('sample', load_layout('city-user-data.json','city-user-data-foe-helper.json'))]:
    cells = sorted([list(k)+[v] for k,v in route(L).items()])
    json.dump(cells, open(f'/tmp/prune_before_{name}.json','w'))
    print(name, len(cells))
"
```
Expected: `darkzig 236`, `sample 142`.

- [ ] **Step 2: Write the failing property test**

Add to `tests/test_router.py`:
```python
def test_prune_real_city_output_is_valid(city_data, helper_data):
    from foeopt.build import build_layout
    from foeopt.validate import unsatisfied
    from foeopt.model import Layout
    layout = build_layout(city_data, helper_data)
    roads = route(layout)
    probe = Layout(layout.region, layout.buildings, layout.townhall, roads)
    assert unsatisfied(probe) == []        # every consumer connected & covered
    assert len(roads) == 142               # golden count preserved
```
(This passes against the current code too; it is the behavior-preserving guard that must remain green after the rewrite. The genuine RED for this task is the Step 5 set-equality verification, which only holds once the rewrite is correct.)

- [ ] **Step 3: Run the property test (baseline)**

Run: `uv run pytest tests/test_router.py::test_prune_real_city_output_is_valid -v`
Expected: PASS (against current code).

- [ ] **Step 4: Rewrite `_prune`**

Replace the body of `_prune` in `foeopt/router.py` with:
```python
def _prune(
    layout: Layout,
    roads: dict[tuple[int, int], int],
) -> dict[tuple[int, int], int]:
    """Remove redundant road cells, keeping every consumer connected & covered.

    Building positions are fixed during pruning, so consumer borders and the
    Townhall border are computed once. Each pass finds all articulation points
    in one O(roads) Tarjan pass; only a non-articulation cell can be removed
    without disconnecting another road, so we never run a per-cell connectivity
    BFS. Same deterministic removal order and result as the prior implementation.
    """
    th_border = (
        layout.townhall.footprint.border_cells() if layout.townhall is not None else set()
    )
    consumers = [
        (b.footprint.border_cells(), b.road_level) for b in layout.road_needing()
    ]

    def connected(rd: dict[tuple[int, int], int]) -> set[tuple[int, int]]:
        seen = {c for c in rd if c in th_border}
        queue: deque[tuple[int, int]] = deque(seen)
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in _ORTHO:
                n = (cx + dx, cy + dy)
                if n in rd and n not in seen:
                    seen.add(n)
                    queue.append(n)
        return seen

    roads = dict(roads)
    changed = True
    while changed:
        changed = False
        art = _articulation_points(roads, th_border)
        conn = connected(roads)
        for cell in sorted(roads, reverse=True):
            if cell in art:
                continue  # removing it would disconnect another road from the Townhall
            # Non-articulation: every other road stays connected. The cell itself
            # disappears, so each consumer bordering it must keep another covered road.
            ok = True
            for border, level in consumers:
                if cell in border and not any(
                    c != cell and c in conn and roads.get(c, 0) >= level for c in border
                ):
                    ok = False
                    break
            if ok:
                del roads[cell]
                changed = True
                break
    return roads
```

- [ ] **Step 5: Verify set-equality vs the captured (old) output, then run the suites**

Run the set-equality check against Step 1's capture:
```bash
uv run python -c "
import json
from foeopt.loader import load_layout
from foeopt.router import route
for name, L in [('darkzig', load_layout('darkzig.json')),
                ('sample', load_layout('city-user-data.json','city-user-data-foe-helper.json'))]:
    now = sorted([list(k)+[v] for k,v in route(L).items()])
    before = json.load(open(f'/tmp/prune_before_{name}.json'))
    print(name, 'identical:', now == before, '| count', len(now))
    assert now == before, f'{name} prune output changed!'
print('SET-EQUALITY VERIFIED')
"
```
Expected: `darkzig identical: True`, `sample identical: True`, `SET-EQUALITY VERIFIED`. **Record this output in the task report.**

Then run the full router suite and the whole suite:
```bash
uv run pytest tests/test_router.py -v
uv run pytest -q
```
Expected: all PASS — small-grid tests (straight line = 3, shared corridor ≤ 4, level-2, unreachable → RouteError), the new property test, and golden counts unchanged.

- [ ] **Step 6: Confirm the speedup (record, not a test)**

Run:
```bash
uv run python -c "
import time
from foeopt.loader import load_layout
from foeopt.router import route
L = load_layout('darkzig.json')
route(L)  # warm
t = time.time(); route(L); print('darkzig route(): %.0f ms' % ((time.time()-t)*1000))
"
```
Expected: ~10ms (down from ~60ms). Record in the report.

- [ ] **Step 7: Commit**

```bash
git add foeopt/router.py tests/test_router.py
git commit -m "perf(router): articulation-aware prune (O(roads)/pass, ~6x faster route)"
```

---

## Self-Review

**Spec coverage:**
- `_articulation_points` helper (spec §3/§4) → Task 1. ✓
- `_prune` rewrite using articulation + cheap consumer check, same order/result (spec §4) → Task 2. ✓
- Behavior-preserving + guard (spec §5): existing router small-grid tests (untouched, run in Task 2 Step 5); golden counts 236/142 (property test + the route goldens); validity property test (Task 2 Step 2); one-time set-equality verification vs captured old output (Task 2 Steps 1 & 5, recorded). ✓
- route()/validate/public API unchanged (spec §3) → only `_prune` body + new private helper. ✓
- Testing: articulation unit tests (cut vertex, leaf, cycle, empty), validity property, real-city goldens (spec §6) → Tasks 1–2. ✓
- Payoff confirmation (route ~10ms) (spec §6) → Task 2 Step 6 (recorded). ✓

**Placeholder scan:** No placeholders; both tasks have complete code. Task 2's RED is honestly characterized: the property test passes against old code (it's the green-must-stay guard), and the genuine correctness gate is the Step 5 set-equality verification, which only holds when the rewrite is correct.

**Type consistency:** `_articulation_points(roads, th_border) -> set[(x,y)]` defined in Task 1, consumed in Task 2's `_prune`. `_prune(layout, roads) -> dict[(x,y)->level]` signature unchanged. `connected()` is a local helper mirroring the existing `validate.connected_road_cells` semantics (BFS from Townhall-bordering road cells). `_ORTHO`/`deque` already imported in `router.py`.
