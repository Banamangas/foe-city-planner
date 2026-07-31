# Remaining work — Track F and the productionisation pass

_Written 2026-07-31 when closing `feat/track-f-skeleton-filters`. Everything here is
**not done**; what *was* done is in `tasks/lessons.md` (2026-07-30 / 07-31 entries) and
`tasks/todo.md` Track F. Ordered by what I would pick up first._

**State at close:** 7 commits on `feat/track-f-skeleton-filters`, 463 python + 19 frontend
tests passing, working tree clean, branch **not merged and not pushed**.

**Records held:** darkzig **94** (was 98 at session start, 250 as found; 121% efficiency),
FR16 **76** (was 79; 116%). Both verified — `route()` matches, `exact_route()` OPTIMAL,
`is_valid`, `rotated_buildings`=0, all buildings placed, 0 unsatisfied consumers.
Artifacts in `docs/records/`.

---

## 1. The defect class that keeps recurring — one instance still unfixed

**Three phases turned out to be bounded by their own parameter rather than by the remaining
budget.** Two were found and fixed during the box experiment; the third was found while writing
this document. The *class* matters more than the instances:

| phase | symptom at a 120 s box | status |
|---|---|---|
| `probe_limit >= time_box` | 292 s, 2.43x | fixed (preset 300 -> 30) |
| `pick_k_start` margin | whole budget above where results live | fixed (family-aware) |
| `seed_polish` after the walk | **281 s, 2.34x, for ONE road** | preset fixed, **root cause not** |

### 1.1 `seed_polish` root cause is still unfixed
`_apply_seed_polish` runs *after* the k-walk and `seed_minimize_roads` loops **sequentially**
over seeds with **no deadline check**, so worst case adds `seed_polish x probe_limit` seconds
on top of the whole box. Measured on darkzig at a 120 s box:
`seed_polish=0` -> 127 s (1.06x), best **101**; `seed_polish=12` -> **281 s (2.34x)**, best
**100**. 154 extra seconds for one road.

`BEST_PRESET` now ships `seed_polish=0` with a regression test, so the *default* is safe — but a
user raising the slider still gets an unbounded overrun.
- [x] **DONE on `fix/budget-bounded-phases`.** `seed_minimize_roads` takes `should_stop`, polled
      before every seed; the search reserves a slice for polish **only when it can fit a seed**;
      polish refuses a seed it cannot finish. 120 s box: 2.34x -> **1.02x**, no wasted budget.
      Also cured a second bug: the Stop button was inert during polish.
- [x] **Audit done, and it found a fourth by inspection:** `warm_start` ran `repack(budget_seconds=
      warm_start_budget)` *entirely outside* the box (a 60 s request took 90 s). Now charged
      against the box and capped at half of it.
- [ ] **End-to-end check of the polish path in a box big enough to use it** (600 s -> 150 s
      reserve -> ~5 seeds). The arithmetic is unit-tested; only the "does nothing at 120 s" case
      has been verified end to end

---

## 2. Correctness / honesty gaps in what shipped

### 2.1 `SAT_FILLER_FAIL` is untreated — 34% of FR16 probes
CP-SAT places every road-needing consumer, then the *filler* buildings have nowhere to go.
Measured on FR16: **91 of 270 probes**, worsening monotonically with k (16 / 32 / 43 at
k=84 / 88 / 92). Counting it, 83% of probes found a valid consumer placement but only 50%
produced a usable layout.

A user sees this as a run that found nothing, with no explanation. Never observed on darkzig
(more slack), so it was invisible until the second city.
- [ ] Surface it distinctly in the webapp rather than as a generic failure
- [ ] Consider reserving filler area in the pattern prefilter, or packing fillers first

### 2.2 A hand-set `probe_limit > time_box` still overruns
Only `BEST_PRESET` was fixed. A user setting `time_box=120, probe_limit=300` manually still
waits 292 s. Deliberately **not** clamped in the library — someone may legitimately want one
deep probe — so it needs a UI-level warning instead.
- [ ] Warn in the Optimize panel when `probe_limit > time_box / 2`

### 2.3 No UI test for `ScreenBanner`
Backend is tested (`test_api_load_includes_the_instance_screen`); the React component that
renders the verdict is not.
- [ ] Component test: renders for UNLIKELY/UNCERTAIN/INFEASIBLE, renders nothing for LIKELY,
      and never disables the Optimize button

---

## 3. Calibration that rests on too few cities

### 3.1 `screen_city` thresholds — n=3 and confounded
`road_pressure = sigma_half / slack` separates the measured cities (0.40 / 0.43 succeed,
0.89 fails) where *fill* does not (89.6% succeeds, 90.2% fails). **But FR24 has both high
pressure AND 2.3x the consumers**, and probe time scales 36 s -> 95 s -> 301 s with consumer
count, which points at CP-SAT model size rather than packing. Three cities cannot separate them.
- [ ] Synthesise a disentangling city with `rl.curriculum.make_real_like_city`: many consumers
      at low pressure, and few consumers at high pressure. Whichever fails identifies the cause
- [ ] Re-tune the 0.8 / 0.5 thresholds once the cause is known

