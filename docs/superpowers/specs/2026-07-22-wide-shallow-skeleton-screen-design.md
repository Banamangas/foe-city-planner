# Wide-shallow skeleton screen — design

_2026-07-22. Track: R&D (can any lane skeleton beat 102 roads?). Status: spec, not yet planned._
_Supersedes the deep-probe method of `2026-07-21-richer-skeleton-diagnostic-design.md` (not its question)._

## 1. Why the deep probe was the wrong instrument

The richer-skeleton diagnostic ran 72 probes at 300 s (2.96 h) and spent **90 % of its wall clock on
UNKNOWN**. It sampled **72 of ~67,300** available patterns per k-level — a screen with almost no power,
exactly the weakness §6 of the prior spec flagged. Three measurements (2026-07-22) show the budget was
being spent on the wrong axis:

- **UNSAT is nearly free.** Of 26 comb probes, 15 were refuted by CP-SAT *presolve* with
  `branches=0` in ~5 ms; their entire share of wall clock was **0.3 %**. The observed "0.4 s UNSAT" is
  our own Python anchor-candidate enumeration, not solver time.
- **UNKNOWN does not converge with budget.** `kwalk_autopsy.py` re-solved 8 frontier UNKNOWNs at
  **900 s × 12 workers** (30× their original budget): **0 SAT / 4 UNSAT / 4 still UNKNOWN**
  (lessons.md:974). This session reproduced the pattern: 15 s → 300 s converted only 2 of 6.
- **Feasible patterns resolve fast.** Across the 1459-instance darkzig corpus, all 34 SATs finished
  well inside the cap: **median 10.4 s, p90 24.3 s, max 29.2 s**.

Together: long budgets buy proofs of infeasibility we do not need, while the thing we *are* hunting —
a SAT — announces itself in seconds or not at all. The binding resource is **patterns sampled**, not
seconds per pattern.

## 2. The question (unchanged)

Does any **lane** skeleton admit a legal placement whose `route()` count is **< 102**, darkzig's
standing floor? The prior run establishes lane reaches **103** (legal, at k=107) — one road short.
That near-miss is the reason to sample properly rather than close the track.

## 3. Method: wide and shallow

Screen a large sample at a short budget, with **concurrency across patterns instead of threads within
one probe**.

- **Family:** `lane` only. **`hybrid` is dropped** — measured 2026-07-22, `max_lane_len` is a pure
  *filter*: for every cap (3,4,6,8,12,24) and every k (105,107,109,120,140), the capped pattern set is
  a strict **subset** of the uncapped one (`novel = 0`). Round-robin front growth makes lanes balanced,
  so a cap is either inert or starves growth until `remaining != 0` rejects the pattern outright. A
  "hybrid arm" therefore re-samples `lane`, and in the prior run consumed half the compute for
  correlated evidence. Keep `comb` as a small control only.
- **Budget:** **30 s** per probe, justified by the corpus SAT distribution (max 29.2 s). See §6 for the
  censoring caveat and its calibration arm.
- **Parallelism:** a `multiprocessing.Pool` of 12 workers each running `probe_workers=1`, i.e. 12
  patterns in flight, rather than today's one pattern with 12 CP-SAT threads. Reuses the existing
  `_worker_init` / `_run_probe` plumbing in `foeopt/roads_first.py`.
- **Sample:** draw uniformly without replacement from the full generated population per (k, family)
  — ~67.3k patterns per k-level — with a fixed seed. **k ∈ {105, 106, 107}** at **~5,000 patterns
  each** (~2.8 h/level, ~8.3 h total at the measured rate; see §4a).
  **k=109 is dropped as unwinnable:** the deep run's SATs landed at 103/103 for k=107 and 105/108 for
  k=109, so at k=109 the achieved count cannot reach ≤101 whatever we sample. k=106 is added — it was
  never probed and sits in the middle of the live band.
- **Prefilter:** apply `prefilter()` before dispatch (the prior diagnostic skipped it). It is free and
  removes provably-dead patterns without a solver call.
- **Persist every SAT.** For each SAT, write the achieved count **and the full layout + pattern
  identity (TH anchor, road cells, seed index)** to disk. The prior run found a legal 103 it cannot
  reproduce; that must not recur.

## 4. Expected power (the reason this is worth running)

With `n` patterns screened, feasibility rate `p`, and detection probability `d` for a feasible pattern
at 30 s, expected discoveries are `n·p·d`. Against the prior run:

| | patterns | budget | threads |
|---|---|---|---|
| deep probe (prior) | 72 | 300 s | 12 per probe |
| wide screen (this) | ~5,000/k-level | 30 s | 1 per probe, 12 concurrent |

