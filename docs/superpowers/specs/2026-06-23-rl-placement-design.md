# RL / ML for FoE Layout — Design & Training Blueprint

Status: **env + PPO stack built and CPU-smoke-tested; AMD/ROCm GPU path verified
working; training to convergence is the remaining work.** This is a refinement of
the original 2026-06-23 design, locked to a concrete M2→M4 plan after code review
and GPU verification (2026-06-25).

Companion code: `foeopt/rlenv.py` + `rl/{encode,policy,curriculum,ppo,train,eval}.py`
(+ `tests/test_rlenv.py`). Context: `tasks/lessons.md`. Run guide: `rl/README.md`.

## 1. Why this, why now

Every *local* method plateaus at ~**158** roads on the realistic darkzig city (vs
the Σ(short-side)/2 ≈ **114** target): the constructive grow-tree (6 structural
variants), simulated annealing, and LNS+CP-SAT (1-road gain, not worth the
dependency). The wall is structural — the problem is globally coupled and NP-hard,
so local re-optimization can't escape a decent local optimum. See `tasks/lessons.md`
for the five constructive-heuristic attempts and the CP-SAT scaling ceiling.

Two facts make ML/RL the right next bet:
- **Placement is the lever.** `route()` is already near-optimal for a *fixed*
  placement, and after Task A it's a **fast simulator** (~1.3 ms/call). The open
  problem is arranging buildings into route-cheap double-rows.
- **This is chip floorplanning** (place blocks, minimize routing), where RL has
  worked (Google, *Nature* 2021). The payoff is an **amortized** solver: train
  once across many cities, then get *instant* near-optimal layouts for any pasted
  city. (For a *single* city, classical optimization is better — RL's value is
  generality + inference speed.)

**Scope of this plan: M2→M4** — make PPO actually learn, then transfer to darkzig
and attempt to beat 158 (the make-or-break gate). Full generalization (M5: train
across a city distribution for unseen cities) and the ambitious AlphaZero-style
MCTS path are **explicitly deferred to later phases**; the gate is the priority.

## 2. What is already built (verified)

- **`foeopt/rlenv.py`** — `PlacementEnv`, a pure-stdlib sequential-placement MDP
  (the router is the simulator). 8 tests in `tests/test_rlenv.py`.
- **`rl/encode.py`** — obs → 5-channel `[C,H,W]` grid tensor (region, occupancy,
  current w, current l, needs-road) + boolean action mask over `H*W` anchors.
- **`rl/policy.py`** — `PlacementPolicy`: fully-conv CNN body + per-cell policy
  head + value head. Fully-conv ⇒ same weights work on any grid size.
- **`rl/curriculum.py`** — 5 synthetic stages (10×10/6 blds → 26×26/36 blds),
  fixed grid size per stage so episodes batch within a stage.
- **`rl/ppo.py`** — `collect_episode`, GAE, clipped PPO update, `evaluate` (greedy
  rollout), `train` loop with auto-curriculum advancement.
- **`rl/train.py` / `rl/eval.py`** — CLI entry points.
- **Smoke-tested on CPU:** one PPO update + eval run cleanly. **Not** trained to
  convergence — that needs the GPU and hours-to-days.
- **GPU verified (2026-06-25):** the dev box has an **AMD Radeon RX 9070 XT
  (gfx1201, 16 GB)** with ROCm 7.2. `torch 2.10.0+rocm7.0` runs on it out of the
  box (2048² matmul = 10 ms, correct vs CPU; device 0 is the dGPU). **Caveat:** the
  project's `rl` extra (`torch>=2`, no index) pulls the *CPU* wheel — see §7 for the
  ROCm index config this plan adds.

## 3. The environment (`foeopt/rlenv.py`)

A sequential-placement MDP — pure-stdlib, the router is the simulator:
- **State (`Obs`):** region mask, occupancy, current building `(w, l, needs_road)`,
  count remaining. Framework-agnostic; the policy encodes it.
- **Action:** an `(x, y)` anchor for the current building. `valid_actions()`
  returns the legal (non-overlapping, in-region) set for masking.
- **Episode:** Townhall pre-placed; place the rest in a **fixed order
  (largest-area first, then entity_id for determinism)** — the agent picks WHERE,
  not WHICH. Making order part of the policy is a noted future extension, not this
  phase. `route()` scores once all are down.
- **Reward:** sparse terminal `target − roads` (>0 below the Σ/2 estimate);
  `−100` for an unplaceable or unroutable layout. Optional per-placement shaping
  (`placement_reward`, default 0.1).

## 4. The central challenge (measured): sparse reward on dense cities

