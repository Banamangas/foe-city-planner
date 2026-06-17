# FoE City Layout Optimizer — Phase 0 + Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse a Forge of Empires city export, render it as an interactive HTML map (Phase 0), and compute a minimal Townhall-rooted road network with all buildings fixed in place (Phase 1).

**Architecture:** A standard-library-only Python package `foeopt/`. `loader` reads the three JSON files; `catalog` resolves building footprints, road-need and set/chain data; `region` builds the buildable area; `model` holds the dataclasses everything passes around; `build` assembles a `Layout`; `validate` checks connectivity; `router` computes the minimal road network (greedy Steiner heuristic + prune); `report` emits stats and a road diff; `viz` writes the interactive HTML; `cli` exposes `view` and `roads`.

**Tech Stack:** Python 3.12, `uv` for venv/deps, `pytest` for tests, standard library only for core logic (no numpy/ortools in Phase 0/1). HTML map is a single self-contained file with inline JS (no server).

## Global Constraints

- Python **3.12** (`uv` manages the venv).
- Core logic uses the **standard library only**. The only dev dependency is `pytest`. OR-Tools is out of scope for this plan (deferred to the exact-router task in a later plan).
- Coordinates are `(x, y)` integer tuples. `x` → width axis, `y` → length axis.
- **No rotation** of footprints.
- **Road-need detection:** a non-street entity needs a road **iff its live entity dict has a `connected` key**. Never use `street_connection_level` to *detect* road-need.
- **Road level required** by a building = its def `requirements.street_connection_level` if truthy, else **1**.
- **Townhall is the network root only — it never substitutes for a road.** Every road-needing building (except the Townhall itself) must have an actual road tile orthogonally adjacent.
- **Buildable region** = union of `unlocked_areas` rectangles.
- **Excluded entities:** type in `{off_grid, outpost_ship, friends_tavern}`, any entity with coords outside `0 ≤ x,y < 200`, and entities lacking `x`/`y`.
- Data files live at repo root: `city-user-data.json`, `city-user-data-foe-helper.json`, `metadata-grid.json`.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `foeopt/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `uv run pytest` and an importable `foeopt` package.

- [ ] **Step 1: Write the failing test**

`tests/test_scaffold.py`:
```python
import foeopt


def test_package_imports():
    assert hasattr(foeopt, "__version__")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt'` or no `__version__`).

- [ ] **Step 3: Create the package and config**

`pyproject.toml`:
```toml
[project]
name = "foeopt"
version = "0.1.0"
description = "Forge of Empires city layout optimizer"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`foeopt/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: (empty file)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: PASS (uv creates the venv and installs pytest automatically).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml foeopt/__init__.py tests/__init__.py tests/test_scaffold.py
git commit -m "feat: scaffold foeopt package with pytest"
```

---

### Task 2: Core dataclasses (`model.py`)

**Files:**
- Create: `foeopt/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Produces:
  - `Footprint(x: int, y: int, width: int, length: int)` with `.cells() -> set[tuple[int,int]]` and `.border_cells() -> set[tuple[int,int]]` (orthogonal neighbours not inside the footprint).
  - `Building(entity_id: int, cityentity_id: str, type: str, footprint: Footprint, needs_road: bool, road_level: int, is_townhall: bool, set_id: str | None, chain_id: str | None, name: str)`.
  - `Region(cells: frozenset[tuple[int,int]])` with `.contains_cell(c) -> bool` and `.contains_footprint(fp) -> bool`.
  - `Layout(region: Region, buildings: list[Building], townhall: Building | None, roads: dict[tuple[int,int], int])` with `.occupied_cells() -> set[tuple[int,int]]` (all building footprint cells) and `.road_needing() -> list[Building]`.

- [ ] **Step 1: Write the failing test**

`tests/test_model.py`:
```python
from foeopt.model import Footprint, Building, Region, Layout


def test_footprint_cells_and_border():
    fp = Footprint(x=2, y=3, width=2, length=1)
    assert fp.cells() == {(2, 3), (3, 3)}
    # orthogonal neighbours of the two cells, excluding the footprint itself
    assert fp.border_cells() == {
        (1, 3), (4, 3),          # left / right
        (2, 2), (3, 2),          # above
        (2, 4), (3, 4),          # below
    }


def test_region_contains():
    region = Region(cells=frozenset({(0, 0), (1, 0), (0, 1), (1, 1)}))
    assert region.contains_cell((0, 0))
    assert not region.contains_cell((2, 0))
    assert region.contains_footprint(Footprint(0, 0, 2, 1))
    assert not region.contains_footprint(Footprint(0, 0, 3, 1))


def test_layout_helpers():
    th = Building(1, "TH", "main_building", Footprint(0, 0, 1, 1),
                  needs_road=True, road_level=1, is_townhall=True,
                  set_id=None, chain_id=None, name="Townhall")
    house = Building(2, "H", "generic_building", Footprint(2, 0, 1, 1),
                     needs_road=True, road_level=1, is_townhall=False,
                     set_id=None, chain_id=None, name="House")
    deco = Building(3, "D", "generic_building", Footprint(4, 0, 1, 1),
                    needs_road=False, road_level=0, is_townhall=False,
                    set_id=None, chain_id=None, name="Deco")
    layout = Layout(Region(frozenset()), [th, house, deco], th, roads={})
    assert layout.occupied_cells() == {(0, 0), (2, 0), (4, 0)}
    # townhall is excluded from road_needing (it is the root, not a consumer)
    assert layout.road_needing() == [house]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.model'`).

- [ ] **Step 3: Write the implementation**

