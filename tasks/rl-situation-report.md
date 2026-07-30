# RL situation report — what was tried, what changed, what is possible now

_Written 2026-07-30. Sources: `tasks/todo.md`, `tasks/lessons.md`, `tasks/next-things-to-try.md`,
`docs/superpowers/specs/2026-06-23-rl-placement-design.md`,
`docs/superpowers/specs/2026-07-14-learned-kwalk-acceleration-design.md`, the `rl/` package,
`foeopt/roads_first.py`, and **new measurements taken this session** on
`output/wide-screen.jsonl` (the 98-road record run). All new numbers are marked
**[measured 2026-07-30]** and are reproducible from the scratchpad scripts described in §4.5._

---

## OUTCOME ADDENDUM (2026-07-30, same day) — the sequence in §8 was executed; three
## of this report's conclusions are now superseded

The §8 sequence ran the same day this was written. Summary; full detail in `tasks/todo.md`
Track F and the `tasks/lessons.md` 2026-07-30 entry.

**Two records fell, on two different cities: darkzig 98 → 95 and FR16 79 → 76.** Both verified
end-to-end (`route()` matches, `exact_route()` OPTIMAL, `is_valid`, `rotated_buildings`=0, all
buildings placed, 0 unsatisfied consumers); 120% and 116% efficiency against their Σ/2 estimates.
`docs/records/darkzig-95-roads-lane-k105.json`, `fr16-76-roads-nonuniform-k84.json`, plus two
independent 97s on the way down. The darkzig 95 came from a screen-99 that seed-polish improved
by four; the FR16 76 was found in **14 probes**, at a k-level the comb family had left
INCONCLUSIVE after a full 2 h run.

| conclusion in this report | status after execution |
|---|---|
| §0.2 / §4.3 "the objective has ~20 labels; that is the binding constraint" | **SUPERSEDED.** 242 labelled SATs in 300 probes (8.6 core-h). The famine is over. |
| §0.2 / §4.4 "feasibility and quality point in opposite directions; no quality proxy exists" | **HALF SUPERSEDED.** The anti-correlation is real and reconfirmed, but a *different* statistic — `mean_free_adjacency` — predicts `achieved` at Spearman **+0.76** / **+0.64** on two independent datasets. §6.3 passed its gate. |
| §6.1 "expect ~5–6× more SATs per core-hour" | **BEATEN by ~3×.** Measured **0.27 → ~19 SAT/core-h (~70×)** once the truncated pitch range was unlocked; the prefilter alone gave the predicted ~4×. |
| §6.5 / §7 (RL framing, city counts, cost model) | **Stands.** |
| §6.5 "skeleton-generation RL is the surviving lever" | **CLOSED on evidence (later same day).** Both search spaces measured: outside comb/lane almost nothing is feasible (0 SAT/240 in-band; only `scatter` works, at 103 vs 95); inside the grammar, lifting the uniformity constraints reaches 96 against a 95 baseline the cheap pipeline already hits. RL has a validated in-grammar reward (rho **+0.825**) and free feasibility — and nothing left worth searching for. |
| §7 "3 cities to ship" | **Partly answered.** It transfers: **FR16 79 -> 76**, found in 14 probes. FR24 (146 consumers, road pressure 0.89) returns 0 SAT/135. The boundary is **road pressure**, not slack. |

**The lever this report missed entirely.** `generate_lane_patterns` enumerated
`for pitch in (5,…,11)`. §4.1 measured the SAT rate rising monotonically across that whole
range and I read it as "prefer high pitch" rather than "the range is truncated at its own
optimum." Widening it exposed **93,284 never-probed patterns per k** — more than the entire
population the project had ever searched — and that is where both 97s came from (pitch 17 and
the 12–18 band). Generalisable rule: *when every measured knob's optimum sits at the boundary
of its enumerated range, the range is the bug.*

**Net effect on the RL verdict: the case is weaker, not stronger.** Step 4 passing means RL now
has a real objective surrogate, which was its precondition. But if one microsecond-scale
geometric statistic captures the objective at rho 0.76, the honest move is to filter and sample
with it — done, and it took the record — not to train a policy to rediscover it. RL's remaining
distinct value is exactly §6.5 and nothing above it: **escaping the comb/lane families**, since
searching *within* them is now handled. The §6.5 hazard also sharpened: the surrogate is fitted
only on comb/lane skeletons, so it is out-of-distribution on precisely the novel topologies RL
would exist to find.

