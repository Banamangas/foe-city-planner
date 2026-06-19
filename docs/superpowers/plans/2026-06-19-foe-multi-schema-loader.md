# FoE Optimizer — Multi-Schema Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every `foeopt` command load any FOE-Helper export — two-file old, single combined-old (`city.txt`), and single combined-new (`darkzig.json`, with `coords`/`size`/`needsStreet` and a UTF-8 BOM) — via an auto-detecting loader, with full backward compatibility.

**Architecture:** A new `foeopt/loader.py` with a BOM-safe `read_json`, a combined-file assembler `_build_combined` that handles both old- and new-style entities per-entity, and a `load_layout(city, helper=None)` dispatcher. The existing `build_layout(city_data, helper_data)` is left untouched (split-old delegates to it). The CLI's `helper` arg becomes optional and all commands call `load_layout`.

**Tech Stack:** Python 3.12, `uv`, `pytest`. Standard library only. Reuses `foeopt.model/region/catalog/build`.

## Global Constraints

- Python **3.12**; standard library only; dev dep `pytest`. Test runner: `uv run pytest`.
- Coordinates are `(x, y)` integer tuples; `x` → width, `y` → length. **No rotation.**
- **Auto-detect, no flags.** File-level: top-level `entities` (list) → split-old (helper required); top-level `CityMapData` (dict) → combined. Per-entity: has `coords` → new-style; else old-style.
- **New-style road-need is authoritative:** `needs_road = needsStreet > 0`, `road_level = needsStreet` (≥1). For a new-style `street`, `needsStreet` is the level it provides (default 1 if 0/absent).
- **Old-style road-need unchanged:** `("connected" in entity) and road-adjacent`; level from def `street_connection_level` else 1.
- **Off-grid = footprint anchor not in the region** (union of `UnlockedAreas`). This is the only placement exclusion (no per-type list). Plus: `isInInventory: true` excluded.
- `street` entities expand all footprint cells into the road set at their level (`roads[cell] = max(existing, level)`); they are never buildings.
- **BOM-safe:** read files with `utf-8-sig`.
- **Back-compat:** `build_layout` keeps its signature/behavior; existing tests (sample: 314 buildings / 142 roads / 82 consumers) stay green. Combined files **skip** entities with unresolvable size; the old two-file `build_layout` keeps its existing `ValueError` contract.
- Reuse `foeopt.catalog.Catalog`, `foeopt.region.build_region`, `foeopt.model` (`Building`, `Footprint`, `Layout`), `foeopt.build.build_layout`.

---

### Task 1: BOM-safe JSON reader (`loader.py`)

**Files:**
- Create: `foeopt/loader.py`
- Test: `tests/test_loader.py`

**Interfaces:**
- Produces: `read_json(path: str) -> dict` — reads a file with `utf-8-sig` (tolerating a leading UTF-8 BOM) and returns the parsed JSON object.

- [ ] **Step 1: Write the failing test**

`tests/test_loader.py`:
```python
import json
from foeopt.loader import read_json


def test_read_json_plain(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text(json.dumps({"a": 1, "b": [2, 3]}), encoding="utf-8")
    assert read_json(str(p)) == {"a": 1, "b": [2, 3]}


def test_read_json_with_bom(tmp_path):
    p = tmp_path / "bom.json"
    # write a UTF-8 BOM followed by JSON
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"x": 5}).encode("utf-8"))
    assert read_json(str(p)) == {"x": 5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loader.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'foeopt.loader'`).

- [ ] **Step 3: Write the implementation**

`foeopt/loader.py`:
```python
from __future__ import annotations

import json

from foeopt.build import build_layout
from foeopt.catalog import Catalog
from foeopt.model import Building, Footprint, Layout
from foeopt.region import build_region


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_loader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/loader.py tests/test_loader.py
git commit -m "feat: BOM-safe JSON reader"
```

---

### Task 2: Combined-file assembler (`loader.py`)

**Files:**
- Modify: `foeopt/loader.py`
- Test: `tests/test_loader.py`