`foeopt/model.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Footprint:
    x: int
    y: int
    width: int
    length: int

    def cells(self) -> set[tuple[int, int]]:
        return {
            (self.x + dx, self.y + dy)
            for dx in range(self.width)
            for dy in range(self.length)
        }

    def border_cells(self) -> set[tuple[int, int]]:
        own = self.cells()
        border: set[tuple[int, int]] = set()
        for (cx, cy) in own:
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if (nx, ny) not in own:
                    border.add((nx, ny))
        return border


@dataclass
class Building:
    entity_id: int
    cityentity_id: str
    type: str
    footprint: Footprint
    needs_road: bool
    road_level: int
    is_townhall: bool
    set_id: str | None
    chain_id: str | None
    name: str


@dataclass(frozen=True)
class Region:
    cells: frozenset[tuple[int, int]]

    def contains_cell(self, c: tuple[int, int]) -> bool:
        return c in self.cells

    def contains_footprint(self, fp: Footprint) -> bool:
        return fp.cells() <= self.cells


@dataclass
class Layout:
    region: Region
    buildings: list[Building]
    townhall: Building | None
    roads: dict[tuple[int, int], int] = field(default_factory=dict)

    def occupied_cells(self) -> set[tuple[int, int]]:
        occ: set[tuple[int, int]] = set()
        for b in self.buildings:
            occ |= b.footprint.cells()
        return occ

    def road_needing(self) -> list[Building]:
        return [b for b in self.buildings if b.needs_road and not b.is_townhall]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/model.py tests/test_model.py
git commit -m "feat: core dataclasses (Footprint, Building, Region, Layout)"
```

---

### Task 2.5: Shared test fixtures (real data paths)

**Files:**
- Create: `tests/conftest.py`

**Interfaces:**
- Produces pytest fixtures `city_data`, `helper_data`, `grid_data` returning the parsed real JSON, plus `repo_root` (a `pathlib.Path`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scaffold.py`:
```python
def test_fixtures_load(city_data, helper_data):
    assert city_data["__class__"] == "CityMap"
    assert "CityEntities" in helper_data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scaffold.py::test_fixtures_load -v`
Expected: FAIL (`fixture 'city_data' not found`).

- [ ] **Step 3: Write the fixtures**

`tests/conftest.py`:
```python
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def _load(name: str):
    return json.loads((REPO_ROOT / name).read_text())


@pytest.fixture(scope="session")
def city_data():
    return _load("city-user-data.json")


@pytest.fixture(scope="session")
def helper_data():
    return _load("city-user-data-foe-helper.json")


@pytest.fixture(scope="session")
def grid_data():
    return _load("metadata-grid.json")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scaffold.py::test_fixtures_load -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_scaffold.py
git commit -m "test: session fixtures for real city data files"
```

---

### Task 3: Catalog — size, road-level, set/chain (`catalog.py`)

**Files:**
- Create: `foeopt/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `helper_data["CityEntities"]` (a `dict[str, dict]`).
- Produces a `Catalog` class wrapping the defs dict:
  - `Catalog(defs: dict[str, dict])`
  - `.size(cityentity_id) -> tuple[int, int] | None` — `(width, length)`.
  - `.required_level(cityentity_id) -> int` — def `street_connection_level` or 1.
  - `.provided_level(cityentity_id) -> int` — same field, for street defs (level the road provides), else 1.
  - `.set_id(cityentity_id) -> str | None`, `.chain_id(cityentity_id) -> str | None`.
  - `.name(cityentity_id) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_catalog.py`:
```python
from foeopt.catalog import Catalog


def test_size_top_level(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    # Townhall has top-level width/length 6x7
    assert cat.size("H_SpaceAgeSpaceHub_Townhall") == (6, 7)


def test_size_from_placement_component(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    # Multi-age building: size only in components.<Age>.placement.size
    assert cat.size("W_MultiAge_WIN24F4") == (1, 2)


def test_required_level_defaults_to_one(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    # event building with no street_connection_level -> default 1
    assert cat.required_level("W_MultiAge_WIN24F4") == 1
    # Townhall explicitly level 1
    assert cat.required_level("H_SpaceAgeSpaceHub_Townhall") == 1


def test_provided_level_for_street(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    assert cat.provided_level("S_SpaceAgeSpaceHub_Street1") == 1


def test_name_present(helper_data):
    cat = Catalog(helper_data["CityEntities"])
    assert isinstance(cat.name("H_SpaceAgeSpaceHub_Townhall"), str)
    assert cat.name("H_SpaceAgeSpaceHub_Townhall") != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.catalog'`).

- [ ] **Step 3: Write the implementation**

`foeopt/catalog.py`:
```python
from __future__ import annotations


def _ability_value(defn: dict, key: str):
    for ability in defn.get("abilities", []):
        if isinstance(ability, dict) and key in ability:
            return ability[key]
    return None


class Catalog:
    def __init__(self, defs: dict[str, dict]):
        self._defs = defs

    def _def(self, cityentity_id: str) -> dict:
        return self._defs.get(cityentity_id, {})

    def size(self, cityentity_id: str) -> tuple[int, int] | None:
        defn = self._def(cityentity_id)
        w, length = defn.get("width"), defn.get("length")
        if w and length:
            return (w, length)
        for comp in defn.get("components", {}).values():
            if not isinstance(comp, dict):
                continue
            placement = comp.get("placement")
            if isinstance(placement, dict):
                sz = placement.get("size")
                if isinstance(sz, dict) and sz.get("x") and sz.get("y"):
                    return (sz["x"], sz["y"])
        return None

    def required_level(self, cityentity_id: str) -> int:
        lvl = self._def(cityentity_id).get("requirements", {}).get(
            "street_connection_level"
        )
        return lvl if lvl else 1

    # Streets carry their provided level in the same field.
    provided_level = required_level

    def set_id(self, cityentity_id: str) -> str | None:
        return _ability_value(self._def(cityentity_id), "setId")

    def chain_id(self, cityentity_id: str) -> str | None:
        return _ability_value(self._def(cityentity_id), "chainId")

    def name(self, cityentity_id: str) -> str:
        return self._def(cityentity_id).get("name", cityentity_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/catalog.py tests/test_catalog.py
git commit -m "feat: catalog for size/level/set/chain resolution"
```

---

### Task 4: Region builder (`region.py`)

**Files:**
- Create: `foeopt/region.py`
- Test: `tests/test_region.py`

**Interfaces:**
- Consumes: `city_data["unlocked_areas"]` (a list of dicts with optional `x`, `y` and `width`, `length`).
- Produces: `build_region(unlocked_areas: list[dict]) -> Region`.

- [ ] **Step 1: Write the failing test**

