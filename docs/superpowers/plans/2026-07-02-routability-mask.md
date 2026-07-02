# Routability-Preserving Placement Mask — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An exact, fast `placement_is_safe` guarantee — no placement may cut free space off from the road-network origin or seal a placed consumer — wired into the packer (flag-gated) and the RL env, then A/B-measured.

**Architecture:** One pure-stdlib module `foeopt/reach.py`: an exact predicate (`placement_is_safe`, the oracle) plus a per-step accelerator (`ReachChecker`) whose fast path is a local band check with a full-BFS fallback, equivalence-tested against the oracle. Consumers: `first_fit`/`first_fit_adjacent` gain an anchor filter, `build_candidate`/`repack` gain `safe_placements` (default **off** until the A/B gate passes), `PlacementEnv.valid_actions` gains `safe=`.

**Tech Stack:** Python 3.12 stdlib only, pytest.

Spec: `docs/superpowers/specs/2026-07-02-routability-mask-design.md`.

## Global Constraints

- `foeopt/` stays **pure-stdlib**; no new dependencies.
- **Exactness contract:** `ReachChecker.is_safe` must equal `placement_is_safe` on every query — enforced by a randomized oracle-equivalence test (golden-oracle discipline, as in Task A).
- **Default-off:** `safe_placements=False` everywhere until the §5 spec gates pass (0-unplaced-budget A/B, ≥8 seeds, throughput regression < ~30%). Flipping the default is NOT part of this plan.
- **Determinism:** the mask is a pure function of state; packer/env determinism (given seed/config) must be unchanged.
- **Benchmark discipline:** compare only 0-unplaced results; benchmark on darkzig + real-like fills, never the 97%-full bundled city.

---

## File Structure

| file | role | task |
|---|---|---|
| `docs/superpowers/specs/2026-07-02-routability-mask-design.md` | spec amendment: guarded-borders condition | T1 |
| `foeopt/reach.py` | NEW: `placement_is_safe` + `ReachChecker` | T1, T2 |
| `tests/test_reach.py` | NEW: hand cases + oracle equivalence | T1, T2 |
| `foeopt/rlenv.py` | `valid_actions(safe=)` | T3 |
| `tests/test_rlenv.py` | safe-mode tests (append) | T3 |
| `foeopt/packing.py` | `ok=` anchor filter on `first_fit`/`first_fit_adjacent` | T4 |
| `foeopt/packer.py` | `safe_placements` on `build_candidate`/`repack` | T4 |
| `foeopt/cli.py` | `--safe-placements` on the `layout` command | T4 |
| `tests/test_packing.py`, `tests/test_packer.py` | filter + flag tests (append) | T4 |
| `scripts/exp_safe_ab.py` | NEW: A/B measurement harness | T5 |
| `tasks/lessons.md` | A/B results entry | T5 |

---

## Task 1: Exact predicate `placement_is_safe` (+ spec amendment)

Planning found a hole in the committed spec: free-space connectivity alone does **not** guarantee routability — later placements can seal all border cells of an already-placed consumer while free space stays connected elsewhere. The fix is a second condition: every guarded border set (placed consumers + Townhall) must keep ≥ 1 free cell. With condition (1) making all remaining free cells source-reachable, "≥ 1 free border cell" is automatically "≥ 1 *reachable* free border cell", which is what `route()` needs. Amend the spec, then implement the exact predicate.

**Files:**
- Modify: `docs/superpowers/specs/2026-07-02-routability-mask-design.md` (§2)
- Create: `foeopt/reach.py`
- Test: `tests/test_reach.py`