### 3.2 `K_START_MARGIN["nonuniform"] = -4` — safe on two cities, optimal on neither
The cliff is sharp: one step of 4 too low returns `FAMILY_TOO_WEAK` (nothing at all).
Measured: darkzig 106 works / 104 fails; FR16 84 works / 80 fails. -8 is optimal on darkzig
(98 vs 103) and **fatal on FR16**. -4 is the largest margin safe on both, and leaves ~5 roads
on the table on darkzig.
- [ ] **Adaptive cliff-finding** (the real fix): spend ~20% of the box bisecting for the
      feasibility frontier with short probes, then exploit the remainder at the lowest feasible
      k. Needs no per-city calibration and self-corrects where -4 is wrong. **Separate design +
      pre-committed gate — not a productionisation ride-along**
- [ ] Until then, validate -4 on a third city before trusting it generally

### 3.3 The quality band `[3,4]` — two cities
`quality_index = (2 - mfa) * k == losses - 2c`. Every record sits at 3-4 (darkzig k=105/106,
FR16 k=84); both >=98-road layouts sit at 2. Encouraging that it held across different k, but
it is still n=2.
- [ ] Check the band on a third city before treating it as a law

---

## 4. Untested cities and configurations

- [ ] **FR17** — never run with the new stack (nonuniform + band + fixed k_start)
- [ ] **The user's own city** (`city-user-data.json`, the 142-road expert layout) — never run
      with the new stack. This is the most interesting one: it is the only city where a
      human-optimised reference exists to compare against
- [ ] **FR24 remains unsolved** — 0 SAT in 135 probes at k=205/220/235 plus 0 in 1047 at
      k=246-266. Every probe UNKNOWN (undecided, *not* refuted). Open question whether it is
      road pressure (0.89) or CP-SAT model size (146 consumers)
- [ ] **60 s and 600 s boxes** with the fixed `k_start` — only 120 s was verified end-to-end
- [x] **A real webapp run — DONE at close, PASS.** Live Flask server: `/api/load` returned the
      instance screen (LIKELY, pressure 0.405); `/api/optimize` applied BEST_PRESET at a 60 s
      box; the k-walk started at the family-aware `k_start=111`; SSE streamed four progressive
      improvements (107 -> 105 -> 104 -> **101**); the `done` event reported
      `best_achieved=101`, wall 62.1 s (**1.03x** — the box was honoured).
- [ ] **60 s reached the same 101 as 120 s** — the box may be shorter than necessary. Cheap
      follow-up: sweep 30 / 45 / 60 s to find where quality actually starts to degrade

---

## 5. Leads found and never followed

- [ ] **`mode=alternate` (comb family)** — pooled FR16+FR17, `alternate` holds **9 of 9 SATs**
      and `both` is **0 of 528**. Found free in existing probe logs, never exploited. Cheap: a
      one-line default flip for the comb family, but needs an A/B
- [ ] **`SkeletonScorer` / `opts_total` is now unused in production** — superseded by the band
      filter (cheaper *and* better: 69.6% vs 46.7% SAT). Kept as tested research tooling. Decide
      whether to keep or delete
- [ ] **Are 94 / 76 optimal?** No lower bound beyond `bound_adjacency` (21 on darkzig — far too
      weak to be informative). The true optimum is unknown

---

## 6. Closed — do not reopen without new evidence

Recording these so they are not re-litigated. Full reasoning in `tasks/lessons.md`.

- **Skeleton-generation RL / bandit / CEM.** Closed on *mechanism*, not on cost: within the
  productive band **nothing predicts `achieved`** (106 in-band SATs, all |rho| < 0.22 across
  nine features). `mean_free_adjacency`'s rho +0.825 was the *band* effect — it is a
  **classifier, not a gradient**, and is flat (-0.147) inside the band. There is no surface to
  climb; the residual variance is CP-SAT seed luck, which `seed_polish` already exploits.
  *Reopen only if a feature is found that correlates with `achieved` inside the band.*
- **M2-M4 placement RL** — archived; CP-SAT solves that sub-problem exactly.
- **RL as k-walk scheduler** — closed twice (C-bis Stage 1, next-things #1).
- **Free-form / non-trunk-and-branch skeletons** — 0 SAT / 240 in-band; spatial coverage is the
  binding constraint and comb/lane-like topologies are near-optimal for it.
- **Perturbing a good skeleton** — 0-for-64. The neighbourhood is sharp, not smooth, so
  diffusion / local-refinement over skeletons is dead.

---

## 7. Branch state

`feat/track-f-skeleton-filters`, 6 commits, **not merged, not pushed**:

    2daef89  fix: family-aware k_start + honest time box
    3f2ee5b  feat(webapp): record-holding settings + instance screen
    869b373  feat: quality_index band, nonuniform family, road-pressure screen
    702505c  fix: matched quality-filter test overturns the RL closure -- 95 -> 94
    cff7679  feat: non-uniform grammar -- FR16 79 -> 76, RL closed on evidence
    24f5015  feat: skeleton pre-filters + widened pitch range -- 98 -> 95

`3f2ee5b` also contains pre-existing uncommitted webapp/frontend work that was interleaved
with these edits in the same files — noted in its commit message.

**Decide before merging:** whether item 1.1 (the `seed_polish` overrun) should be fixed on this
branch first, since it is a defect in a shipped default rather than a missing feature.