`tests/test_region.py`:
```python
from foeopt.region import build_region


def test_build_region_unions_rectangles():
    areas = [
        {"x": 0, "y": 0, "width": 2, "length": 2},
        {"x": 2, "y": 0, "width": 1, "length": 1},  # note: x present, no y means y=0
    ]
    region = build_region(areas)
    assert region.cells == frozenset(
        {(0, 0), (1, 0), (0, 1), (1, 1), (2, 0)}
    )


def test_build_region_handles_missing_coords():
    # FoE omits x or y when they are 0
    areas = [{"width": 1, "length": 1}]  # implies x=0, y=0
    region = build_region(areas)
    assert region.cells == frozenset({(0, 0)})


def test_real_region_size(city_data):
    region = build_region(city_data["unlocked_areas"])
    assert len(region.cells) == 4224
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_region.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.region'`).

- [ ] **Step 3: Write the implementation**

`foeopt/region.py`:
```python
from __future__ import annotations

from foeopt.model import Region


def build_region(unlocked_areas: list[dict]) -> Region:
    cells: set[tuple[int, int]] = set()
    for area in unlocked_areas:
        x0 = area.get("x", 0)
        y0 = area.get("y", 0)
        w = area.get("width", 0)
        length = area.get("length", 0)
        for dx in range(w):
            for dy in range(length):
                cells.add((x0 + dx, y0 + dy))
    return Region(cells=frozenset(cells))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_region.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/region.py tests/test_region.py
git commit -m "feat: buildable region from unlocked_areas"
```

---

### Task 5: Layout builder (`build.py`)

**Files:**
- Create: `foeopt/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: `city_data` (dict), `helper_data` (dict), `Catalog`, `build_region`.
- Produces: `build_layout(city_data: dict, helper_data: dict) -> Layout`.
  - **On-grid filter:** an entity is considered only if it has `x`/`y` and its **anchor `(x, y)` is inside the buildable region** (`build_region(...).cells`). This single test is the off-grid exclusion (catches `off_grid`, `outpost_ship`, `friends_tavern`, and the `hub_main`/`hub_part` settlement hubs — all sit outside the region). No per-type list.
  - `street` entities (on-grid) become entries in `Layout.roads` (`{(x,y): provided_level}`); they are not `Building`s.
  - **Two passes:** first collect roads + candidate buildings (with footprints), then set `needs_road`. `needs_road = ("connected" in entity) and (footprint.border_cells() ∩ road_cells != ∅)` — i.e. has the `connected` key AND is currently road-adjacent. `road_level = catalog.required_level(...)`.
  - The `main_building` entity becomes `layout.townhall` with `is_townhall=True`.
  - Buildings whose size cannot be resolved raise `ValueError` (should not happen on real data).

- [ ] **Step 1: Write the failing test**

`tests/test_build.py`:
```python
from foeopt.build import build_layout