**Interfaces:**
- Produces (used by every later task):
  - `placement_is_safe(free: set[tuple[int,int]] | frozenset, footprint_cells, sources, guarded=()) -> bool` — exact oracle. `sources`: cells the network roots at/along (Townhall footprint cells, or the packer's road set — need not be free cells). `guarded`: iterable of cell-sets, each of which must retain ≥ 1 cell in the remaining free set.
  - `_reachable(free, sources) -> set` — module-private BFS helper (`ReachChecker` reuses it in T2).

- [ ] **Step 1: Amend the spec**

In `docs/superpowers/specs/2026-07-02-routability-mask-design.md`, replace the §2 code block and the sentence after it:

```python
def placement_is_safe(free: set[Cell], footprint_cells: frozenset[Cell],
                      sources: set[Cell]) -> bool
```

```
True **iff** after removing `footprint_cells` from `free`, every remaining
orthogonally-connected free component contains at least one cell of (or
orthogonally adjacent to) `sources`.
```

with:

```python
def placement_is_safe(free: set[Cell], footprint_cells: frozenset[Cell],
                      sources: set[Cell], guarded: Iterable[frozenset[Cell]] = ()) -> bool
```

```
True **iff** after removing `footprint_cells` from `free`: (1) every remaining
orthogonally-connected free component contains at least one cell of (or
orthogonally adjacent to) `sources`, AND (2) every cell-set in `guarded` — the
border cells of already-placed road-needing buildings and the Townhall — still
intersects the remaining free set. Condition (2) closes the sealing hole:
free-space connectivity alone cannot stop later placements from occupying every
border cell of a placed consumer; given (1), one surviving free border cell is
automatically a *reachable* one, which is exactly what route() needs.
```

- [ ] **Step 2: Write the failing hand-case tests**

Create `tests/test_reach.py`:

```python
import random

from foeopt.reach import placement_is_safe


def _rect(x, y, w, l):
    return frozenset((x + dx, y + dy) for dx in range(w) for dy in range(l))


def _grid(w, h):
    return {(x, y) for x in range(w) for y in range(h)}


def test_open_space_is_safe():
    free = _grid(8, 8)
    assert placement_is_safe(free, _rect(3, 3, 2, 2), sources={(0, 0)})


def test_one_wide_corridor_severed_is_unsafe():
    # corridor y=0, x=0..7; a 1x1 at (3,0) splits it; right half loses the source
    free = {(x, 0) for x in range(8)}
    assert not placement_is_safe(free, _rect(3, 0, 1, 1), sources={(-1, 0)})


def test_two_wide_corridor_severed_by_2x2_is_unsafe():
    # THE articulation counter-example: no single cell of the 2x2 is an
    # articulation point, yet the pair severs the 2-wide corridor.
    free = {(x, y) for x in range(8) for y in range(2)}
    assert not placement_is_safe(free, _rect(3, 0, 2, 2), sources={(-1, 0)})


def test_pocket_reachable_around_corner_is_safe():
    # L-shaped free space; footprint in the corridor leaves an around-the-corner
    # path to the pocket
    free = {(x, 0) for x in range(6)} | {(5, y) for y in range(4)} \
         | {(x, 3) for x in range(3, 6)}
    assert placement_is_safe(free, _rect(2, 0, 1, 1), sources={(-1, 0)}) is False
    # severing the only path is unsafe; consuming the dead-end tip (3,3) is
    # safe — (4,3),(5,3) stay connected around the corner via (5,2)
    assert placement_is_safe(free, _rect(3, 3, 1, 1), sources={(-1, 0)})


def test_consuming_a_whole_pocket_exactly_is_safe():
    # 2x2 pocket connected to the corridor only via (2,1)->(2,0); filling the
    # pocket exactly leaves no stranded component
    free = {(x, 0) for x in range(6)} | {(1, 1), (2, 1), (1, 2), (2, 2)}
    assert placement_is_safe(free, frozenset({(1, 1), (2, 1), (1, 2), (2, 2)}),
                             sources={(-1, 0)})


def test_guarded_border_must_keep_a_free_cell():
    # consumer's border has one free cell left at (4,0); occupying it is unsafe
    free = {(x, 0) for x in range(8)}
    guard = frozenset({(4, 0)})
    assert not placement_is_safe(free, _rect(4, 0, 1, 1),
                                 sources={(-1, 0)}, guarded=(guard,))
    assert placement_is_safe(free, _rect(6, 0, 1, 1),
                             sources={(-1, 0)}, guarded=(guard,))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_reach.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foeopt.reach'`.

- [ ] **Step 4: Implement the exact predicate**

Create `foeopt/reach.py`:

```python
"""Routability-preserving placement checks (2026-07-02 spec).

A placement is *safe* iff, after occupying the footprint: (1) every remaining
free component still contains or borders a source cell, and (2) every guarded
border set (placed road-needing buildings + the Townhall) keeps at least one
free cell. Under (1), that surviving border cell is reachable — which is what
route() needs — so a layout grown under this mask can never end unroutable.

`placement_is_safe` is the exact oracle; `ReachChecker` is the per-step
accelerator (built once per placement step, queried per candidate anchor) and
must return identical answers — see tests/test_reach.py's equivalence test.
"""
from __future__ import annotations

from typing import Iterable

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


def _reachable(free: set[Cell] | frozenset[Cell], sources) -> set[Cell]:
    """Free cells reachable from `sources`: seeded at every free cell that is
    a source or orthogonally adjacent to one (sources need not be free)."""
    seeds = [c for c in free
             if c in sources
             or any((c[0] + dx, c[1] + dy) in sources for dx, dy in _ORTHO)]
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        cx, cy = stack.pop()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in free and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def placement_is_safe(free: set[Cell] | frozenset[Cell],
                      footprint_cells: frozenset[Cell],
                      sources: set[Cell] | frozenset[Cell],
                      guarded: Iterable[frozenset[Cell]] = ()) -> bool:
    remaining = set(free) - set(footprint_cells)
    if _reachable(remaining, sources) != remaining:
        return False
    return all(g & remaining for g in guarded)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_reach.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-07-02-routability-mask-design.md foeopt/reach.py tests/test_reach.py
git commit -m "feat(reach): exact routability-preserving placement predicate (+spec guarded-borders fix)"
```

---

## Task 2: `ReachChecker` fast path (oracle-equivalence gated)

Per placement step the packer/env queries many candidate anchors against the same free set. `ReachChecker` does the O(free) BFS labelling once, then answers most queries with an O(perimeter) local band check, falling back to the oracle when the fast path can't prove safety.

Fast-accept soundness (all three required): (a) every free cell was reachable pre-removal, (b) the footprint covers no BFS *seed* cell (a cell in/adjacent to `sources`), and (c) all free cells orthogonally adjacent to the footprint (the ring) lie in one orthogonally-connected component of the free *band* around the footprint (Chebyshev distance ≤ 1 — the band includes diagonal corner cells, otherwise ring arcs always split at rectangle corners). Then any path through the footprint detours through the band, no seed is lost, so connectivity and reachability are preserved. An empty ring means the footprint consumed an entire pocket exactly — safe under (a)+(b).

**Files:**
- Modify: `foeopt/reach.py` (append)
- Test: `tests/test_reach.py` (append)

**Interfaces:**
- Consumes: `placement_is_safe`, `_reachable` (T1).
- Produces: `ReachChecker(free, sources, guarded=())` with `is_safe(footprint_cells, extra_guarded=()) -> bool`. `extra_guarded` lets the env/packer pass the *candidate building's own* border set when it needs a road (its border must keep a free cell too).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reach.py`:

```python
from foeopt.reach import ReachChecker


def test_checker_matches_oracle_on_hand_cases():
    free = {(x, y) for x in range(8) for y in range(2)}
    chk = ReachChecker(free, sources={(-1, 0)})
    assert chk.is_safe(_rect(5, 0, 1, 1)) == \
        placement_is_safe(free, _rect(5, 0, 1, 1), {(-1, 0)})
    assert not chk.is_safe(_rect(3, 0, 2, 2))     # 2x2 severs the 2-wide corridor


def test_checker_rejects_covering_the_only_seed():
    # the ONLY source-adjacent free cell is (0,0); covering it must be unsafe
    # even though the ring around (0,0) is locally one arc
    free = {(x, 0) for x in range(5)}
    chk = ReachChecker(free, sources={(-1, 0)})
    assert not chk.is_safe(_rect(0, 0, 1, 1))


def test_checker_oracle_equivalence_randomized():
    rng = random.Random(0)
    for trial in range(30):
        w, h = rng.randint(6, 12), rng.randint(6, 12)
        free = {(x, y) for x in range(w) for y in range(h)}
        for _ in range(rng.randint(0, 6)):        # random occupied blobs
            bx, by = rng.randrange(w), rng.randrange(h)
            free -= _rect(bx, by, rng.randint(1, 3), rng.randint(1, 3))
        sources = {(0, 0)}
        guard = (frozenset({(w - 1, h - 1), (w - 2, h - 1)}),)
        chk = ReachChecker(free, sources, guarded=guard)
        for _ in range(40):
            fx, fy = rng.randrange(w), rng.randrange(h)
            fp = frozenset(_rect(fx, fy, rng.randint(1, 3), rng.randint(1, 3)) & free)
            if not fp:
                continue
            assert chk.is_safe(fp) == placement_is_safe(free, fp, sources, guard), \
                f"trial {trial}: mismatch on fp={sorted(fp)}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reach.py -v -k checker`
Expected: FAIL with `ImportError: cannot import name 'ReachChecker'`.

- [ ] **Step 3: Implement ReachChecker**

Append to `foeopt/reach.py`:

```python
class ReachChecker:
    """Per-step accelerator: build once for a (free, sources, guarded) state,
    query many candidate footprints. Exact — every answer equals
    placement_is_safe (randomized-equivalence-tested)."""

    def __init__(self, free, sources, guarded: Iterable[frozenset[Cell]] = ()):
        self.free = frozenset(free)
        self.sources = sources
        self.guarded = tuple(frozenset(g) for g in guarded)
        self.reachable = _reachable(self.free, sources)
        self._all_reachable = self.reachable == self.free
        self._seeds = frozenset(
            c for c in self.free
            if c in sources
            or any((c[0] + dx, c[1] + dy) in sources for dx, dy in _ORTHO))

    def is_safe(self, footprint_cells,
                extra_guarded: Iterable[frozenset[Cell]] = ()) -> bool:
        fp = frozenset(footprint_cells)
        guards = self.guarded + tuple(frozenset(g) for g in extra_guarded)
        if not all(any(c in self.free and c not in fp for c in g)
                   for g in guards):
            return False
        if self._all_reachable and not (fp & self._seeds) \
                and self._ring_in_one_band(fp):
            return True
        return placement_is_safe(self.free, fp, self.sources, guards)

    def _ring_in_one_band(self, fp: frozenset[Cell]) -> bool:
        """Fast sufficient check: the ring (free orthogonal neighbours of the
        footprint) lies in one orthogonally-connected component of the free
        band (Chebyshev distance <= 1, so corner cells join the arcs). Then any
        path through the footprint can detour through the band. Empty ring =
        the footprint consumed a whole pocket exactly — nothing to disconnect."""
        ring: set[Cell] = set()
        band: set[Cell] = set()
        for (x, y) in fp:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    c = (x + dx, y + dy)
                    if c in self.free and c not in fp:
                        band.add(c)
                        if abs(dx) + abs(dy) == 1:
                            ring.add(c)
        if not ring:
            return True
        start = next(iter(ring))
        seen = {start}
        stack = [start]
        while stack:
            cx, cy = stack.pop()
            for dx, dy in _ORTHO:
                n = (cx + dx, cy + dy)
                if n in band and n not in seen:
                    seen.add(n)
                    stack.append(n)
        return ring <= seen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reach.py -v`
Expected: all pass, including the 1200-query randomized equivalence sweep. Any mismatch is a fast-path soundness bug: fix `ReachChecker` (typically by tightening the fast-accept conditions), never by weakening the oracle.

- [ ] **Step 5: Commit**

```bash
git add foeopt/reach.py tests/test_reach.py
git commit -m "feat(reach): ReachChecker fast path — band check + BFS fallback, oracle-equivalent"
```

---

## Task 3: `valid_actions(safe=)` in PlacementEnv

**Files:**
- Modify: `foeopt/rlenv.py` (`valid_actions` at `foeopt/rlenv.py:97-123`, `step` at `foeopt/rlenv.py:188`, `reset`)
- Test: `tests/test_rlenv.py` (append)

**Interfaces:**
- Consumes: `ReachChecker` (T2).
- Produces: `PlacementEnv.valid_actions(prior=False, safe=False)` — with `safe=True`, keep only anchors whose placement `is_safe`. Sources = the Townhall footprint cells; guarded = borders of placed road-needing buildings; extra_guarded = the candidate's own border when `current.needs_road`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rlenv.py` (reusing that file's existing `_b`, `_env`, `_region_grid` helpers):

