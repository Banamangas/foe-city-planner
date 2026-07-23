# Wide-shallow skeleton screen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Screen ~5,000 lane skeletons per k-level at a 30 s budget with 12-way pattern concurrency, to decide whether any lane skeleton admits a legal placement routing below darkzig's 102-road floor — and, on a null, produce a quantified bound instead of an unfalsifiable shrug.

**Architecture:** A `scripts/`-only experiment. Patterns come from the existing `generate_lane_patterns` (which shuffles the full ~67.3k population and truncates, giving a uniform sample without replacement for a fixed seed). Each pattern is `prefilter`ed, then probed in a `multiprocessing.Pool` of 12 workers each running `probe_workers=1` — the dispatch measured at 10.29× the old one-pattern-×-12-threads arrangement. Rows stream to JSONL as they complete so an interrupted 8 h run resumes instead of restarting; every SAT is persisted in the existing `best-k*.json` schema so it can be re-verified by the already-built exact router. Verdict logic is pure and unit-tested; the solver path is covered by `--selftest`.

**Tech Stack:** Python ≥3.12, OR-Tools CP-SAT (via `foeopt.roads_first.probe`, lazy-imported), `multiprocessing`, pytest. Spec: `docs/superpowers/specs/2026-07-22-wide-shallow-skeleton-screen-design.md`.

## Global Constraints

- Python `>=3.12`. **Experiment script under `scripts/` only — do NOT modify `foeopt/`.** The one core change this needs (`probe(..., diag=)`) is already committed in `b4465fe`.
- **Family: `lane` only.** `hybrid`/`max_lane_len` is a strict subset of `lane` (measured: `novel = 0` at every cap and k) and must NOT be added as a second arm.
- **k-levels: `105,106,107`.** k=109 is excluded as unwinnable (its SATs achieved 105/108; beating the floor needs ≤101).
- **Budget: 30.0 s per probe. Workers: 12 processes × `probe_workers=1`.** Never `probe_workers=12`.
- **Floor: 102.** A result "breaks the floor" only when `status == "SAT"` **and** `validate(...) == "OK"` **and** `achieved < 102` **and** `legal` (`rotated_buildings == 0`). Ties at 102 are not wins.
- **No symmetry breaking**, no hints, no stub_priority — all default off.
- **FoE buildings cannot rotate.** Legality is checked via `rotated_buildings(vlay, canonical_dims(layout)) == 0`.
- Determinism: seeded `random.Random(seed)`. Pattern identity is `(k, idx)` where `idx` is the position in the seeded sample — **regeneration with the same `--seed` and `--n` reproduces the same patterns**, which is what makes resume and the §6 recheck arm possible.
- Persist SATs in the **existing `best-k*.json` schema** (`{"k","achieved","roads","buildings"}` with `buildings` keyed by str(entity_id) → `[x,y,w,l]`) so `scripts/exp_exact_router.py:reconstruct_fixed` consumes them unchanged.

---

## File Structure

- `scripts/exp_wide_skeleton_screen.py` — **new.** Pure logic (`rule_of_three`, `classify_verdict`, `summarize`), sampling (`sample_patterns`), pool worker (`_init_worker`, `_screen_one`, `_sat_artifact`), driver (`run_screen`, `load_done`, `persist_sat`), recheck arm (`run_recheck`), `_selftest`, `main`.
- `tests/test_wide_skeleton_screen.py` — **new.** Unit tests for the pure logic and the JSONL/resume helpers. No solver.
- `tasks/lessons.md` — **modify (append)** in Task 6, after the real run.

**Row schema** (one JSON object per line in the JSONL):

```python
{"k": int, "idx": int, "status": str, "achieved": int | None, "legal": bool | None,
 "secs": float, "th": [int, int], "reason": str | None, "branches": int | None,
 "solve_s": float | None}
```

`status` ∈ `"SAT" | "UNSAT" | "UNKNOWN" | "PREFILTERED"` plus `validate()`'s own terminal statuses passed through verbatim: `"ROUTE_FAIL" | "INVALID" | "SAT_FILLER_FAIL" | "SAT_ROTATED"`. (Corrected during Task 3 review: `validate()` already returns these pre-prefixed, so re-prefixing them emitted `"SAT_SAT_ROTATED"` and broke the vocabulary used by `foeopt/roads_first.py:handle_result` and `tests/test_kwalk_data.py`.)

