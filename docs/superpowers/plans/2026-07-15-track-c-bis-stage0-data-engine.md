# Track C-bis Stage 0 — Data Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the roads-first CP-SAT k-walk into an optimal-labeled data engine — persist, as a zero-solve-cost side effect of normal runs, a per-city corpus of `(fixed road skeleton, road-needing building set) → status [+ CP-SAT placement]` instances that later Track C-bis stages train on.

**Architecture:** A new, dependency-light `foeopt/corpus.py` owns the on-disk format: a per-city `manifest.json` (region + road-needing building set — the large constant data, written once) and an append-only `instances.jsonl` (one line per probe: skeleton road cells, status, solve time, and the CP-SAT placement `pos` for SAT). The probe worker (`_run_probe`) already computes `pos` but drops it; this plan threads it out. `RoadsFirstSearch` gains an opt-in `corpus_dir` that, when set, writes the manifest and records every probe via a hook in `_probe_level`'s `handle_result`. A `--corpus DIR` CLI flag exposes it. Everything is zero-cost when off.

**Tech Stack:** Python 3.12, stdlib `json`/`hashlib`/`pathlib`, `ortools` (already a hard dep, used only by the existing probe), `pytest`.

## Global Constraints

- The corpus is **opt-in**: no `corpus_dir` / no `--corpus` ⇒ zero behavior change and zero cost. This matches the project's gated-extras policy.
- `foeopt/corpus.py` must not import `ortools` and should stay decoupled from the search internals — it takes plain data (a `Layout` for the manifest; plain values per record). It may import `foeopt.model` only for typing/duck-typed access.
- The manifest holds the per-city constants (region cells, road-needing buildings). Per-probe records hold only what varies: skeleton `roads`, `th` (the pattern's TH anchor can differ per pattern), `status`, `secs`, and `pos`.
- `pos` is the CP-SAT placement `{entity_id: (x, y, w, l)}` that `probe()` returns on SAT. Capture it whenever CP-SAT returned SAT, regardless of the later `validate()` outcome (OK / SAT_ROTATED / SAT_FILLER_FAIL / ROUTE_FAIL / INVALID). For non-SAT probes `pos` is `None`.
- Record all probe statuses that reach `handle_result` (`SAT`, `UNSAT`, `UNKNOWN`, `ROUTE_FAIL`, `INVALID`, `SAT_FILLER_FAIL`, `SAT_ROTATED`). `PREFILTERED` patterns never reach `handle_result` and are intentionally not recorded.
- Corpus output belongs under `output/` (already gitignored). Tests write to `tmp_path`.
- No comments in code unless the surrounding source already has them at that location.
- Adding `corpus=None` to `_probe_level` and `corpus_dir=None` to `RoadsFirstSearch` must be backward compatible (trailing keyword args with defaults); existing callers and the `test_roads_first_parallel` monkeypatches must be unaffected.

## Scope

This plan is **Stage 0 only** (the data engine). Stages 1 (feasibility CNN), 1.5 (UNKNOWN autopsy), 2 (CP-SAT warm-start), and 3 (scale) each get their own plan, gated on the preceding stage's result per `docs/superpowers/specs/2026-07-14-learned-kwalk-acceleration-design.md`. Do not implement any model here.

---

### Task 1: `foeopt/corpus.py` — corpus writer + loaders

**Files:**
- Create: `foeopt/corpus.py`
- Test: `tests/test_corpus.py`

**Interfaces:**
- Consumes: `foeopt.model.Layout` (for `CorpusWriter.__init__`, via `layout.road_needing()` and `layout.region.cells`); plain values elsewhere.
- Produces:
  - `CorpusWriter(corpus_dir, layout)` — writes `manifest.json` on init, opens `instances.jsonl` for append; `.record(*, k, roads, th, status, secs, pos)` appends one line; `.close()`.
  - `load_manifest(corpus_dir) -> dict`
  - `load_instances(corpus_dir) -> Iterator[dict]`
  - `reconstruct(manifest, record) -> dict` with keys `region` (set of cells), `skeleton` (set of cells), `buildings` (list), `th` (4-tuple), `status`, `pos`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_corpus.py`:

```python
import json

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.corpus import CorpusWriter, load_manifest, load_instances, reconstruct


def _tiny_layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 1, 1), True, 2, False, None, None, "hut")
    region = Region(frozenset((x, y) for x in range(5) for y in range(5)))
    return Layout(region, [th, c1], th, {})