---

## 0. TL;DR

1. **Two learning attempts happened, only one was RL.** M2–M4 was masked **PPO** over
   sequential building placement — archived at 0% success on darkzig-density cities.
   Track C-bis was a **supervised CNN** (not RL) used as a k-walk scheduler — AUC 0.999,
   **zero** end-to-end benefit, archived.
2. **Both failed for reasons that no longer apply**, but a *third* reason now binds:
   the objective (`achieved` roads) has **~20 training labels in the entire project**.
   Feasibility has thousands. Any learner you train today learns feasibility, and
   feasibility is **anti-correlated with quality** (Spearman **+0.50**, i.e. wrong direction)
   among the SATs we have. **[measured 2026-07-30]**
3. **The current problem is not an MDP.** As formulated by `RoadsFirstSearch`, the decision
   is a single 5-tuple `(th_x, th_y, side, pitch, stubs)` per `k` — a **contextual bandit over
   ~67,000 arms**, not a sequential control problem. PPO is the wrong tool for it; a surrogate
   ranker or a bandit is the right tool. RL proper only becomes the right tool if you change
   the action space to *generating* a skeleton cell-by-cell (§6.5) — which is also the only
   lever that escapes the comb/lane family ceiling the project has been stuck against.
4. **The cheapest win found this session needs no ML at all.** A feature `probe()` *already
   computes and throws away* ranks 19 of 20 known SATs into the top 5% of patterns
   (AUC **0.99**). Filtering to the top 10% keeps **20/20** SATs at **11.2** core-hours instead
   of **74.5** — a **6.6× increase in SATs found per core-hour**, at zero modelling risk.
   **[measured 2026-07-30]** Details and the important caveat in §4.4.
5. **One city is enough to chase the darkzig record.** Three are needed to ship anything
   learned in the webapp. See §7.
6. **Nothing here needs months of GPU.** The expensive resource is CP-SAT reward evaluation
   (300 s/probe), not gradient steps. Full cost model in §5.

---

## 1. What was actually tried — attempt 1: RL placement (M2–M4)

**Timeline:** spec 2026-06-23, built ~06-25, archived 2026-07-02.
**Files:** `foeopt/rlenv.py` (env), `rl/encode.py`, `rl/policy.py`, `rl/ppo.py`, `rl/curriculum.py`,
`rl/imitate.py`, `rl/train.py`, `rl/eval.py`, `rl/oracle.py`, `rl/baselines.py`, `rl/gate.py`.
**Checkpoints still on disk:** `rl_ckpt.pt`, `rl_ckpt_bc.pt`, `rl_ckpt_m2m3.pt`.
**Logs still on disk:** `training.log` (348 KB), `training_bridge.log`, `training_m4.log`,
`training_bc_rl.log`, `bc_training.log`, `bc_05.log`.

### 1.1 The exact algorithm

| Component | Choice (from `rl/ppo.py`, `rl/policy.py`) |
|---|---|
| Algorithm | **Masked PPO**, clipped surrogate, clip = 0.2, 4 epochs/update |
| Advantage | GAE, γ = 0.99, λ = 0.95, terminal bootstrap 0 |
| Losses | `pol + 0.5·value − 0.01·entropy` |
| Optimiser | Adam, lr 3e-4 |
| Policy | Fully-convolutional policy+value head, `hidden=64`, size-agnostic over the grid |
| Action space | **one grid cell = one action** (`W×H` logits), masked categorical over valid anchors |
| Decision order | buildings placed in a **fixed** largest-area-first order — the policy chooses *where*, never *which* |
| Reward | terminal `−roads`; dense shaping `+0.1` per placed building; **`−100`** on invalid/unroutable |
| Action prior | road-adjacency mask, strength annealed 0.95 → 0.2 as success rises (`prior_strength_for_success`) |
| Curriculum | 5 synthetic stages 10×10/4 consumers → 26×26/24 consumers, then `make_real_like_city` at fill 0.5/0.7/0.9 |
| Warm start | **Behavioural cloning** from `repack()` expert trajectories, cross-entropy, 30 epochs, lr 1e-3, batch 256 |
| Hardware | AMD RX 9070 XT, ROCm 7.2, torch 2.10 (`scripts/setup-rocm-venv.sh`) |