```python
def test_valid_actions_safe_is_subset_of_full():
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(_region_grid(10, 10), [th, _b(10, 3, 2), _b(11, 2, 2)])
    env.reset()
    assert set(env.valid_actions(safe=True)) <= set(env.valid_actions())
    assert env.valid_actions(safe=True)


def test_safe_mask_forbids_walling_off_a_pocket():
    # 1-wide corridor region: TH at the left, a 1x1 anywhere strictly inside
    # the corridor would strand the right side -> only end placements are safe
    from foeopt.model import Region
    region = Region(frozenset((x, 0) for x in range(8)))
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(region, [th, _b(10, 1, 1), _b(11, 1, 1)])
    env.reset()
    safe = env.valid_actions(safe=True)
    assert (7, 0) in safe                # corridor end: nothing stranded
    assert (4, 0) not in safe            # mid-corridor: strands (5..7, 0)


def test_safe_rollouts_never_end_unroutable():
    import random as _random
    rng = _random.Random(0)
    for seed in range(10):
        th = _b(1, 2, 2, needs=False, th=True)
        bs = [_b(10 + i, rng.choice([2, 3]), rng.choice([2, 3]),
                 needs=rng.random() < 0.7) for i in range(8)]
        env = _env(_region_grid(10, 10), [th, *bs])
        env.reset()
        res = None
        while not env.done:
            acts = env.valid_actions(safe=True)
            if not acts:
                break                      # stuck is allowed; unroutable is not
            res = env.step(rng.choice(acts))
        if res is not None and res.done:
            assert res.info.get("error") != "unroutable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rlenv.py -k safe -v`