---

### Task 1: verdict logic + rule-of-three bound (pure, no solver)

**Files:**
- Create: `scripts/exp_wide_skeleton_screen.py`
- Test: `tests/test_wide_skeleton_screen.py`

**Interfaces:**
- Produces: `FLOOR = 102`; `rule_of_three(n: int) -> float`; `classify_verdict(rows: list[dict], floor: int = FLOOR) -> tuple[str, dict]`. Verdict strings: `"BREAK_FLOOR"`, `"FEASIBLE_NOT_SUPERIOR"`, `"NULL_WITH_BOUND"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wide_skeleton_screen.py`:

```python
import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "exp_wide_skeleton_screen",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_wide_skeleton_screen.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _row(status, achieved=None, legal=None, k=105, idx=0):
    return {"k": k, "idx": idx, "status": status, "achieved": achieved, "legal": legal}


def test_rule_of_three_bound():
    assert mod.rule_of_three(5000) == 3.0 / 5000
    assert mod.rule_of_three(1) == 3.0
    # n=0 must not divide by zero; an unobserved event after 0 trials is unbounded
    assert mod.rule_of_three(0) == 1.0


def test_verdict_break_floor_on_legal_sub_102():
    rows = [_row("SAT", achieved=101, legal=True), _row("UNSAT")]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "BREAK_FLOOR"
    assert detail["best_achieved"] == 101


def test_verdict_tie_at_floor_is_not_a_win():
    # achieved == floor ties the record, it does not beat it
    rows = [_row("SAT", achieved=102, legal=True), _row("UNSAT")]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "FEASIBLE_NOT_SUPERIOR"
    assert detail["best_achieved"] == 102


def test_verdict_ignores_illegal_sat():
    # a rotated (illegal) sub-floor SAT must never trigger BREAK_FLOOR
    rows = [_row("SAT", achieved=99, legal=False), _row("UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "NULL_WITH_BOUND"


def test_verdict_null_reports_bound_over_all_screened_rows():
    # PREFILTERED rows are determinations too and must count toward n
    rows = [_row("UNSAT"), _row("UNKNOWN"), _row("PREFILTERED")]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "NULL_WITH_BOUND"
    assert detail["n"] == 3
    assert detail["p_bound"] == 1.0
    assert detail["best_achieved"] is None


def test_verdict_break_floor_wins_over_a_worse_sat():
    rows = [_row("SAT", achieved=104, legal=True), _row("SAT", achieved=100, legal=True)]
    verdict, detail = mod.classify_verdict(rows)
    assert verdict == "BREAK_FLOOR"
    assert detail["best_achieved"] == 100
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: FAIL — `FileNotFoundError` / `ModuleNotFoundError` for `scripts/exp_wide_skeleton_screen.py`.

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/exp_wide_skeleton_screen.py`:

```python
"""Wide-shallow lane-skeleton screen.

Screen a large sample of lane skeletons at a SHORT budget with concurrency
across patterns, rather than a tiny sample at a long budget with concurrency
inside one probe. Rationale (spec 2026-07-22): UNSAT is nearly free
(presolve, ~5ms), UNKNOWN does not converge with budget (900s autopsy
resolved 4 of 8), and every SAT in the 1459-instance corpus resolved within
29.2s -- so the binding resource is patterns sampled, not seconds per pattern.

  uv run python scripts/exp_wide_skeleton_screen.py --selftest
  uv run python scripts/exp_wide_skeleton_screen.py darkzig.json \
      --k-levels 105,106,107 --n 5000 --budget 30 --workers 12 \
      --out output/wide-screen.jsonl --sat-dir output/wide-screen-sats
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

FLOOR = 102


def rule_of_three(n: int) -> float:
    """95% upper bound on the rate of an event observed ZERO times in n trials.

    Reported on a null screen so "we found nothing" becomes a number: 0 SATs
    in 5,000 patterns bounds p*d below 0.06%, where "0 in 12" bounds nothing.
    """
    if n <= 0:
        return 1.0
    return min(1.0, 3.0 / n)


def classify_verdict(rows: list[dict], floor: int = FLOOR) -> tuple[str, dict]:
    """Pre-committed verdict (spec section 5). Only a LEGAL, validated SAT
    strictly below `floor` counts as breaking it -- a tie does not."""
    sats = [r for r in rows
            if r["status"] == "SAT" and r.get("legal") and r.get("achieved") is not None]
    detail = {"n": len(rows), "n_sat": len(sats),
              "best_achieved": (min(r["achieved"] for r in sats) if sats else None)}
    if any(r["achieved"] < floor for r in sats):
        return "BREAK_FLOOR", detail
    if sats:
        return "FEASIBLE_NOT_SUPERIOR", detail
    detail["p_bound"] = rule_of_three(len(rows))
    return "NULL_WITH_BOUND", detail
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_wide_skeleton_screen.py tests/test_wide_skeleton_screen.py
git commit -m "feat: wide-screen verdict logic with rule-of-three bound

A null screen now reports a number instead of a shrug: 0 SATs in n patterns
bounds the feasible-and-detectable rate below 3/n (95%). Ties at the 102
floor are explicitly not wins, and illegal (rotated) SATs never count."
```