### 1.2 What happened

- Curriculum stages **do** learn: at moderate fill, 80–86 % episode success — but
  `mean_roads ≈ 100` against a target ≈ 35, i.e. **~3× target even when it succeeds**.
- At darkzig-like fill (0.7–0.9): **0 % success across the board**. Every greedy darkzig
  evaluation ends `stuck` or `unroutable`.
- The designated rescue lever — BC warm-start — reached **45.8 % top-1 accuracy**, then
  **collapsed to 6–12 % success** under PPO fine-tuning (catastrophic forgetting; no KL anchor
  was used).
- Archived per the design's own §9.4 fail-fast rule.

### 1.3 The diagnosed root cause (still the load-bearing lesson)

> The policy **never observes road structure during an episode** — roads are computed only at
> the terminal step by `route()`. At 90 % fill it therefore cannot learn to *leave road
> channels*, so the `−100` trap fires as soon as density rises.

Two secondary causes worth carrying forward:
- **The BC teacher capped quality.** `repack()` produces ~169-road layouts; imitating it caps
  the student at ~169 — below the classical polish plateau of 158, and far above today's 98.
- **The action space was enormous** (`W×H` ≈ 2,700 actions/step × 224 steps) with a reward
  that is a single scalar at the end of a 224-step episode.

### 1.4 Related infrastructure built for RL and kept

`foeopt/reach.py` (exact routability-preserving placement mask, the "C1" lever) was built
2026-07-05 as a **pre-registered prerequisite for any RL revival**. It is opt-in; its own A/B
failed both flip-the-default gates (throughput −67 to −73 %). It is tested and available.

---

## 2. What was actually tried — attempt 2: Track C-bis (supervised, *not* RL)

**Timeline:** spec 2026-07-14, Stages 0/1/1.5 run 2026-07-15, archived same day.
**Files:** `foeopt/corpus.py` (data engine), `rl/kwalk_data.py` (encoding), `rl/kwalk_classifier.py`
(model), `rl/kwalk_scorer.py` (hook), `rl/kwalk_eval.py`, `scripts/kwalk_gate.py`,
`scripts/kwalk_autopsy.py`.

### 2.1 The exact model

`FeasibilityCNN`: 3 × `Conv2d(3×3)` (16→32→32) + ReLU → `AdaptiveAvgPool2d(1)` → concat 9 global
scalars → MLP(64) → 1 logit. Loss `BCEWithLogitsLoss(pos_weight = neg/pos)`, Adam 1e-3, 30 epochs.

Input channels (`rl/kwalk_data.encode_instance`): `[region, skeleton roads, TH footprint,
road-adjacent free cells]`. Globals: `[n_buildings, total_area, Σ min-side, slack, k,
4 size-bucket counts]`.

Training data: Stage-0 corpus, **darkzig 1459 + FR16 800 probes; 1062 labeled, only 42 positive.**

### 2.2 What happened

- **Offline: excellent.** Held-out ROC-AUC **0.999**; within-k-level AUC **0.987** (mean over 9
  levels) — the statistic that strips the trivial "SAT lives at higher k" correlation.
- **End-to-end: exactly zero benefit.** Baseline vs CNN-guided k-walk, 30 min each, equal
  config: **identical** — both reached lowest feasible k = 111, both `best_achieved = 102`.
- **Stage 1.5 autopsy** (the pre-committed diagnostic): 8 frontier UNKNOWNs re-solved at
  900 s × 12 workers → **0 SAT / 4 UNSAT / 4 UNKNOWN**. No feasible-but-hard frontier ⇒ Stage 2
  (learned placement proposer as CP-SAT warm-start) was never built.

### 2.3 Why the null happened — and the crucial mechanistic detail

The recorded reason is "the k-walk frontier is **decision-limited, not ordering-limited**."
That is correct, but there is a sharper mechanism visible in the code, and it matters for §6:

`_probe_levels_batch` (`foeopt/roads_first.py:602`) generates patterns via
`generate_lane_patterns(..., max_patterns=params.patterns)`, which **shuffles the full
population and truncates to 200**. The scorer was then applied to `surviving` — i.e. **to the
already-uniformly-sampled 200**, all of which get probed anyway.

So the scorer could only *reorder* or *prune* an already-random sample. It never got to
influence **which 200 of the 67,308 patterns were drawn in the first place.**

> **This is the single most important carry-over for any future learned component:**
> ranking inside a sample that will be fully consumed is a no-op by construction. Ranking that
> selects the sample from the population is a completely different lever, and it has never
> been tested.

---

## 3. What changed between then and now

| Old RL/ML killer | Status today |
|---|---|
| `unroutable` — placement severs free space from the TH | **Gone by construction.** The skeleton is fixed and pre-connected before any building is placed. |
| Road objective mismatch (`mean_roads ≈ 3× target`) | **Gone.** `k` is fixed externally; the inner problem is pure placement feasibility. |
| Roads unobservable until the terminal step | **Gone.** The skeleton is the fixed, fully-observed input. |
| BC teacher caps quality at ~169 | **Gone.** CP-SAT SAT-probes are an *optimal-for-the-skeleton* teacher; the corpus stores every placement (`corpus.record(pos=…)`). |
| Enormous action space, 224-step episodes | **Gone.** The decision is a 5-tuple. |
| — | **NEW: the objective has almost no labels.** See §4.3. |
| — | **NEW: feasibility and quality point in opposite directions.** See §4.4. |
| Scorer ranking is a no-op | **Fixable** — score the population, not the sample (§2.3, §6.1). |

The project's own recorded verdict (lessons 2026-07-07, "Productionization analysis + RL
verdict") pre-registered two conditions for revisiting RL: (1) the time-boxed CP-SAT search
ships, and (2) the richer lane/stub family ships. **Both are now true** — the lane family
holds the 98-road record (`docs/records/darkzig-98-roads-lane-k105.json`), and the webapp
exposes `pattern_family`, `probe_limit`, `seed_polish` etc. (`webapp/params.py`). So the
question is legitimately open again; it just does not resolve the way "revive RL" suggests.

---

## 4. New measurements taken this session

All from `output/wide-screen.jsonl` — the 1,400-probe run that produced the 98-road record —
joined against regenerated pattern parameters (deterministic: `generate_lane_patterns(...,
random.Random(0), 700, th_mode="full")`, verified by matching the recorded `th` on all 1,400 rows).

**Instance:** darkzig — region 2,720 cells, 224 buildings, **63 road-needing consumers**,
TH 6×7 at (8, 42).
**Population:** lane family at k = 105 → **67,308** distinct patterns (k = 106 → 67,302);
comb at k = 110 → 55,266. The screen sampled **700 per level = ~1.0 %.**
**Outcome:** 1,400 probes, 7.7 h wall on 12 workers = **72.8 core-hours**;
**20 SAT (1.43 %)**, 527 UNSAT (37.6 %), 853 UNKNOWN (60.9 %).

### 4.1 The parameter space is strongly structured — one knob explains everything

| pitch | n | SAT | SAT rate | UNKNOWN | best achieved |
|---|---|---|---|---|---|
| 5 | 256 | 0 | 0.0 % | 12.1 % | — |
| 6 | 181 | 0 | 0.0 % | 40.3 % | — |
| 7 | 191 | 0 | 0.0 % | 46.1 % | — |
| 8 | 199 | 0 | 0.0 % | 76.9 % | — |
| 9 | 191 | 2 | 1.0 % | 81.7 % | 102 |
| 10 | 190 | 6 | 3.2 % | 91.6 % | **98** |
| 11 | 192 | 12 | 6.2 % | 92.7 % | 101 |

**All 20 SATs have pitch ≥ 9. Pitch 5–8 is 0 SAT in 827 probes** — and mostly *proven* UNSAT
(pitch 5 is 88 % UNSAT), so this is genuine infeasibility, not undetected feasibility.
**59 % of the entire 72.8-core-hour budget was spent on pitch ≤ 8.**