Expected: FAIL with `TypeError: valid_actions() got an unexpected keyword argument 'safe'`.

- [ ] **Step 3: Implement**

In `foeopt/rlenv.py`, change the `valid_actions` signature and add the filter. Replace the method header and the two return paths (`foeopt/rlenv.py:97-123`):

```python
    def valid_actions(self, prior: bool = False, safe: bool = False) -> list[tuple[int, int]]:
```

At the end of the method (both cached and uncached paths funnel through), apply the filter by replacing each `return` of the anchor list with `return self._filter_safe(out, w, l) if safe else out` — concretely, restructure the method tail to:

```python
        b = self.current
        if b is None:
            return []
        w, l = b.footprint.width, b.footprint.length
        if not self._cache_valid_actions:
            out = self._valid_actions_uncached(w, l, prior)
        else:
            full = self._valid_cache[(w, l)]
            if not prior:
                out = list(full)
            else:
                frontier = self._frontier
                out = sorted(a for a in full
                             if any((a[0] + dx, a[1] + dy) in frontier
                                    for dx in range(w) for dy in range(l)))
        return self._filter_safe(out, w, l) if safe else out
```

Add the helper + checker cache (append after `valid_actions`, and add `self._reach: ReachChecker | None = None` in `reset` plus `self._reach = None` right after `self._ptr += 1` in `step`):

