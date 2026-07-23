# Richer-skeleton feasibility diagnostic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Probe lane/hybrid skeletons below comb's 102 floor at a big budget and classify the barrier (break-the-floor / feasibility-wall / decidability-wall) — the verdict that picks the next richer-skeleton track.

**Architecture:** A `kwalk_autopsy`-style diagnostic script generates a (family × k) grid via the existing pattern generators, probes each pattern at a large budget, records SAT/UNSAT/UNKNOWN + the achieved `route()` count, and applies a pre-committed verdict. Pure-logic `classify_verdict` is unit-tested; the generate/probe path is exercised by `--selftest` and the real run.

**Tech Stack:** Python ≥3.12, OR-Tools CP-SAT (via `foeopt.roads_first.probe`, lazy import), pytest. Spec: `docs/superpowers/specs/2026-07-21-richer-skeleton-diagnostic-design.md`.

## Global Constraints

- Python `>=3.12`. Throwaway experiment script under `scripts/`; do NOT modify `foeopt/` core.
- Reuse the existing generators and solver — `generate_patterns` (comb), `generate_lane_patterns` (lane; hybrid = `max_lane_len=24`), `probe`, `validate`, `rotated_buildings`, `canonical_dims`. `ortools` stays inside `probe` (lazy).
- **Families:** `comb` (control), `lane`, `hybrid` (cap=24). **Full-TH** sampling (`th_mode="full"`).
- **The metric is the achieved `route()` count**, not k. A result counts as "beats the floor" only when `status == "SAT"`, `validate(...) == "OK"`, `achieved < 102`, AND it is legal (`rotated_buildings == 0`).
- Determinism: seeded `random.Random`. (CP-SAT's multi-worker portfolio is not perfectly reproducible — a documented noise floor; the verdict reads the aggregate, not a single probe.)
- **Pre-committed verdict (spec §4):** any lane/hybrid SAT with legal `achieved < 102` → **BREAK_FLOOR** (re-verify, new best). Else if lane/hybrid probes are UNKNOWN-dominated → **DECIDABILITY_WALL**. Else (decided; UNSAT or SATs only at ≥102) → **FEASIBILITY_WALL**.
- **Scope:** diagnostic only — no skeleton generator is built; the verdict chooses the next track. Exhaustive enumeration is an out-of-scope follow-up.

---

## File Structure

- `scripts/exp_richer_skeleton_probe.py` — **new, throwaway.** `gen_family`, `probe_pattern`, `run_diagnostic`, `classify_verdict`, `_selftest`, `main`.
- `tests/test_richer_skeleton_probe.py` — **new.** Unit tests for `classify_verdict` (pure logic).
- `tasks/lessons.md` — **modify (append).** The tally + verdict (Task 2).

`Row` shape: `{"family": str, "k": int, "status": str, "achieved": int|None, "legal": bool|None}`. `status` ∈ `"SAT"|"UNSAT"|"UNKNOWN"|"SAT_<validatefail>"`.

---

### Task 1: the diagnostic script + verdict logic

**Files:**
- Create: `scripts/exp_richer_skeleton_probe.py`
- Test: `tests/test_richer_skeleton_probe.py`

**Interfaces:**
- Consumes: `foeopt.loader.load_layout`, `foeopt.roads_first.{generate_patterns, generate_lane_patterns, probe, validate}`, `foeopt.validate.{rotated_buildings, canonical_dims}`.
- Produces: `classify_verdict(rows, floor=102, unknown_frac=0.5) -> tuple[str, str]`; `run_diagnostic(layout, families, ks, n_per, budget, workers, seed) -> list[dict]`.

- [ ] **Step 1: Write the failing tests** (verdict logic is the unit-testable core)

```python
# tests/test_richer_skeleton_probe.py
import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "exp_richer_skeleton_probe",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "exp_richer_skeleton_probe.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _row(family, status, achieved=None, legal=None):
    return {"family": family, "k": 100, "status": status, "achieved": achieved, "legal": legal}


def test_verdict_break_floor_on_legal_sub_102_sat():
    rows = [_row("lane", "SAT", achieved=100, legal=True), _row("comb", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "BREAK_FLOOR"


def test_verdict_feasibility_wall_when_sats_are_at_or_above_floor():
    # a lane SAT that lands at 106 (feasible but not below comb) is a wall, not a win.
    rows = [_row("lane", "SAT", achieved=106, legal=True), _row("hybrid", "UNSAT"),
            _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "FEASIBILITY_WALL"


def test_verdict_decidability_wall_when_unknown_dominated():
    rows = [_row("lane", "UNKNOWN"), _row("hybrid", "UNKNOWN"), _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)  # 2/3 richer UNKNOWN >= 0.5
    assert verdict == "DECIDABILITY_WALL"


def test_verdict_ignores_illegal_sub_102_sat():
    # a sub-102 SAT that is not legal (rotated) must NOT trigger BREAK_FLOOR.
    rows = [_row("lane", "SAT", achieved=99, legal=False), _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "FEASIBILITY_WALL"


def test_verdict_control_comb_excluded_from_richer_tally():
    # comb is a control; only lane/hybrid drive the verdict.
    rows = [_row("comb", "UNKNOWN"), _row("comb", "UNKNOWN"), _row("lane", "UNSAT")]
    verdict, _ = mod.classify_verdict(rows)
    assert verdict == "FEASIBILITY_WALL"     # richer = 1 lane UNSAT, 0 unknown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_richer_skeleton_probe.py -v`
Expected: FAIL — module does not exist yet

- [ ] **Step 3: Write the implementation**

```python
# scripts/exp_richer_skeleton_probe.py
"""Richer-skeleton feasibility diagnostic.

Probe lane/hybrid skeletons below comb's 102 floor at a BIG budget and classify the
barrier: do any resolve SAT with a legal achieved route() count < 102 (break the
floor), are they UNSAT (feasibility wall), or UNKNOWN (decidability wall)? comb is a
control. Reuses the roads-first generators + probe + validate. Spec:
docs/superpowers/specs/2026-07-21-richer-skeleton-diagnostic-design.md.

  uv run python scripts/exp_richer_skeleton_probe.py --selftest
  uv run python scripts/exp_richer_skeleton_probe.py darkzig.json \
      --families comb,lane,hybrid --k-levels 96,100,104 --n 12 \
      --budget 300 --workers 8 --out output/richer-skeleton.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from foeopt.loader import load_layout
from foeopt.roads_first import (
    generate_patterns, generate_lane_patterns, probe, validate,
)
from foeopt.validate import rotated_buildings, canonical_dims

RICHER = ("lane", "hybrid")


def gen_family(family, region, tw, tl, k, rng, n):
    if family == "comb":
        return generate_patterns(region, tw, tl, k, rng, n, th_mode="full")
    if family == "lane":
        return generate_lane_patterns(region, tw, tl, k, rng, n, th_mode="full")
    if family == "hybrid":
        return generate_lane_patterns(region, tw, tl, k, rng, n, th_mode="full", max_lane_len=24)
    raise ValueError(f"unknown family {family}")


def probe_pattern(layout, region, consumers, pat, budget, workers):
    """Returns (status, achieved, legal). achieved/legal set only for a valid SAT layout."""
    st, pos = probe(pat, region, consumers, probe_limit=budget, probe_workers=workers)
    if st != "SAT":
        return st, None, None
    vst, vlay, achieved = validate(layout, pat, pos)
    if vst != "OK":
        return f"SAT_{vst}", None, None          # SAT placement but not a placeable full layout
    legal = len(rotated_buildings(vlay, canonical_dims(layout))) == 0
    return "SAT", achieved, legal


def run_diagnostic(layout, families, ks, n_per, budget, workers, seed):
    region = set(layout.region.cells)
    consumers = layout.road_needing()
    tw, tl = layout.townhall.footprint.width, layout.townhall.footprint.length
    rng = random.Random(seed)
    rows = []
    for family in families:
        for k in ks:
            pats = gen_family(family, region, tw, tl, k, rng, n_per)
            for pat in pats:
                t0 = time.monotonic()
                status, achieved, legal = probe_pattern(layout, region, consumers, pat, budget, workers)
                rows.append({"family": family, "k": k, "status": status,
                             "achieved": achieved, "legal": legal,
                             "secs": round(time.monotonic() - t0, 1)})
                print(json.dumps(rows[-1]), flush=True)
    return rows


def classify_verdict(rows, floor=102, unknown_frac=0.5):
    richer = [r for r in rows if r["family"] in RICHER]
    wins = [r for r in richer if r["status"] == "SAT" and r.get("legal")
            and r["achieved"] is not None and r["achieved"] < floor]
    if wins:
        best = min(r["achieved"] for r in wins)
        return "BREAK_FLOOR", f"lane/hybrid SAT achieves legal {best} < {floor}"
    n = len(richer)
    n_unknown = sum(1 for r in richer if r["status"] == "UNKNOWN")
    if n and n_unknown / n >= unknown_frac:
        return "DECIDABILITY_WALL", f"{n_unknown}/{n} richer probes UNKNOWN, no legal SAT < {floor}"
    return "FEASIBILITY_WALL", f"richer probes decided (no legal SAT < {floor}; {n_unknown}/{n} UNKNOWN)"


def _summary(rows, floor=102):
    out = {}
    for fam in sorted({r["family"] for r in rows}):
        fr = [r for r in rows if r["family"] == fam]
        sats = [r["achieved"] for r in fr if r["status"] == "SAT" and r["achieved"] is not None]
        out[fam] = {"n": len(fr),
                    "SAT": sum(1 for r in fr if r["status"] == "SAT"),
                    "UNSAT": sum(1 for r in fr if r["status"] == "UNSAT"),
                    "UNKNOWN": sum(1 for r in fr if r["status"] == "UNKNOWN"),
                    "min_achieved": (min(sats) if sats else None)}
    verdict, reason = classify_verdict(rows, floor)
    return {"per_family": out, "verdict": verdict, "reason": reason}


def _selftest():
    from foeopt.model import Building, Footprint, Layout, Region
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2), False, 1, True, None, None, "th")
    c1 = Building(2, "c2", "g", Footprint(0, 0, 2, 1), True, 1, False, None, None, "a")
    region = Region(frozenset((x, y) for x in range(6) for y in range(6)))
    layout = Layout(region, [th, c1], th, {})
    rows = run_diagnostic(layout, ["comb"], [4], n_per=2, budget=5.0, workers=1, seed=0)
    v, _ = classify_verdict(rows)
    assert v in ("BREAK_FLOOR", "FEASIBILITY_WALL", "DECIDABILITY_WALL")
    # verdict logic sanity on synthetic rows
    assert classify_verdict([{"family": "lane", "k": 100, "status": "SAT",
                              "achieved": 50, "legal": True}])[0] == "BREAK_FLOOR"
    print("SELFTEST OK:", json.dumps(_summary(rows)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?")
    ap.add_argument("--families", default="comb,lane,hybrid")
    ap.add_argument("--k-levels", default="96,100,104")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--floor", type=int, default=102)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.city:
        ap.error("city file required (or --selftest)")
    layout = load_layout(args.city)
    families = args.families.split(",")
    ks = [int(x) for x in args.k_levels.split(",")]
    rows = run_diagnostic(layout, families, ks, args.n, args.budget, args.workers, args.seed)
    summary = _summary(rows, args.floor)
    print("SUMMARY:", json.dumps(summary, indent=2))
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps({"rows": rows, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests and the selftest**

Run: `uv run pytest tests/test_richer_skeleton_probe.py -v`
Expected: PASS (5 tests)

Run: `uv run python scripts/exp_richer_skeleton_probe.py --selftest`
Expected: prints `SELFTEST OK: {...}` and exits 0

- [ ] **Step 5: Commit**

```bash
git add scripts/exp_richer_skeleton_probe.py tests/test_richer_skeleton_probe.py
git commit -m "feat: richer-skeleton feasibility diagnostic (lane/hybrid probe + verdict)"
```

---

### Task 2: run the diagnostic and record the verdict

**Files:**
- Modify: `tasks/lessons.md` (append a dated entry)

No unit test — runs the experiment and applies the pre-committed verdict. Requires the gitignored `darkzig.json`. If absent, stop and tell the user.

- [ ] **Step 1: Cheap smoke first (confirm the pipeline on real data)**

Run: `uv run python scripts/exp_richer_skeleton_probe.py darkzig.json --families lane --k-levels 100 --n 3 --budget 30 --workers 4`
Expected: 3 JSON rows + a `SUMMARY` with a `verdict`. Confirms generation + probe + validate work on darkzig before the long run.

- [ ] **Step 2: Full diagnostic (background — it can run a few hours; longer if UNKNOWN-heavy)**

Run: `uv run python scripts/exp_richer_skeleton_probe.py darkzig.json --families comb,lane,hybrid --k-levels 96,100,104 --n 12 --budget 300 --workers 8 --out output/richer-skeleton.json`
Expected: per-row JSON streamed; a final `SUMMARY` with per-family SAT/UNSAT/UNKNOWN/min_achieved and the verdict.

- [ ] **Step 3: Apply the verdict and write the lessons entry**

Read `output/richer-skeleton.json`'s `summary`. The `verdict` field is the pre-committed call:
- **BREAK_FLOOR** → a lane/hybrid skeleton produced a legal `achieved < 102`. Independently re-verify that layout (`route()` == achieved, `is_valid`, `rotated_buildings == 0`) and record it as a new all-time best; the next track is a richer-skeleton generator / decidability work.
- **FEASIBILITY_WALL** → richer families are decided but can't pack below 102 (SATs, if any, at ≥ 102). This route to <102 is closed.
- **DECIDABILITY_WALL** → richer families are UNKNOWN-dominated at 300 s; viable only with a different solver/encoding. An exhaustive frontier sweep or a longer budget is the escalation.

Append to `tasks/lessons.md` an entry `## Richer-skeleton feasibility diagnostic (2026-07-21)` with: the exact command, the per-family tally + min achieved, the verdict, and its implication for the next track. Match the voice of `kwalk_autopsy`'s autopsy entry and the "TESTED … closed" entries.

- [ ] **Step 4: Commit**

```bash
git add tasks/lessons.md
git commit -m "docs: richer-skeleton feasibility diagnostic result + verdict"
```

*(If `output/richer-skeleton.json` was written and `output/` is gitignored, don't add it — commit only `tasks/lessons.md`.)*

---

## Self-Review

**1. Spec coverage.** Spec §3 method (families comb/lane/hybrid, full-TH, big budget, achieved-on-SAT, legality guard) → Task 1 `gen_family`/`probe_pattern`/`run_diagnostic`. §4 three-way verdict → `classify_verdict` + Task 2 Step 3, with the exact branch conditions (legal SAT<102 → BREAK_FLOOR; UNKNOWN-dominated → DECIDABILITY_WALL; else FEASIBILITY_WALL). §2 metric (achieved, not k) → `probe_pattern` runs `validate` for the achieved count; §6 legality → `rotated_buildings`/`canonical_dims` guard, and `classify_verdict` ignores illegal SATs (tested). §5 non-goals honored — read-only diagnostic, no generator, comb is control (excluded from the richer tally, tested).

**2. Placeholder scan.** No TBD/TODO. Every code step is complete. Task 2 is analysis with exact commands + the verbatim verdict rule.

**3. Type consistency.** Row dict keys (`family`/`k`/`status`/`achieved`/`legal`/`secs`) consistent between `run_diagnostic`, `classify_verdict`, `_summary`, and the tests' `_row`. `classify_verdict(rows, floor=102, unknown_frac=0.5) -> (str, str)` consistent between script and tests. `gen_family` dispatches to the real generator signatures (`generate_patterns(region, tw, tl, k, rng, n, th_mode)`, `generate_lane_patterns(..., max_lane_len=)`). `probe_pattern` uses `probe(pat, region, consumers, probe_limit=, probe_workers=)` and `validate(layout, pat, pos) -> (status, layout, achieved)` matching `foeopt/roads_first.py`.
