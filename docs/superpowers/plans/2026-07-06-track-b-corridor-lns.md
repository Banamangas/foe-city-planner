# Track B — Corridor LNS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corridor-granularity destroy-repair (LNS) on top of `polish()`, A/B-gated at equal wall-clock against plain polish, plus the TH-offset diagnostic probe.

**Architecture:** New pure-stdlib `foeopt/lns.py` (corridor finder → exact double-row template repair → accept-only-improvements loop with short re-anneal slices), alternating on top of the untouched `polish()`. Roads are never placed directly: repairs re-place buildings around a 1-wide gap and `route()` lays the lane. Shared A/B harness core extracted to `scripts/_ab_common.py` first; per-run before/after HTML via the existing `foeopt.viz.render_comparison`.

**Tech Stack:** Python 3.12 stdlib only in `foeopt/`; pytest; harnesses run via `uv run python`.

Spec: `docs/superpowers/specs/2026-07-06-track-b-corridor-lns-design.md`.

## Global Constraints

- `foeopt/` stays **pure stdlib**. No OR-Tools anywhere (spec §10).
- **Never-worse invariants** (spec §6): `final.unplaced == base.unplaced`; `len(final.layout.roads) ≤ len(base_layout.roads)`; deterministic for fixed seed (all randomness through one `random.Random(seed)`).
- **Destroy cap:** ≤ 12 destroyed buildings per move (bounds the exact partition at 2^12).
- **Byte-identity:** `repack` default path and `th_stub_template=False` keep today's behavior exactly, RNG stream included; `th_stub_template=True` must equal `th_styles=("corner","stub")`.
- **Gate (spec §1.1/§8, pre-committed):** equal total wall-clock per seed; darkzig mean 0-unplaced roads ≥2 better in the LNS arm AND `max(B roads) ≤ max(A roads)`; ≥8 seeds; fail → verdict recorded, flag stays opt-in, Track B closes.
- **TH-offset probe (spec §8b):** diagnostic only, pure-style arms (corner-only vs offset-only), no flip gate, no CLI flag.
- Library writes no files; HTML written by CLI/harness only, under `output/lns/` (gitignored).
- TDD for all `foeopt/` code.

---

## File Structure