```python
    def _filter_safe(self, anchors: list[tuple[int, int]], w: int, l: int) -> list[tuple[int, int]]:
        """Keep anchors whose placement preserves routability: free space stays
        connected to the Townhall and no placed consumer (nor the candidate, if
        it needs a road) loses its last free border cell. Exact via ReachChecker."""
        if self._reach is None:
            guarded = tuple(b.footprint.border_cells()
                            for b in self._placed if b.needs_road)
            free = self.region.cells - self._occ
            self._reach = ReachChecker(free, set(self.townhall.footprint.cells()),
                                       guarded=guarded)
        b = self.current
        out = []
        for (x, y) in anchors:
            fp = Footprint(x, y, w, l).cells()
            extra = (Footprint(x, y, w, l).border_cells(),) if b.needs_road else ()
            if self._reach.is_safe(fp, extra_guarded=extra):
                out.append((x, y))
        return out
```

Add the import at the top of `foeopt/rlenv.py`:

```python
from foeopt.reach import ReachChecker
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_rlenv.py tests/test_reach.py -v`
Expected: all pass, including all pre-existing rlenv tests (default `safe=False` leaves every existing path untouched).

- [ ] **Step 5: Commit**

```bash
git add foeopt/rlenv.py tests/test_rlenv.py
git commit -m "feat(rlenv): safe= routability mask in valid_actions"
```