---

### Task 2: sampling, prefilter, and crash-safe JSONL with resume

**Files:**
- Modify: `scripts/exp_wide_skeleton_screen.py`
- Test: `tests/test_wide_skeleton_screen.py`

**Interfaces:**
- Consumes: `foeopt.roads_first.{generate_lane_patterns, prefilter}`.
- Produces: `sample_patterns(region, tw, tl, k, n, seed) -> list[Pattern]`; `load_done(path: pathlib.Path) -> set[tuple[int, int]]`; `append_row(fh, row: dict) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wide_skeleton_screen.py`:

```python
def test_load_done_returns_k_idx_pairs(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text('{"k": 105, "idx": 0, "status": "UNSAT"}\n'
                 '{"k": 105, "idx": 7, "status": "UNKNOWN"}\n')
    assert mod.load_done(p) == {(105, 0), (105, 7)}


def test_load_done_missing_file_is_empty(tmp_path):
    assert mod.load_done(tmp_path / "nope.jsonl") == set()


def test_load_done_tolerates_torn_final_line(tmp_path):
    """An 8h run killed mid-write leaves a partial last line. Resume must
    skip it rather than crash, or the whole run is unrecoverable."""
    p = tmp_path / "rows.jsonl"
    p.write_text('{"k": 105, "idx": 0, "status": "UNSAT"}\n{"k": 105, "idx')
    assert mod.load_done(p) == {(105, 0)}


def test_sample_patterns_is_deterministic_and_sized():
    """Resume and the recheck arm both rely on (seed, n, k) reproducing the
    exact same patterns in the exact same order."""
    region = {(x, y) for x in range(20) for y in range(20)}
    a = mod.sample_patterns(region, 2, 2, 20, 5, seed=0)
    b = mod.sample_patterns(region, 2, 2, 20, 5, seed=0)
    assert len(a) == 5
    assert [p.roads for p in a] == [p.roads for p in b]
    c = mod.sample_patterns(region, 2, 2, 20, 5, seed=1)
    assert [p.roads for p in a] != [p.roads for p in c]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: FAIL with `AttributeError: module has no attribute 'load_done'`.

- [ ] **Step 3: Write the implementation**

Add these imports to the top-level import block (immediately after the `sys.path.insert` line, matching `scripts/exp_richer_skeleton_probe.py`):

```python
from foeopt.roads_first import generate_lane_patterns, prefilter
```

Then add after `classify_verdict`:

```python
def sample_patterns(region, tw, tl, k, n, seed):
    """Uniform sample without replacement from the full lane population.

    `generate_lane_patterns` builds every pattern for this k, shuffles with the
    supplied rng, then truncates -- so a fixed seed makes the sample and its
    index order reproducible, which is what `--resume` and `--recheck` rely on.
    """
    return generate_lane_patterns(region, tw, tl, k, random.Random(seed), n,
                                  th_mode="full")


def load_done(path: pathlib.Path) -> set[tuple[int, int]]:
    """(k, idx) pairs already recorded. Tolerates a torn final line from a
    killed run -- otherwise one interrupted write would strand the whole file."""
    done: set[tuple[int, int]] = set()
    if not path.exists():
        return done
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add((r["k"], r["idx"]))
    return done


def append_row(fh, row: dict) -> None:
    """Write and flush immediately: an 8h run must survive a kill -9."""
    fh.write(json.dumps(row) + "\n")
    fh.flush()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_wide_skeleton_screen.py tests/test_wide_skeleton_screen.py