**Interfaces:**
- Consumes: `Catalog`, `build_region`, `Building`, `Footprint`, `Layout`.
- Produces: `_build_combined(data: dict) -> Layout` — builds a `Layout` from a combined file dict (`CityMapData` dict + `UnlockedAreas` + `CityEntities`), handling both old- and new-style entities per-entity. Plus helpers `_entity_coords(e) -> tuple[int,int]`, `_entity_size(e, catalog) -> tuple[int,int] | None`, `_cid(e) -> str`.
  - Excludes `isInInventory` and entities whose anchor is outside the region; skips entities with unresolvable size.
  - `street` entities expand footprint cells into `roads` at their level.
  - Road-need: new-style (`needsStreet` present) → `needsStreet > 0` / level `needsStreet or 1`; old-style → `("connected" in e) and border∩roads` / level `catalog.required_level`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loader.py`:
```python
from foeopt.loader import _build_combined


def _area(x, y, w, l):
    return {"x": x, "y": y, "width": w, "length": l}


def test_build_combined_new_schema():
    # 8x8 region; new-style entities with coords/size/needsStreet
    data = {
        "UnlockedAreas": [_area(0, 0, 8, 8)],
        "CityEntities": {},
        "CityMapData": {
            "1": {"id": 1, "entityId": "TH", "type": "main_building",
                  "coords": {"x": 0, "y": 0}, "size": {"width": 2, "length": 2},
                  "needsStreet": 1, "isInInventory": False, "name": "Townhall"},
            "2": {"id": 2, "entityId": "H", "type": "residential",
                  "coords": {"x": 3, "y": 0}, "size": {"width": 2, "length": 2},
                  "needsStreet": 1, "isInInventory": False, "name": "House"},
            "3": {"id": 3, "entityId": "D", "type": "decoration",
                  "coords": {"x": 0, "y": 3}, "size": {"width": 1, "length": 1},
                  "needsStreet": 0, "isInInventory": False, "name": "Deco"},
            "4": {"id": 4, "entityId": "S", "type": "street",
                  "coords": {"x": 2, "y": 0}, "size": {"width": 1, "length": 1},
                  "needsStreet": 1, "isInInventory": False, "name": "Road"},
            "5": {"id": 5, "entityId": "INV", "type": "residential",
                  "coords": {"x": 6, "y": 6}, "size": {"width": 1, "length": 1},
                  "needsStreet": 1, "isInInventory": True, "name": "Stored"},
        },
    }
    layout = _build_combined(data)
    ids = {b.entity_id for b in layout.buildings}
    assert ids == {1, 2, 3}                       # street + inventory excluded
    assert layout.roads == {(2, 0): 1}            # street cell in road set
    assert layout.townhall is not None and layout.townhall.entity_id == 1
    by_id = {b.entity_id: b for b in layout.buildings}
    assert by_id[2].needs_road and by_id[2].road_level == 1   # needsStreet=1
    assert not by_id[3].needs_road                            # needsStreet=0


def test_build_combined_excludes_out_of_region():
    data = {
        "UnlockedAreas": [_area(0, 0, 4, 4)],
        "CityEntities": {},
        "CityMapData": {
            "1": {"id": 1, "entityId": "A", "type": "residential",
                  "coords": {"x": -2, "y": 0}, "size": {"width": 1, "length": 1},
                  "needsStreet": 0, "isInInventory": False, "name": "Off"},
        },
    }
    assert _build_combined(data).buildings == []


