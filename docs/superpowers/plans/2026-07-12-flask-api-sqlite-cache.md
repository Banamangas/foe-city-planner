# Phase 2: Flask API + SQLite Cache — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the Flask backend as a pure JSON API (`/api/...` routes) with SQLite-backed city/layout persistence, add `load_layout_from_dict()` for slim payloads, add `layout_to_view()` for React map data, and wire `RoadsFirstSearch` as a background job with SSE streaming of improvements.

**Architecture:** Flask becomes a pure JSON API — no server-rendered HTML. `webapp/cache.py` manages SQLite CRUD for cities (slim payloads keyed by SHA-256 hash) and layouts. `webapp/runner.py` rewrites to use `RoadsFirstSearch` with a thread-safe per-job improvement queue that the SSE endpoint drains. `foeopt/loader.py` gains `load_layout_from_dict(data)` so the API can build a `Layout` from a dict without a filesystem round-trip. `foeopt/viz.py` gains `layout_to_view(layout)` returning pure-data JSON (no HTML template) for the React Canvas. The old `webapp/static/` stays served temporarily for Phase 3 cutover.

**Tech Stack:** Python 3.12+, Flask 3, SQLite (stdlib `sqlite3`), `ortools>=9`, `pytest`.

## Global Constraints

- `ortools>=9` is a hard dependency (Phase 1, already merged to main).
- `/api/...` routes only — no HTML rendering on the API side. Old `/`, `/load`, `/run`, `/status` routes replaced.
- Bad input must yield structured 400 JSON, never a 500 HTML page (the React frontend parses body as JSON).
- SQLite DB at `webapp/cities.db` (gitignored). Use stdlib `sqlite3` — no ORM, no migrations framework.
- Slim city payload format: same structure as the full combined JSON but with `CityEntities` stripped to only `{id, width, length, name, requirements, abilities, components}` per entity (Phase 3 will do the stripping client-side; Phase 2 accepts both slim and full payloads via `/api/load`).
- `RoadsFirstSearch` callbacks: `on_improvement(layout, k, achieved)` pushes to a per-job `queue.Queue`; `should_stop()` checks a `threading.Event`.
- SSE event format: `event: improvement\ndata: {json}\n\n` and `event: done\ndata: {json}\n\n`.
- Layout serialization for SSE/API: `{"k": int, "achieved": int, "roads": [[x,y],...], "buildings": {"entity_id": [x,y,w,l],...}}`.
- Old `webapp/static/` (index.html, app.js, style.css) stays served at `/` and `/static/` until Phase 3 deletes them.
- No comments added to code unless the original source had them at that location.

---

### Task 1: Add `layout_to_view()` to foeopt/viz.py

**Files:**
- Modify: `foeopt/viz.py` (add function after `render_html`, before `render_comparison`)
- Test: `tests/test_viz.py` (add test)

**Interfaces:**
- Consumes: `foeopt.model.Layout`, existing `_bounds()`, `_CELL`, palette constants
- Produces: `layout_to_view(layout, optimized_roads=None) -> dict` returning the same data structure `render_html` builds internally (lines 64-82), but as a plain dict (no HTML template substitution)

- [ ] **Step 1: Write failing test**

Add to `tests/test_viz.py` (append to existing file):

```python
def test_layout_to_view_returns_dict_with_required_keys():
    from foeopt.viz import layout_to_view
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    b1 = Building(10, "c10", "g", Footprint(3, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th, b1], th, {(0, 2): 1})
    view = layout_to_view(lay)
    assert isinstance(view, dict)
    assert view["cell"] == 12
    assert "width" in view and "height" in view
    assert isinstance(view["region"], list)
    assert len(view["buildings"]) == 2
    assert view["buildings"][0]["name"] in ("TH", "a")
    assert isinstance(view["current_roads"], list)
    assert view["optimized_roads"] is None
    assert "palette" in view
    for key in ("background", "region", "current_road", "optimized_road",
                "townhall", "road_building", "plain_building", "border"):
        assert key in view["palette"]


def test_layout_to_view_with_optimized_roads():
    from foeopt.viz import layout_to_view
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    lay = Layout(region, [th], th, {(0, 2): 1})
    opt = {(3, 0): 1}
    view = layout_to_view(lay, optimized_roads=opt)
    assert view["optimized_roads"] is not None
    assert len(view["optimized_roads"]) == 1
    assert view["optimized_roads"][0]["level"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_viz.py::test_layout_to_view_returns_dict_with_required_keys tests/test_viz.py::test_layout_to_view_with_optimized_roads -v`
Expected: FAIL with "ImportError: cannot import name 'layout_to_view' from 'foeopt.viz'"

- [ ] **Step 3: Implement `layout_to_view`**