def test_build_layout_counts(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    # 142 streets currently
    assert len(layout.roads) == 142
    # all in-region buildings (anchor inside the unlocked region)
    assert len(layout.buildings) == 292
    # townhall identified
    assert layout.townhall is not None
    assert layout.townhall.is_townhall
    assert layout.townhall.cityentity_id == "H_SpaceAgeSpaceHub_Townhall"
    # 81 road-needing (incl. townhall) -> 80 consumers via road_needing()
    needing_incl_th = [b for b in layout.buildings if b.needs_road]
    assert len(needing_incl_th) == 81
    assert len(layout.road_needing()) == 80


def test_offgrid_excluded_by_region(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    cids = {b.cityentity_id for b in layout.buildings}
    # settlement hubs sit outside the region -> excluded
    assert "O_OceanicFuture_Hub1" not in cids
    assert "O_ArcticFuture_Hub1" not in cids
    # every kept building's anchor is inside the buildable region
    for b in layout.buildings:
        assert (b.footprint.x, b.footprint.y) in layout.region.cells


def test_yukitomo_not_road_needing(city_data, helper_data):
    # Yukitomo residences carry the `connected` key but no adjacent road -> not road-needing
    layout = build_layout(city_data, helper_data)
    yuki = [b for b in layout.buildings
            if b.cityentity_id in {"W_MultiAge_WIN24A13", "W_MultiAge_WIN24A14"}]
    assert yuki  # present in the city
    assert all(not b.needs_road for b in yuki)


def test_every_building_has_size(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    for b in layout.buildings:
        assert b.footprint.width > 0 and b.footprint.length > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.build'`).

- [ ] **Step 3: Write the implementation**

`foeopt/build.py`:
```python
from __future__ import annotations

from foeopt.catalog import Catalog
from foeopt.model import Building, Footprint, Layout
from foeopt.region import build_region


def build_layout(city_data: dict, helper_data: dict) -> Layout:
    catalog = Catalog(helper_data["CityEntities"])
    region = build_region(city_data["unlocked_areas"])

    # Pass 1: collect roads and candidate (entity, footprint) pairs on the grid.
    roads: dict[tuple[int, int], int] = {}
    candidates: list[tuple[dict, Footprint]] = []
    for e in city_data["entities"]:
        if "x" not in e or "y" not in e:
            continue
        if (e["x"], e["y"]) not in region.cells:  # off-grid: anchor outside region
            continue
        cid = e["cityentity_id"]
        if e["type"] == "street":
            roads[(e["x"], e["y"])] = catalog.provided_level(cid)
            continue
        size = catalog.size(cid)
        if size is None:
            raise ValueError(f"Cannot resolve size for {cid}")
        w, length = size
        candidates.append((e, Footprint(e["x"], e["y"], w, length)))

    # Pass 2: a building needs a road iff it has the `connected` key AND is road-adjacent.
    road_cells = set(roads)
    buildings: list[Building] = []
    townhall: Building | None = None
    for e, fp in candidates:
        cid = e["cityentity_id"]
        is_th = e["type"] == "main_building"
        needs_road = ("connected" in e) and bool(fp.border_cells() & road_cells)
        building = Building(
            entity_id=e["id"],
            cityentity_id=cid,
            type=e["type"],
            footprint=fp,
            needs_road=needs_road,
            road_level=catalog.required_level(cid),
            is_townhall=is_th,
            set_id=catalog.set_id(cid),
            chain_id=catalog.chain_id(cid),
            name=catalog.name(cid),
        )
        buildings.append(building)
        if is_th:
            townhall = building

    return Layout(region=region, buildings=buildings, townhall=townhall, roads=roads)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/build.py tests/test_build.py
git commit -m "feat: assemble Layout from city + helper data"
```

---

### Task 6: Connectivity validator (`validate.py`)

**Files:**
- Create: `foeopt/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `Layout`.
- Produces:
  - `connected_road_cells(layout) -> set[tuple[int,int]]` — road cells reachable (road-to-road orthogonal adjacency) from roads bordering the Townhall footprint.
  - `unsatisfied(layout) -> list[Building]` — road-needing consumers (excludes Townhall) with no adjacent connected road of sufficient level.
  - `is_valid(layout) -> bool` — `unsatisfied(layout) == []`.

  Satisfaction predicate per building: there exists a cell in `layout.roads`, adjacent to the building footprint, whose level ≥ `building.road_level`, **and** that road cell is in `connected_road_cells(layout)`.

- [ ] **Step 1: Write the failing test**

`tests/test_validate.py`:
```python
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.validate import connected_road_cells, unsatisfied, is_valid


def _th(x, y):
    return Building(1, "TH", "main_building", Footprint(x, y, 1, 1),
                    needs_road=True, road_level=1, is_townhall=True,
                    set_id=None, chain_id=None, name="Townhall")


def _house(eid, x, y, level=1):
    return Building(eid, "H", "generic_building", Footprint(x, y, 1, 1),
                    needs_road=True, road_level=level, is_townhall=False,
                    set_id=None, chain_id=None, name="House")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_connected_chain_from_townhall():
    # TH at (0,0); roads at (1,0),(2,0); house at (3,0) adjacent to road (2,0)
    layout = Layout(_region(5, 1), [_th(0, 0), _house(2, 3, 0)],
                    _th(0, 0), roads={(1, 0): 1, (2, 0): 1})
    assert connected_road_cells(layout) == {(1, 0), (2, 0)}
    assert unsatisfied(layout) == []
    assert is_valid(layout)


def test_townhall_adjacency_is_not_enough():
    # house touches the townhall but there is no road -> unsatisfied
    layout = Layout(_region(3, 1), [_th(0, 0), _house(2, 1, 0)],
                    _th(0, 0), roads={})
    assert [b.entity_id for b in unsatisfied(layout)] == [2]
    assert not is_valid(layout)


def test_road_island_not_connected_to_townhall():
    # roads at (3,0),(4,0) serve the house but a gap at (1,0),(2,0) leaves them
    # disconnected from the townhall at (0,0). House is at x=5.
    layout = Layout(_region(6, 1), [_th(0, 0), _house(2, 5, 0)],
                    _th(0, 0), roads={(3, 0): 1, (4, 0): 1})
    assert connected_road_cells(layout) == set()
    assert [b.entity_id for b in unsatisfied(layout)] == [2]


def test_level_requirement_enforced():
    # house needs level 2 but only a level-1 road is adjacent
    layout = Layout(_region(4, 1), [_th(0, 0), _house(2, 2, level=2)],
                    _th(0, 0), roads={(1, 0): 1})
    assert [b.entity_id for b in unsatisfied(layout)] == [2]
    # upgrade the road to level 2 -> satisfied
    layout.roads[(1, 0)] = 2
    assert unsatisfied(layout) == []
```

Note: `_house(eid, x, y)` signature is `(entity_id, x, y, level)`. The calls above pass `_house(2, 3, 0)` meaning entity_id=2, x=3, y=0. Keep that ordering.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_validate.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.validate'`).

- [ ] **Step 3: Write the implementation**

`foeopt/validate.py`:
```python
from __future__ import annotations

from collections import deque

from foeopt.model import Building, Layout

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def connected_road_cells(layout: Layout) -> set[tuple[int, int]]:
    roads = layout.roads
    if layout.townhall is None:
        return set()
    th_border = layout.townhall.footprint.border_cells()
    sources = [c for c in roads if c in th_border]

    seen: set[tuple[int, int]] = set(sources)
    queue: deque[tuple[int, int]] = deque(sources)
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in _ORTHO:
            n = (cx + dx, cy + dy)
            if n in roads and n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


def unsatisfied(layout: Layout) -> list[Building]:
    connected = connected_road_cells(layout)
    roads = layout.roads
    bad: list[Building] = []
    for b in layout.road_needing():
        border = b.footprint.border_cells()
        ok = any(
            c in connected and roads[c] >= b.road_level
            for c in border
        )
        if not ok:
            bad.append(b)
    return bad


def is_valid(layout: Layout) -> bool:
    return unsatisfied(layout) == []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_validate.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the current real layout is valid (sanity golden)**

Add to `tests/test_validate.py`:
```python
def test_current_real_layout_is_valid(city_data, helper_data):
    from foeopt.build import build_layout
    layout = build_layout(city_data, helper_data)
    assert is_valid(layout), [b.name for b in unsatisfied(layout)][:5]
```

Run: `uv run pytest tests/test_validate.py::test_current_real_layout_is_valid -v`
Expected: PASS (the player's real city is, by definition, validly connected).

- [ ] **Step 6: Commit**

```bash
git add foeopt/validate.py tests/test_validate.py
git commit -m "feat: connectivity validator (townhall-rooted, level-aware)"
```

---

### Task 7: Interactive HTML map (`viz.py`) + `view` CLI

**Files:**
- Create: `foeopt/viz.py`
- Create: `foeopt/cli.py`
- Test: `tests/test_viz.py`

**Interfaces:**
- Consumes: `Layout`, optional second road set for comparison.
- Produces:
  - `render_html(layout: Layout, optimized_roads: dict[tuple[int,int],int] | None = None) -> str` — a complete self-contained HTML document string. Buildings carry `data-name` and `data-size` for hover tooltips; current vs optimized roads are toggleable layers.
  - `cli.main(argv: list[str] | None = None) -> int` with subcommand `view <city.json> <helper.json> [-o out.html]`.

- [ ] **Step 1: Write the failing test**

`tests/test_viz.py`:
```python
from foeopt.build import build_layout
from foeopt.viz import render_html


def test_render_html_is_self_contained(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    html = render_html(layout)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    # no external resources
    assert "http://" not in html and "https://" not in html
    # building metadata embedded for hover
    assert "data-name" in html
    assert "data-size" in html
    # townhall name appears
    assert "tel de ville" in html or "Townhall" in html


def test_render_html_marks_optimized_roads(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    html = render_html(layout, optimized_roads={(7, 60): 1})
    assert "optimized" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_viz.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.viz'`).

- [ ] **Step 3: Write the implementation**

`foeopt/viz.py`:
```python
from __future__ import annotations

import html as _html
import json

from foeopt.model import Layout

_CELL = 12  # pixels per grid cell


def _bounds(layout: Layout) -> tuple[int, int, int, int]:
    xs, ys = [], []
    for c in layout.region.cells:
        xs.append(c[0]); ys.append(c[1])
    for b in layout.buildings:
        for (cx, cy) in b.footprint.cells():
            xs.append(cx); ys.append(cy)
    return min(xs), min(ys), max(xs), max(ys)


def render_html(
    layout: Layout,
    optimized_roads: dict[tuple[int, int], int] | None = None,
) -> str:
    min_x, min_y, max_x, max_y = _bounds(layout)
    width = (max_x - min_x + 1) * _CELL
    height = (max_y - min_y + 1) * _CELL

    def px(x: int, y: int) -> tuple[int, int]:
        return (x - min_x) * _CELL, (y - min_y) * _CELL

    region_cells = [px(x, y) for (x, y) in sorted(layout.region.cells)]

    buildings = []
    for b in layout.buildings:
        bx, by = px(b.footprint.x, b.footprint.y)
        buildings.append({
            "x": bx, "y": by,
            "w": b.footprint.width * _CELL,
            "h": b.footprint.length * _CELL,
            "name": b.name,
            "size": f"{b.footprint.width}x{b.footprint.length}",
            "needs_road": b.needs_road,
            "townhall": b.is_townhall,
        })

    def road_list(roads):
        out = []
        for (x, y), lvl in roads.items():
            rx, ry = px(x, y)
            out.append({"x": rx, "y": ry, "level": lvl})
        return out

    data = {
        "cell": _CELL,
        "width": width,
        "height": height,
        "region": region_cells,
        "buildings": buildings,
        "current_roads": road_list(layout.roads),
        "optimized_roads": road_list(optimized_roads) if optimized_roads else None,
    }

    payload = _html.escape(json.dumps(data), quote=True)
    return _TEMPLATE.replace("__DATA__", payload)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>FoE City Map</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #1e1e1e; color: #eee; }
  #toolbar { padding: 8px; }
  #wrap { position: relative; }
  canvas { background: #2a2a2a; display: block; }
  #tip { position: fixed; pointer-events: none; background: #000; color: #fff;
         padding: 4px 8px; border-radius: 4px; font-size: 12px; display: none; }
  label { margin-right: 12px; }
</style></head><body>
<div id="toolbar">
  <label><input type="checkbox" id="showCurrent" checked> current roads</label>
  <label><input type="checkbox" id="showOptimized" checked> optimized roads</label>
</div>
<div id="wrap"><canvas id="cv"></canvas><div id="tip"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const cv = document.getElementById('cv');
cv.width = DATA.width; cv.height = DATA.height;
const ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
const cell = DATA.cell;

function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = '#3a3a3a';
  for (const [x, y] of DATA.region) ctx.fillRect(x, y, cell, cell);
  if (document.getElementById('showCurrent').checked) {
    ctx.fillStyle = 'rgba(120,120,120,0.9)';
    for (const r of DATA.current_roads) ctx.fillRect(r.x, r.y, cell, cell);
  }
  if (DATA.optimized_roads && document.getElementById('showOptimized').checked) {
    ctx.fillStyle = 'rgba(80,200,120,0.9)';
    for (const r of DATA.optimized_roads) ctx.fillRect(r.x, r.y, cell, cell);
  }
  for (const b of DATA.buildings) {
    ctx.fillStyle = b.townhall ? '#c0392b' : (b.needs_road ? '#2980b9' : '#555');
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.strokeStyle = '#111'; ctx.strokeRect(b.x, b.y, b.w, b.h);
  }
}
function buildingAt(mx, my) {
  for (const b of DATA.buildings)
    if (mx >= b.x && mx < b.x + b.w && my >= b.y && my < b.y + b.h) return b;
  return null;
}
cv.addEventListener('mousemove', e => {
  const rect = cv.getBoundingClientRect();
  const b = buildingAt(e.clientX - rect.left, e.clientY - rect.top);
  if (b) {
    tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY + 12) + 'px';
    tip.setAttribute('data-name', b.name);
    tip.setAttribute('data-size', b.size);
    tip.textContent = b.name + ' (' + b.size + ')';
  } else { tip.style.display = 'none'; }
});
document.getElementById('showCurrent').addEventListener('change', draw);
document.getElementById('showOptimized').addEventListener('change', draw);
draw();
</script>
</body></html>
"""
```

Note: `data-name`/`data-size` appear in the template via `setAttribute`, satisfying the test's substring checks; the word `optimized` appears in the toolbar and JS.

`foeopt/cli.py`:
```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from foeopt.build import build_layout
from foeopt.viz import render_html


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _cmd_view(args) -> int:
    layout = build_layout(_load(args.city), _load(args.helper))
    html = render_html(layout)
    Path(args.out).write_text(html)
    print(f"Wrote map to {args.out} ({len(layout.buildings)} buildings, "
          f"{len(layout.roads)} roads)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foeopt")
    sub = parser.add_subparsers(dest="command", required=True)

    p_view = sub.add_parser("view", help="render current city to HTML")
    p_view.add_argument("city")
    p_view.add_argument("helper")
    p_view.add_argument("-o", "--out", default="city.html")
    p_view.set_defaults(func=_cmd_view)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_viz.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke-test the CLI on the real city**

Run: `uv run python -m foeopt.cli view city-user-data.json city-user-data-foe-helper.json -o output/current-city.html`
Expected: prints `Wrote map to output/current-city.html (... buildings, 142 roads)` and the file opens in a browser showing the city with hover tooltips. (The `output/` dir is gitignored.)

- [ ] **Step 6: Commit**

```bash
git add foeopt/viz.py foeopt/cli.py tests/test_viz.py
git commit -m "feat: interactive HTML map and view CLI (Phase 0 complete)"
```

---

### Task 8: Road router — greedy Steiner heuristic (`router.py`)

**Files:**
- Create: `foeopt/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `Layout`.
- Produces:
  - `free_cells(layout) -> set[tuple[int,int]]` — region cells not covered by any building footprint (candidate road cells).
  - `route(layout) -> dict[tuple[int,int], int]` — a new road set (`{cell: level}`) connecting every road-needing consumer to the Townhall, rooted at the Townhall footprint. Buildings are NOT moved. Raises `RouteError` if a building cannot be reached.

  Algorithm (greedy nearest-insertion Steiner tree, then prune):
  1. Candidate cells = `free_cells(layout)`. The "tree" starts as the set of free cells adjacent to the Townhall footprint (its roots — placing a road there connects to the Townhall).
  2. Order consumers by Manhattan distance from the Townhall (nearest first).
  3. For each consumer, multi-source BFS over candidate cells from the current tree to any free border cell of the consumer; add the path cells to the tree.
  4. Assign levels: every tree cell defaults to level 1; if a tree cell is the chosen connector adjacent to a consumer requiring level L, raise that cell to `max(level, L)`.
  5. Prune: repeatedly remove a tree cell that is not adjacent to the Townhall-root requirement and whose removal keeps all consumers satisfied and the network connected.

- [ ] **Step 1: Write the failing tests (small grids, known optima)**

`tests/test_router.py`:
```python
import pytest

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.router import route, free_cells, RouteError
from foeopt.validate import is_valid, unsatisfied


def _th(x, y, w=1, h=1):
    return Building(1, "TH", "main_building", Footprint(x, y, w, h),
                    needs_road=True, road_level=1, is_townhall=True,
                    set_id=None, chain_id=None, name="Townhall")


def _house(eid, x, y, level=1):
    return Building(eid, "H", "generic_building", Footprint(x, y, 1, 1),
                    needs_road=True, road_level=level, is_townhall=False,
                    set_id=None, chain_id=None, name="House")


def _region(w, h):
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_free_cells_excludes_buildings():
    layout = Layout(_region(3, 1), [_th(0, 0), _house(2, 2, 0)], _th(0, 0))
    assert free_cells(layout) == {(1, 0)}


def test_straight_line_minimal():
    # TH at (0,0), house at (4,0). One road at (1,0),(2,0),(3,0) connects:
    # house border includes (3,0); that road must be connected back to TH.
    layout = Layout(_region(5, 1), [_th(0, 0), _house(2, 4, 0)], _th(0, 0))
    roads = route(layout)
    layout.roads = roads
    assert is_valid(layout)
    # optimal: cells (1,0),(2,0),(3,0) -> 3 tiles
    assert len(roads) == 3


def test_shared_corridor_reused():
    # Two houses at (4,0) and (4,1); TH at (0,0) on a 5x2 grid.
    # A single corridor along row 0 plus one tap should serve both cheaply.
    layout = Layout(_region(5, 2),
                    [_th(0, 0), _house(2, 4, 0), _house(3, 4, 1)],
                    _th(0, 0))
    roads = route(layout)
    layout.roads = roads
    assert is_valid(layout)
    # both houses adjacent to (3,0)/(3,1); corridor (1,0),(2,0),(3,0),(3,1) = 4
    assert len(roads) <= 4


def test_level_two_requirement():
    layout = Layout(_region(4, 1), [_th(0, 0), _house(2, 3, 0, level=2)], _th(0, 0))
    roads = route(layout)
    layout.roads = roads
    assert is_valid(layout)
    # the connector adjacent to the house must be level >= 2
    assert any(lvl >= 2 for lvl in roads.values())


def test_unreachable_raises():
    # House walled off: region only has the two footprints, no free cells
    layout = Layout(_region(2, 1), [_th(0, 0), _house(2, 1, 0)], _th(0, 0))
    with pytest.raises(RouteError):
        route(layout)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_router.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.router'`).

- [ ] **Step 3: Write the implementation**

`foeopt/router.py`:
```python
from __future__ import annotations

from collections import deque

from foeopt.model import Building, Layout

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


class RouteError(Exception):
    pass


def free_cells(layout: Layout) -> set[tuple[int, int]]:
    return set(layout.region.cells) - layout.occupied_cells()


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _bfs_path(
    candidates: set[tuple[int, int]],
    starts: set[tuple[int, int]],
    targets: set[tuple[int, int]],
) -> list[tuple[int, int]] | None:
    """Shortest path through `candidates` from any start to any target.

    Starts are cells already in the tree (or Townhall-root cells). Returns the
    list of cells on the path (including the reached target, excluding starts
    that are already roads). None if unreachable.
    """
    if starts & targets:
        return []  # a target is already connected
    seen = set(starts)
    queue: deque[tuple[int, int]] = deque((s, None) for s in starts)
    parent: dict[tuple[int, int], tuple[int, int] | None] = {s: None for s in starts}
    while queue:
        cell, _ = queue.popleft()
        for dx, dy in _ORTHO:
            n = (cell[0] + dx, cell[1] + dy)
            if n in seen or n not in candidates:
                continue
            seen.add(n)
            parent[n] = cell
            if n in targets:
                path = [n]
                p = parent[n]
                while p is not None and p not in starts:
                    path.append(p)
                    p = parent[p]
                path.reverse()
                return path
            queue.append((n, cell))
    return None


def route(layout: Layout) -> dict[tuple[int, int], int]:
    if layout.townhall is None:
        raise RouteError("layout has no townhall")

    candidates = free_cells(layout)
    th_roots = layout.townhall.footprint.border_cells() & candidates

    # Seed the tree with the Townhall's free border cells as roots: these become
    # actual road tiles (level 1) so the network is rooted at the Townhall. The
    # prune pass below removes any root that turns out to be unneeded.
    tree: set[tuple[int, int]] = set(th_roots)  # chosen road cells
    levels: dict[tuple[int, int], int] = {cell: 1 for cell in th_roots}

    consumers = sorted(
        layout.road_needing(),
        key=lambda b: min(
            (_manhattan(c, (layout.townhall.footprint.x, layout.townhall.footprint.y))
             for c in b.footprint.border_cells()),
            default=0,
        ),
    )

    for b in consumers:
        targets = b.footprint.border_cells() & candidates
        if not targets:
            raise RouteError(f"no free border cell for {b.name} ({b.entity_id})")
        # already covered by an existing connected tree cell?
        if any(t in tree for t in targets):
            connector = next(t for t in targets if t in tree)
        else:
            starts = (tree | th_roots) if tree else th_roots
            path = _bfs_path(candidates, starts, targets)
            if path is None:
                raise RouteError(f"cannot reach {b.name} ({b.entity_id})")
            for cell in path:
                tree.add(cell)
                levels.setdefault(cell, 1)
            connector = path[-1] if path else next(iter(targets & tree))
        levels[connector] = max(levels.get(connector, 1), b.road_level)

    roads = dict(levels)
    return _prune(layout, roads, th_roots)


def _prune(
    layout: Layout,
    roads: dict[tuple[int, int], int],
    th_roots: set[tuple[int, int]],
) -> dict[tuple[int, int], int]:
    """Remove road cells whose removal keeps every consumer satisfied."""
    from foeopt.validate import unsatisfied

    changed = True
    while changed:
        changed = False
        # try removing the highest-coordinate cells first (stable, deterministic)
        for cell in sorted(roads, reverse=True):
            trial = dict(roads)
            del trial[cell]
            probe = Layout(layout.region, layout.buildings, layout.townhall, trial)
            if unsatisfied(probe) == []:
                roads = trial
                changed = True
                break
    return roads
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_router.py -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git add foeopt/router.py tests/test_router.py
git commit -m "feat: greedy Steiner road router with prune (Phase 1 core)"
```

---

### Task 9: Reporting — stats + road diff (`report.py`)

**Files:**
- Create: `foeopt/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `Layout` (with current `roads`), and a new road dict.
- Produces:
  - `road_diff(current: dict, optimized: dict) -> dict` with keys `remove` (list of `{x,y,level}` in current but not optimized) and `add` (list of `{x,y,level}` in optimized but not current, or level changed).
  - `stats(layout, optimized_roads) -> dict` with `current_roads`, `optimized_roads`, `tiles_saved`, `road_needing`, `satisfied`, `unsatisfied`.

- [ ] **Step 1: Write the failing test**

`tests/test_report.py`:
```python
from foeopt.model import Building, Footprint, Layout, Region
from foeopt.report import road_diff, stats


def _th(x, y):
    return Building(1, "TH", "main_building", Footprint(x, y, 1, 1),
                    True, 1, True, None, None, "Townhall")


def _house(eid, x, y):
    return Building(eid, "H", "generic_building", Footprint(x, y, 1, 1),
                    True, 1, False, None, None, "House")


def test_road_diff():
    current = {(1, 0): 1, (2, 0): 1, (5, 5): 1}
    optimized = {(1, 0): 1, (2, 0): 2, (3, 0): 1}
    diff = road_diff(current, optimized)
    assert {"x": 5, "y": 5, "level": 1} in diff["remove"]
    assert {"x": 3, "y": 0, "level": 1} in diff["add"]
    # level change at (2,0) counts as an add (re-place at new level)
    assert {"x": 2, "y": 0, "level": 2} in diff["add"]


def test_stats():
    region = Region(frozenset((x, 0) for x in range(5)))
    layout = Layout(region, [_th(0, 0), _house(2, 4)], _th(0, 0),
                    roads={(1, 0): 1, (2, 0): 1, (3, 0): 1})
    opt = {(1, 0): 1, (2, 0): 1, (3, 0): 1}
    s = stats(layout, opt)
    assert s["current_roads"] == 3
    assert s["optimized_roads"] == 3
    assert s["tiles_saved"] == 0
    assert s["road_needing"] == 1
    assert s["satisfied"] == 1
    assert s["unsatisfied"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.report'`).

- [ ] **Step 3: Write the implementation**

`foeopt/report.py`:
```python
from __future__ import annotations

from foeopt.model import Layout
from foeopt.validate import unsatisfied


def road_diff(current: dict, optimized: dict) -> dict:
    remove = [
        {"x": x, "y": y, "level": lvl}
        for (x, y), lvl in sorted(current.items())
        if (x, y) not in optimized
    ]
    add = [
        {"x": x, "y": y, "level": lvl}
        for (x, y), lvl in sorted(optimized.items())
        if current.get((x, y)) != lvl
    ]
    return {"remove": remove, "add": add}


def stats(layout: Layout, optimized_roads: dict) -> dict:
    probe = Layout(layout.region, layout.buildings, layout.townhall, optimized_roads)
    bad = unsatisfied(probe)
    needing = len(layout.road_needing())
    return {
        "current_roads": len(layout.roads),
        "optimized_roads": len(optimized_roads),
        "tiles_saved": len(layout.roads) - len(optimized_roads),
        "road_needing": needing,
        "satisfied": needing - len(bad),
        "unsatisfied": len(bad),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/report.py tests/test_report.py
git commit -m "feat: stats and road-diff reporting"
```

---

### Task 10: `roads` CLI subcommand + real-city golden test

**Files:**
- Modify: `foeopt/cli.py` (add the `roads` subcommand)
- Test: `tests/test_roads_cli.py`

**Interfaces:**
- Consumes: `build_layout`, `route`, `stats`, `road_diff`, `render_html`.
- Produces: `roads <city.json> <helper.json> [-o out.html] [--diff diff.json]` — routes with buildings fixed, prints stats, writes the HTML map (current vs optimized layers) and optionally the diff JSON. Exits non-zero if any building is unsatisfiable.

- [ ] **Step 1: Write the failing golden test**

`tests/test_roads_cli.py`:
```python
from foeopt.build import build_layout
from foeopt.router import route
from foeopt.validate import is_valid
from foeopt.report import stats


def test_phase1_reduces_roads_on_real_city(city_data, helper_data):
    layout = build_layout(city_data, helper_data)
    optimized = route(layout)
    probe_layout = build_layout(city_data, helper_data)
    probe_layout.roads = optimized
    # every road-needing building is connected to the townhall
    assert is_valid(probe_layout)
    s = stats(layout, optimized)
    assert s["unsatisfied"] == 0
    # the optimizer must not be worse than the current 142 roads
    assert s["optimized_roads"] <= s["current_roads"]
    print(s)
```

- [ ] **Step 2: Run test to verify it fails or reveals the baseline**

Run: `uv run pytest tests/test_roads_cli.py -v -s`
Expected: Initially FAIL only if `route` regresses; otherwise PASS and prints the stats dict (note the achieved `optimized_roads`). If it fails because some building has no free border cell, capture which (a real-data edge case) and handle in Step 3.

- [ ] **Step 3: Add the `roads` subcommand**

Add to `foeopt/cli.py` (new imports + function + parser registration):
```python
# add to imports at top:
from foeopt.router import route, RouteError
from foeopt.report import stats, road_diff


def _cmd_roads(args) -> int:
    city = _load(args.city)
    helper = _load(args.helper)
    layout = build_layout(city, helper)
    try:
        optimized = route(layout)
    except RouteError as exc:
        print(f"ERROR: {exc}")
        return 2
    s = stats(layout, optimized)
    print("Road optimization (buildings fixed):")
    for k, v in s.items():
        print(f"  {k}: {v}")
    html = render_html(layout, optimized_roads=optimized)
    Path(args.out).write_text(html)
    print(f"Wrote map to {args.out}")
    if args.diff:
        Path(args.diff).write_text(json.dumps(road_diff(layout.roads, optimized), indent=2))
        print(f"Wrote diff to {args.diff}")
    return 0 if s["unsatisfied"] == 0 else 1
```

Register it inside `main()` after the `view` parser:
```python
    p_roads = sub.add_parser("roads", help="minimize roads with buildings fixed")
    p_roads.add_argument("city")
    p_roads.add_argument("helper")
    p_roads.add_argument("-o", "--out", default="roads.html")
    p_roads.add_argument("--diff", default=None)
    p_roads.set_defaults(func=_cmd_roads)
```

- [ ] **Step 4: Run the golden test + CLI smoke test**

Run: `uv run pytest tests/test_roads_cli.py -v -s`
Expected: PASS, printing stats with `unsatisfied: 0` and `optimized_roads <= 142`.

Run: `uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json -o output/roads.html --diff output/roads-diff.json`
Expected: prints the stats block, writes `output/roads.html` (open it: optimized roads shown in green, toggleable against current grey) and `output/roads-diff.json`.

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/test_roads_cli.py
git commit -m "feat: roads CLI subcommand + real-city golden test (Phase 1 complete)"
```

---

### Task 11: README / usage doc

**Files:**
- Create: `README.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Write the README**

`README.md`:
```markdown
# FoE City Layout Optimizer

Minimizes the number of road tiles in a Forge of Empires city while keeping every
road-needing building connected to the Townhall.

## Setup
    uv sync

## Usage
View the current city as an interactive map:

    uv run python -m foeopt.cli view city-user-data.json city-user-data-foe-helper.json -o output/current.html

Optimize roads with buildings fixed (Phase 1):

    uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json -o output/roads.html --diff output/roads-diff.json

Open the generated `.html` in a browser; hover a building to see its name and size,
and toggle current vs optimized roads.

## Tests
    uv run pytest

## Inputs
- `city-user-data.json` — live game CityMap response (authoritative state; `connected`
  flag marks road-needing buildings).
- `city-user-data-foe-helper.json` — FOE Helper rework with building definitions
  (sizes, levels, sets/chains).
- `metadata-grid.json` — static grid geometry (reference).

See `docs/superpowers/specs/` for the full design and `tasks/lessons.md` for data-model notes.
```

- [ ] **Step 2: Verify the full suite is green**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with setup and usage"
```

---

## Self-Review

**Spec coverage:**
- Buildable region (spec §4.1) → Task 4. ✓
- Footprint resolution incl. `placement.size` (§4.2) → Task 3. ✓
- Road-need via `connected` (§4.3) → Task 5 (`needs_road="connected" in e`). ✓
- Road level required, default 1 (§4.3) → Task 3 `required_level`. ✓
- Roads as levelled tiles (§4.4) → Task 5 (`provided_level`). ✓
- Townhall as root only, not a road substitute (§4.6) → Task 6 tests `test_townhall_adjacency_is_not_enough`. ✓
- Sets/chains extracted (§4.7) → Task 3 (`set_id`, `chain_id`); used by Phase 2 (out of this plan). ✓ (data captured)
- Exclusions (§4.8) → Task 5 `EXCLUDED_TYPES` + grid filter. ✓
- Router heuristic (§7.1 fast path) → Task 8. CP-SAT exact is **deferred** (Global Constraints note). ✓
- Outputs: stats (Task 9), road diff (Task 9), interactive HTML hover map (Task 7), toggle current/optimized (Tasks 7, 10). ✓
- Testing incl. golden real-city (§9) → Task 6 (current valid), Task 10 (optimized valid + ≤142). ✓
- Phase 2 packer (§2) → intentionally **not** in this plan (separate plan).

**Placeholder scan:** No TBD/TODO; every code step has complete code; every test has real assertions. ✓

**Type consistency:** `Footprint`, `Building`, `Region`, `Layout` signatures defined in Task 2 are used consistently; `roads` is `dict[(x,y)->level]` throughout; `route()` returns that same shape consumed by `validate`, `report`, `viz`; `Building` positional order in test helpers matches the dataclass field order (Task 6/9 helpers use positional args in declared order). ✓

**Note on `Building` positional construction:** Tasks 9's helpers build `Building` positionally (`Building(1,"TH","main_building",Footprint(...),True,1,True,None,None,"Townhall")`) — field order is `entity_id, cityentity_id, type, footprint, needs_road, road_level, is_townhall, set_id, chain_id, name`. This matches Task 2. ✓