def test_manifest_written_on_init(tmp_path):
    CorpusWriter(tmp_path, _tiny_layout()).close()
    man = load_manifest(tmp_path)
    assert isinstance(man["city_id"], str) and len(man["city_id"]) == 16
    assert [0, 0] in man["region"] and len(man["region"]) == 25
    assert man["buildings"] == [{"id": "10", "w": 1, "l": 1, "road_level": 2}]


def test_records_round_trip(tmp_path):
    w = CorpusWriter(tmp_path, _tiny_layout())
    th = Footprint(0, 0, 2, 2)
    w.record(k=9, roads=frozenset({(2, 1), (2, 0)}), th=th,
             status="SAT", secs=1.2, pos={10: (3, 0, 1, 1)})
    w.record(k=9, roads=frozenset({(2, 0)}), th=th,
             status="UNSAT", secs=0.4, pos=None)
    w.close()
    recs = list(load_instances(tmp_path))
    assert len(recs) == 2
    assert recs[0]["k"] == 9 and recs[0]["status"] == "SAT"
    assert recs[0]["roads"] == [[2, 0], [2, 1]]          # sorted
    assert recs[0]["th"] == [0, 0, 2, 2]
    assert recs[0]["pos"] == {"10": [3, 0, 1, 1]}        # keys stringified, tuples -> lists
    assert recs[1]["status"] == "UNSAT" and recs[1]["pos"] is None


def test_reconstruct(tmp_path):
    w = CorpusWriter(tmp_path, _tiny_layout())
    w.record(k=9, roads=frozenset({(2, 0), (2, 1)}), th=Footprint(0, 0, 2, 2),
             status="SAT", secs=1.0, pos={10: (3, 0, 1, 1)})
    w.close()
    man = load_manifest(tmp_path)
    rec = next(iter(load_instances(tmp_path)))
    out = reconstruct(man, rec)
    assert out["region"] == {(x, y) for x in range(5) for y in range(5)}
    assert out["skeleton"] == {(2, 0), (2, 1)}
    assert out["buildings"] == [{"id": "10", "w": 1, "l": 1, "road_level": 2}]
    assert out["th"] == (0, 0, 2, 2)
    assert out["status"] == "SAT" and out["pos"] == {"10": [3, 0, 1, 1]}