Add to `foeopt/viz.py` after `render_html` (after line 85, before `render_comparison`):

```python
def layout_to_view(
    layout: Layout,
    optimized_roads: dict[tuple[int, int], int] | None = None,
) -> dict:
    """Return the map data as a plain dict (no HTML template). This is the
    JSON contract for the React Canvas component — same structure render_html
    builds internally, but consumed directly by the frontend instead of being
    stringified into an iframe."""
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

    return {
        "cell": _CELL,
        "width": width,
        "height": height,
        "region": region_cells,
        "buildings": buildings,
        "current_roads": road_list(layout.roads),
        "optimized_roads": road_list(optimized_roads) if optimized_roads else None,
        "palette": {
            "background": COLOR_BACKGROUND,
            "region": COLOR_REGION,
            "current_road": COLOR_CURRENT_ROAD,
            "optimized_road": COLOR_OPTIMIZED_ROAD,
            "townhall": COLOR_TOWNHALL,
            "road_building": COLOR_ROAD_BUILDING,
            "plain_building": COLOR_PLAIN_BUILDING,
            "border": COLOR_BUILDING_BORDER,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_viz.py::test_layout_to_view_returns_dict_with_required_keys tests/test_viz.py::test_layout_to_view_with_optimized_roads -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full viz suite for regressions**

Run: `uv run pytest tests/test_viz.py -v`
Expected: All viz tests pass

- [ ] **Step 6: Commit**

```bash
git add foeopt/viz.py tests/test_viz.py
git commit -m "feat: add layout_to_view() pure-data function to viz"
```

---

### Task 2: Add `load_layout_from_dict()` to foeopt/loader.py

**Files:**
- Modify: `foeopt/loader.py` (add function after `_build_combined`, before `load_layout`)
- Test: `tests/test_loader.py` (add test)

**Interfaces:**
- Consumes: existing `_build_combined(data)`, `build_layout(data, helper_data)`
- Produces: `load_layout_from_dict(data: dict, helper_data: dict | None = None) -> Layout` — same logic as `load_layout` but accepts a dict instead of a file path

- [ ] **Step 1: Write failing test**

Add to `tests/test_loader.py` (append to existing file):

```python
def test_load_layout_from_dict_combined_format(city_data_combined):
    from foeopt.loader import load_layout_from_dict
    layout = load_layout_from_dict(city_data_combined)
    assert len(layout.buildings) > 0
    assert layout.townhall is not None
    assert len(layout.region.cells) > 0
```

If `city_data_combined` fixture doesn't exist, add it to `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def city_data_combined():
    import json
    return json.loads((REPO_ROOT / "darkzig.json").read_text())
```

Note: use `darkzig.json` because it's the combined format (`CityMapData` key). The `city-user-data.json` is the split format. Check if `darkzig.json` exists at repo root — if it does, use it. If not, skip the test.

Actually, to avoid depending on a 42MB file, read just enough to verify. The test should be:

```python
def test_load_layout_from_dict_combined_format():
    import json, pathlib
    from foeopt.loader import load_layout_from_dict
    p = pathlib.Path("darkzig.json")
    if not p.exists():
        pytest.skip("darkzig.json not present")
    data = json.loads(p.read_text())
    layout = load_layout_from_dict(data)
    assert len(layout.buildings) > 0
    assert layout.townhall is not None
    assert len(layout.region.cells) > 0
```

Add `import pytest` at the top of `test_loader.py` if not already there.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loader.py::test_load_layout_from_dict_combined_format -v`
Expected: FAIL with "ImportError: cannot import name 'load_layout_from_dict' from 'foeopt.loader'"

- [ ] **Step 3: Implement `load_layout_from_dict`**

Add to `foeopt/loader.py` after `_build_combined` (after line 92, before `load_layout`):

```python
def load_layout_from_dict(data: dict, helper_data: dict | None = None) -> Layout:
    """Build a Layout from an in-memory dict (slim or full combined format).

    Same logic as load_layout but avoids a filesystem round-trip — the API
    receives the slim payload as JSON in the request body, not as a file path.
    """
    if "entities" in data:
        if helper_data is None:
            raise ValueError(
                "this city file is the split format; a helper file is required"
            )
        return build_layout(data, helper_data)
    if "CityMapData" in data:
        return _build_combined(data)
    raise ValueError("unrecognized city file format")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_loader.py::test_load_layout_from_dict_combined_format -v`
Expected: PASS (or skip if darkzig.json absent)

- [ ] **Step 5: Run full loader suite for regressions**

Run: `uv run pytest tests/test_loader.py -v`
Expected: All loader tests pass

- [ ] **Step 6: Commit**

```bash
git add foeopt/loader.py tests/test_loader.py
git commit -m "feat: add load_layout_from_dict() for in-memory city parsing"
```