| file | role | task |
|---|---|---|
| `scripts/_ab_common.py` | NEW: shared harness core (`base_parser`, `load_cities`, `summarize`) | T1 |
| `scripts/exp_safe_ab.py`, `scripts/exp_th_ab.py` | refactor onto `_ab_common` | T1 |
| `foeopt/packer.py` | `th_styles` on `repack`; `_offset_fit`; `th_style="offset"` | T2 |
| `tests/test_packer.py` | offset + back-compat byte-identity tests | T2 |
| `foeopt/lns.py` | NEW: `find_corridor` (T3), `rebuild_corridor` (T4), `lns_polish`/`LNSResult` (T5) | T3-T5 |
| `tests/test_lns.py` | NEW: unit + invariant + determinism tests | T3-T5 |
| `foeopt/cli.py` | `--lns SECONDS` on `layout` (+ HTML write) | T6 |
| `tests/test_layout_cli.py` (or the repo's CLI test file) | `--lns` smoke | T6 |
| `scripts/exp_lns_ab.py` | NEW: LNS A/B harness (+ per-run HTML) | T7 |
| `scripts/exp_th_offset_ab.py` | NEW: TH-offset probe harness | T7 |
| `tasks/lessons.md`, `tasks/todo.md` | run experiments, record verdicts | T8 |

---

## Task 1: Extract `scripts/_ab_common.py` and refactor the two existing harnesses

The whole-branch review's dedup recommendation, landed before the fourth harness copy. Honest DRY only: the shared part is city loading, the argparser, and the summary line — each harness keeps its own arm loop.

**Files:**
- Create: `scripts/_ab_common.py`
- Modify: `scripts/exp_safe_ab.py`, `scripts/exp_th_ab.py`
- Test: none (scripts/ has no pytest by design); verification = smoke runs with byte-comparable summary lines.

**Interfaces:**
- Produces (used by T7):
  - `base_parser(doc: str) -> argparse.ArgumentParser` — positional `city`, optional `helper`, `--seeds` (int, 8), `--budget` (float, 120.0), `--fills` (str, "0.5,0.7,0.9").
  - `load_cities(city: str, helper: str | None, fills: str) -> list[tuple[str, Layout]]` — `[("city", ref)] + [(f"real-like fill={f}", make_real_like_city(random.Random(0), ref, fill=float(f))) for f in fills.split(",") if f]`.
  - `summarize(name: str, rows: list[dict]) -> None` — prints exactly the current format: `f"{name}: unplaced min/mean/max {min}/{mean:.1f}/{max} | 0-unplaced roads {sorted list or 'NONE'} | trials/run mean {mean:.0f}"`.

- [ ] **Step 1: Write `scripts/_ab_common.py`**

Copy the bodies verbatim from `scripts/exp_safe_ab.py` (they are identical in `exp_th_ab.py`): the `sys.path.insert` bootstrap, the imports (`argparse`, `random`, `statistics`, `foeopt.loader.load_layout`, `rl.curriculum.make_real_like_city`), then:

```python
def base_parser(doc):
    p = argparse.ArgumentParser(description=doc)
    p.add_argument("city")
    p.add_argument("helper", nargs="?", default=None)
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--budget", type=float, default=120.0)
    p.add_argument("--fills", default="0.5,0.7,0.9",
                   help="real-like synthesis fills; empty string = city only")
    return p


def load_cities(city, helper, fills):
    ref = load_layout(city, helper)
    cities = [("city", ref)]
    for f in filter(None, fills.split(",")):
        cities.append((f"real-like fill={f}",
                       make_real_like_city(random.Random(0), ref, fill=float(f))))
    return cities


def summarize(name, rows):
    unp = [r["unplaced"] for r in rows]
    ok_roads = [r["roads"] for r in rows if r["unplaced"] == 0]
    trials = [r["trials"] for r in rows]
    print(f"{name}: unplaced min/mean/max {min(unp)}/{statistics.mean(unp):.1f}/{max(unp)}"
          f" | 0-unplaced roads {sorted(ok_roads) if ok_roads else 'NONE'}"
          f" | trials/run mean {statistics.mean(trials):.0f}")
```

(Adapt names to the exact current code — the two harnesses' `summary`/city-loop bodies are the source of truth; the printed format must not change.)

- [ ] **Step 2: Refactor both harnesses onto it**

Each keeps its own `run_arm` and `main`; replace their local copies of the parser, city loop, and summary with `from _ab_common import base_parser, load_cities, summarize` (scripts import as plain module — they share the directory).

- [ ] **Step 3: Smoke both**

```bash
uv run python scripts/exp_safe_ab.py darkzig.json --seeds 1 --budget 5 --fills ""
uv run python scripts/exp_th_ab.py darkzig.json --seeds 1 --budget 5 --fills ""
```

Expected: two summary lines each, exact same format as before the refactor, no exceptions.

- [ ] **Step 4: Commit**

```bash
git add scripts/_ab_common.py scripts/exp_safe_ab.py scripts/exp_th_ab.py
git commit -m "refactor(scripts): extract shared A/B harness core (_ab_common)"
```

---

## Task 2: `th_styles` on repack + the `"offset"` TH style

Spec §8b. `"offset"` = same corner-outward scan, but skip positions with Chebyshev distance < d from the anchor corner, d drawn per trial from {2, 4, 6, 8}. Placement only — no road seeding change, no pre-pack.

**Files:**
- Modify: `foeopt/packer.py` (`repack` signature ~line 340; `build_candidate` TH-placement step ~line 85; add `_offset_fit` next to `_corner_fit`)
- Test: `tests/test_packer.py` (append)

**Interfaces:**
- Consumes: existing `_corner_fit(grid, w, l, anchor)`, `PackConfig(anchor, seed, th_style)`.
- Produces: `repack(layout, *, thorough=False, budget_seconds=None, seed=0, safe_placements=False, th_stub_template=False, th_styles: tuple[str, ...] = ("corner",))`; `PackConfig.th_style` accepts `"offset"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_packer.py` (reuse its existing `_sparse_layout`/`_b` helpers and imports):

```python
def test_offset_style_places_th_away_from_corner():
    from foeopt.packer import PackConfig, build_candidate
    layout = _sparse_layout()
    res = build_candidate(layout, PackConfig("bl", 3, th_style="offset"))
    th = res.layout.townhall
    assert th is not None
    # anchor bl scans from (0, 0); offset requires Chebyshev distance >= d >= 2
    assert max(th.footprint.x, th.footprint.y) >= 2
    assert res.unplaced == []


def test_th_styles_default_is_byte_identical():
    from foeopt.packer import repack
    layout = _sparse_layout()
    a = repack(layout, budget_seconds=2, seed=5)
    b = repack(layout, budget_seconds=2, seed=5, th_styles=("corner",))
    assert {x.entity_id: x.footprint for x in a.layout.buildings} == \
           {x.entity_id: x.footprint for x in b.layout.buildings}
    assert a.layout.roads == b.layout.roads


def test_th_stub_template_is_sugar_for_styles():
    from foeopt.packer import repack
    layout = _sparse_layout()
    a = repack(layout, budget_seconds=2, seed=5, th_stub_template=True)
    b = repack(layout, budget_seconds=2, seed=5, th_styles=("corner", "stub"))
    assert {x.entity_id: x.footprint for x in a.layout.buildings} == \
           {x.entity_id: x.footprint for x in b.layout.buildings}
    assert a.layout.roads == b.layout.roads
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packer.py -k "offset or styles or sugar" -v`
Expected: FAIL (`TypeError: repack() got an unexpected keyword argument 'th_styles'`; offset style silently behaving as corner or an assertion error, depending on current `th_style` handling).

- [ ] **Step 3: Implement**

In `foeopt/packer.py`:

1. Add `_offset_fit` next to `_corner_fit` (same scan order, distance guard):

```python
def _offset_fit(grid: Grid, w: int, l: int, anchor: str, d: int) -> tuple[int, int] | None:
    """Corner-outward scan like _corner_fit, but skip positions closer than
    Chebyshev distance d to the anchor corner. Produces expert-style TH spots:
    offset d along one axis, flush on the other (the first accepted position)."""
    xs = range(grid.width) if anchor in ("bl", "tl") else range(grid.width - 1, -1, -1)
    ys = range(grid.height) if anchor in ("bl", "br") else range(grid.height - 1, -1, -1)
    cx = 0 if anchor in ("bl", "tl") else grid.width - 1
    cy = 0 if anchor in ("bl", "br") else grid.height - 1
    for y in ys:
        for x in xs:
            if max(abs(x - cx), abs(y - cy)) < d:
                continue
            if grid.fits(x, y, w, l):
                return (x, y)
    return None
```

2. In `build_candidate`'s TH-placement step, add the branch (mirroring the existing `"stub"` branch's structure; `rng` already exists at that point):

```python
    if config.th_style == "offset":
        d = rng.choice((2, 4, 6, 8))
        pos = _offset_fit(grid, tw, tl, config.anchor, d) or _corner_fit(grid, tw, tl, config.anchor)
```

(Fallback to `_corner_fit` when no offset position fits — same degrade-gracefully pattern as `"stub"`. The `d` draw happens ONLY on the offset branch, so corner/stub RNG streams are untouched.)

3. `repack`: add `th_styles: tuple[str, ...] = ("corner",)`; compute effective styles once:

```python
    styles = tuple(th_styles) + (("stub",) if th_stub_template else ())
```

and in the trial loop replace the current style selection with: one style → use it with **no rng draw**; multiple → `master.choice(styles)`. CRITICAL back-compat: today `th_stub_template=True` draws `master.choice(("corner", "stub"))` — `styles` computes to exactly that tuple in that case, so the stream is identical. Verify against the existing code before editing; the flag-off path must not gain or lose any rng draw.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_packer.py -v`
Expected: all pass, including the pre-existing byte-identity and stub tests.

- [ ] **Step 5: Commit**

```bash
git add foeopt/packer.py tests/test_packer.py
git commit -m "feat(packer): th_styles portfolio param + offset TH style (spec 8b probe)"
```

---

## Task 3: Corridor finder (`foeopt/lns.py`)

Spec §4. Under-used = load ≤ 1, excluding tolerated junctions (load-1 cells with ≥3 orthogonal road neighbours). Corridor = orthogonally-connected run within the under-used set. Destroy set = run cells + all non-TH buildings orthogonally adjacent to the run, capped at 12 by truncating the run from the end farthest (in BFS order) from the seed cell.

**Files:**
- Create: `foeopt/lns.py`
- Test: `tests/test_lns.py`

**Interfaces:**
- Consumes: `foeopt.quality.road_cell_load`, `foeopt.model.Layout/Building`.
- Produces (T4/T5 use these): `find_corridor(layout, rng, *, max_buildings=12) -> tuple[list[Cell], list[Building]] | None` — (run cells in BFS order from the seed, victim buildings) or None when no under-used cells exist. `_ORTHO`, `Cell` module-level as in `reach.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lns.py`:

```python
import random

from foeopt.lns import find_corridor
from foeopt.model import Building, Footprint, Layout, Region


def _b(eid, x, y, w, l, *, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(x, y, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def _comb_layout():
    """Deliberately wasteful: four 2x2 consumers in one column at x=4..5,
    served single-loaded by the road column x=3 (y=0..7). TH 2x2 at (0,0),
    roads: (2,0) links TH border to the column."""
    th = _b(1, 0, 0, 2, 2, needs=False, th=True)
    cons = [_b(10 + i, 4, 2 * i, 2, 2) for i in range(4)]
    roads = {(3, y): 1 for y in range(8)} | {(2, 0): 1}
    return Layout(_region(10, 11), [th, *cons], th, roads)


def test_find_corridor_locates_single_loaded_run():
    lay = _comb_layout()
    run, victims = find_corridor(lay, random.Random(0))
    assert set(run) <= set(lay.roads)
    assert len(run) >= 4                       # a real stretch, not one cell
    assert {b.entity_id for b in victims} <= {10, 11, 12, 13}
    assert victims                             # at least one adjacent consumer


def test_find_corridor_none_when_all_double_loaded():
    # road row y=1 double-loaded: consumers above and below every cell
    th = _b(1, 0, 0, 1, 1, needs=False, th=True)
    top = [_b(10 + i, 1 + i, 0, 1, 1) for i in range(4)]
    bot = [_b(20 + i, 1 + i, 2, 1, 1) for i in range(4)]
    roads = {(x, 1): 1 for x in range(5)}      # (0,1) borders the TH
    lay = Layout(_region(6, 3), [th, *top, *bot], th, roads)
    # every road cell has load 2 except (0,1) which is a TH-adjacent connector
    res = find_corridor(lay, random.Random(0), max_buildings=12)
    if res is not None:                        # only the load<=1 connector may qualify
        run, _ = res
        assert set(run) <= {(0, 1)}


def test_find_corridor_caps_victims():
    lay = _comb_layout()
    run, victims = find_corridor(lay, random.Random(0), max_buildings=2)
    assert len(victims) <= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_lns.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foeopt.lns'`.

- [ ] **Step 3: Implement**

Create `foeopt/lns.py`:

```python
"""Corridor-granularity LNS (Track B, 2026-07-06 spec).

Destroy an under-used road corridor's neighbourhood, rebuild it as a balanced
double row around a 1-wide gap, keep only strict improvements. Roads are never
placed directly: route() recomputes the network from building positions, so a
repair shapes roads by shaping placements."""
from __future__ import annotations

import random

from foeopt.model import Building, Layout
from foeopt.quality import road_cell_load

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))
Cell = tuple[int, int]


def _underused(layout: Layout) -> set[Cell]:
    """Road cells with load <= 1, excluding tolerated junctions (a load-1 cell
    whose other >=3 orthogonal neighbours are roads — rule-2 semantics)."""
    load = road_cell_load(layout)
    roads = layout.roads
    out = set()
    for c, v in load.items():
        if v >= 2:
            continue
        n_road = sum(((c[0] + dx, c[1] + dy) in roads) for dx, dy in _ORTHO)
        if v == 1 and n_road >= 3:
            continue
        out.add(c)
    return out


def find_corridor(layout: Layout, rng: random.Random, *,
                  max_buildings: int = 12) -> tuple[list[Cell], list[Building]] | None:
    """One corridor pick: BFS-flood the under-used set from an rng-chosen seed
    cell; victims = non-TH buildings orthogonally adjacent to the run. Runs are
    truncated from the far end (BFS order) until the victim count fits."""
    cand = _underused(layout)
    if not cand:
        return None
    seed = rng.choice(sorted(cand))
    run: list[Cell] = [seed]
    seen = {seed}
    i = 0
    while i < len(run):                        # BFS: run stays sorted by distance
        cx, cy = run[i]
        i += 1
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in cand and n not in seen:
                seen.add(n)
                run.append(n)
    cell_owner: dict[Cell, Building] = {}
    for b in layout.buildings:
        if b.is_townhall:
            continue
        for c in b.footprint.cells():
            cell_owner[c] = b

    def victims_of(cells: list[Cell]) -> list[Building]:
        found: dict[int, Building] = {}
        for (cx, cy) in cells:
            for dx, dy in _ORTHO:
                b = cell_owner.get((cx + dx, cy + dy))
                if b is not None:
                    found[b.entity_id] = b
        return [found[k] for k in sorted(found)]

    while run:
        vs = victims_of(run)
        if len(vs) <= max_buildings:
            return (run, vs) if vs else None
        run = run[:-1]                         # drop the BFS-farthest cell
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_lns.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add foeopt/lns.py tests/test_lns.py
git commit -m "feat(lns): corridor finder — under-used run + capped victim set"
```

---

## Task 4: Exact double-row template repair

Spec §5. Freed area → lane candidates (both axes, rng-shuffled order) → exact two-side partition of the consumers (≤ 2^12 subsets, minimize the longer side's frontage) → geometric row placement (ragged backs fine, lane cells stay free) → fillers via first-fit → `route()` + `is_valid`.

**Files:**
- Modify: `foeopt/lns.py` (append)
- Test: `tests/test_lns.py` (append)

**Interfaces:**
- Consumes: T3's `find_corridor` output shapes; `foeopt.router.route/RouteError`; `foeopt.validate.is_valid`.
- Produces (T5 uses): `rebuild_corridor(layout, run_cells, victims, rng) -> Layout | None` — a routed, valid candidate with strictly ALL victims re-placed, or None. Helper `_partition(frontages: list[int]) -> int` (bitmask of side A).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lns.py`:

```python
from foeopt.lns import rebuild_corridor, _partition
from foeopt.router import route


def test_partition_is_exact():
    # frontages [4,3,3,2]: greedy-by-size gives sides {4,3}/{3,2} -> max 7;
    # the optimum is {4,2}/{3,3} -> max 6.
    mask = _partition([4, 3, 3, 2])
    side_a = sum(f for i, f in enumerate([4, 3, 3, 2]) if mask >> i & 1)
    assert max(side_a, 12 - side_a) == 6


def test_rebuild_comb_strictly_reduces_roads():
    lay = _comb_layout()
    baseline = len(route(lay))
    rng = random.Random(0)
    run, victims = find_corridor(lay, rng)
    cand = rebuild_corridor(lay, run, victims, rng)
    assert cand is not None
    assert len(cand.buildings) == len(lay.buildings)         # nobody lost
    assert len(cand.roads) < baseline                        # strict improvement


def test_rebuild_returns_none_when_nothing_fits():
    # freed area too small for any lane: single 1x1 victim in a 1-wide pocket
    th = _b(1, 0, 0, 1, 1, needs=False, th=True)
    c = _b(10, 2, 0, 1, 1)
    lay = Layout(Region(frozenset({(0, 0), (1, 0), (2, 0)})), [th, c], th, {(1, 0): 1})
    res = rebuild_corridor(lay, [(1, 0)], [c], random.Random(0))
    # the only re-placement is the original spot; None or an equal layout are both
    # acceptable — but never an invalid/worse claim of improvement
    if res is not None:
        assert len(res.roads) <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_lns.py -k "partition or rebuild" -v`
Expected: FAIL with `ImportError: cannot import name 'rebuild_corridor'`.

- [ ] **Step 3: Implement**

Append to `foeopt/lns.py`:

```python
from dataclasses import replace

from foeopt.model import Footprint
from foeopt.router import RouteError, route
from foeopt.validate import is_valid


def _partition(frontages: list[int]) -> int:
    """Exact two-side split minimizing the longer side's total frontage.
    n <= 12 (destroy cap), so 2^n enumeration is trivial."""
    total = sum(frontages)
    best_mask, best_key = 0, None
    for mask in range(1 << len(frontages)):
        s = sum(f for i, f in enumerate(frontages) if mask >> i & 1)
        key = max(s, total - s)
        if best_key is None or key < best_key:
            best_mask, best_key = mask, key
    return best_mask


def _lane_candidates(area: set[Cell]) -> list[list[Cell]]:
    """Maximal straight 1-wide segments (len >= 2) inside `area`, both axes."""
    lanes: list[list[Cell]] = []
    for horiz in (True, False):
        key = (lambda c: (c[1], c[0])) if horiz else (lambda c: (c[0], c[1]))
        step = (1, 0) if horiz else (0, 1)
        cells = sorted(area, key=key)
        seg: list[Cell] = []
        for c in cells:
            if seg and (seg[-1][0] + step[0], seg[-1][1] + step[1]) == c:
                seg.append(c)
            else:
                if len(seg) >= 2:
                    lanes.append(seg)
                seg = [c]
        if len(seg) >= 2:
            lanes.append(seg)
    return lanes


def _place_row(members: list[Building], lane: list[Cell], side: int,
               free: set[Cell], horiz: bool) -> list[Building] | None:
    """Pack `members` shoulder-to-shoulder along the lane on one side.
    side=-1: before the lane row/col; side=+1: after. Returns re-footprinted
    buildings or None if any member cannot fit."""
    placed: list[Building] = []
    used: set[Cell] = set()
    cursor = 0
    lx, ly = lane[0]
    for b in members:
        w, l = b.footprint.width, b.footprint.length
        for ext, dep in ((min(w, l), max(w, l)), (max(w, l), min(w, l))):
            if horiz:
                bx = lx + cursor
                by = ly - dep if side < 0 else ly + 1
                fp = Footprint(bx, by, ext, dep)
            else:
                bx = lx - dep if side < 0 else lx + 1
                by = ly + cursor
                fp = Footprint(bx, by, dep, ext)
            cells = fp.cells()
            frontage = {(lx + i, ly) if horiz else (lx, ly + i)
                        for i in range(cursor, cursor + ext)}
            if cells <= (free - used) and frontage <= set(lane):
                placed.append(replace(b, footprint=fp))
                used |= cells
                cursor += ext
                break
        else:
            return None
    return placed


def _place_fillers(fillers: list[Building], free: set[Cell]) -> list[Building] | None:
    placed: list[Building] = []
    remaining = set(free)
    for b in sorted(fillers, key=lambda b: -(b.footprint.width * b.footprint.length)):
        w, l = b.footprint.width, b.footprint.length
        spot = None
        for (x, y) in sorted(remaining):
            for fw, fl in ((w, l), (l, w)):
                fp = Footprint(x, y, fw, fl)
                if fp.cells() <= remaining:
                    spot = fp
                    break
            if spot:
                break
        if spot is None:
            return None
        placed.append(replace(b, footprint=spot))
        remaining -= spot.cells()
    return placed


def rebuild_corridor(layout: Layout, run_cells: list[Cell], victims: list[Building],
                     rng: random.Random) -> Layout | None:
    victim_ids = {b.entity_id for b in victims}
    keep = [b for b in layout.buildings if b.entity_id not in victim_ids]
    occupied: set[Cell] = set()
    for b in keep:
        occupied |= b.footprint.cells()
    free = set(layout.region.cells) - occupied
    core: set[Cell] = set(run_cells)
    for v in victims:
        core |= v.footprint.cells()
    area = {c for c in free
            if c in core or any((c[0] + dx, c[1] + dy) in core for dx, dy in _ORTHO)}
    lanes = _lane_candidates(area)
    rng.shuffle(lanes)
    consumers = [v for v in victims if v.needs_road]
    fillers = [v for v in victims if not v.needs_road]
    for lane in lanes:
        horiz = len(lane) > 1 and lane[1][1] == lane[0][1]
        if consumers:
            mask = _partition([min(b.footprint.width, b.footprint.length)
                               for b in consumers])
            side_a = [b for i, b in enumerate(consumers) if mask >> i & 1]
            side_b = [b for i, b in enumerate(consumers) if not mask >> i & 1]
        else:
            side_a, side_b = [], []
        lane_free = free - set(lane)           # buildings must not cover the lane
        rows_a = _place_row(side_a, lane, -1, lane_free, horiz)
        if rows_a is None:
            continue
        used_a: set[Cell] = set()
        for b in rows_a:
            used_a |= b.footprint.cells()
        rows_b = _place_row(side_b, lane, +1, lane_free - used_a, horiz)
        if rows_b is None:
            continue
        used: set[Cell] = set(used_a)
        for b in rows_b:
            used |= b.footprint.cells()
        filled = _place_fillers(fillers, free - used - set(lane))
        if filled is None:
            continue
        cand = Layout(layout.region, keep + rows_a + rows_b + filled,
                      layout.townhall, {})
        try:
            cand.roads = route(cand)
        except RouteError:
            continue
        if not is_valid(cand):
            continue
        return cand
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_lns.py -v`
Expected: all pass. If `test_rebuild_comb_strictly_reduces_roads` fails on geometry (fixture layouts have bitten twice in this project), verify the comb by hand with `route()` prints before touching the algorithm, and report the corrected fixture in your task report.

- [ ] **Step 5: Commit**

```bash
git add foeopt/lns.py tests/test_lns.py
git commit -m "feat(lns): exact double-row template repair"
```

---

## Task 5: `lns_polish` loop + `LNSResult`

Spec §3/§6. Alternating phases on top of the untouched `polish()`; accept only strict improvements; 2-second re-anneal slice after each acceptance, drawn from `lns_budget`.

**Files:**
- Modify: `foeopt/lns.py` (append)
- Test: `tests/test_lns.py` (append)

**Interfaces:**
- Consumes: `foeopt.polish.polish`, `foeopt.anneal.anneal`, T3/T4 functions.
- Produces (T6/T7 use): 

```python
@dataclass
class LNSResult:
    final: PackResult
    base_layout: Layout
    rounds: int
    accepted: int

def lns_polish(layout, *, repack_budget: float, anneal_budget: float,
               lns_budget: float, seed: int = 0) -> LNSResult
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lns.py`:

```python
from foeopt.lns import lns_polish


def _lns_kwargs():
    return dict(repack_budget=2.0, anneal_budget=1.0, lns_budget=3.0, seed=0)


def test_lns_polish_never_worse_and_preserves_buildings():
    lay = _comb_layout()
    res = lns_polish(lay, **_lns_kwargs())
    assert res.final.unplaced == []
    assert len(res.final.layout.buildings) == len(lay.buildings)
    assert len(res.final.layout.roads) <= len(res.base_layout.roads)
    assert res.rounds >= res.accepted >= 0


def test_lns_polish_is_deterministic():
    lay = _comb_layout()
    a = lns_polish(lay, **_lns_kwargs())
    b = lns_polish(lay, **_lns_kwargs())
    assert a.final.layout.roads == b.final.layout.roads
    assert (a.rounds, a.accepted) == (b.rounds, b.accepted)
```

(Note: determinism here relies on trial-count determinism of `repack` given equal budgets on an idle machine; if the repo's existing byte-identity tests use a different guard for that, mirror it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_lns.py -k lns_polish -v`
Expected: FAIL with `ImportError: cannot import name 'lns_polish'`.

- [ ] **Step 3: Implement**

Append to `foeopt/lns.py`:

```python
import time
from dataclasses import dataclass

from foeopt.anneal import anneal
from foeopt.packer import PackResult
from foeopt.polish import polish

_REANNEAL_SLICE = 2.0


@dataclass
class LNSResult:
    final: PackResult
    base_layout: Layout
    rounds: int
    accepted: int


def lns_polish(layout: Layout, *, repack_budget: float, anneal_budget: float,
               lns_budget: float, seed: int = 0) -> LNSResult:
    """polish(), then corridor destroy-repair until lns_budget is spent.
    Accepts only strict road improvements; re-anneals briefly after each
    acceptance. Invariants: same unplaced set as the polish base; roads never
    worse than the base; deterministic for a fixed seed."""
    base = polish(layout, repack_budget=repack_budget,
                  anneal_budget=anneal_budget, seed=seed)
    rng = random.Random(seed)
    best = base.layout
    rounds = accepted = 0
    deadline = time.monotonic() + lns_budget
    while time.monotonic() < deadline:
        picked = find_corridor(best, rng)
        if picked is None:
            break
        rounds += 1
        run, victims = picked
        cand = rebuild_corridor(best, run, victims, rng)
        if cand is None or len(cand.roads) >= len(best.roads):
            continue
        accepted += 1
        best = cand
        slice_budget = min(_REANNEAL_SLICE, max(0.0, deadline - time.monotonic()))
        if slice_budget > 0:
            refined = anneal(best, budget_seconds=slice_budget,
                             seed=rng.randrange(2 ** 32))
            routed = Layout(best.region, refined.layout.buildings,
                            refined.layout.townhall, route(refined.layout))
            if is_valid(routed) and len(routed.roads) <= len(best.roads):
                best = routed
    final = PackResult(layout=best, unplaced=base.unplaced, trials=base.trials,
                       base_roads=len(base.layout.roads))
    return LNSResult(final=final, base_layout=base.layout,
                     rounds=rounds, accepted=accepted)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_lns.py tests/test_packer.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add foeopt/lns.py tests/test_lns.py
git commit -m "feat(lns): lns_polish alternating loop with never-worse anchoring"
```

---

## Task 6: CLI `--lns SECONDS` + before/after HTML

Spec §7/§5b. The library writes no files; the CLI writes `render_comparison(base_layout, final.layout)` to `output/lns/<city-stem>-<timestamp>.html` and prints the path.

**Files:**
- Modify: `foeopt/cli.py` (`_cmd_layout` at ~line 49; layout sub-parser at ~line 130)
- Test: the repo's CLI test file for the layout command (locate via `ls tests/ | grep -i cli`; follow its call style)

**Interfaces:**
- Consumes: `lns_polish` (T5), `foeopt.viz.render_comparison` (existing).
- Produces: `foeopt layout CITY [HELPER] --lns SECONDS [--budget/--anneal-budget/--seed ...]`.

- [ ] **Step 1: Write the failing test**

Append to the CLI test file (mirror its existing invocation fixture style — the test below assumes a `main(argv)` entry; adapt to the file's conventions):

```python
def test_layout_lns_writes_comparison_html(tmp_path, monkeypatch):
    import foeopt.cli as cli
    monkeypatch.chdir(tmp_path)               # output/lns lands under tmp_path
    # copy the small bundled fixture the other CLI tests use (same source path)
    rc = cli.main(["layout", str(_CITY_FIXTURE), "--budget", "2",
                   "--anneal-budget", "1", "--lns", "2", "-o", "layout.html"])
    assert rc == 0
    out_dir = tmp_path / "output" / "lns"
    files = list(out_dir.glob("*.html"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "before" in text.lower() and "after" in text.lower()
```

(`_CITY_FIXTURE`: reuse whatever city file the existing layout CLI tests load; if they use the bundled `city-user-data.json`, use a smaller fixture only if one already exists — do not add new data files.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ -k "lns and cli or layout_lns" -v`
Expected: FAIL (`error: unrecognized arguments: --lns`).

- [ ] **Step 3: Implement**

In the layout sub-parser (after `--th-stub-template`):

```python
    p_layout.add_argument("--lns", type=float, default=None, metavar="SECONDS",
                          help="corridor destroy-repair budget after polish "
                               "(implies --polish; writes a before/after HTML "
                               "under output/lns/; experimental, A/B-gated)")
```

In `_cmd_layout`, before the existing polish/repack branch:

```python
    if args.lns is not None:
        from datetime import datetime
        from pathlib import Path

        from foeopt.lns import lns_polish
        from foeopt.viz import render_comparison

        res = lns_polish(current, repack_budget=rbudget,
                         anneal_budget=args.anneal_budget,
                         lns_budget=args.lns, seed=args.seed)
        out_dir = Path("output") / "lns"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.city).stem
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        cmp_path = out_dir / f"{stem}-{stamp}.html"
        cmp_path.write_text(render_comparison(res.base_layout, res.final.layout))
        print(f"lns: {res.accepted}/{res.rounds} corridor rewrites accepted | "
              f"before/after: {cmp_path}")
        result = res.final
    elif args.polish:
        # the existing polish branch, byte-for-byte unchanged
```

i.e. the new `--lns` branch goes FIRST and short-circuits; the existing `polish`/`repack` branches stay untouched below it, and the function's existing result-reporting tail consumes `result` exactly as it consumes the polish branch's result today (adapt the local variable name to whatever the real function body uses).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/ -k cli -v`
Expected: all pass (new + pre-existing CLI tests).

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/
git commit -m "feat(cli): --lns corridor-repair budget with before/after HTML"
```

---

## Task 7: The two harnesses (`exp_lns_ab.py`, `exp_th_offset_ab.py`)

Spec §8/§8b. Equal wall-clock arms; arm B of the LNS A/B writes per-run HTML into a timestamped folder.

**Files:**
- Create: `scripts/exp_lns_ab.py`, `scripts/exp_th_offset_ab.py`
- Test: none (scripts); verification = smoke runs.

**Interfaces:**
- Consumes: `_ab_common` (T1), `lns_polish` (T5), `repack(th_styles=)` (T2), `foeopt.viz.render_comparison`.

- [ ] **Step 1: Write `scripts/exp_lns_ab.py`**

```python
"""LNS A/B (Track B spec section 8). Arm A: polish(R, N+L). Arm B:
lns_polish(R, N, L). Identical wall-clock per seed. Gate: darkzig mean
0-unplaced roads >=2 better in B AND max(B) <= max(A); B's per-run
before/after HTML goes to output/lns/<run-stamp>/.

  uv run python scripts/exp_lns_ab.py darkzig.json --seeds 8
"""
import pathlib
import sys
import time
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ab_common import base_parser, load_cities, summarize
from foeopt.lns import lns_polish
from foeopt.polish import polish
from foeopt.viz import render_comparison

R_FRAC, N_FRAC, L_FRAC = 0.5, 0.25, 0.25      # of --budget (default 120 -> 60/30/30)


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = pathlib.Path("output") / "lns" / stamp
    for name, lay in load_cities(args.city, args.helper, args.fills):
        R, N, L = (args.budget * f for f in (R_FRAC, N_FRAC, L_FRAC))
        rows_a, rows_b = [], []
        for seed in range(args.seeds):
            t0 = time.monotonic()
            a = polish(lay, repack_budget=R, anneal_budget=N + L, seed=seed)
            rows_a.append({"seed": seed, "unplaced": len(a.unplaced),
                           "roads": len(a.layout.roads), "trials": a.trials,
                           "secs": round(time.monotonic() - t0, 1)})
            t0 = time.monotonic()
            b = lns_polish(lay, repack_budget=R, anneal_budget=N,
                           lns_budget=L, seed=seed)
            rows_b.append({"seed": seed, "unplaced": len(b.final.unplaced),
                           "roads": len(b.final.layout.roads),
                           "trials": b.final.trials, "accepted": b.accepted,
                           "secs": round(time.monotonic() - t0, 1)})
            out_dir.mkdir(parents=True, exist_ok=True)
            safe = name.replace(" ", "_").replace("=", "")
            (out_dir / f"{safe}-seed{seed}.html").write_text(
                render_comparison(b.base_layout, b.final.layout))
        summarize(f"{name} lns=off", rows_a)
        summarize(f"{name} lns=on ", rows_b)
        acc = [r["accepted"] for r in rows_b]
        print(f"  lns accepted rewrites per seed: {acc}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `scripts/exp_th_offset_ab.py`**

```python
"""TH-offset probe (Track B spec section 8b). Pure-style arms: corner-only vs
offset-only (every trial th_style='offset'). Diagnostic only — no flip gate.

  uv run python scripts/exp_th_offset_ab.py darkzig.json --seeds 8
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ab_common import base_parser, load_cities, summarize
from foeopt.packer import repack


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    for name, lay in load_cities(args.city, args.helper, args.fills):
        for label, styles in (("corner", ("corner",)), ("offset", ("offset",))):
            rows = []
            for seed in range(args.seeds):
                t0 = time.monotonic()
                res = repack(lay, budget_seconds=args.budget, seed=seed,
                             th_styles=styles)
                rows.append({"seed": seed, "unplaced": len(res.unplaced),
                             "roads": len(res.layout.roads), "trials": res.trials,
                             "secs": round(time.monotonic() - t0, 1)})
            summarize(f"{name} th={label}", rows)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke both**

```bash
uv run python scripts/exp_lns_ab.py darkzig.json --seeds 1 --budget 8 --fills ""
uv run python scripts/exp_th_offset_ab.py darkzig.json --seeds 1 --budget 5 --fills ""
```

Expected: summary lines print for both arms of each; `output/lns/<stamp>/city-seed0.html` exists after the first command; no exceptions.

- [ ] **Step 4: Commit**

```bash
git add scripts/exp_lns_ab.py scripts/exp_th_offset_ab.py
git commit -m "feat(scripts): LNS A/B + TH-offset probe harnesses"
```

---

## Task 8: Run both experiments, apply the gate, record verdicts

**Files:**
- Modify: `tasks/lessons.md`, `tasks/todo.md`

**Interfaces:**
- Consumes: T7 harnesses; spec §1.1/§8 gate; §8b probe rules.

- [ ] **Step 1: Run the LNS A/B** (long-running, ~2.2h — run it detached with output redirected, the way the previous A/Bs were run: `setsid nohup ... &` plus a completion watcher)

```bash
uv run python scripts/exp_lns_ab.py darkzig.json --seeds 8 --budget 120 > output/lns-ab.txt 2>&1
```

- [ ] **Step 2: Run the TH-offset probe** (after Step 1 finishes — never concurrently; CPU contention corrupts equal-wall-clock comparisons; ~2.1h)

```bash
uv run python scripts/exp_th_offset_ab.py darkzig.json --seeds 8 --budget 120 > output/th-offset-ab.txt 2>&1
```

- [ ] **Step 3: Apply the gate and record**

- LNS gate (darkzig, 0-unplaced rows only): mean(B) ≤ mean(A) − 2 AND max(B) ≤ max(A) → **pass** (Track B lives; row-shift/stub-promotion moves become candidate follow-ups); else **fail** → flag stays opt-in, Track B closes.
- Any darkzig seed with unplaced > 0 in either arm: report it; if it is arm B's, the gate fails (spec §8).
- Probe: no gate — record the distributions and a one-paragraph diagnostic reading (does offset-only match/beat corner-only per trial?).
- Append `## Track B corridor-LNS A/B + TH-offset probe (2026-07-XX)` to `tasks/lessons.md`: all summary lines verbatim, the gate arithmetic (recompute every mean yourself from the raw lists — two prior entries had derived-number slips), the verdict, one paragraph of mechanism reading, and a pointer to the `output/lns/<stamp>/` HTML folder for visual inspection. Update `tasks/todo.md`: Track B checklist + Review section (scope: Track B items + Review only).

- [ ] **Step 4: Commit**

```bash
git add tasks/lessons.md tasks/todo.md
git commit -m "docs: Track B LNS A/B + TH-offset probe verdicts"
```

---

## Self-review notes

- Spec coverage: §3→T5, §4→T3, §5→T4, §5b/§7→T6 (CLI HTML) + T7 (harness HTML), §6→T4/T5 acceptance+invariant tests, §8→T7/T8, §8b→T2 (style) + T7 (probe) + T8 (verdict), §9 tests 1-6 → T3/T4/T5/T6/T2 respectively, §10 respected (no OR-Tools, no default flips, no TH moves in the LNS itself).
- Type consistency: `find_corridor -> (list[Cell], list[Building]) | None` consumed identically in T4 tests and T5 loop; `LNSResult.final/base_layout/rounds/accepted` consumed by T6 CLI and T7 harness; `th_styles` tuple consumed by T7 probe.
- Known-risk notes for the executor: fixture geometry (T3/T4 comb) has bitten twice before — verify by hand before blaming the algorithm; `route()` may legitimately produce a better-than-x=3 tree on the comb, in which case adjust the fixture so the baseline is genuinely wasteful and report the correction.