Similarly: `stubs=True` → 2.8 % SAT vs 0.6 % for `False`; `trunk_len` in the 30s → 14.7 % SAT
vs 0.6 % (40s) and 0.0 % (50s).

### 4.2 A two-bit filter is worth ~4× on its own

| pitch ≥ 10 | stubs | n | SAT | rate | core-h | **SAT / core-h** | achieved values |
|---|---|---|---|---|---|---|---|
| no | no | 646 | 0 | 0.00 % | 21.4 | 0.00 | — |
| no | yes | 372 | 2 | 0.54 % | 21.4 | 0.09 | 102, 107 |
| yes | no | 217 | 5 | 2.30 % | 17.4 | 0.29 | 101, 101, 103, 103, 106 |
| **yes** | **yes** | **165** | **13** | **7.88 %** | **12.6** | **1.03** | **98**, 101, 102, 102, 103, 103, 105, 105, 106, 106, 106, 108, 108 |
| *(all)* | | 1400 | 20 | 1.43 % | 72.8 | 0.27 | |

The best bucket is 13.2 % of the population (8,910 patterns per k), so it is nowhere near
exhausted — 165 of ~17,800 probed across the two levels.

### 4.3 The objective has essentially no training data

- Feasibility labels available project-wide: **~2,500** (1,062 C-bis corpus + 1,400 wide screen).
- Quality labels (`achieved` road count, only defined for a SAT): **20** from the screen,
  ~230 from the older, looser-k roads-first runs (achieved 102–128, a different regime).