---

### Task 3: Create `webapp/cache.py` — SQLite cache for cities + layouts

**Files:**
- Create: `webapp/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: `sqlite3`, `json`, `hashlib`
- Produces: `CityCache` class with methods:
  - `__init__(db_path=":memory:")` — opens SQLite connection, creates tables if not exist
  - `store_city(city_id: str, payload: bytes, buildings: list[dict], region_cells: int, road_estimate: int) -> None`
  - `get_city(city_id: str) -> dict | None` — returns `{id, payload (parsed as dict), buildings, region_cells, road_estimate}`
  - `list_cities() -> list[dict]` — returns `[{id, region_cells, road_estimate, created_at}]`
  - `store_layout(layout_id: str, city_id: str, k: int, achieved: int, layout: dict, roads_count: int) -> None`
  - `get_layout(layout_id: str) -> dict | None`
  - `list_layouts(city_id: str | None = None) -> list[dict]`
  - `delete_layout(layout_id: str) -> bool`
  - `close() -> None`

- [ ] **Step 1: Write failing test**

Create `tests/test_cache.py`:

```python
import json
import pytest

from webapp.cache import CityCache


@pytest.fixture()
def cache():
    c = CityCache(":memory:")
    yield c
    c.close()


def test_store_and_get_city(cache):
    payload = json.dumps({"CityMapData": {}, "UnlockedAreas": [], "CityEntities": {}}).encode()
    cache.store_city("abc123", payload, [{"name": "TH", "is_townhall": True}], 100, 50)
    city = cache.get_city("abc123")
    assert city is not None
    assert city["id"] == "abc123"
    assert city["region_cells"] == 100
    assert city["road_estimate"] == 50
    assert len(city["buildings"]) == 1
    assert city["buildings"][0]["name"] == "TH"
    assert isinstance(city["payload"], dict)


def test_get_city_returns_none_if_not_found(cache):
    assert cache.get_city("nonexistent") is None


def test_list_cities(cache):
    payload = b'{}'
    cache.store_city("city1", payload, [], 50, 25)
    cache.store_city("city2", payload, [], 100, 50)
    cities = cache.list_cities()
    assert len(cities) == 2
    ids = {c["id"] for c in cities}
    assert ids == {"city1", "city2"}