def test_build_combined_old_schema_in_combined_file():
    # old-style entities inside a CityMapData (like city.txt): cityentity_id + x/y + connected,
    # size resolved from CityEntities. Road-need = connected AND road-adjacent.
    data = {
        "UnlockedAreas": [_area(0, 0, 5, 1)],
        "CityEntities": {
            "TH": {"id": "TH", "name": "TownHall", "type": "main_building",
                   "width": 1, "length": 1,
                   "requirements": {"street_connection_level": 1}},
            "H": {"id": "H", "name": "House", "type": "residential",
                  "width": 1, "length": 1,
                  "requirements": {"street_connection_level": 1}},
            "S": {"id": "S", "name": "Street", "type": "street",
                  "width": 1, "length": 1,
                  "requirements": {"street_connection_level": 1}},
        },
        "CityMapData": {
            "1": {"id": 1, "cityentity_id": "TH", "type": "main_building",
                  "x": 0, "y": 0, "connected": 1},
            "2": {"id": 2, "cityentity_id": "H", "type": "residential",
                  "x": 2, "y": 0, "connected": 1},
            "3": {"id": 3, "cityentity_id": "S", "type": "street", "x": 1, "y": 0},
        },
    }
    layout = _build_combined(data)
    assert layout.roads == {(1, 0): 1}
    by_id = {b.entity_id: b for b in layout.buildings}
    # house at (2,0) is connected AND borders the road (1,0) -> needs_road True
    assert by_id[2].needs_road
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loader.py -k build_combined -v`
Expected: FAIL (`cannot import name '_build_combined'`).

- [ ] **Step 3: Write the implementation**

Append to `foeopt/loader.py`:
```python
def _cid(e: dict) -> str:
    return e.get("cityentity_id") or e.get("entityId") or ""


def _entity_coords(e: dict) -> tuple[int, int]:
    coords = e.get("coords")
    if isinstance(coords, dict):
        return (coords.get("x", 0), coords.get("y", 0))
    return (e.get("x", 0), e.get("y", 0))


def _entity_size(e: dict, catalog: Catalog) -> tuple[int, int] | None:
    size = e.get("size")
    if isinstance(size, dict) and size.get("width") and size.get("length"):
        return (size["width"], size["length"])
    return catalog.size(_cid(e))


def _street_level(e: dict, catalog: Catalog) -> int:
    if "needsStreet" in e:
        return e["needsStreet"] or 1
    return catalog.provided_level(_cid(e))


def _build_combined(data: dict) -> Layout:
    catalog = Catalog(data.get("CityEntities", {}))
    region = build_region(data["UnlockedAreas"])

    roads: dict[tuple[int, int], int] = {}
    candidates: list[tuple[dict, Footprint]] = []
    for e in data["CityMapData"].values():
        if e.get("isInInventory"):
            continue
        x, y = _entity_coords(e)
        if (x, y) not in region.cells:
            continue
        size = _entity_size(e, catalog)
        if size is None:
            continue
        w, length = size
        fp = Footprint(x, y, w, length)
        if e.get("type") == "street":
            level = _street_level(e, catalog)
            for cell in fp.cells():
                roads[cell] = max(roads.get(cell, 0), level)
            continue
        candidates.append((e, fp))

    road_cells = set(roads)
    buildings: list[Building] = []
    townhall: Building | None = None
    for e, fp in candidates:
        cid = _cid(e)
        if "needsStreet" in e:
            lvl = e["needsStreet"] or 0
            needs_road, road_level = (lvl > 0, lvl if lvl > 0 else 1)
        else:
            needs_road = ("connected" in e) and bool(fp.border_cells() & road_cells)
            road_level = catalog.required_level(cid)
        is_th = e.get("type") == "main_building"
        building = Building(
            entity_id=e["id"],
            cityentity_id=cid,
            type=e.get("type", ""),
            footprint=fp,
            needs_road=needs_road,
            road_level=road_level,
            is_townhall=is_th,
            set_id=catalog.set_id(cid),
            chain_id=catalog.chain_id(cid),
            name=e.get("name") or catalog.name(cid),
        )
        buildings.append(building)
        if is_th:
            townhall = building

    return Layout(region=region, buildings=buildings, townhall=townhall, roads=roads)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_loader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foeopt/loader.py tests/test_loader.py
git commit -m "feat: combined-file assembler (old + new entity schemas)"
```

---

### Task 3: `load_layout` dispatcher + real-file goldens (`loader.py`)

**Files:**
- Modify: `foeopt/loader.py`
- Test: `tests/test_loader.py`

**Interfaces:**
- Consumes: `read_json`, `build_layout`, `_build_combined`.
- Produces: `load_layout(city_path: str, helper_path: str | None = None) -> Layout`.
  - Reads `city_path`. If it has `entities` (split-old): require `helper_path`, read it, return `build_layout(city, helper)` (raises `ValueError` if `helper_path` is `None`). If it has `CityMapData` (combined): return `_build_combined(city)`. Else raise `ValueError("unrecognized city file format")`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_loader.py`:
```python
import pytest
from foeopt.loader import load_layout
from foeopt.build import build_layout
from foeopt.validate import is_valid

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def test_load_layout_split_old_matches_build_layout():
    layout = load_layout(str(REPO / "city-user-data.json"),
                         str(REPO / "city-user-data-foe-helper.json"))
    assert len(layout.buildings) == 314
    assert len(layout.roads) == 142
    assert len(layout.road_needing()) == 82


def test_load_layout_split_old_requires_helper():
    with pytest.raises(ValueError):
        load_layout(str(REPO / "city-user-data.json"))     # helper missing


def test_load_layout_combined_old_city_txt():
    layout = load_layout(str(REPO / "city.txt"))
    assert len(layout.buildings) == 88
    assert len(layout.roads) == 92
    assert is_valid(layout)


def test_load_layout_combined_new_darkzig():
    layout = load_layout(str(REPO / "darkzig.json"))
    assert len(layout.buildings) == 224
    assert len(layout.roads) == 250
    assert len(layout.road_needing()) == 63
    assert layout.townhall is not None
    assert is_valid(layout)


def test_load_layout_unrecognized(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{\"nope\": 1}")
    with pytest.raises(ValueError):
        load_layout(str(p))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_loader.py -k load_layout -v`
Expected: FAIL (`cannot import name 'load_layout'`).

- [ ] **Step 3: Write the implementation**

Append to `foeopt/loader.py`:
```python
def load_layout(city_path: str, helper_path: str | None = None) -> Layout:
    data = read_json(city_path)
    if "entities" in data:
        if helper_path is None:
            raise ValueError(
                "this city file is the split format; a helper file is required"
            )
        return build_layout(data, read_json(helper_path))
    if "CityMapData" in data:
        return _build_combined(data)
    raise ValueError("unrecognized city file format")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_loader.py -v`
Expected: PASS (the real-file goldens confirm split-old=314/142/82, city.txt=88/92, darkzig=224/250/63 valid).

- [ ] **Step 5: Commit**

```bash
git add foeopt/loader.py tests/test_loader.py
git commit -m "feat: load_layout auto-detecting dispatcher + real-file goldens"
```

---

### Task 4: CLI — optional helper, load via `load_layout`

**Files:**
- Modify: `foeopt/cli.py`
- Test: `tests/test_loader_cli.py`

**Interfaces:**
- Consumes: `foeopt.loader.load_layout`.
- Produces: every subcommand (`view`, `roads`, `layout`, `improve`) accepts `helper` as an **optional** positional and builds its layout via `load_layout(args.city, args.helper)`. Behavior for the two-file invocation is unchanged.

- [ ] **Step 1: Write the failing test**

`tests/test_loader_cli.py`:
```python
from foeopt.cli import main

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def test_view_accepts_single_combined_file(tmp_path):
    out = tmp_path / "map.html"
    rc = main(["view", str(REPO / "darkzig.json"), "-o", str(out)])
    assert rc == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")


def test_roads_accepts_two_file_split(tmp_path):
    out = tmp_path / "roads.html"
    rc = main(["roads", str(REPO / "city-user-data.json"),
               str(REPO / "city-user-data-foe-helper.json"), "-o", str(out)])
    assert rc == 0
    assert out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loader_cli.py -v`
Expected: FAIL — `view` currently requires two positionals and builds via `build_layout(_load(city), _load(helper))`, so a single-file `view` errors (argparse) or the build fails.

- [ ] **Step 3: Update the CLI**