Baseline rollouts on darkzig (90% fill) **all** end "unroutable" (−100) — naive
policies pack with no road channels, stranding a building. A flat −100 gives **no
learning gradient**. Mitigations and their build status:

1. **Reward shaping — ✅ built (`placement_reward`).** To refine (M3): replace the
   flat −100 with a penalty scaled by #unplaced/#unsatisfied for a smoother
   gradient; add potential-based shaping using `road_estimate` of the partial
   layout.
2. **Curriculum — ✅ built (`rl/curriculum.py`, 5 stages).** To extend (M4): add
   real-city-like instances (§8).
3. **Action prior — ❌ NOT built; this is the core of M2 and the biggest lever**
   (per `rl/README.md`). Restrict `valid_actions()` to anchors adjacent to existing
   buildings / the growing road, not the whole free grid. This shrinks the action
   space ~100× and avoids most unroutable dead-ends (it bakes in the grow-tree's
   road-adjacency prior that makes layouts feasible).
   - **Mechanism (locked): soft + annealed, not hard.** The grow-tree's
     road-adjacency prior is *exactly* the heuristic that produces the ~158 floor.
     A hard prior ⇒ RL rediscovers grow-tree layouts and caps at 158 — the very
     floor we're trying to beat. So: start strict (road-adjacent / near-occupancy
     anchors only) to escape the −100 trap; then **anneal** — widen the allowed
     anchor set as episode success-rate rises; always keep a small ε fraction of
     fully-free anchors for exploration.
   - **Location (locked):** implement as a `valid_actions(prior=...)` mode **in
     `foeopt/rlenv.py`** (the env stays the single source of legality) and reflect
     it in `rl/encode.action_mask`. Keeping it in the env means eval, tests, and
     any future imitation rollouts all see the same legality.