---

## Task 4: Packer wiring (flag-gated) + CLI

The packer applies the mask to building placements only — road cells never disconnect free space from the road (they *are* the sources). Free space for routability = region − building cells; the grow-tree's reserved road cells stay routable, so the packer tracks building occupancy (`bocc`) separately from `Grid` occupancy. Gap-fill (after `route()`) needs no mask: roads are final and fillers can't invalidate them.

**Files:**
- Modify: `foeopt/packing.py:37-43` (`first_fit`), `foeopt/packing.py:55+` (`first_fit_adjacent`)
- Modify: `foeopt/packer.py:69` (`build_candidate`), `foeopt/packer.py:194` (`repack`)
- Modify: `foeopt/cli.py` (`_cmd_layout`, `layout` sub-parser)
- Test: `tests/test_packing.py`, `tests/test_packer.py` (append)

**Interfaces:**
- Consumes: `ReachChecker` (T2).
- Produces:
  - `first_fit(grid, w, l, ok=None)` / `first_fit_adjacent(grid, w, l, road, ok=None)` — `ok(x, y) -> bool` filters anchors; `None` = unchanged behavior.
  - `build_candidate(layout, config, *, safe_placements=False)` and `repack(..., safe_placements=False)`; CLI `foeopt layout --safe-placements`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_packing.py` (reusing its existing Grid setup style):

```python
def test_first_fit_respects_ok_filter():
    from foeopt.packing import Grid, first_fit
    grid = Grid(4, 4, set())
    p_all = first_fit(grid, 2, 2)
    p_filtered = first_fit(grid, 2, 2, ok=lambda x, y: (x, y) != p_all)
    assert p_filtered is not None and p_filtered != p_all


def test_first_fit_adjacent_respects_ok_filter():
    from foeopt.packing import Grid, first_fit_adjacent
    grid = Grid(6, 2, set())
    road = {(2, 0)}
    p_all = first_fit_adjacent(grid, 1, 1, road)
    p2 = first_fit_adjacent(grid, 1, 1, road, ok=lambda x, y: (x, y) != p_all)
    assert p2 is not None and p2 != p_all
```

Append to `tests/test_packer.py`:

```python
def test_safe_placements_off_is_byte_identical():
    from foeopt.packer import PackConfig, build_candidate
    layout = _sparse_layout()          # reuse this file's existing fixture helper
    a = build_candidate(layout, PackConfig("bl", 7))
    b = build_candidate(layout, PackConfig("bl", 7), safe_placements=False)
    assert {x.entity_id: x.footprint for x in a.layout.buildings} == \
           {x.entity_id: x.footprint for x in b.layout.buildings}
    assert a.layout.roads == b.layout.roads


def test_safe_placements_produces_valid_routed_layout():
    from foeopt.packer import PackConfig, build_candidate
    from foeopt.validate import is_valid
    layout = _sparse_layout()
    res = build_candidate(layout, PackConfig("bl", 7), safe_placements=True)
    assert res.unplaced == []
    assert is_valid(res.layout)
```

(If `tests/test_packer.py` has no reusable sparse-layout helper, add one at the top of the file mirroring the fixture style already used there: a ~14×14 all-cells region, a 2×2 Townhall, 4 road-needing 2×2/3×2 consumers, 3 fillers.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packing.py tests/test_packer.py -k "ok_filter or safe_placements" -v`
Expected: FAIL with `TypeError: first_fit() got an unexpected keyword argument 'ok'` (and the packer equivalents).

- [ ] **Step 3: Add the ok= filter to packing**

In `foeopt/packing.py`, change `first_fit` (line 37) and `first_fit_adjacent` (line 55) signatures to accept `ok=None` and skip anchors failing it. For `first_fit`:

```python
def first_fit(grid: Grid, w: int, l: int, ok=None) -> tuple[int, int] | None:
    for y in range(grid.height):
        for x in range(grid.width):
            if grid.fits(x, y, w, l) and (ok is None or ok(x, y)):
                return (x, y)
    return None
```