- Worse, `achieved` is **noisy per skeleton**: re-solving one fixed skeleton under 24 CP-SAT
  seeds gives min/median/max of 102/103/106 and 103/104/**112** (lessons 2026-07-22). So the
  reward has a **±3–10 road** solver-luck component, and detection probability is **d ≈ 0.77**
  even for a known-feasible pattern at 300 s.

**This, not the algorithm, is the binding constraint on any learner aimed at the real goal.**

### 4.4 A free feature ranks feasibility at AUC 0.99 — and mis-ranks quality

`probe()` computes, before it builds any CP-SAT model, the per-building road-adjacent anchor
candidate lists (`_anchor_candidates`, `foeopt/roads_first.py:428-440`), and already records
`opts_total` / `opts_min` into `diag`. It then **throws that away**.

Measured on 320 patterns (all 20 SATs + 150 random non-SATs per k; costs **0.37 s** per pattern,
vs a 300 s probe):

| feature | AUC SAT vs UNSAT | AUC SAT vs UNKNOWN | AUC SAT vs rest | AUC *within* the best bucket |
|---|---|---|---|---|
| **`opts_tot`** | **1.00** | **0.984** | **0.990** | **0.993** |
| `opts_min` | 0.997 | 0.927 | 0.954 | 0.88 |
| greedy road-adjacent first-fit count | 0.99 | 0.815 | 0.882 | 0.697 |
| free-cell count | 0.46 | 0.45 | 0.45 | — |

It is **not** collinear with the pitch/stubs filter — AUC 0.993 *inside* the best bucket.

Population-reweighted "probe only the top q % by `opts_tot`" policy:

| top q % | probes | SATs found | core-hours | SAT / core-h | vs baseline |
|---|---|---|---|---|---|
| 5 % | 75 | 19 / 20 | 5.3 | 3.59 | **13.3×** |
| **10 %** | **146** | **20 / 20** | **11.2** | **1.79** | **6.6×** |
| 15 % | 216 | 20 / 20 | 17.0 | 1.17 | 4.3× |
| 100 % (today) | 1420 | 20 / 20 | 74.5 | 0.27 | 1× |

> ⚠️ **The caveat that matters.** Among the 20 SATs, `opts_tot` correlates with `achieved` at
> Spearman **+0.50** — *the wrong sign*. The top-ranked pattern achieved **108**; the
> record-holding 98 sits at rank 26/320 (**top 8.1 %**), and 101/102-road patterns sit at
> ranks 39 and 27. A top-**5 %** cut would have **missed the 98-road record.**
> So use `opts_tot` as a **floor filter** (drop the bottom ~85–90 %, which contain zero SATs),
> then sample **uniformly within the survivors**. Do not rank-and-take-the-top.

This is the same failure shape the placement-objective Stage 0 study found (lessons 2026-07-21):
proxies that predict one thing (feasibility / skeleton sharing) can be *anti*-correlated with
`route()`'s output. It is now measured twice, in two different places. Treat it as a law of
this problem.

### 4.5 Prior-art check (per the 2026-07-22 process rule)

Before proposing the `opts_tot` filter, the adjacent closed items:

- **next-things-to-try #1 (prune-mode / `--score-threshold`)** — closed null 2026-07-16.
  *Difference:* #1 pruned the already-sampled 200 patterns inside the k-walk, where the
  bottleneck was per-probe decidability. The proposal here changes **which patterns are drawn
  from the 67,308-pattern population** in the wide-screen regime, where only ~1 % is sampled.
  §2.3 explains why those are structurally different levers. This has never been tested.
- **next-things-to-try #4 (tightened UNSAT prefilter)** — kept, null at the operating range.
  *Difference:* #4's prefilter is a **sound certificate** (never rejects a feasible pattern),
  which is why it can be always-on and why it is weak. `opts_tot` is a **heuristic** filter
  that can reject feasible patterns — strictly more powerful, strictly less safe, and it must
  therefore be opt-in and A/B'd.
- **Track C-bis Stage 1 (CNN scorer)** — closed null. Same regime distinction as #1.
- **#8 (CP-SAT parameter portfolio)** — clean null; also established a real noise floor
  (a no-override control arm itself flipped 1/20 samples). Any A/B here needs ≥2 repeats.

Reproduction: the scratchpad scripts for §4.1–4.4 are at
`/tmp/claude-1000/-home-born-Github-foe-city-planner/<session>/scratchpad/proxy.py` and the
inline analyses in this session's transcript. Nothing in the repo was modified.

---

## 5. Is RL affordable? A cost model

The expensive resource is **not** gradient steps. It is reward evaluation.

| Reward source | Cost per evaluation | Notes |
|---|---|---|
| CP-SAT probe at the frontier (k = 105/106) | **300 s** (60.9 % return UNKNOWN, i.e. *no* reward signal) | the true reward |
| CP-SAT probe at loose k (≥ 115) | ~5–30 s | wrong regime — everything is feasible, no gradient toward 98 |
| `opts_tot` + anchor enumeration | **0.37 s** (pure Python; a numpy/bitset rewrite should reach ~ms) | AUC 0.99 for feasibility |
| Greedy road-adjacent first-fit | 0.11 s | AUC 0.88 |
| `FeasibilityCNN` forward pass | < 1 ms | already trained, AUC 0.999 offline |
| `prefilter()` (area + adjacency capacity) | ~ms | sound but null at the operating range |

**PPO against the true reward** (typical 1e5–1e6 episodes):
1e5 × 300 s / 12 parallel workers ≈ **29 days**; 1e6 ≈ **9.5 months**.
And ~61 % of those episodes return UNKNOWN — a *censored* reward, not a zero one, which PPO
has no principled way to consume. **This configuration is not worth running**, even at your
stated tolerance, because the sample budget is spent on undecidable probes rather than on
learning.

**PPO/GFlowNet against a surrogate reward:** 1e6 episodes × 1 ms ≈ **20 minutes on CPU**.
Entirely affordable. The cost moves to (a) building the surrogate's label set and (b) verifying
the policy's proposals with real CP-SAT.

> **Conclusion: any RL here must be model-based** — a learned/heuristic surrogate in the loop,
> CP-SAT only as (i) the label generator and (ii) the certificate authority on the policy's
> top-N proposals. That is exactly the architecture C-bis pre-committed to
> ("CP-SAT remains the decider; learned models only schedule/prune/hint") and it remains right.

And the corollary: **the surrogate is the whole ballgame.** We have a good feasibility
surrogate for free (§4.4). We have **no** quality surrogate, and the best available proxy for
quality points the wrong way. An RL agent trained on today's surrogates will reliably produce
*feasible* skeletons around 105–108 roads and will not find 98.

---

## 6. The levers, ranked

Ordered by (expected value ÷ cost). Each has a pre-committed gate in the project's style.

### 6.1 Population-level `opts_tot` prefilter — **do this first, no ML**
Score the full 67 k population (after the free 2-bit pitch/stubs cut → ~9 k patterns → ~55 min
on 1 core, ~5 min on 12), drop the bottom 85–90 %, then **sample uniformly** among survivors.
- Expected: **~5–6× more SATs per core-hour**; the same 7.7 h run yields ~100–130 SATs instead
  of 20, sampling the `achieved` left tail ~6× deeper. Given min-of-13 = 98 in the best bucket,
  min-of-~100 plausibly lands **95–97**, before seed-polish.
- Cost: a scoring pass + a sampler change in `scripts/exp_wide_skeleton_screen.py`. Throwaway.
- Risk: heuristic filter can reject feasible patterns (§4.4 caveat). Mitigate by keeping the
  cut loose (10–15 %) and sampling uniformly inside it.
- Gate: ≥ 3× SATs per core-hour at equal wall-clock vs the recorded baseline, **and**
  `min(achieved)` no worse than 98. Two repeats (noise floor, §4.5).

### 6.2 Retarget the existing `FeasibilityCNN` as a *population* sampler — cheap ML
The model exists, is trained, and scores at < 1 ms — cheap enough to score all 67 k patterns.
Its null result was a *placement* problem (§2.3), not a model-quality problem.
- Gate: must beat the free `opts_tot` filter (§6.1) on SATs/core-hour on a held-out city.
  **If it does not beat a 1-feature heuristic, do not ship a neural network.**
- Note the training set is 42 positives; retrain on the 2,500 labels available now.

### 6.3 Learn `achieved | SAT` — the actual objective
Nothing in the project has ever modelled this. Blocked on data: 20 labels.
**Ordering matters:** §6.1/§6.2 are the label factory. Run them first, get 100–300 SAT+achieved
pairs, *then* fit a quality model. Attempting this before §6.1 is fitting to n = 20.
- Watch for: the +0.50 anti-correlation means a quality model must be *placement-intrinsic*,
  not skeleton-relative — the exact conclusion of the 2026-07-21 placement-objective study.

### 6.4 Contextual bandit / CEM over the 5-tuple — the right classical framing
`(th_x, th_y, side, pitch, stubs)` per `k`. Thompson sampling or cross-entropy method over
this space, with the CP-SAT probe as the (censored, noisy) reward.
- Honest assessment: **§6.1 already captures most of what a bandit would learn** (the structure
  in §4.1–4.2 is coarse and a filter exploits it directly). A bandit adds value mainly by
  learning the *spatial* TH-position structure, where the evidence is currently weak (n = 20).
- Treat as an *upgrade path* from §6.1, not a parallel track.

### 6.5 True RL: generate the skeleton cell-by-cell — the only lever that escapes the family
This is the one formulation where RL is genuinely the right tool and where the upside is not
capped by the pattern generator.
- **MDP:** state = (region, TH, partial road set, remaining budget); action = add one road cell
  adjacent to the existing tree; episode ends at `k` cells. Every intermediate state is a valid
  connected skeleton by construction — *no invalid-action trap*, which was M2–M4's killer.
- **Why it matters:** the project's own recorded conclusion is that the frontier is a
  **pattern-family limit** (C-bis Stage 1.5; the corrected richer-skeleton run). The comb and
  lane generators are hand-written 4-knob templates. A cell-by-cell generator spans *every*
  connected k-cell skeleton — the expert's own 142-road city (2.02 sharing, 5 overhead cells)
  is in that space and is not in the comb/lane space.
- **Why it is hard:** (a) reward must be the surrogate (§5), and today's surrogate optimises the
  wrong thing (§4.4); (b) the surrogate is trained *only on comb/lane skeletons*, so it will be
  out-of-distribution on anything genuinely novel — the classic model-based RL failure;
  (c) GFlowNet is a better fit than PPO here (you want *diverse* high-reward samples to feed
  CP-SAT, not one mode).
- **Prerequisite, non-negotiable:** §6.3 must produce a quality model that generalises, or this
  optimises feasibility and lands at 105+.
- Cost if attempted: days of CPU for labels, hours of GPU for the policy, then a CP-SAT
  verification run on the top ~1,000 proposals (~1 day). Not months — **provided** the
  surrogate exists.

### 6.6 Explicitly *not* recommended
- **Reviving M2–M4 placement RL.** Superseded by CP-SAT, which solves that exact sub-problem
  exactly. Recorded rule stands: don't resume training on that formulation.
- **RL to pick CP-SAT random seeds.** Seeds are unstructured; `seed_polish` already samples
  them and the measured tail is thin (~1 road over the median).
- **RL as a k-walk scheduler.** Closed twice (C-bis Stage 1, next-things #1), and the mechanism
  (§2.3) says it cannot work in that regime.

---

## 7. One city, or several?

**Two different goals with two different answers.**

**Goal A — beat 98 on darkzig (record chase).** *One city is enough, and is correct.*
The task is single-instance black-box optimisation; overfitting to darkzig is not a bug, it is
the objective. §6.1/§6.3/§6.5 all work fine on darkzig alone, and every existing label
(1,459 corpus + 1,400 screen probes) is already darkzig. Adding cities here only dilutes the
label budget on the one instance that has a record to beat.

**Goal B — a learned component that ships in the webapp for arbitrary user cities.**
*Minimum three: two train, one held out.* Available today:

| city | file | notes |
|---|---|---|
| darkzig | `darkzig.json` | 224 buildings, the benchmark, 98-road record |
| the user's own city | `city-user-data.json` (+ `-foe-helper.json`) | the expert 142-road layout, 2.02 sharing — the *quality* reference |
| FR16 / FR17 / FR24 | `CityMap-Born-FR*-2026-07-07.json` | three real cities; FR16 already has an 800-probe corpus |
| synthetic | `rl/curriculum.make_real_like_city(ref, fill)` | unlimited variants of any reference at any fill |

The C-bis spec already pre-registered the right split (darkzig + FR16 train, a second FR city
held out). Reuse it.

**The generalisation argument that should drive the decision:**
`opts_tot` is computed *per instance from the instance's own geometry* — it needs no training
and therefore transfers to any city for free. A learned model must beat it **on a held-out
city** to justify existing. That single gate makes the "how many cities" question
self-answering: you need exactly as many cities as it takes to run that comparison honestly —
**three**.

One genuinely open transfer question worth one cheap experiment: is the pitch ≈ 10–11 optimum
(§4.1) universal? It plausibly reflects `2 × typical building depth + 1 road`, which is a
property of FoE's building catalogue, not of darkzig. If it holds on FR16, the 2-bit filter
ships as a default for every city at zero risk. **Cost: one 2-hour screen on FR16.** This is
the highest information-per-hour experiment in this entire document.

---

## 8. Recommended sequence

| # | Action | Cost | Gate |
|---|---|---|---|
| 1 | Confirm the pitch/stubs structure on FR16 | 2 h | Does pitch ≥ 10 dominate SATs there too? |
| 2 | `opts_tot` population prefilter + uniform sampling within survivors (§6.1) | ~1 day build, 2 × 8 h runs | ≥ 3× SAT/core-h **and** `min(achieved) ≤ 98` |
| 3 | Seed-polish the resulting SAT frontier (already shipped: `seed_polish`) | hours | improves ~35 % of SATs by 1–3 roads |
| 4 | With 100–300 fresh (skeleton → achieved) labels, fit the quality model (§6.3) | days | rank-corr ≥ 0.4 on held-out SATs (the 2026-07-21 bar) |
| 5 | **Only if 4 passes:** cell-by-cell skeleton RL / GFlowNet against that surrogate (§6.5) | ~1 week + CP-SAT verification | proposes a legal skeleton beating the best of step 2/3 |

Steps 1–3 are the ones with a real expected payoff and no modelling risk. Step 4 is the gate
that decides whether RL is *possible at all* on the real objective. Step 5 is where RL earns
its name — and it is the only path that can escape the hand-written pattern families the
project has been fighting since 2026-07-16.

**The honest bottom line:** RL is not blocked by algorithms, compute, or the environment —
all three are in better shape than they have ever been. It is blocked by having 20 labels for
the thing you actually want to minimise, and by the fact that the one cheap signal we have for
feasibility points *away* from quality. Fix the label famine first; RL becomes a reasonable
next step, not before.
