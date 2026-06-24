# RL / ML for FoE Layout — Design & Training Blueprint

Status: **design** (the environment is built & tested; training is future work needing GPU).
Companion code: `foeopt/rlenv.py` (+ `tests/test_rlenv.py`). Context: `tasks/lessons.md`.

## 1. Why this, why now

Every *local* method we tried plateaus at ~**158** roads on the realistic darkzig
city (vs the Σ(short-side)/2 ≈ **114** target): the constructive grow-tree (6
structural variants), simulated annealing, and LNS+CP-SAT (1-road gain, not worth
the dependency). The wall is structural — the problem is globally coupled and
NP-hard, so local re-optimization can't escape a decent local optimum.

Two facts make ML/RL the right next bet:
- **Placement is the lever.** `route()` is already near-optimal for a *fixed*
  placement, and after Task A it's a **fast simulator** (~1.3 ms/call). The open
  problem is arranging buildings into route-cheap double-rows.
- **This is chip floorplanning** (place blocks, minimize routing), where RL has
  worked (Google, *Nature* 2021). The payoff is an **amortized** solver: train
  once across many cities, then get *instant* near-optimal layouts for any pasted
  city. (For a *single* city, classical optimization is better — RL's value is
  generality + inference speed.)

## 2. The environment (built: `foeopt/rlenv.py`)

A sequential-placement MDP — pure-stdlib, the router is the simulator:
- **State (`Obs`):** region mask, occupancy, current building `(w, l, needs_road)`,
  count remaining. Framework-agnostic; the policy encodes it.
- **Action:** an `(x, y)` anchor for the current building. `valid_actions()`
  returns the legal (non-overlapping, in-region) set for masking.
- **Episode:** Townhall pre-placed; place the rest in a fixed order (agent picks
  WHERE, not WHICH); `route()` scores once all are down.
- **Reward:** sparse terminal `target − roads` (>0 below the Σ/2 estimate);
  `−100` for an unplaceable or unroutable layout. Optional per-placement shaping
  (`placement_reward`).

## 3. The central challenge (measured): sparse reward on dense cities

Baseline rollouts on darkzig (90% fill) **all** end "unroutable" (−100) — naive
policies pack with no road channels, stranding a building. A flat −100 gives **no
learning gradient**. Fixing this is the heart of the training design:

1. **Reward shaping.** Per-placement progress bonus (`placement_reward`); replace
   the flat −100 with a penalty scaled by #unplaced/#unsatisfied; potential-based
   shaping using `road_estimate` of the partial layout.
2. **Curriculum.** Start on roomy/synthetic cities where random already succeeds
   (a 10×10 / 6-building env gave a valid roads=17), then raise density and size
   toward darkzig.
3. **Action prior.** Restrict actions to road-adjacent / near-occupancy anchors —
   shrinks the action space and avoids most unroutable dead-ends (bakes in the
   grow-tree's road-adjacency prior that makes layouts feasible).
4. **Imitation warm-start.** Pretrain to imitate CP-SAT optima (small instances)
   and repack/polish outputs, then fine-tune with RL.

## 4. Policy architecture

- **Encoder:** grid as image-like channels — `[region mask, occupancy,
  road-needing occupancy, current-building footprint broadcast]` → CNN; or a GNN
  over placed-buildings + candidate-slot graph (closer to the chip-placement work).
- **Head:** a score per grid cell (pointer); mask via `valid_actions()`; softmax →
  sample anchor. Plus a value head for actor-critic / MCTS.

## 5. Training algorithm

- **Start: PPO** actor-critic with action masking (stable, well-supported).
- **Ambitious: AlphaZero-style MCTS + learned policy/value** — the env is a
  deterministic single-player "game" and `route()` is a cheap rollout simulator,
  which fits MCTS well.
- Self-play across a **distribution** of cities (darkzig-like real + synthetic
  generated with varied size / density / building mix).

## 6. Benchmark / signal

- **Primary:** 0-unplaced road count vs the Σ/2 target on a held-out city set;
  compare to repack/polish (~158 on darkzig) and CP-SAT optima (small instances).
- **Secondary:** the placement-quality metric (`foeopt/quality.py`, Rule 1/2).

## 7. Infrastructure

- PyTorch (+ GPU). Optional dependency group `[rl]`; the training script lives
  **outside** `foeopt/` core (e.g. `rl/train.py`) so the core stays pure-stdlib
  and inference/eval need no torch unless actually running a learned policy.
- Vectorized envs for throughput. `route()` is fast but Python — if it bottlenecks
  training, batch it or port the hot path (BFS/prune) to Rust/C.

## 8. Milestones (each independently validatable)

1. ✅ **Environment + baselines + tests** (this session).
2. **Shaping + curriculum:** a PPO agent learns to place *all* buildings (escapes
   −100) on roomy synthetic cities. *Validate:* episode success-rate → ~100% on the
   easy curriculum.
3. **Beat random/greedy** on medium synthetic cities (roads approach Σ/2).
4. **Transfer to darkzig: match or beat repack/polish (158).** The make-or-break
   gate — if a trained agent can't beat 158, the approach doesn't pay off. *Fail
   fast here.*
5. **Generalize:** train across a city distribution; instant inference on unseen
   cities.

## 9. Honest risks

- **Sample efficiency:** RL on combinatorial placement is notoriously sample-hungry
  (potentially millions of episodes).
- **May not beat 158:** the global-coupling difficulty that defeated local methods
  could equally cap RL — no guarantee. Milestone 4 is the gate.
- **Effort:** weeks + GPU. This is a research project, not a feature. Treat the
  brainstorm's Tier-1 (productionizing the existing 158 pipeline) as the low-risk
  alternative if the RL gate fails.