git commit -m "feat: deterministic sampling + crash-safe resumable JSONL

Rows stream and flush per probe so an 8h screen resumes from a kill instead
of restarting, and load_done tolerates the torn final line such a kill
leaves behind. Sampling is seed-reproducible so (k, idx) identifies a
pattern well enough to regenerate it later."
```

---

### Task 3: pooled 12×1 screen dispatch + SAT persistence

**Files:**
- Modify: `scripts/exp_wide_skeleton_screen.py`
- Test: `tests/test_wide_skeleton_screen.py`

**Interfaces:**
- Consumes: `foeopt.roads_first.{probe, validate}`, `foeopt.validate.{rotated_buildings, canonical_dims}`.
- Produces: `_init_worker(layout, budget)`; `_screen_one(payload) -> tuple[dict, dict | None]` where payload is `(k, idx, pat)`; `_sat_artifact(k, idx, pat, vlay, achieved) -> dict`; `persist_sat(sat_dir, art) -> pathlib.Path`; `run_screen(layout, ks, n_per, budget, workers, seed, out_path, sat_dir, resume) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wide_skeleton_screen.py`:

```python
def test_sat_artifact_matches_best_k_schema(tmp_path):
    """SAT artifacts must be consumable by exp_exact_router.reconstruct_fixed
    unchanged -- that is how a floor-breaking layout gets independently
    re-verified. reconstruct_fixed reads best["buildings"] as
    {str(entity_id): [x, y, w, l]}."""
    from foeopt.model import Building, Footprint, Layout, Region
    from foeopt.roads_first import Pattern
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(2, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    vlay = Layout(region, [th, c1], th, {})
    vlay.roads = [(0, 2), (1, 2)]
    pat = Pattern(th=Footprint(0, 0, 2, 2), roads=frozenset({(0, 2), (1, 2)}),
                  params={"th": (0, 0), "k": 2})
    art = mod._sat_artifact(105, 3, pat, vlay, 2)
    assert art["k"] == 105 and art["idx"] == 3 and art["achieved"] == 2
    assert art["buildings"] == {"1": [0, 0, 2, 2], "2": [2, 0, 2, 1]}
    assert sorted(art["roads"]) == [[0, 2], [1, 2]]
    assert sorted(art["pattern_roads"]) == [[0, 2], [1, 2]]
    # every key reconstruct_fixed touches must be JSON round-trippable
    assert json.loads(json.dumps(art))["buildings"]["1"] == [0, 0, 2, 2]


def test_persist_sat_writes_identifiable_filename(tmp_path):
    art = {"k": 106, "idx": 42, "achieved": 101, "th": [1, 1, 2, 2],
           "pattern_roads": [], "roads": [], "buildings": {}}
    p = mod.persist_sat(tmp_path, art)
    assert p.exists()
    assert p.name == "sat-k106-i42-a101.json"
    assert json.loads(p.read_text())["achieved"] == 101
```

Add `import json` to the test file's imports if not already present.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: FAIL with `AttributeError: module has no attribute '_sat_artifact'`.

- [ ] **Step 3: Write the implementation**

Add to `scripts/exp_wide_skeleton_screen.py`:

Extend the top-level import block with:

```python
from foeopt.loader import load_layout
from foeopt.roads_first import probe, validate
from foeopt.validate import canonical_dims, rotated_buildings
```

Then add:

```python
_W: dict = {}


def _init_worker(layout, budget):
    """Pool initializer: each worker holds the layout once, not per task."""
    _W["layout"] = layout
    _W["region"] = set(layout.region.cells)
    _W["consumers"] = layout.road_needing()
    _W["budget"] = budget


def _sat_artifact(k, idx, pat, vlay, achieved) -> dict:
    """Serialize a SAT in the existing best-k*.json schema (plus pattern
    identity) so scripts/exp_exact_router.py:reconstruct_fixed consumes it
    unchanged. Built inside the worker so no Layout crosses the process
    boundary."""
    return {
        "k": k, "idx": idx, "achieved": achieved,
        "th": [pat.th.x, pat.th.y, pat.th.width, pat.th.length],
        "pattern_roads": sorted([x, y] for (x, y) in pat.roads),
        "roads": sorted([x, y] for (x, y) in vlay.roads),
        "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                         b.footprint.width, b.footprint.length]
                      for b in vlay.buildings},
    }