Nearly two orders of magnitude more patterns, against a `d` that the corpus says is high for genuinely
feasible instances. Crucially this also makes a **null result meaningful**: 0 SATs in n = 5,000 bounds
`p·d < 3/5000` by the rule of three (95 %), i.e. feasibility below ~0.06 % — an actual bound, where
"0 SATs in 12 patterns" bounds nothing.

## 4a. Throughput calibration — RUN 2026-07-22, assumption confirmed

§6 required this before committing to a long sweep. Same 50 lane k=107 patterns (prefilter kept
50/50), same 30 s budget, both dispatch strategies:

| arm | wall | throughput | decided | outcomes |
|---|---|---|---|---|
| A: 1 pattern × 12 workers (today) | 16.48 min | 3.0 probes/min | 18/50 | 18 UNSAT, 32 UNKNOWN |
| B: 12 patterns × 1 worker (proposed) | **1.60 min** | **31.2 probes/min** | 16/50 | 16 UNSAT, 34 UNKNOWN |

**Wall speedup 10.29x; decided-per-minute 9.14x.** The parallelism is sublinear as predicted (10.3x of
a theoretical 12x) and the resolution cost is **2 probes in 50** — both of them *search*-refuted UNSATs,
the expensive infeasibility proofs the screen does not need. Both arms found the identical 16
presolve-refuted UNSATs; neither found a SAT. Arm B is adopted.

**Sizing.** ~30 probes/min sustained (24/min if every probe pinned the full 30 s; the ~30 % that
presolve-refute instantly lift the average). 5,000 patterns/k-level ≈ 2.8 h; three levels ≈ 8.3 h.
Rule-of-three power at n=5,000: a null bounds `p·d < 3/5000` = **0.06 %**.

## 5. Pre-committed verdict

- **Any legal SAT with achieved < 102** → **floor broken.** Independently re-verify
  (`rotated_buildings == 0`, `is_valid`, re-run `route()` on the persisted layout) before claiming a new
  all-time best — the standing rule after the retracted-127 incident.
- **Legal SATs found, all achieving ≥ 102** → lane is **feasible but not superior**; the family caps at
  or just above comb. Report the minimum achieved (the prior run's 103 is the number to beat). Combined
  with a tight `p` bound, this closes parametric lane skeletons as a route below 102.
- **Zero SATs across ~5,000/k-level** → report the rule-of-three bound on `p`. This is a genuine
  negative for the family, and the first one with quantified power.

The 50 %-UNKNOWN decidability/feasibility split of the prior spec is **retired**: at a 30 s budget
UNKNOWN is the expected majority outcome and carries no information about which wall we are against.
The verdict now rests on SATs found and the bound on `p`, not on the UNSAT/UNKNOWN mix.

## 6. Risks / open questions

- **Censoring.** 30 s was chosen from a distribution itself capped at 30 s, so a slow-resolving SAT
  population would be invisible. Mitigation — **calibration arm:** re-probe a random subsample
  (~30) of the screen's UNKNOWNs at 300 s. If ~0 convert, `d` is high and the screen is sound; if many
  convert, the budget must rise and the power calculation be redone. This is cheap (~2.5 h worst case)
  and is the only place a long budget is justified.
- ~~**Throughput assumption untested.**~~ **RESOLVED 2026-07-22** — measured at **10.29× wall /
  9.14× decided-per-minute**, resolution cost 2 probes in 50 (both search-refuted UNSATs). Sublinear as
  suspected, but nowhere near enough to change the design. See §4a.
- **Sampling still isn't exhaustive.** ~5k of 67.3k is ~7 %. The rule-of-three bound is the honest
  claim; "no feasible lane skeleton exists" is not.
- **Uniform sampling may be weak.** The generator's population is dominated by TH anchors; if
  feasibility concentrates in a small TH region, uniform draws waste effort. Out of scope here, but a
  scorer-guided screen (the existing opt-in `scorer=` hook) is the natural follow-up if the null holds.

## 7. Non-goals

- **No new skeleton family is built.** Still a read-only diagnostic over existing generators.
- **No deep re-probe of UNKNOWNs** beyond the §6 calibration subsample — that is the method this spec
  exists to replace.
- **No symmetry breaking.** Its k-walk closure stands (lessons.md:1039); the 2026-07-22 amendment shows
  the recorded *mechanism* was wrong and that it helps at big budgets, but this screen runs at 30 s
  where its 1 ms/probe build cost is a real fraction and its branch savings are unproven. Separate test.

## 8. Deliverables

- A screen script (e.g. `scripts/exp_wide_skeleton_screen.py`): pooled 12×1-worker dispatch, prefilter,
  30 s probes, streaming JSONL output, per-(k) tallies, persisted SAT layouts, and the pre-committed
  verdict including the rule-of-three bound.
- The throughput calibration (§6) run and recorded **before** the main sweep.
- A `tasks/lessons.md` entry with the tally, any achieved counts, the `p` bound, and the verdict.