For `first_fit_adjacent`, add the same `(ok is None or ok(x, y))` conjunct to its existing fit-acceptance condition, leaving the road-adjacency scan order untouched (order is load-bearing for determinism).

- [ ] **Step 4: Wire safe_placements through build_candidate/repack**

In `foeopt/packer.py`:

1. Add the import: `from foeopt.reach import ReachChecker`.
2. Change the signature (line 69): `def build_candidate(layout: Layout, config: PackConfig, *, safe_placements: bool = False) -> PackResult:`.
3. Track building occupancy + guarded borders. After the Townhall placement (line 89-91) add:

```python
    th_cells = set(Footprint(pos[0], pos[1], tw, tl).cells())
    bocc: set[tuple[int, int]] = set(th_cells)
    guarded: list[frozenset[tuple[int, int]]] = [th_border]
```

4. Add a local helper right after (before step 3 of the algorithm):

```python
    def _safe_ok(b: Building) -> "callable | None":
        if not safe_placements:
            return None
        checker = ReachChecker(region - bocc, road | th_cells,
                               guarded=guarded)
        bw, bl = b.footprint.width, b.footprint.length

        def ok(x: int, y: int) -> bool:
            fp = Footprint(x, y, bw, bl)
            extra = (fp.border_cells(),) if b.needs_road else ()
            return checker.is_safe(fp.cells(), extra_guarded=extra)
        return ok
```