def _screen_one(payload):
    """Probe one pattern at probe_workers=1. Returns (row, sat_artifact|None)."""
    k, idx, pat = payload
    diag: dict = {}
    t0 = time.monotonic()
    st, pos = probe(pat, _W["region"], _W["consumers"],
                    probe_limit=_W["budget"], probe_workers=1, diag=diag)
    row = {"k": k, "idx": idx, "status": st, "achieved": None, "legal": None,
           "secs": round(time.monotonic() - t0, 2),
           "th": list(pat.params["th"]), "reason": diag.get("reason"),
           "branches": diag.get("branches"), "solve_s": diag.get("solve_s")}
    if st != "SAT":
        return row, None
    vst, vlay, achieved = validate(_W["layout"], pat, pos)
    if vst != "OK":
        row["status"] = f"SAT_{vst}"
        return row, None
    row["achieved"] = achieved
    row["legal"] = len(rotated_buildings(vlay, canonical_dims(_W["layout"]))) == 0
    return row, _sat_artifact(k, idx, pat, vlay, achieved)


def persist_sat(sat_dir: pathlib.Path, art: dict) -> pathlib.Path:
    sat_dir.mkdir(parents=True, exist_ok=True)
    p = sat_dir / f"sat-k{art['k']}-i{art['idx']}-a{art['achieved']}.json"
    p.write_text(json.dumps(art, indent=1), encoding="utf-8")
    return p


def run_screen(layout, ks, n_per, budget, workers, seed, out_path, sat_dir,
               resume=False):
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    th = layout.townhall.footprint
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out_path) if resume else set()
    if done:
        print(f"resume: skipping {len(done)} already-recorded probes", flush=True)

    rows: list[dict] = []
    payloads = []
    with out_path.open("a") as fh:
        for k in ks:
            pats = sample_patterns(region, th.width, th.length, k, n_per, seed)
            print(f"k={k}: sampled {len(pats)} lane patterns", flush=True)
            for idx, pat in enumerate(pats):
                if (k, idx) in done:
                    continue
                reason = prefilter(pat, region, consumers)
                if reason is not None:
                    # provably dead without a solver call; still a determination,
                    # so it counts toward n in the rule-of-three bound
                    row = {"k": k, "idx": idx, "status": "PREFILTERED",
                           "achieved": None, "legal": None, "secs": 0.0,
                           "th": list(pat.params["th"]),
                           "reason": f"prefilter:{reason}",
                           "branches": None, "solve_s": None}
                    append_row(fh, row)
                    rows.append(row)
                    continue
                payloads.append((k, idx, pat))

        print(f"dispatching {len(payloads)} probes on {workers} workers "
              f"at {budget:.0f}s each", flush=True)
        t0 = time.monotonic()
        with mp.Pool(workers, initializer=_init_worker,
                     initargs=(layout, budget)) as pool:
            for i, (row, art) in enumerate(pool.imap_unordered(_screen_one, payloads), 1):
                append_row(fh, row)
                rows.append(row)
                if art is not None:
                    p = persist_sat(sat_dir, art)
                    print(f"  SAT k={art['k']} idx={art['idx']} "
                          f"achieved={art['achieved']} legal={row['legal']} -> {p}",
                          flush=True)
                if i % 200 == 0:
                    rate = i / ((time.monotonic() - t0) / 60)
                    print(f"  [{i}/{len(payloads)}] {rate:.1f} probes/min", flush=True)
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: PASS, 12 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_wide_skeleton_screen.py tests/test_wide_skeleton_screen.py
git commit -m "feat: pooled 12x1-worker screen dispatch with SAT persistence