def test_store_and_get_layout(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    layout_data = {"k": 92, "achieved": 79, "roads": [[0, 1]], "buildings": {"1": [0, 0, 2, 2]}}
    cache.store_layout("lay1", "city1", 92, 79, layout_data, 79)
    lay = cache.get_layout("lay1")
    assert lay is not None
    assert lay["id"] == "lay1"
    assert lay["city_id"] == "city1"
    assert lay["k"] == 92
    assert lay["achieved"] == 79
    assert lay["roads_count"] == 79
    assert isinstance(lay["layout"], dict)
    assert lay["layout"]["k"] == 92


def test_list_layouts_by_city(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    cache.store_city("city2", b'{}', [], 100, 50)
    cache.store_layout("lay1", "city1", 92, 79, {}, 79)
    cache.store_layout("lay2", "city1", 88, 85, {}, 85)
    cache.store_layout("lay3", "city2", 100, 95, {}, 95)
    layouts = cache.list_layouts(city_id="city1")
    assert len(layouts) == 2
    for l in layouts:
        assert l["city_id"] == "city1"


def test_list_all_layouts(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    cache.store_layout("lay1", "city1", 92, 79, {}, 79)
    cache.store_layout("lay2", "city1", 88, 85, {}, 85)
    layouts = cache.list_layouts()
    assert len(layouts) == 2


def test_delete_layout(cache):
    cache.store_city("city1", b'{}', [], 50, 25)
    cache.store_layout("lay1", "city1", 92, 79, {}, 79)
    assert cache.delete_layout("lay1") is True
    assert cache.get_layout("lay1") is None
    assert cache.delete_layout("lay1") is False


def test_store_city_is_idempotent(cache):
    payload1 = b'{"v": 1}'
    payload2 = b'{"v": 2}'
    cache.store_city("city1", payload1, [], 50, 25)
    cache.store_city("city1", payload2, [], 100, 50)
    city = cache.get_city("city1")
    assert city["region_cells"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cache.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'webapp.cache'"

- [ ] **Step 3: Implement `webapp/cache.py`**

Create `webapp/cache.py`:

```python
from __future__ import annotations

import json
import sqlite3


class CityCache:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS cities (
                id TEXT PRIMARY KEY,
                payload BLOB NOT NULL,
                buildings TEXT NOT NULL,
                region_cells INTEGER,
                road_estimate INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS layouts (
                id TEXT PRIMARY KEY,
                city_id TEXT NOT NULL,
                k INTEGER,
                achieved INTEGER,
                layout TEXT NOT NULL,
                roads_count INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self._conn.commit()

    def store_city(self, city_id: str, payload: bytes,
                   buildings: list[dict], region_cells: int,
                   road_estimate: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cities (id, payload, buildings, region_cells, road_estimate) "
            "VALUES (?, ?, ?, ?, ?)",
            (city_id, payload, json.dumps(buildings), region_cells, road_estimate)
        )
        self._conn.commit()

    def get_city(self, city_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM cities WHERE id = ?", (city_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "payload": json.loads(row["payload"]),
            "buildings": json.loads(row["buildings"]),
            "region_cells": row["region_cells"],
            "road_estimate": row["road_estimate"],
            "created_at": row["created_at"],
        }

    def list_cities(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, region_cells, road_estimate, created_at FROM cities ORDER BY created_at DESC"
        ).fetchall()
        return [{"id": r["id"], "region_cells": r["region_cells"],
                 "road_estimate": r["road_estimate"], "created_at": r["created_at"]}
                for r in rows]

    def store_layout(self, layout_id: str, city_id: str, k: int,
                     achieved: int, layout: dict, roads_count: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO layouts (id, city_id, k, achieved, layout, roads_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (layout_id, city_id, k, achieved, json.dumps(layout), roads_count)
        )
        self._conn.commit()

    def get_layout(self, layout_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM layouts WHERE id = ?", (layout_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"], "city_id": row["city_id"],
            "k": row["k"], "achieved": row["achieved"],
            "layout": json.loads(row["layout"]),
            "roads_count": row["roads_count"],
            "created_at": row["created_at"],
        }

    def list_layouts(self, city_id: str | None = None) -> list[dict]:
        if city_id is not None:
            rows = self._conn.execute(
                "SELECT id, city_id, k, achieved, roads_count, created_at "
                "FROM layouts WHERE city_id = ? ORDER BY created_at DESC",
                (city_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, city_id, k, achieved, roads_count, created_at "
                "FROM layouts ORDER BY created_at DESC"
            ).fetchall()
        return [{"id": r["id"], "city_id": r["city_id"], "k": r["k"],
                 "achieved": r["achieved"], "roads_count": r["roads_count"],
                 "created_at": r["created_at"]}
                for r in rows]

    def delete_layout(self, layout_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM layouts WHERE id = ?", (layout_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cache.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add webapp/cache.py tests/test_cache.py
git commit -m "feat: add SQLite cache for cities and layouts (webapp/cache.py)"
```

---

### Task 4: Rewrite `webapp/runner.py` — RoadsFirstSearch job runner with SSE queue

**Files:**
- Rewrite: `webapp/runner.py`
- Test: `tests/test_runner.py` (rewrite — old repack/sweep tests no longer apply)

**Interfaces:**
- Consumes: `foeopt.roads_first.RoadsFirstSearch`, `foeopt.model.Layout`, `foeopt.viz.layout_to_view`, `threading`, `queue.Queue`, `uuid`, `time`
- Produces:
  - `JobManager` class with per-job improvement queue + stop event:
    - `submit(layout, *, time_box, ...) -> job_id`
    - `pop_improvement(job_id, timeout=0.1) -> dict | None`
    - `status(job_id) -> dict`
    - `result(job_id) -> dict | None`
    - `is_done(job_id) -> bool`
    - `stop(job_id) -> None`
    - `elapsed(job_id) -> float`
  - `layout_to_dict(layout) -> dict` — serialize a validated Layout to the compact dict format

- [ ] **Step 1: Write failing test**

Rewrite `tests/test_runner.py`:

```python
import time
import pytest

from foeopt.model import Building, Footprint, Layout, Region
from webapp.runner import JobManager, layout_to_dict


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 2, 2), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    return Layout(region, [th, c1], th, {})


def test_layout_to_dict_serializes_layout():
    lay = _tiny_layout()
    lay.roads = {(0, 2): 1}
    d = layout_to_dict(lay)
    assert isinstance(d, dict)
    assert "roads" in d
    assert isinstance(d["roads"], list)
    assert [0, 2] in d["roads"]
    assert "buildings" in d
    assert isinstance(d["buildings"], dict)
    for eid, coords in d["buildings"].items():
        assert len(coords) == 4


def test_job_manager_submit_and_status():
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=1.0, patterns=5, probe_limit=1.0, workers=1)
    assert isinstance(jid, str)
    st = jobs.status(jid)
    assert st["state"] in ("running", "done", "error")
    # wait for completion
    for _ in range(300):
        st = jobs.status(jid)
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["state"] in ("done", "error")


def test_job_manager_stop_signals_search():
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=600.0, patterns=5, probe_limit=1.0, workers=1)
    jobs.stop(jid)
    for _ in range(300):
        if jobs.is_done(jid):
            break
        time.sleep(0.1)
    assert jobs.is_done(jid)


def test_job_manager_pop_improvement_returns_none_when_empty():
    lay = _tiny_layout()
    jobs = JobManager()
    jid = jobs.submit(lay, time_box=1.0, patterns=5, probe_limit=1.0, workers=1)
    imp = jobs.pop_improvement(jid, timeout=0.1)
    # may be None if no improvement found yet, or a dict if found
    assert imp is None or isinstance(imp, dict)


def test_job_manager_unknown_job_status():
    jobs = JobManager()
    assert jobs.status("nonexistent")["state"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL (old runner.py has different API)

- [ ] **Step 3: Rewrite `webapp/runner.py`**

Replace entire contents of `webapp/runner.py`:

```python
from __future__ import annotations

import queue
import threading
import time
import uuid

from foeopt.model import Layout
from foeopt.roads_first import RoadsFirstSearch


def layout_to_dict(layout: Layout) -> dict:
    """Serialize a validated Layout to the compact dict format for SSE/API."""
    return {
        "roads": sorted(layout.roads.keys()),
        "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                         b.footprint.width, b.footprint.length]
                      for b in layout.buildings},
    }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, layout: Layout, *, time_box: float, patterns: int = 200,
               probe_limit: float = 60.0, workers: int = 4,
               probe_workers: int = 4, th_anchors: str = "full",
               k_start="auto") -> str:
        job_id = uuid.uuid4().hex
        stop_event = threading.Event()
        improvements: queue.Queue = queue.Queue()
        state = {"state": "running", "start": time.monotonic(),
                 "result": None, "error": None}
        with self._lock:
            self._jobs[job_id] = {
                "state": state,
                "stop_event": stop_event,
                "improvements": improvements,
            }

        def on_improvement(best_layout, k, achieved):
            improvements.put({
                "k": k, "achieved": achieved,
                **layout_to_dict(best_layout),
            })

        def on_status(k, level_status, probes_done, probes_total):
            pass

        def should_stop():
            return stop_event.is_set()

        def worker():
            try:
                search = RoadsFirstSearch(
                    layout, time_box=time_box, patterns=patterns,
                    probe_limit=probe_limit, workers=workers,
                    probe_workers=probe_workers, th_anchors=th_anchors,
                    k_start=k_start,
                )
                res = search.run(on_improvement=on_improvement,
                                 on_status=on_status,
                                 should_stop=should_stop)
                state["state"] = "done"
                state["result"] = res
            except Exception as exc:
                state["state"] = "error"
                state["error"] = str(exc)

        threading.Thread(target=worker, daemon=True).start()
        return job_id

    def pop_improvement(self, job_id: str, timeout: float = 0.1) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        try:
            return job["improvements"].get(timeout=timeout)
        except queue.Empty:
            return None

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"state": "error", "elapsed": 0, "error": "unknown job"}
        return {"state": job["state"]["state"],
                "elapsed": round(time.monotonic() - job["state"]["start"], 1),
                "error": job["state"]["error"]}

    def result(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        return job["state"]["result"]

    def is_done(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return True
        return job["state"]["state"] in ("done", "error")

    def stop(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            job["stop_event"].set()

    def elapsed(self, job_id: str) -> float:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return 0.0
        return time.monotonic() - job["state"]["start"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS (5 tests; the submit+status test may take a few seconds for the search to complete)

- [ ] **Step 5: Commit**

```bash
git add webapp/runner.py tests/test_runner.py
git commit -m "feat: rewrite runner.py with RoadsFirstSearch + per-job SSE improvement queue"
```

---

### Task 5: Rewrite `webapp/app.py` — pure JSON API

**Files:**
- Rewrite: `webapp/app.py`
- Test: `tests/test_api.py` (new — replaces test_webapp.py)

**Interfaces:**
- Consumes: `webapp.cache.CityCache`, `webapp.runner.JobManager`, `foeopt.loader.load_layout_from_dict`, `foeopt.report.road_estimate`, `foeopt.viz.layout_to_view`
- Produces: Flask app with routes:
  - `GET /` → serves old `static/index.html` (temporary until Phase 3)
  - `GET /static/<path>` → serves old static files (temporary)
  - `POST /api/load` → accepts JSON body (slim or full city payload), parses, caches, returns `{city_id, buildings, region_cells, road_estimate, map_view}`
  - `POST /api/load/raw` → accepts multipart upload (fallback for no `file.stream()`), same return as `/api/load`
  - `POST /api/optimize` → accepts `{city_id, time_box}`, starts search job, returns `{job_id}`
  - `GET /api/stream/<job_id>` → SSE stream of improvements + done
  - `POST /api/stop/<job_id>` → signals search to stop
  - `GET /api/cities` → list cached cities
  - `GET /api/cities/<id>` → city summary
  - `GET /api/cities/<id>/export` → `.city` file (slim JSON attachment)
  - `POST /api/cities/import` → upload `.city` file → dedup by hash → `{city_id}`
  - `GET /api/layouts` → list saved layouts (optional `?city_id=` filter)
  - `GET /api/layouts/<id>` → full layout JSON
  - `POST /api/layouts` → save a layout `{city_id, k, achieved, layout_json}`
  - `DELETE /api/layouts/<id>` → delete a saved layout

- [ ] **Step 1: Write failing test**

Create `tests/test_api.py`:

```python
import json
import time
import io
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def _slim_payload():
    return {
        "CityMapData": {},
        "UnlockedAreas": [{"x": 0, "y": 0, "width": 4, "length": 4}],
        "CityEntities": {},
    }


def _combined_payload():
    return {
        "CityMapData": {
            "th1": {"id": 1, "type": "main_building", "x": 0, "y": 0,
                    "cityentity_id": "R_MultiAge_CityHall", "name": "Town Hall"}
        },
        "UnlockedAreas": [{"x": 0, "y": 0, "width": 6, "length": 6}],
        "CityEntities": {
            "R_MultiAge_CityHall": {"id": "R_MultiAge_CityHall", "width": 7, "length": 7,
                                    "name": "Town Hall", "requirements": {}}
        },
    }


def test_api_load_with_json_body(client):
    r = client.post("/api/load", json=_combined_payload())
    assert r.status_code == 200
    body = r.get_json()
    assert "city_id" in body
    assert isinstance(body["buildings"], list)
    assert any(b["is_townhall"] for b in body["buildings"])
    assert "region_cells" in body
    assert "road_estimate" in body
    assert "map_view" in body


def test_api_load_bad_json_returns_400(client):
    r = client.post("/api/load", data=b"not json", content_type="application/json")
    assert r.status_code == 400
    assert r.is_json
    assert "error" in r.get_json()


def test_api_load_dedup_by_hash(client):
    payload = _combined_payload()
    r1 = client.post("/api/load", json=payload)
    r2 = client.post("/api/load", json=payload)
    assert r1.get_json()["city_id"] == r2.get_json()["city_id"]


def test_api_optimize_returns_job_id(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.post("/api/optimize", json={"city_id": city_id, "time_box": 1.0})
    assert r.status_code == 200
    assert "job_id" in r.get_json()


def test_api_optimize_without_load_returns_400(client):
    r = client.post("/api/optimize", json={"city_id": "nonexistent", "time_box": 1.0})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_api_stop_unknown_job(client):
    r = client.post("/api/stop/nonexistent")
    assert r.status_code == 404


def test_api_cities_list(client):
    client.post("/api/load", json=_combined_payload())
    r = client.get("/api/cities")
    assert r.status_code == 200
    cities = r.get_json()
    assert len(cities) >= 1
    assert "id" in cities[0]


def test_api_cities_get(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.get(f"/api/cities/{city_id}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["id"] == city_id
    assert "buildings" in body
    assert "region_cells" in body


def test_api_cities_get_not_found(client):
    r = client.get("/api/cities/nonexistent")
    assert r.status_code == 404


def test_api_cities_export(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    r = client.get(f"/api/cities/{city_id}/export")
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    data = json.loads(r.data)
    assert "CityMapData" in data or "entities" in data


def test_api_layouts_crud(client):
    r_load = client.post("/api/load", json=_combined_payload())
    city_id = r_load.get_json()["city_id"]
    layout_data = {"k": 92, "achieved": 79, "roads": [[0, 1]], "buildings": {"1": [0, 0, 2, 2]}}
    r_save = client.post("/api/layouts", json={
        "city_id": city_id, "k": 92, "achieved": 79,
        "layout_json": layout_data, "roads_count": 79,
    })
    assert r_save.status_code == 200
    layout_id = r_save.get_json()["id"]

    r_get = client.get(f"/api/layouts/{layout_id}")
    assert r_get.status_code == 200
    assert r_get.get_json()["k"] == 92

    r_list = client.get("/api/layouts")
    assert r_list.status_code == 200
    assert len(r_list.get_json()) >= 1

    r_del = client.delete(f"/api/layouts/{layout_id}")
    assert r_del.status_code == 200
    assert client.get(f"/api/layouts/{layout_id}").status_code == 404


def test_api_load_raw_fallback(client):
    payload = json.dumps(_combined_payload()).encode()
    r = client.post("/api/load/raw", data={"city": (io.BytesIO(payload), "city.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert "city_id" in body
    assert len(body["buildings"]) > 0


def test_old_routes_still_served(client):
    r = client.get("/")
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL (old app.py has different routes/API)

- [ ] **Step 3: Rewrite `webapp/app.py`**

Replace entire contents of `webapp/app.py`:

```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid

from flask import Flask, Response, jsonify, request, send_from_directory

from foeopt.loader import load_layout_from_dict, load_layout
from foeopt.report import road_estimate
from foeopt.viz import layout_to_view
from webapp.cache import CityCache
from webapp.runner import JobManager

_STATIC = os.path.join(os.path.dirname(__file__), "static")


def _city_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def _buildings_summary(layout) -> list[dict]:
    return [{
        "entity_id": b.entity_id, "name": b.name,
        "width": b.footprint.width, "length": b.footprint.length,
        "needs_road": b.needs_road, "is_townhall": b.is_townhall,
    } for b in layout.buildings]


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=_STATIC, static_url_path="/static")
    cache = CityCache(db_path or os.path.join(os.path.dirname(__file__), "cities.db"))
    jobs = JobManager()

    def _save_tmp(file_storage) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        file_storage.save(path)
        return path

    def _parse_and_cache(data: dict) -> dict:
        layout = load_layout_from_dict(data)
        payload = json.dumps(data).encode()
        city_id = _city_hash(payload)
        buildings = _buildings_summary(layout)
        cache.store_city(city_id, payload, buildings,
                         len(layout.region.cells), road_estimate(layout))
        return {
            "city_id": city_id,
            "buildings": buildings,
            "region_cells": len(layout.region.cells),
            "road_estimate": road_estimate(layout),
            "map_view": layout_to_view(layout),
        }

    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.post("/api/load")
    def api_load():
        data = request.get_json(silent=True)
        if data is None:
            return jsonify(error="invalid JSON body"), 400
        try:
            return jsonify(_parse_and_cache(data))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.post("/api/load/raw")
    def api_load_raw():
        if "city" not in request.files:
            return jsonify(error="no city file"), 400
        city_path = _save_tmp(request.files["city"])
        helper_path = _save_tmp(request.files["helper"]) if "helper" in request.files else None
        try:
            from foeopt.loader import read_json
            data = read_json(city_path)
            helper_data = read_json(helper_path) if helper_path else None
        except Exception as exc:
            return jsonify(error=f"could not read file: {exc}"), 400
        finally:
            for p in (city_path, helper_path):
                if p:
                    os.unlink(p)
        try:
            return jsonify(_parse_and_cache(data))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.post("/api/optimize")
    def api_optimize():
        data = request.get_json(silent=True) or {}
        city_id = data.get("city_id")
        if not city_id:
            return jsonify(error="city_id is required"), 400
        city = cache.get_city(city_id)
        if city is None:
            return jsonify(error="city not found, load it first"), 400
        time_box = float(data.get("time_box", 300))
        patterns = int(data.get("patterns", 200))
        probe_limit = float(data.get("probe_limit", 60))
        workers = int(data.get("workers", 4))
        probe_workers = int(data.get("probe_workers", 4))
        th_anchors = data.get("th_anchors", "full")
        k_start = data.get("k_start", "auto")
        layout = load_layout_from_dict(city["payload"])
        job_id = jobs.submit(layout, time_box=time_box, patterns=patterns,
                             probe_limit=probe_limit, workers=workers,
                             probe_workers=probe_workers, th_anchors=th_anchors,
                             k_start=k_start)
        return jsonify(job_id=job_id)

    @app.get("/api/stream/<job_id>")
    def api_stream(job_id):
        def generate():
            while not jobs.is_done(job_id):
                imp = jobs.pop_improvement(job_id, timeout=0.2)
                if imp is not None:
                    yield f"event: improvement\ndata: {json.dumps(imp)}\n\n"
                else:
                    st = jobs.status(job_id)
                    yield f"event: heartbeat\ndata: {json.dumps(st)}\n\n"
            final = jobs.result(job_id)
            yield f"event: done\ndata: {json.dumps(final)}\n\n"
        return Response(generate(), mimetype="text/event-stream")

    @app.post("/api/stop/<job_id>")
    def api_stop(job_id):
        if not jobs.is_done(job_id):
            jobs.stop(job_id)
            return jsonify(ok=True)
        return jsonify(ok=True, already_done=True)

    @app.get("/api/cities")
    def api_cities_list():
        return jsonify(cache.list_cities())

    @app.get("/api/cities/<city_id>")
    def api_cities_get(city_id):
        city = cache.get_city(city_id)
        if city is None:
            return jsonify(error="not found"), 404
        return jsonify(city)

    @app.get("/api/cities/<city_id>/export")
    def api_cities_export(city_id):
        city = cache.get_city(city_id)
        if city is None:
            return jsonify(error="not found"), 404
        resp = Response(json.dumps(city["payload"]), mimetype="application/json")
        resp.headers["Content-Disposition"] = f'attachment; filename="{city_id}.city"'
        return resp

    @app.post("/api/cities/import")
    def api_cities_import():
        data = request.get_json(silent=True)
        if data is None:
            return jsonify(error="invalid JSON body"), 400
        try:
            return jsonify(_parse_and_cache(data))
        except Exception as exc:
            return jsonify(error=f"could not parse city: {exc}"), 400

    @app.get("/api/layouts")
    def api_layouts_list():
        city_id = request.args.get("city_id")
        return jsonify(cache.list_layouts(city_id=city_id))

    @app.get("/api/layouts/<layout_id>")
    def api_layouts_get(layout_id):
        layout = cache.get_layout(layout_id)
        if layout is None:
            return jsonify(error="not found"), 404
        return jsonify(layout)

    @app.post("/api/layouts")
    def api_layouts_save():
        data = request.get_json(silent=True) or {}
        city_id = data.get("city_id")
        if not city_id:
            return jsonify(error="city_id is required"), 400
        layout_id = uuid.uuid4().hex[:12]
        k = int(data.get("k", 0))
        achieved = int(data.get("achieved", 0))
        layout_json = data.get("layout_json", {})
        roads_count = int(data.get("roads_count", 0))
        cache.store_layout(layout_id, city_id, k, achieved, layout_json, roads_count)
        return jsonify(id=layout_id)

    @app.delete("/api/layouts/<layout_id>")
    def api_layouts_delete(layout_id):
        ok = cache.delete_layout(layout_id)
        if ok:
            return jsonify(ok=True)
        return jsonify(error="not found"), 404

    return app


if __name__ == "__main__":
    create_app().run(port=5000, debug=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (14 tests; the optimize test starts a real search but with time_box=1.0 so it's fast)

- [ ] **Step 5: Run full suite for regressions**

Run: `uv run pytest -q --ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`
Expected: All pass (old test_webapp.py tests will fail — they test old routes. That's expected; Task 6 addresses them.)

Actually, `test_webapp.py` tests old routes (`/load`, `/run`) that no longer exist. They should fail. But don't skip them — the plan says to update them in Task 6. For now, verify that `test_api.py` passes and other tests are unaffected:

Run: `uv run pytest tests/test_api.py tests/test_cache.py tests/test_runner.py tests/test_viz.py tests/test_loader.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py tests/test_api.py
git commit -m "feat: rewrite app.py as pure JSON API with /api/ routes, SSE, SQLite cache"
```

---

### Task 6: Update/replace `tests/test_webapp.py`

**Files:**
- Rewrite: `tests/test_webapp.py`

**Interfaces:**
- Consumes: new API routes from Task 5
- Produces: tests that verify the old routes still serve the old static UI (temporary), and that the new API routes work. Actually, since `test_api.py` (Task 5) already covers all API routes, `test_webapp.py` should either be deleted or reduced to just the "old static routes still served" test.

- [ ] **Step 1: Rewrite `test_webapp.py`**

Replace entire contents of `tests/test_webapp.py`:

```python
import pytest

flask = pytest.importorskip("flask")
from webapp.app import create_app


@pytest.fixture()
def client():
    app = create_app(db_path=":memory:")
    app.config.update(TESTING=True)
    return app.test_client()


def test_old_index_still_served(client):
    """Old static index.html must still be served until Phase 3 replaces it."""
    r = client.get("/")
    assert r.status_code == 200


def test_old_static_assets_still_served(client):
    """Old static assets (app.js, style.css) must still be served."""
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_webapp.py -v`
Expected: PASS (2 tests — old static serving only)

- [ ] **Step 3: Run full suite for regressions**

Run: `uv run pytest -q --ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`
Expected: All pass (old webapp tests that tested /load, /run, etc. are gone; new API tests cover the new routes)

- [ ] **Step 4: Commit**

```bash
git add tests/test_webapp.py
git commit -m "test: reduce test_webapp.py to old-static-serving checks (API covered by test_api.py)"
```

---

### Task 7: Add `.gitignore` entries and final verification

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add gitignore entries**

Add to `.gitignore`:

```
webapp/cities.db
frontend/node_modules/
webapp/dist/
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -q --ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`
Expected: All pass

- [ ] **Step 3: Verify selftest still passes**

Run: `uv run python scripts/exp_roads_first.py --selftest`
Expected: PASS

- [ ] **Step 4: Run API tests specifically**

Run: `uv run pytest tests/test_api.py tests/test_cache.py tests/test_runner.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore cities.db, frontend node_modules, webapp/dist"
```