(Sources are the road set plus the Townhall's own footprint cells — so BFS seeds are exactly the free cells in/adjacent to the network origin. Do NOT use `th_border` as sources: a free cell adjacent to an *occupied* border cell would then be seeded even though no road can pass there, silently over-accepting.)

5. Use it at both placement sites and maintain state:
   - consumer placement (line 116): `p = first_fit_adjacent(grid, bw, bl, road, ok=_safe_ok(b))`, and after a successful placement add `bocc |= Footprint(p[0], p[1], bw, bl).cells()` and, `if b.needs_road:`, `guarded.append(Footprint(p[0], p[1], bw, bl).border_cells())`.
   - filler placement (line 134): `p = first_fit(grid, bw, bl, ok=_safe_ok(b))`, plus the same `bocc` update (fillers are not guarded).
6. `repack` (line 194): add `safe_placements: bool = False` to the signature and pass it through in the `build_candidate(layout, cfg)` call (line 210): `build_candidate(layout, cfg, safe_placements=safe_placements)`.

In `foeopt/cli.py`: add to the `layout` sub-parser (after `--anneal-budget`):

```python
    p_layout.add_argument("--safe-placements", action="store_true",
                          help="mask placements that wall off free space or seal a "
                               "consumer (experimental; A/B-gated, off by default)")
```

and pass `safe_placements=args.safe_placements` into the `repack(...)` call inside `_cmd_layout`. (The `--polish` path's `polish()` keeps using the default; polish integration comes only if the A/B gate passes.)

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_packing.py tests/test_packer.py tests/test_layout_cli.py -v`
Expected: all pass — including every pre-existing packer/CLI test (flag off must be byte-identical; if any existing test changes behavior, the wiring leaked into the default path — fix before proceeding).

- [ ] **Step 6: Commit**

```bash
git add foeopt/packing.py foeopt/packer.py foeopt/cli.py tests/test_packing.py tests/test_packer.py
git commit -m "feat(packer): flag-gated safe-placements routability mask (+first_fit ok= filter)"
```

---

## Task 5: A/B measurement harness + verdict

The spec's §5 gates decide whether the flag ever defaults on. This task builds the harness, runs it, and records the result — whatever it is (a negative result is a complete, committable outcome; see the five proxy-heuristic lessons).

**Files:**
- Create: `scripts/exp_safe_ab.py`
- Modify: `tasks/lessons.md`

**Interfaces:**
- Consumes: `repack(..., safe_placements=)` (T4), `rl.curriculum.make_real_like_city` (stdlib, existing).

- [ ] **Step 1: Write the harness**

Create `scripts/exp_safe_ab.py`:

```python
"""A/B harness for the safe-placements mask (2026-07-02 spec section 5).

Runs repack with the mask off/on across seeds on darkzig + synthesized
real-like cities, printing unplaced/road distributions and throughput. Gates
for flipping the default (both must hold, 0-unplaced comparisons only):
  1. unplaced distribution strictly no worse everywhere, better in the tails
  2. 0-unplaced road distribution not worse AND trials/budget regression < ~30%

  uv run python scripts/exp_safe_ab.py darkzig.json --seeds 8 --budget 120
"""
from __future__ import annotations

import argparse
import random
import statistics
import time

from foeopt.loader import load_layout
from foeopt.packer import repack
from rl.curriculum import make_real_like_city


def run_arm(layout, *, safe, seeds, budget):
    rows = []
    for seed in range(seeds):
        t0 = time.monotonic()
        res = repack(layout, budget_seconds=budget, seed=seed,
                     safe_placements=safe)
        rows.append({"seed": seed, "unplaced": len(res.unplaced),
                     "roads": len(res.layout.roads), "trials": res.trials,
                     "secs": round(time.monotonic() - t0, 1)})
    return rows


def summary(name, rows):
    unp = [r["unplaced"] for r in rows]
    ok_roads = [r["roads"] for r in rows if r["unplaced"] == 0]
    trials = [r["trials"] for r in rows]
    print(f"{name}: unplaced min/mean/max {min(unp)}/{statistics.mean(unp):.1f}/{max(unp)}"
          f" | 0-unplaced roads {sorted(ok_roads) if ok_roads else 'NONE'}"
          f" | trials/run mean {statistics.mean(trials):.0f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("city")
    p.add_argument("helper", nargs="?", default=None)
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--budget", type=float, default=120.0)
    p.add_argument("--fills", default="0.5,0.7,0.9",
                   help="real-like synthesis fills; empty string = city only")
    args = p.parse_args()
    ref = load_layout(args.city, args.helper)
    cities = [("city", ref)]
    for f in filter(None, args.fills.split(",")):
        cities.append((f"real-like fill={f}",
                       make_real_like_city(random.Random(0), ref, fill=float(f))))
    for name, lay in cities:
        for safe in (False, True):
            rows = run_arm(lay, safe=safe, seeds=args.seeds, budget=args.budget)
            summary(f"{name} safe={safe}", rows)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run the harness**

```bash
uv run python scripts/exp_safe_ab.py darkzig.json --seeds 2 --budget 10 --fills 0.5
```

Expected: four summary lines (city×{off,on}, fill-0.5×{off,on}), no exceptions. Short budget = partial layouts are fine *for the smoke test only*.

- [ ] **Step 3: Run the real A/B**

```bash
uv run python scripts/exp_safe_ab.py darkzig.json --seeds 8 --budget 120
```

(~2.5 h wall-clock. Run it in the background and capture output to `output/safe-ab.txt`.) Apply the spec §5 gates to the printed distributions, comparing only 0-unplaced road lists.

- [ ] **Step 4: Record the verdict**

Append a `## Safe-placements mask A/B (2026-07-XX)` entry to `tasks/lessons.md`: the distributions per city/fill, the trials-throughput delta, the gate verdict (flip default / keep opt-in / remove), and one sentence of interpretation. Update the `tasks/todo.md` Track-C1 checkbox + Review section.

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_safe_ab.py tasks/lessons.md tasks/todo.md
git commit -m "feat(scripts): safe-placements A/B harness + gate verdict"
```

---

## Self-review notes

- Spec §2 (interface) → T1 (including the guarded-borders amendment the plan adds — the sealing hole found during planning); §3 (two-tier implementation, rejected articulation prefilter — its counter-example is a pinned test) → T1/T2; §4 (packer + env wiring, default off) → T3/T4; §5 (measured gates) → T5; §7 (test list: hand cases, oracle equivalence, safe-subset, never-unroutable) → T1/T2/T3.
- Type consistency: `placement_is_safe(free, footprint_cells, sources, guarded)` and `ReachChecker(free, sources, guarded).is_safe(fp, extra_guarded)` are used with exactly these names/orders in T3 and T4.
- Flipping the default on, and polish/webapp integration, are explicitly out of scope (spec §8) — no task does them.