12 patterns in flight at probe_workers=1 -- measured 10.29x the wall clock
of one pattern with 12 CP-SAT threads, for a cost of 2 decisions in 50.
SATs are written in the best-k*.json schema so exp_exact_router's
reconstruct_fixed can re-verify them unchanged; the previous run produced a
legal 103 it could not reproduce."
```

---

### Task 4: CLI, summary, and end-to-end selftest

**Files:**
- Modify: `scripts/exp_wide_skeleton_screen.py`

**Interfaces:**
- Produces: `summarize(rows, floor=FLOOR) -> dict`; `_selftest() -> int`; `main() -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wide_skeleton_screen.py`:

```python
def test_summarize_tallies_per_k_and_carries_verdict():
    rows = [
        {"k": 105, "idx": 0, "status": "UNSAT", "achieved": None, "legal": None, "reason": "presolve"},
        {"k": 105, "idx": 1, "status": "UNKNOWN", "achieved": None, "legal": None, "reason": "search"},
        {"k": 106, "idx": 0, "status": "SAT", "achieved": 101, "legal": True, "reason": "search"},
        {"k": 106, "idx": 1, "status": "PREFILTERED", "achieved": None, "legal": None, "reason": "prefilter:area"},
    ]
    s = mod.summarize(rows)
    assert s["per_k"][105]["UNSAT"] == 1 and s["per_k"][105]["UNKNOWN"] == 1
    assert s["per_k"][106]["SAT"] == 1 and s["per_k"][106]["PREFILTERED"] == 1
    assert s["per_k"][106]["min_achieved"] == 101
    assert s["per_k"][105]["min_achieved"] is None
    assert s["verdict"] == "BREAK_FLOOR"
    assert s["detail"]["best_achieved"] == 101
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: FAIL with `AttributeError: module has no attribute 'summarize'`.

- [ ] **Step 3: Write the implementation**

Add to `scripts/exp_wide_skeleton_screen.py`:

```python
def summarize(rows, floor: int = FLOOR) -> dict:
    per_k: dict = {}
    for r in rows:
        d = per_k.setdefault(r["k"], {"n": 0, "SAT": 0, "UNSAT": 0, "UNKNOWN": 0,
                                      "PREFILTERED": 0, "other": 0,
                                      "min_achieved": None})
        d["n"] += 1
        if r["status"] in d:
            d[r["status"]] += 1
        else:
            d["other"] += 1      # SAT_ROTATED, SAT_FILLER_FAIL, ... (raw JSONL keeps the detail)
        if r["status"] == "SAT" and r.get("achieved") is not None:
            if d["min_achieved"] is None or r["achieved"] < d["min_achieved"]:
                d["min_achieved"] = r["achieved"]
    verdict, detail = classify_verdict(rows, floor)
    return {"per_k": per_k, "verdict": verdict, "detail": detail}


def _selftest() -> int:
    """End-to-end on a toy layout: exercises sampling -> prefilter -> pool ->
    JSONL -> summary, which the unit tests deliberately do not (no solver)."""
    import tempfile
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(10) for y in range(10)))
    layout = Layout(region, [th, c1], th, {})
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "rows.jsonl"
        rows = run_screen(layout, [6], n_per=6, budget=5.0, workers=2, seed=0,
                          out_path=out, sat_dir=pathlib.Path(td) / "sats")
        assert rows, "selftest produced no rows"
        assert out.exists() and out.read_text().strip(), "no JSONL written"
        assert load_done(out) == {(r["k"], r["idx"]) for r in rows}, "resume keys mismatch"
        s = summarize(rows)
        assert s["verdict"] in ("BREAK_FLOOR", "FEASIBLE_NOT_SUPERIOR", "NULL_WITH_BOUND")
    print("SELFTEST OK:", json.dumps(s))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("--k-levels", default="105,106,107")
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--floor", type=int, default=FLOOR)
    ap.add_argument("--out", default="output/wide-screen.jsonl")
    ap.add_argument("--sat-dir", default="output/wide-screen-sats")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    layout = load_layout(args.city)
    ks = [int(x) for x in args.k_levels.split(",")]
    out_path = pathlib.Path(args.out)
    rows = run_screen(layout, ks, args.n, args.budget, args.workers, args.seed,
                      out_path, pathlib.Path(args.sat_dir), resume=args.resume)
    if args.resume:
        rows = [json.loads(l) for l in out_path.open() if l.strip()]
    summary = summarize(rows, args.floor)
    print("SUMMARY:", json.dumps(summary, indent=2))
    out_path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests and the selftest**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: PASS, 13 passed.

Run: `uv run python scripts/exp_wide_skeleton_screen.py --selftest`
Expected: a line starting `SELFTEST OK: {"per_k": ...` and exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_wide_skeleton_screen.py tests/test_wide_skeleton_screen.py
git commit -m "feat: screen CLI, per-k summary, and end-to-end selftest

The selftest covers the path the unit tests cannot (real pool, real solver,
real JSONL) on a toy layout in seconds, including that load_done round-trips
every row it wrote -- the resume invariant."
```

---

### Task 5: censoring recheck arm (spec §6)

The 30 s budget was chosen from a SAT distribution that was itself capped at 30 s. This arm tests whether that censoring hides a slow-SAT population — the one place a long budget is justified.

**Files:**
- Modify: `scripts/exp_wide_skeleton_screen.py`

**Interfaces:**
- Produces: `run_recheck(layout, rows_path, sample_n, budget, workers, seed, n_per) -> dict`. Reachable via `--recheck N`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wide_skeleton_screen.py`:

```python
def test_pick_recheck_targets_samples_only_unknowns(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"k": 105, "idx": 0, "status": "UNSAT"},
        {"k": 105, "idx": 1, "status": "UNKNOWN"},
        {"k": 106, "idx": 2, "status": "UNKNOWN"},
        {"k": 106, "idx": 3, "status": "SAT"},
        {"k": 106, "idx": 4, "status": "PREFILTERED"},
    ]) + "\n")
    picked = mod.pick_recheck_targets(p, sample_n=2, seed=0)
    assert len(picked) == 2
    assert set(picked) <= {(105, 1), (106, 2)}
    # deterministic for a fixed seed
    assert picked == mod.pick_recheck_targets(p, sample_n=2, seed=0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: FAIL with `AttributeError: module has no attribute 'pick_recheck_targets'`.

- [ ] **Step 3: Write the implementation**

Add to `scripts/exp_wide_skeleton_screen.py`:

```python
def pick_recheck_targets(rows_path: pathlib.Path, sample_n: int, seed: int):
    """A random subsample of the screen's UNKNOWNs, as (k, idx) pairs."""
    unknown = []
    with rows_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r["status"] == "UNKNOWN":
                unknown.append((r["k"], r["idx"]))
    unknown.sort()
    random.Random(seed).shuffle(unknown)
    return unknown[:sample_n]


def run_recheck(layout, rows_path, sample_n, budget, workers, seed, n_per):
    """Re-probe screen UNKNOWNs at a LONG budget to test whether the 30s cut
    is hiding slow-resolving SATs. `n_per`/`seed` must match the screen run --
    that is what regenerates the same patterns from (k, idx)."""
    targets = pick_recheck_targets(rows_path, sample_n, seed)
    if not targets:
        print("no UNKNOWN rows to recheck")
        return {"n": 0, "converted": 0, "rows": []}
    region = set(layout.region.cells)
    th = layout.townhall.footprint
    by_k: dict = {}
    for k, idx in targets:
        by_k.setdefault(k, []).append(idx)
    payloads = []
    for k, idxs in sorted(by_k.items()):
        pats = sample_patterns(region, th.width, th.length, k, n_per, seed)
        for idx in idxs:
            payloads.append((k, idx, pats[idx]))
    print(f"recheck: {len(payloads)} UNKNOWNs at {budget:.0f}s each", flush=True)
    out = []
    with mp.Pool(workers, initializer=_init_worker,
                 initargs=(layout, budget)) as pool:
        for row, art in pool.imap_unordered(_screen_one, payloads):
            out.append(row)
            print(f"  k={row['k']} idx={row['idx']} -> {row['status']} "
                  f"in {row['secs']}s", flush=True)
    converted = sum(1 for r in out if r["status"] != "UNKNOWN")
    res = {"n": len(out), "converted": converted,
           "sat": sum(1 for r in out if r["status"] == "SAT"), "rows": out}
    print("RECHECK:", json.dumps({k: v for k, v in res.items() if k != "rows"}))
    return res
```

Wire into `main()` — add the argument next to `--resume`:

```python
    ap.add_argument("--recheck", type=int, default=0,
                   help="re-probe N screen UNKNOWNs at --recheck-budget (spec section 6)")
    ap.add_argument("--recheck-budget", type=float, default=300.0)
```

and immediately after `layout = load_layout(args.city)` in `main()`:

```python
    if args.recheck:
        res = run_recheck(layout, pathlib.Path(args.out), args.recheck,
                          args.recheck_budget, args.workers, args.seed, args.n)
        pathlib.Path(args.out).with_suffix(".recheck.json").write_text(
            json.dumps(res, indent=2))
        return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_wide_skeleton_screen.py -q`
Expected: PASS, 14 passed.

Run: `uv run pytest -q`
Expected: PASS — full suite green (was 372 before this plan; expect 372 + 14).

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_wide_skeleton_screen.py tests/test_wide_skeleton_screen.py
git commit -m "feat: censoring recheck arm for the 30s budget choice

The 30s cut was derived from a SAT distribution itself capped at 30s. This
re-probes a random subsample of the screen's UNKNOWNs at 300s: near-zero
conversions confirm the screen is sound, many conversions invalidate the
budget and the power calculation."
```

---

### Task 6: run the screen and record the verdict

**Files:**
- Modify: `tasks/lessons.md`

- [ ] **Step 1: Smoke-test at small n before committing 8 hours**

Run:
```bash
uv run python scripts/exp_wide_skeleton_screen.py darkzig.json \
  --k-levels 107 --n 60 --budget 30 --workers 12 \
  --out output/wide-screen-smoke.jsonl --sat-dir output/wide-screen-smoke-sats
```
Expected: completes in ~2-3 min, prints a `SUMMARY:` block, `output/wide-screen-smoke.jsonl` has 60 lines. Sanity-check the observed probes/min against the calibrated ~30/min before scaling up. **If throughput is far below 30/min, stop and diagnose rather than launching the long run.**

- [ ] **Step 2: Launch the full screen**

Run:
```bash
uv run python scripts/exp_wide_skeleton_screen.py darkzig.json \
  --k-levels 105,106,107 --n 5000 --budget 30 --workers 12 \
  --out output/wide-screen.jsonl --sat-dir output/wide-screen-sats
```
Expected: ~8.3 h. Resume after any interruption by re-running the identical command with `--resume` appended.

- [ ] **Step 3: Run the censoring recheck**

Run:
```bash
uv run python scripts/exp_wide_skeleton_screen.py darkzig.json \
  --n 5000 --recheck 30 --recheck-budget 300 --workers 12 \
  --out output/wide-screen.jsonl
```
Expected: ~2.5 h worst case. Record `converted` and `sat`.

- [ ] **Step 4: Independently re-verify any sub-102 SAT**

For each artifact in `output/wide-screen-sats/` with `achieved < 102`, confirm it survives the exact router and the legality guard — the standing rule after the retracted-127 incident:

```bash
uv run python -c "
import json, sys; sys.path.insert(0,'.')
from foeopt.loader import load_layout
from foeopt.validate import is_valid, rotated_buildings, canonical_dims
from foeopt.router import route
sys.path.insert(0,'scripts')
from exp_exact_router import reconstruct_fixed
lay = load_layout('darkzig.json')
best = json.load(open('output/wide-screen-sats/<FILE>.json'))
fixed = reconstruct_fixed(lay, best)
roads = route(fixed); fixed.roads = roads
print('route()  =', len(roads), 'claimed =', best['achieved'])
print('is_valid =', is_valid(fixed))
print('rotated  =', len(rotated_buildings(fixed, canonical_dims(lay))))
"
```
Expected for a genuine record: `route()` equals the claimed `achieved`, `is_valid` is True, `rotated` is 0.

- [ ] **Step 5: Append the lessons entry and commit**

Write a `tasks/lessons.md` entry in the voice of the existing entries containing: the per-k tally, any achieved counts, the **rule-of-three bound** on a null, the recheck conversion rate, the pre-committed verdict that fired, and the wall clock. State plainly whether the 102 floor was beaten.

```bash
git add tasks/lessons.md
git commit -m "docs: wide-shallow lane screen result and verdict"
```

---

## Self-Review

**Spec coverage:** §3 family/budget/parallelism/sample/prefilter/persistence → Tasks 2-3; §4a calibrated dispatch → Task 3; §5 pre-committed verdict incl. rule-of-three → Tasks 1, 4, 6; §6 censoring arm → Task 5; §8 deliverables (script, calibration, lessons entry) → Tasks 1-6, calibration already run and recorded in §4a.

**Deliberate spec deviations:** none. §6's "uniform sampling may be weak" is explicitly out of scope in the spec and is not implemented.

**Known gaps, accepted:** `summarize` counts unexpected statuses (`SAT_ROTATED` etc.) under `other` rather than naming each; those are rare and the raw JSONL retains them. Resume re-reads the JSONL to rebuild `rows` for the summary (Task 4, `main`) rather than merging in memory — simpler and correct, at the cost of one file read.
