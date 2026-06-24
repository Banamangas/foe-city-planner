# RL training for FoE layout — how to run it

An amortized placement solver: train a policy that *places* buildings well, and
let `route()` (already near-optimal for a fixed placement) handle the roads. The
goal is to beat the **~158-road plateau** local methods hit on darkzig, toward the
Σ(short-side)/2 ≈ **114** target — and, once trained, to produce good layouts for
*any* city instantly.

**Status:** the environment (`foeopt/rlenv.py`) and this training stack are built
and **structurally smoke-tested on CPU** (one PPO update + eval run cleanly). They
have **not been trained to convergence** — that needs a GPU and hours-to-days.
Design rationale: `docs/superpowers/specs/2026-06-23-rl-placement-design.md`.

## 1. Install (one-time, on your machine)

```bash
uv sync --extra rl          # adds torch + numpy; the foeopt core stays pure-stdlib
```

## 2. Smoke test (verify it runs — ~1 min on CPU)

```bash
uv run python -m rl.train --stage 0 --updates 5 --episodes 8 --device cpu
```
You should see lines like `stage 0 upd 0 | success 100% | mean_roads 12.5 (target ~4)`.
`success` = fraction of episodes that placed everything and routed; `mean_roads` =
average road count of those. Untrained, roads will be far above target — that's
expected. If this runs, the stack works.

## 3. Train (on GPU)

Auto-curriculum from easy (roomy 10×10) to hard (dense 26×26), advancing each
stage when mastered. Point `--eval-city` at your real city to track the real goal:

```bash
uv run python -m rl.train --auto --device cuda \
    --updates 3000 --episodes 64 \
    --eval-city darkzig.json --ckpt rl_ckpt.pt
```

- `--updates` is the **max** updates per stage; `--auto` advances early once a
  stage is mastered (success ≥ 90% for 20 updates).
- `--episodes` = episodes per PPO update (raise it on a GPU; 64–256 is reasonable).
- Checkpoints save every update to `--ckpt`. Resume with `--resume rl_ckpt.pt`.

**What good progress looks like:** within each stage, `success` climbs toward
100% and `mean_roads` falls toward `target`. The `eval: roads=…` lines (every 10
updates) are the real signal — that's a greedy rollout on darkzig.

## 4. Evaluate a checkpoint on a real city

```bash
uv run python -m rl.eval --ckpt rl_ckpt.pt --city darkzig.json
# -> city=darkzig.json roads=NNN status=ok target(Sigma/2)=114
```

## 5. The make-or-break gate (Milestone 4)

The honest test, per the design doc: **does a trained policy beat 158 on darkzig?**
- `status=stuck`/`unroutable` → it can't even place everything yet (keep training
  earlier stages; strengthen the action prior / shaping below).
- `roads` in the 140s–150s → it's competitive; push further.
- `roads` ≤ ~158 with `status=ok` → **the bet is paying off.** This is the result
  to chase; if you can't reach it after substantial training, the global-coupling
  difficulty that capped local methods likely caps RL too — fail fast and fall back
  to productionizing the existing 158 pipeline.

## 6. Tuning levers (in rough order to try)

- **`--placement-reward`** (default 0.1): the dense shaping bonus per placed
  building. On dense cities, naive policies end "unroutable" (−100) with no
  gradient; this rewards partial progress. Raise it if the policy never learns to
  place everything; lower it once it does, so road count dominates.
- **Action prior (biggest lever, not yet implemented):** restrict
  `PlacementEnv.valid_actions()` to anchors adjacent to existing buildings / the
  growing road, not the whole free grid. This shrinks the action space ~100× and
  avoids most unroutable dead-ends (it bakes in the grow-tree's road-adjacency
  prior). Add it in `foeopt/rlenv.py` or filter in `rl/encode.action_mask`.
- **Imitation warm-start:** pretrain to imitate `repack`/`polish` outputs (and
  CP-SAT optima on small instances) before RL — see the design doc.
- **Network size** (`--hidden`), **lr**, **episodes** — standard PPO knobs.
- **Reward shaping:** the flat −100 in `PlacementEnv.step` could become a penalty
  scaled by #unplaced/#unsatisfied for a smoother gradient.

## 7. Known limitations / where to extend

- `valid_actions()` is O(free cells × footprint) per step — fine for eval, a
  throughput bottleneck for training. Cache it or add the action prior.
- Building **order** is fixed (largest-area first). Making order part of the
  policy (choose WHICH and WHERE) is a natural extension.
- One reward signal (roads). The quality metric (`foeopt/quality.py`, Rule 1/2)
  can be folded in as a secondary shaping term.
- Throughput: vectorize envs; if `route()` dominates, batch it or port its hot
  path (BFS/prune in `foeopt/router.py`).

## Files

| file | role |
|---|---|
| `foeopt/rlenv.py` | the environment (pure-stdlib, tested) |
| `rl/encode.py` | obs → grid tensor + action mask |
| `rl/policy.py` | fully-conv policy + value net (works on any grid size) |
| `rl/curriculum.py` | synthetic city generator (easy → hard) |
| `rl/ppo.py` | rollout, GAE, clipped PPO update, train loop, evaluator |
| `rl/train.py` / `rl/eval.py` | CLI entry points |