In `foeopt/cli.py`:
1. Add import: `from foeopt.loader import load_layout`.
2. In each command function (`_cmd_view`, `_cmd_roads`, `_cmd_layout`, `_cmd_improve`), replace the layout construction. Currently they do e.g. `build_layout(_load(args.city), _load(args.helper))` (or `current = build_layout(...)`). Replace each such call with `load_layout(args.city, args.helper)`. Concretely:
   - `_cmd_view`: `layout = load_layout(args.city, args.helper)`
   - `_cmd_roads`: `layout = load_layout(args.city, args.helper)`
   - `_cmd_layout`: `current = load_layout(args.city, args.helper)`
   - `_cmd_improve`: `current = load_layout(args.city, args.helper)`
3. For each parser registration, make `helper` optional by changing `p.add_argument("helper")` to `p.add_argument("helper", nargs="?", default=None)` for all four subcommands.

The `_load` helper may become unused; if so, remove it and its import usage (only if nothing else references it).

- [ ] **Step 4: Run test + smoke tests**

Run: `uv run pytest tests/test_loader_cli.py -v`
Expected: PASS.

Run: `uv run python -m foeopt.cli roads darkzig.json -o output/darkzig_roads.html`
Expected: prints the road-optimization stats for darkzig (current 250 → optimized ~236) and writes the map — single combined file, no helper arg.

- [ ] **Step 5: Commit**

```bash
git add foeopt/cli.py tests/test_loader_cli.py
git commit -m "feat: CLI auto-detects format; helper arg optional"
```

---

### Task 5: README — document multi-format input

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the input docs**

In `README.md`, update the usage/inputs section to note that every command auto-detects the file format:
```markdown
## Input formats

Every command auto-detects the export format — just pass the file(s):

    # newer single-file FOE-Helper export (CityMapData + UnlockedAreas + CityEntities)
    uv run python -m foeopt.cli improve darkzig.json --anneal -o output/out.html

    # older split export (two files)
    uv run python -m foeopt.cli roads city-user-data.json city-user-data-foe-helper.json

Supported: the two-file split export, a single combined file with old-style entities, and the
newer combined file with `coords`/`size`/`needsStreet` entities (UTF-8 BOM tolerated). The
`needsStreet` flag, when present, is used directly as the road requirement.
```

- [ ] **Step 2: Verify the full suite is green**

Run: `uv run pytest -q`
Expected: all tests PASS (existing + new loader/CLI tests).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document multi-format auto-detecting input"
```

---

## Self-Review

**Spec coverage:**
- Three input shapes (spec §2) → `load_layout` dispatch (Task 3) + `_build_combined` per-entity handling (Task 2). ✓
- BOM-safe read (spec §3/§4) → `read_json` (Task 1). ✓
- Auto-detect file-level + per-entity (spec §4) → Task 3 dispatch + Task 2 `coords`-presence branch. ✓
- New-style road-need = `needsStreet`; old-style = connected+adjacent (spec §5) → Task 2 `_build_combined`. ✓
- Off-grid = anchor outside region (only test); `isInInventory` excluded; streets expand to cells (spec §4) → Task 2. ✓
- CLI optional helper + `load_layout` everywhere (spec §6) → Task 4. ✓
- Back-compat: `build_layout` untouched, split-old delegates to it; existing tests stay green (spec §7) → Task 3 delegates; verified by `test_load_layout_split_old_matches_build_layout` (314/142/82). ✓
- Testing matrix incl. BOM, detection, new-schema unit, real goldens (darkzig 224/250/63, city.txt 88/92), CLI single-file (spec §8) → Tasks 1–4. ✓

**Placeholder scan:** No placeholders; every code step has complete code, every test real assertions with concrete expected values verified against the real files (sample 314/142/82, city.txt 88/92, darkzig 224/250/63).

**Type consistency:** `read_json(path) -> dict`, `_build_combined(data) -> Layout`, `_cid(e) -> str`, `_entity_coords(e) -> tuple[int,int]`, `_entity_size(e, catalog) -> tuple[int,int]|None`, `_street_level(e, catalog) -> int`, `load_layout(city_path, helper_path=None) -> Layout` are consistent across Tasks 1–4. `build_layout(city_data, helper_data)` is reused unchanged. `Building` is constructed with the canonical field set; `roads` is `dict[(x,y)->level]`.