def test_load_instances_missing_file_is_empty(tmp_path):
    assert list(load_instances(tmp_path)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foeopt.corpus'`.

- [ ] **Step 3: Implement `foeopt/corpus.py`**

```python
from __future__ import annotations

import hashlib
import json
import pathlib
from collections.abc import Iterator


def _city_id(region: list, buildings: list) -> str:
    h = hashlib.sha256()
    h.update(repr(region).encode())
    h.update(repr([(b["id"], b["w"], b["l"], b["road_level"]) for b in buildings]).encode())
    return h.hexdigest()[:16]


class CorpusWriter:
    """Append-only writer for one city's roads-first probe corpus.

    Writes a manifest (region + road-needing building set, constant per city)
    once, then one JSON line per probe (skeleton + status + optional CP-SAT
    placement) to instances.jsonl. The manifest keeps the large constant data
    out of every record.
    """

    def __init__(self, corpus_dir, layout):
        self.dir = pathlib.Path(corpus_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        buildings = [{"id": str(b.entity_id), "w": b.footprint.width,
                      "l": b.footprint.length, "road_level": b.road_level}
                     for b in layout.road_needing()]
        region = sorted([x, y] for (x, y) in layout.region.cells)
        self.city_id = _city_id(region, buildings)
        (self.dir / "manifest.json").write_text(
            json.dumps({"city_id": self.city_id, "region": region,
                        "buildings": buildings}),
            encoding="utf-8")
        self._fh = open(self.dir / "instances.jsonl", "a", encoding="utf-8")

    def record(self, *, k, roads, th, status, secs, pos):
        rec = {
            "k": k,
            "status": status,
            "secs": secs,
            "th": [th.x, th.y, th.width, th.length],
            "roads": sorted([x, y] for (x, y) in roads),
            "pos": ({str(bid): list(v) for bid, v in pos.items()} if pos else None),
        }
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()


def load_manifest(corpus_dir) -> dict:
    return json.loads((pathlib.Path(corpus_dir) / "manifest.json").read_text(encoding="utf-8"))


def load_instances(corpus_dir) -> Iterator[dict]:
    p = pathlib.Path(corpus_dir) / "instances.jsonl"
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def reconstruct(manifest: dict, record: dict) -> dict:
    return {
        "region": {(x, y) for x, y in manifest["region"]},
        "skeleton": {(x, y) for x, y in record["roads"]},
        "buildings": manifest["buildings"],
        "th": tuple(record["th"]),
        "status": record["status"],
        "pos": record.get("pos"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add foeopt/corpus.py tests/test_corpus.py
git commit -m "feat: add roads-first corpus writer/loader (Track C-bis Stage 0)"
```

---

### Task 2: Capture the CP-SAT placement `pos` in `_run_probe`

**Files:**
- Modify: `foeopt/roads_first.py` (`_run_probe`, lines ~320-338)
- Test: `tests/test_corpus_capture.py`

**Interfaces:**
- Consumes: existing `probe()` (returns `("SAT", pos)` where `pos` is `{entity_id: (x, y, w, l)}`), `_run_probe_seq`.
- Produces: `_run_probe(...)` return dict gains a `"pos"` key — the CP-SAT placement when CP-SAT returned SAT (in both the validate-OK and validate-failed branches), else `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_corpus_capture.py`:

```python
import random
import time
from types import SimpleNamespace

from foeopt.model import Building, Footprint, Layout, Region
from foeopt import roads_first as rf


def _tiny():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    c1 = Building(10, "c10", "g", Footprint(0, 0, 1, 1), True, 1, False, None, None, "hut")
    region = {(x, y) for x in range(5) for y in range(5)}
    layout = Layout(Region(frozenset(region)), [th, c1], th, {})
    pat = rf.Pattern(th=Footprint(0, 0, 2, 2),
                     roads=frozenset({(2, 0), (2, 1)}), params={"src": "test"})
    return layout, region, pat


def test_run_probe_includes_cp_sat_placement():
    layout, region, pat = _tiny()
    consumers = layout.road_needing()
    st, pos = rf.probe(pat, region, consumers, probe_limit=10.0, probe_workers=1)
    assert st == "SAT" and pos and 10 in pos
    res = rf._run_probe_seq((pat, 9, layout, 10.0, 1))
    assert "pos" in res
    assert res["pos"] == pos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_capture.py -v`
Expected: FAIL with `KeyError: 'pos'` (or assertion that `"pos" in res` is False).

- [ ] **Step 3: Add `pos` to every `_run_probe` return**

In `foeopt/roads_first.py`, replace the body of `_run_probe` after the `probe()` call (the three `return {...}` dicts) so each carries `pos`:

```python
    secs = round(time.monotonic() - t0, 1)
    if st != "SAT":
        return {"k": k, "params": pat.params, "status": st,
                "achieved": None, "secs": secs, "layout": None,
                "pat_index": pat_index, "pos": None}
    vstat, vlay, achieved = validate(layout, pat, pos)
    if vstat == "OK":
        return {"k": k, "params": pat.params, "status": "SAT",
                "achieved": achieved, "secs": secs, "layout": vlay,
                "pat_index": pat_index, "pos": pos}
    return {"k": k, "params": pat.params, "status": vstat,
            "achieved": None, "secs": secs, "layout": None,
            "pat_index": pat_index, "pos": pos}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus_capture.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Run the roads-first suite for regressions**

Run: `uv run pytest tests/test_roads_first_parallel.py -q && uv run python scripts/exp_roads_first.py --selftest`
Expected: all pass; selftest prints `selftest: PASS`.

- [ ] **Step 6: Commit**

```bash
git add foeopt/roads_first.py tests/test_corpus_capture.py
git commit -m "feat: surface CP-SAT placement (pos) from _run_probe for the corpus"
```

---

### Task 3: Wire opt-in corpus recording into the search + `--corpus` CLI flag

**Files:**
- Modify: `foeopt/roads_first.py` (`_probe_level` signature + `handle_result`; `RoadsFirstSearch.__init__`/`run`; import)
- Modify: `scripts/exp_roads_first.py` (`--corpus` flag + pass-through)
- Modify: `tests/test_roads_first_parallel.py` (three `spy_probe_level` signatures gain `corpus=None`)
- Test: `tests/test_corpus_capture.py` (append)

**Interfaces:**
- Consumes: `foeopt.corpus.CorpusWriter` (Task 1), the `pos`-carrying `_run_probe` (Task 2).
- Produces:
  - `_probe_level(..., corpus=None)` — records each `handle_result` probe when `corpus` is set.
  - `RoadsFirstSearch(..., corpus_dir=None)` — creates a `CorpusWriter` in `run()` when set, threads it into `_probe_level`, closes it in `finally`.
  - `scripts/exp_roads_first.py --corpus DIR` — passes `corpus_dir=DIR`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_corpus_capture.py`:

```python
def test_probe_level_records_each_probe(tmp_path, monkeypatch):
    from foeopt.corpus import CorpusWriter, load_instances
    layout, region, pat = _tiny()
    monkeypatch.setattr(rf, "generate_patterns", lambda *a, **k: [pat])
    monkeypatch.setattr(rf, "prefilter", lambda *a, **k: None)
    writer = CorpusWriter(tmp_path, layout)
    params = SimpleNamespace(patterns=1, probe_limit=10.0, probe_workers=1,
                             deadline=time.monotonic() + 30, th_anchors="coarse")
    rf._probe_level(layout, set(region), layout.road_needing(), 9,
                    random.Random(0), params, lambda r: None,
                    pool=None, corpus=writer)
    writer.close()
    recs = list(load_instances(tmp_path))
    assert len(recs) == 1
    assert recs[0]["k"] == 9
    assert recs[0]["roads"] == [[2, 0], [2, 1]]
    assert "pos" in recs[0]


def test_search_run_writes_manifest_and_instances(tmp_path):
    from foeopt.corpus import load_manifest, load_instances
    layout, _region, _pat = _tiny()
    rf.RoadsFirstSearch(layout, time_box=20.0, patterns=5, workers=1,
                        probe_workers=1, th_anchors="coarse",
                        corpus_dir=tmp_path).run()
    man = load_manifest(tmp_path)
    assert man["buildings"] == [{"id": "10", "w": 1, "l": 1, "road_level": 1}]
    for r in load_instances(tmp_path):        # every recorded line is well-formed
        assert set(r) >= {"k", "status", "secs", "th", "roads", "pos"}


def test_corpus_off_by_default_writes_nothing(tmp_path, monkeypatch):
    layout, _region, _pat = _tiny()
    monkeypatch.chdir(tmp_path)
    rf.RoadsFirstSearch(layout, time_box=20.0, patterns=5, workers=1,
                        probe_workers=1, th_anchors="coarse").run()
    assert not (tmp_path / "manifest.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_capture.py -v`
Expected: FAIL — `_probe_level` has no `corpus` kwarg / `RoadsFirstSearch` has no `corpus_dir` kwarg (`TypeError`).

- [ ] **Step 3: Add the corpus import**

In `foeopt/roads_first.py`, after `from foeopt.bounds import pick_k_start` (line 11), add:

```python
from foeopt.corpus import CorpusWriter
```

- [ ] **Step 4: Add `corpus` to `_probe_level` and record in `handle_result`**

Change the `_probe_level` signature to add a trailing `corpus=None`:

```python
def _probe_level(layout, region, consumers, k, rng, params, log, pool=None,
                 on_improvement=None, corpus=None) -> tuple[str, int | None]:
```

Inside `handle_result`, immediately after the existing `log({...})` call, add the record hook:

```python
        log({"k": k, "params": pat.params, "status": status,
             "achieved": achieved, "secs": result["secs"], "order": order})
        if corpus is not None:
            corpus.record(k=k, roads=pat.roads, th=pat.th, status=status,
                          secs=result["secs"], pos=result.get("pos"))
```

- [ ] **Step 5: Add `corpus_dir` to `RoadsFirstSearch` and thread it through `run`**

In `RoadsFirstSearch.__init__`, add `corpus_dir=None` to the signature and store it:

```python
    def __init__(self, layout: Layout, *, time_box: float, patterns: int = 200,
                 probe_limit: float = 60.0, workers: int = 4,
                 probe_workers: int = 4, th_anchors: str = "full",
                 k_start="auto", corpus_dir=None):
        ...
        self.k_start = k_start
        self.corpus_dir = corpus_dir
```

In `run()`, create the writer after the `pool = ...` block (before `params = SimpleNamespace(...)`):

```python
        corpus = CorpusWriter(self.corpus_dir, layout) if self.corpus_dir else None
```

Pass it into the `_probe_level` call inside `level(k)`:

```python
                results[k] = _probe_level(layout, region, consumers, k, rng,
                                          params, lambda r: None, pool=pool,
                                          on_improvement=on_improvement,
                                          corpus=corpus)
```

Close it in the `finally` block alongside the pool:

```python
        finally:
            if corpus is not None:
                corpus.close()
            if pool is not None:
                pool.close()
                pool.join()
```

Because `run()` now passes `corpus=corpus` to `_probe_level`, and the k-start tests in
`tests/test_roads_first_parallel.py` **replace** `_probe_level` with a `spy_probe_level`,
those spies must accept the new kwarg or they will raise `TypeError` when `run()` calls them.
There are three such spies (in `test_k_start_auto_resolves_to_pick_k_start`,
`test_k_start_explicit_integer_overrides_auto`, and `test_fallback_cap_is_k_max_not_168`).
For each, add `corpus=None` to the signature:

```python
    def spy_probe_level(layout, region, consumers, k, rng, args, log, pool=None,
                        on_improvement=None, corpus=None):
```

- [ ] **Step 6: Add the `--corpus` CLI flag**

In `scripts/exp_roads_first.py::main`, add the argument next to the other options (after `--probe-workers`):

```python
    p.add_argument("--corpus", default=None, metavar="DIR")
```

And pass it into the `RoadsFirstSearch(...)` constructor in the same `main`:

```python
    res = RoadsFirstSearch(
        layout,
        time_box=args.time_box,
        patterns=args.patterns,
        probe_limit=args.probe_limit,
        workers=args.workers,
        probe_workers=args.probe_workers,
        th_anchors=args.th_anchors,
        k_start=args.k_start,
        corpus_dir=args.corpus,
    ).run(on_improvement=on_improvement, on_status=on_status)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_corpus_capture.py tests/test_corpus.py -v`
Expected: PASS (all corpus tests, including the three appended integration tests).

- [ ] **Step 8: Run the roads-first suite + selftest for regressions**

Run: `uv run pytest tests/test_roads_first_parallel.py -q && uv run python scripts/exp_roads_first.py --selftest`
Expected: all pass; `selftest: PASS`.

- [ ] **Step 9: Commit**

```bash
git add foeopt/roads_first.py scripts/exp_roads_first.py tests/test_corpus_capture.py tests/test_roads_first_parallel.py
git commit -m "feat: opt-in --corpus recording in RoadsFirstSearch k-walk (Track C-bis Stage 0)"
```

---

### Task 4: Full-suite regression + Stage-0 wrap-up

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `uv run pytest -q --ignore=tests/test_rl_anneal.py --ignore=tests/test_rl_gate.py`
Expected: all pass (the new `test_corpus.py` + `test_corpus_capture.py` included), no regressions. Data-dependent tests skip if the large exports are absent.

- [ ] **Step 2: Confirm the selftest and the opt-in default**

Run: `uv run python scripts/exp_roads_first.py --selftest`
Expected: `selftest: PASS`. (The corpus is off by default; the selftest path passes no `--corpus`.)

- [ ] **Step 3: Confirm `--corpus` is wired**

Run: `uv run python scripts/exp_roads_first.py --help`
Expected: the help text lists `--corpus DIR`.

**Stage-0 exit note (G0):** the data engine is complete when a real `--corpus output/corpus/<city>` run on a supplied city (darkzig + one FR city, per the spec) produces a `manifest.json` + non-empty `instances.jsonl` whose SAT records carry a `pos`. That real run uses the user-supplied gitignored exports and is performed when the corpus is actually generated for Stage 1 — it is not a repo test (no large data files are committed).