4. **Imitation warm-start — ❌ deferred (design-for, don't build first).** Pretrain
   to imitate `repack`/`polish` outputs and CP-SAT optima (small instances), then
   RL fine-tune. Design the env/trajectory format so warm-start is easy to add
   later; build it **only if PPO proves too sample-hungry to reach the gate** — it
   is the rescue lever before declaring the gate failed (§9).

## 5. Policy architecture

- **This phase: the CNN already in `rl/policy.py`.** Grid as the 5 image-like
  channels built in `rl/encode.py` — `[region mask, occupancy, current-w, current-l,
  needs-road]` (w/l normalised by `_MAX_SIZE=8`) → fully-conv body; a score per grid
  cell (pointer) masked via `valid_actions()`; softmax → sample anchor; plus a value
  head for actor-critic. Fully-conv ⇒ works on any grid size, which the curriculum
  depends on. (The original spec sketched extra channels — road-needing occupancy,
  footprint broadcast — as aspirational; they are not built and not needed for this
  phase; revisit if the CNN plateaus.)
- **Future option (not this phase): a GNN** over placed-buildings + candidate-slot
  graph (closer to the chip-placement work) — worth trying if the CNN plateaus.
- **Network size (`--hidden`), lr, episodes** — standard PPO knobs (`rl/README.md` §6).

## 6. Training algorithm

- **This phase: PPO** actor-critic with action masking (stable, well-supported;
  `rl/ppo.py` is built). Auto-curriculum advances each stage when mastered
  (success ≥ 90% for 20 updates).
- **Deferred: AlphaZero-style MCTS + learned policy/value.** The env is a
  deterministic single-player "game" and `route()` is a cheap rollout simulator,
  which fits MCTS well — but it is a research-heavy escalation and **out of scope
  for M2→M4**. Reconsider only if PPO clears the gate and we want to push past 158.

## 7. Benchmark / signal

- **Primary — the M4 gate: 0-unplaced road count on darkzig vs the Σ/2 = 114
  target, vs the repack/polish ~158 floor.** `status=ok` and `roads ≤ 158` is the
  bet paying off; `stuck`/`unroutable` ⇒ keep training earlier stages; 140s–150s ⇒
  competitive, push further (see `rl/README.md` §5).
- **Principled baseline for M2/M3 — small roomy CP-SAT-optimal instances.** Per
  `tasks/lessons.md`: the bundled 97%-full city is a perfect-packing puzzle and
  MUST NOT be used as a baseline; CP-SAT proves the optimum on fair small instances
  (e.g. 11×11/10 blds: **5 roads, all placed** vs the greedy packer's 11 + 1
  stranded — the greedy packer is ~2× off optimal on fair inputs). Use these as the
  early-currival signal: does the policy approach CP-SAT optima, not just "beat
  random"?
- **Metrics tracked:** per-update `success` (fraction placed+routed) and
  `mean_roads` vs target; greedy `eval: roads=…` on darkzig every 10 updates;
  `foeopt/quality.py` (Rule 1/2) as a secondary shaping/regression signal.
- **Discipline (from lessons.md):** compare only 0-unplaced results; never compare
  raw road counts across runs without checking `unplaced`/`status`.

## 8. Infrastructure

- **GPU: AMD ROCm, not CUDA.** Add a `rl-rocm` extra (or a `[tool.uv]` index entry)
  pointing at `https://download.pytorch.org/whl/rocm7.0` so `uv sync --extra rl-rocm`
  pulls the GPU wheel on this box. Keep the `rl` (CPU) extra for portability and
  tests. Verified: `torch 2.10.0+rocm7.0` works on gfx1201 with no `HSA_OVERRIDE`.
- **Throughput (as-needed, not a hard prerequisite — GPU is available):** the env
  loop is CPU-bound (`valid_actions()` is O(free × footprint)/step; `route()` is
  Python ~1.3 ms/call) while the policy forward is GPU — so the CPU env loop
  bottlenecks even on GPU. Levers, in order: (1) **incremental `valid_actions`
  delta-cache** (à la Task-A's free-cell deltas — derive the legal-anchor set for a
  candidate by a delta from the last state instead of rescanning the free grid);
  (2) **vectorized envs** (run K envs in parallel, overlap CPU env steps with GPU
  policy forwards); (3) batch `route()` only if it still dominates after (1)+(2).
  Long-term: port the route() hot path (BFS/prune) to Rust/C if it blocks serious
  training.
- **The training stack lives outside `foeopt/` core (`rl/`)** so the core stays
  pure-stdlib and eval needs no torch unless running a learned policy.

## 9. Milestones (each independently validatable)

1. ✅ **Environment + PPO stack + tests + GPU verified** (this session + 2026-06-25).
2. **Escape −100 on roomy synthetic (action prior + shaping).** Add the **soft +
   annealed action prior** to `foeopt/rlenv.py` + `rl/encode.py`; tune
   `placement_reward`. *Validate:* episode success-rate → ~100% on curriculum
   stages 0–1; roads approach the CP-SAT-optimal baseline on the small roomy
   instances (not just "beats random").
3. **Beat random/greedy on medium synthetic (roads → Σ/2).** Scale the curriculum;
   refine reward (scaled −100 by #unplaced/#unsatisfied; potential-based shaping
   via `road_estimate` of the partial layout); do the throughput work
   (delta-cache `valid_actions` + vectorized envs) once episodes scale. *Validate:*
   `mean_roads` approaches the Σ/2 target on stages 2–3 and beats random/greedy
   rollouts; throughput is high enough to train at 64–256 episodes/update without
   wall-clock stall.
4. **Transfer to darkzig: match or beat repack/polish (158).** **Extend
   `rl/curriculum.py` to synthesize darkzig-like cities** — irregular regions, the
   real darkzig building mix at ~90% fill — seeded variants for training, with
   darkzig itself **held out for eval only**. Fine-tune on these. *Validate / gate:*
   greedy `eval` on darkzig ≤ 158 with `status=ok`. **Fail-fast:** if stuck after
   substantial training, the rescue lever is the deferred **imitation warm-start**
   (§4.4); if that also fails, the global-coupling difficulty that capped local
   methods likely caps RL too — fall back to productionizing the existing 158
   pipeline (the low-risk Tier-1 alternative).
5. **(Deferred — later phase) Generalize:** train across a city distribution for
   instant inference on unseen cities. Out of scope for this plan.
6. **(Deferred — later phase) AlphaZero-style MCTS + policy/value.** Out of scope
   for this plan.

## 10. Honest risks

- **Sample efficiency:** RL on combinatorial placement is notoriously sample-hungry
  (potentially millions of episodes). The action prior + curriculum + shaping are
  the mitigations; imitation warm-start is the fallback.
- **May not beat 158:** the global-coupling difficulty that defeated local methods
  could equally cap RL — no guarantee. M4 is the gate. Crucially, the **action
  prior itself can cause this** if too strict: it bakes in the grow-tree prior that
  produces the 158 floor (§4.3) — hence the soft+annealed design. Watch for the
  policy converging to ~158 grow-tree-style layouts; if so, relax the prior sooner.
- **AMD/ROCm wheel support for gfx1201 is new-ish** (RDNA4). Maintain the CPU `rl`
  extra as a fallback; pin a known-good torch+rocm version in the lockfile so a
  future wheel regression doesn't silently break training.
- **Effort:** weeks + GPU. This is a research project, not a feature. Treat the
  low-risk alternative (productionizing the existing 158 pipeline) as the fallback
  if the RL gate fails.
