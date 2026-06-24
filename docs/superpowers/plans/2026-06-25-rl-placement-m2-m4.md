# RL Placement M2→M4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing PPO placement policy actually *learn* (escape the −100 trap on dense cities via a soft+annealed action prior and reward shaping), then transfer it to the realistic `darkzig` city and attempt to beat the ~158-road local-method floor — the make-or-break gate.

**Architecture:** The `foeopt/rlenv.py` environment stays the single source of placement legality; we add a **soft + annealed action prior** (road-adjacency-restricted anchors, relaxed as success rises) inside `valid_actions(prior=...)`, reflected through `rl/encode.py` and applied per-step in `rl/ppo.py`. Reward refinements (scaled failure penalty + potential-based shaping) live in the env. The curriculum (`rl/curriculum.py`) gains a `darkzig`-like city generator (irregular region + real building mix at ~90% fill) for M4 transfer, with `darkzig.json` held out for eval only. Training runs on the verified AMD/ROCm GPU path (separate venv, torch 2.10.0+rocm7.0). MCTS, full generalization, and imitation warm-start are explicitly deferred (spec §9.5/6).

**Tech Stack:** Python 3.12, PyTorch (ROCm 7.0 wheel on AMD RX 9070 XT / gfx1201), NumPy, pytest. The `foeopt` core stays pure-stdlib; all torch code stays in `rl/`.

## Global Constraints

- **GPU is AMD ROCm, not CUDA.** Verified: `torch 2.10.0+rocm7.0` works on gfx1201 out of the box (`torch.cuda.is_available()` is True — PyTorch's HIP layer reuses the `cuda` API). Training uses `--device cuda`. The portable CPU `rl` extra in `pyproject.toml` stays unchanged.
- **Core stays pure-stdlib.** No torch imports in `foeopt/`. All new torch code goes in `rl/`. `foeopt/rlenv.py` changes must remain stdlib-only (the env is imported by tests without torch).
- **Determinism.** `PlacementEnv` is deterministic given input layout + order. New code must preserve this: the prior uses `sorted()` output; the anneal coin-flip uses a passed `random.Random` (seeded in `train`), not a global RNG.
- **Benchmark discipline (lessons.md).** Compare only 0-unplaced results. Never compare raw road counts without checking `status`. The bundled 97%-full `city-user-data.json` must NOT be used as a baseline (it's a perfect-packing puzzle); `darkzig.json` (90% fill, committed) is the gate.
- **Targets:** darkzig Σ(short-side)/2 = **114** (the estimate); local-method floor = **158** (repack+anneal polish); the gate is greedy eval `roads ≤ 158` with `status=ok`.
- **TDD.** Every task writes the failing test first, runs it, implements, runs it green, commits. No comments in shipped code unless asked.

---

## File Structure

| file | role | touched by |
|---|---|---|
| `foeopt/rlenv.py` | the env; add `valid_actions(prior=)`, scaled failure penalty, potential shaping | T2, T4 |
| `rl/encode.py` | `action_mask(env, W, H, prior=)` passes the prior flag through | T3 |
| `rl/ppo.py` | `select_action_mask`, `prior_strength_for_success`, `collect_episode(...prior_strength=)`, `train(...ref_layout=...)` anneal + real-like stage | T3, T6 |
| `rl/curriculum.py` | add `make_real_like_city(rng, reference, *, fill)` for darkzig-like synthesis | T6 |
| `rl/baselines.py` | NEW: `random_rollout`, `greedy_rollout` for comparison | T5 |
| `rl/oracle.py` | NEW (optional): `optimal_roads` branch-and-bound for tiny instances | T9 |
| `rl/gate.py` | NEW: darkzig gate verdict harness (roads vs 158 vs 114 + quality metric) | T8 |
| `rl/train.py` / `rl/eval.py` | add `--prior-strength`, `--ref-city`, `--potential-shaping` CLI flags | T3, T6, T4 |
| `rl/README.md` | document ROCm setup + the new levers | T1, T3 |
| `tests/test_rlenv.py` | extend: prior tests, scaled-penalty + shaping tests | T2, T4 |
| `tests/test_rl_anneal.py` | NEW: `select_action_mask` + `prior_strength_for_success` | T3 |
| `tests/test_rl_baselines.py` | NEW: random/greedy rollout tests | T5 |
| `tests/test_rl_oracle.py` | NEW (optional): tiny-instance oracle tests | T9 |
| `tests/test_rl_curriculum.py` | NEW: `make_real_like_city` properties | T6 |
| `tests/test_rl_throughput.py` | NEW: delta/frontier `valid_actions` equivalence | T7 |
| `scripts/setup-rocm-venv.sh` | NEW: one-time GPU training venv creator | T1 |

---

## Task 1: ROCm GPU training setup

The uv per-extra source approach does NOT work for torch (a single lockfile can't hold both a PyPI-sourced torch for the CPU `rl` extra and a rocm-sourced torch for a GPU extra — verified). So the GPU training env is a **separate venv** with the rocm wheel installed via pip (proven: `torch 2.10.0+rocm7.0` runs on the RX 9070 XT, smoke test completes on `--device cuda`). `foeopt`/`rl` import from the repo root (cwd on `sys.path`), so no editable install is needed.

**Files:**
- Create: `scripts/setup-rocm-venv.sh`
- Modify: `rl/README.md` (install section)
- Test: manual — run the smoke test on `cuda` from the created venv

**Interfaces:**
- Produces: a venv at `$FOE_RL_VENV` (default `~/.venv/foe-rl-rocm`) with torch+numpy; the repo's `foeopt` and `rl` are importable when running from the repo root with that venv's python.

- [ ] **Step 1: Write the setup script**

Create `scripts/setup-rocm-venv.sh`:

```bash
#!/usr/bin/env bash
# One-time setup of an AMD/ROCm GPU training venv for the RL stack.
# The portable CPU `rl` extra (uv sync --extra rl) stays untouched.
# Verified on RX 9070 XT (gfx1201) with ROCm 7.2 + torch 2.10.0+rocm7.0.
set -euo pipefail

VENV="${FOE_RL_VENV:-$HOME/.venv/foe-rl-rocm}"
ROCM_INDEX="https://download.pytorch.org/whl/rocm7.0"

if [ ! -d /opt/rocm ]; then
  echo "ERROR: ROCm not found at /opt/rocm. Install ROCm first." >&2
  exit 1
fi

echo "Creating venv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip

# torch + numpy from the ROCm index. TMPDIR on a big disk avoids tmpfs fill.
echo "Installing torch (ROCm wheel, ~3GB download)..."
TMPDIR="${TMPDIR:-$HOME/.cache/pip-tmp}" \
"$VENV/bin/pip" install --index-url "$ROCM_INDEX" torch numpy

echo "Verifying GPU..."
"$VENV/bin/python" - <<'PY'
import torch
assert torch.cuda.is_available(), "torch.cuda.is_available() is False — ROCm not visible"
print(f"torch {torch.__version__} | GPU: {torch.cuda.get_device_name(0)} | OK")
PY

cat <<EOF

Done. Train with (from the repo root):
  $VENV/bin/python -m rl.train --device cuda --auto --updates 3000 --episodes 64 --eval-city darkzig.json --ckpt rl_ckpt.pt

Eval:
  $VENV/bin/python -m rl.eval --ckpt rl_ckpt.pt --city darkzig.json
EOF
```

- [ ] **Step 2: Make it executable and run it**

Run:
```bash
chmod +x scripts/setup-rocm-venv.sh
TMPDIR=$HOME/.cache/pip-tmp scripts/setup-rocm-venv.sh
```
Expected: ends with `torch 2.10.0+rocm7.0 | GPU: AMD Radeon RX 9070 XT | OK`.

- [ ] **Step 3: Verify the smoke test runs on the GPU**

Run:
```bash
~/.venv/foe-rl-rocm/bin/python -m rl.train --stage 0 --updates 2 --episodes 4 --device cuda
```
Expected: two `stage 0 upd ... | success 100% | mean_roads ... (target ~4)` lines, no errors. This confirms the full env→encode→policy→PPO→eval path runs on the AMD GPU.

- [ ] **Step 4: Document the ROCm path in rl/README.md**

In `rl/README.md`, replace the "## 1. Install" section so it documents both paths. Edit the existing block:

```markdown
## 1. Install (one-time)

**CPU (portable, for tests/smoke):**
```bash
uv sync --extra rl          # adds torch (CPU) + numpy; the foeopt core stays pure-stdlib
```

**AMD GPU (ROCm — for real training):** the uv per-extra index approach does not work
for torch (one lockfile can't hold both a PyPI and a ROCm-sourced torch for the same
package name), so the GPU training env is a separate venv. Verified on RX 9070 XT
(gfx1201) with ROCm 7.2 + torch 2.10.0+rocm7.0:
```bash
scripts/setup-rocm-venv.sh        # creates ~/.venv/foe-rl-rocm with the ROCm torch wheel
# then train with that venv's python, from the repo root:
~/.venv/foe-rl-rocm/bin/python -m rl.train --device cuda ...
```
```

- [ ] **Step 5: Commit**

```bash
git add scripts/setup-rocm-venv.sh rl/README.md
git commit -m "feat(rl): add ROCm GPU training venv setup (verified on RX 9070 XT)"
```

---

## Task 2: Action prior in PlacementEnv (soft, legality in the env)

The biggest lever. Add a `prior` mode to `valid_actions()` that restricts anchors to footprints orthogonally adjacent to already-placed occupancy (the Townhall + placed buildings). This bakes in the grow-tree's contiguity prior — the thing that makes layouts routable — and shrinks the action space ~100×. The env stays the single source of legality; `prior=True` returns a *subset* (possibly empty) of `prior=False`.

**Files:**
- Modify: `foeopt/rlenv.py:82-93` (`valid_actions`)
- Test: `tests/test_rlenv.py` (append)

**Interfaces:**
- Produces: `PlacementEnv.valid_actions(self, prior: bool = False) -> list[tuple[int,int]]`. `prior=False` is unchanged (all legal anchors). `prior=True` returns only anchors whose footprint contains a cell orthogonally adjacent to `self._occ`. Return value is `sorted(...)` for determinism in both modes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rlenv.py`:

```python
def _region_grid(w, h):
    from foeopt.model import Region
    return Region(frozenset((x, y) for x in range(w) for y in range(h)))


def test_valid_actions_prior_is_subset_of_full():
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(_region_grid(10, 10), [th, _b(10, 3, 2), _b(11, 2, 2)])
    env.reset()
    full = set(env.valid_actions())
    prior = set(env.valid_actions(prior=True))
    assert prior <= full
    assert prior, "with the TH placed, the frontier is non-empty"


def test_valid_actions_prior_anchors_border_occupancy():
    th = _b(1, 2, 2, needs=False, th=True)          # TH occupies (0,0),(1,0),(0,1),(1,1)
    env = _env(_region_grid(10, 10), [th, _b(10, 2, 2)])
    env.reset()
    prior = env.valid_actions(prior=True)
    # every prior anchor's footprint must be orthogonally adjacent to the TH
    from foeopt.model import Footprint
    th_cells = th.footprint.cells()
    for (x, y) in prior:
        fp = Footprint(x, y, 2, 2)
        assert fp.border_cells() & th_cells, f"anchor {(x,y)} not adjacent to TH"


def test_valid_actions_prior_can_be_empty_when_full_is_not():
    # TH 2x2 in the corner; a 6x6 building only fits away from the TH -> prior empty.
    th = _b(1, 2, 2, needs=False, th=True)
    env = _env(_region_grid(12, 12), [th, _b(10, 6, 6)])
    env.reset()
    assert env.valid_actions(), "full set must be non-empty (a 6x6 fits)"
    assert env.valid_actions(prior=True) == [], "no 6x6 placement borders the corner TH"


def test_valid_actions_prior_empty_after_nothing_placed_is_frontier():
    # sanity: prior is non-empty right after reset because the TH is occupied
    th = _b(1, 3, 3, needs=False, th=True)
    env = _env(_region_grid(9, 9), [th, _b(10, 2, 2)])
    env.reset()
    assert env.valid_actions(prior=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rlenv.py -k prior -v`
Expected: FAIL with `TypeError: valid_actions() got an unexpected keyword argument 'prior'`.

- [ ] **Step 3: Implement the prior in valid_actions**

Replace `foeopt/rlenv.py:82-93` (the `valid_actions` method) with:

```python
    def valid_actions(self, prior: bool = False) -> list[tuple[int, int]]:
        """All anchor positions where the current building fits without overlap.

        With ``prior=True``, restrict to anchors whose footprint is orthogonally
        adjacent to already-placed occupancy (the Townhall + placed buildings).
        This bakes in the grow-tree's contiguity prior — the layout grows as a
        connected cluster rooted at the Townhall, which is what makes it routable
        — and shrinks the action space ~100x. May return [] when no legal anchor
        is adjacent (callers fall back to the full set). Output is sorted for
        determinism.
        """
        b = self.current
        if b is None:
            return []
        w, l = b.footprint.width, b.footprint.length
        free = self.region.cells - self._occ
        frontier = None
        if prior:
            frontier = {
                c for c in free
                for n in ((c[0] - 1, c[1]), (c[0] + 1, c[1]),
                          (c[0], c[1] - 1), (c[0], c[1] + 1))
                if n in self._occ
            }
        out = []
        for (x, y) in free:
            if not all((x + dx, y + dy) in free for dx in range(w) for dy in range(l)):
                continue
            if prior and not any((x + dx, y + dy) in frontier
                                 for dx in range(w) for dy in range(l)):
                continue
            out.append((x, y))
        return sorted(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rlenv.py -v`
Expected: all pass (including the 4 new prior tests + the existing 8).

- [ ] **Step 5: Commit**

```bash
git add foeopt/rlenv.py tests/test_rlenv.py
git commit -m "feat(rlenv): soft action prior — road-adjacency-restricted valid_actions"
```

---

## Task 3: Annealed prior masking + schedule in PPO

Wire the prior into the policy pipeline. The mask is chosen per-step: with probability `prior_strength` use the prior mask, else the full mask; if the prior mask is empty, always fall back to full (never get stuck). `prior_strength` is annealed by a pure function of the current success rate — strict (≈0.95) while the policy is failing, relaxing toward a floor (0.2) as success rises, so the policy eventually explores beyond the grow-tree prior (avoiding re-capping at the 158 floor).

**Files:**
- Modify: `rl/encode.py:35-40` (`action_mask`)
- Modify: `rl/ppo.py:20-44` (`collect_episode`), `rl/ppo.py:101-145` (`train`)
- Modify: `rl/train.py:16-44` (CLI flags)
- Test: `tests/test_rl_anneal.py` (new)

**Interfaces:**
- Consumes: `PlacementEnv.valid_actions(prior=)` from T2.
- Produces:
  - `rl.encode.action_mask(env, W, H, prior=False) -> torch.Tensor` (boolean `[H*W]`).
  - `rl.ppo.select_action_mask(full, prior, prior_strength, rng) -> torch.Tensor`.
  - `rl.ppo.prior_strength_for_success(success_rate, *, strict_below=0.5, floor=0.2) -> float`.
  - `rl.ppo.collect_episode(env, policy, W, H, device, prior_strength=1.0, rng=...)` (added param).
  - `rl.ppo.train(..., prior_strength_start=0.95, prior_strength_floor=0.2)` anneals per-update from the update's success rate. (The `ref_layout` / darkzig-like stage is wired in T6, where `make_real_like_city` is defined — not here, to avoid a forward dependency.)

- [ ] **Step 1: Write the failing tests for the schedule and mask selection**

Create `tests/test_rl_anneal.py`:

```python
import random
import torch

from rl.ppo import prior_strength_for_success, select_action_mask


def test_prior_strength_strict_when_success_low():
    assert prior_strength_for_success(0.0) == 1.0
    assert prior_strength_for_success(0.5) == 1.0          # at the threshold, still strict


def test_prior_strength_relaxes_to_floor_as_success_rises():
    assert prior_strength_for_success(1.0) == 0.2          # floor
    mid = prior_strength_for_success(0.75)                 # halfway between 0.5 and 1.0
    assert 0.2 < mid < 1.0
    # monotonic: higher success -> lower (more relaxed) strength
    assert prior_strength_for_success(0.6) > prior_strength_for_success(0.9)


def test_select_mask_uses_full_when_prior_empty():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([False, False, False])
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=1.0, rng=rng)
    assert torch.equal(out, full)          # fallback: prior empty -> full


def test_select_mask_strict_uses_prior_when_nonempty():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([True, False, False])
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=1.0, rng=rng)
    assert torch.equal(out, prior)


def test_select_mask_zero_strength_uses_full():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([True, False, False])
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=0.0, rng=rng)
    assert torch.equal(out, full)


def test_select_mask_intermediate_flips_by_rng():
    full = torch.tensor([True, True, True])
    prior = torch.tensor([True, False, False])
    # rng draws < 0.5 -> prior; >= 0.5 -> full. With seed 0, first draw is ~0.844 -> full.
    rng = random.Random(0)
    out = select_action_mask(full, prior, prior_strength=0.5, rng=rng)
    assert torch.equal(out, full)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rl_anneal.py -v`
Expected: FAIL with `ImportError: cannot import name 'prior_strength_for_success'`.

- [ ] **Step 3: Add prior= to action_mask**

In `rl/encode.py`, replace `action_mask` (lines 35-40) with:

```python
def action_mask(env: PlacementEnv, W: int, H: int, *, prior: bool = False) -> torch.Tensor:
    """Boolean [H*W]: True where the current building may anchor.

    With ``prior=True``, only road-adjacency-restricted anchors (the soft action
    prior) are True; may be all-False when no legal anchor is adjacent."""
    m = np.zeros(H * W, dtype=bool)
    for (x, y) in env.valid_actions(prior=prior):
        m[y * W + x] = True
    return torch.from_numpy(m)
```

- [ ] **Step 4: Add the schedule + mask selection + wire collect_episode**

In `rl/ppo.py`, add these two functions after the imports (before `collect_episode`):

```python
def prior_strength_for_success(success_rate: float, *, strict_below: float = 0.5,
                               floor: float = 0.2) -> float:
    """Anneal the action-prior strength from strict (1.0) while the policy is
    failing toward ``floor`` as success -> 1.0. Strict below ``strict_below``;
    linear relaxation above it. Keeps ``floor`` exploration off-prior so the
    policy can escape the grow-tree prior (which re-caps at ~158)."""
    if success_rate <= strict_below:
        return 1.0
    t = (success_rate - strict_below) / (1.0 - strict_below)   # 0..1
    return 1.0 - t * (1.0 - floor)


def select_action_mask(full: torch.Tensor, prior: torch.Tensor,
                       prior_strength: float, rng: random.Random) -> torch.Tensor:
    """Pick the per-step action mask: the prior mask with prob ``prior_strength``,
    else the full mask. Falls back to full when the prior mask is empty (never
    get stuck on a step where no anchor is road-adjacent)."""
    if prior_strength <= 0.0 or not bool(prior.any()):
        return full
    if prior_strength >= 1.0:
        return prior
    return prior if rng.random() < prior_strength else full
```

Then replace `collect_episode` (lines 20-44) with:

```python
def collect_episode(env, policy, W, H, device, prior_strength=1.0, rng=None):
    """Run one episode under the current policy. ``prior_strength`` anneals the
    action prior (1.0 = strict road-adjacency, 0.0 = full free grid). Returns
    (transitions, info). The mask actually used is stored per transition so PPO
    importance ratios stay consistent."""
    if rng is None:
        rng = random.Random()
    obs = env.reset()
    trans, info = [], {"roads": None, "status": "incomplete"}
    while not env.done:
        full = action_mask(env, W, H, prior=False).to(device)
        if not bool(full.any()):                 # stuck: nothing fits at all
            if trans:
                trans[-1]["reward"] += env.INVALID_PENALTY
            info["status"] = "stuck"
            return trans, info
        prior = action_mask(env, W, H, prior=True).to(device)
        mask = select_action_mask(full, prior, prior_strength, rng).to(device)
        x = encode_obs(obs, W, H).unsqueeze(0).to(device)
        with torch.no_grad():
            logits, value = policy(x)
            dist = masked_dist(logits, mask.unsqueeze(0))
            action = dist.sample()
            logp = dist.log_prob(action)
        idx = int(action.item())
        res = env.step(index_to_action(idx, W))
        trans.append({"x": x.squeeze(0).cpu(), "mask": mask.cpu(), "action": idx,
                      "logp": float(logp.item()), "value": float(value.item()),
                      "reward": float(res.reward)})
        obs = res.obs
        info = res.info if res.done else info
    return trans, info
```

- [ ] **Step 5: Anneal in the train loop**

In `rl/ppo.py`, update the `train` signature (line 101) to add the anneal params (NOT `ref_layout` or `potential_shaping` — those come in T6 and T4 respectively):

```python
def train(*, stage=0, updates=200, episodes_per_update=16, lr=3e-4, device="cpu",
          seed=0, ckpt="rl_ckpt.pt", placement_reward=0.1, hidden=64,
          eval_layout=None, resume=None, auto=False, advance_success=0.9,
          advance_patience=20, prior_strength_start=0.95, prior_strength_floor=0.2,
          log=print):
```

Then replace the per-update episode loop (lines 118-130) so it anneals `prior_strength` from the previous update's success and passes it into `collect_episode`. Insert `succ_prev = 0.0` before the `for upd in range(updates):` loop, then:

```python
            batch, roads, successes, target = [], [], 0, None
            for _ in range(episodes_per_update):
                city = curriculum.make_city(stg, rng)
                target = road_estimate(city)
                env = PlacementEnv(city, placement_reward=placement_reward)
                trans, info = collect_episode(
                    env, policy, W, H, device,
                    prior_strength=prior_strength_for_success(
                        succ_prev, floor=prior_strength_floor),
                    rng=rng)
                if not trans:
                    continue
                gae(trans)
                batch.extend(trans)
                if info.get("roads") is not None:
                    roads.append(info["roads"]); successes += 1
            succ = successes / episodes_per_update
            succ_prev = succ
```

(Leave the rest of the loop body — `mean_roads`, logging, checkpoint, eval-print, auto-advance — unchanged. The eval-print line `r, st = evaluate(...)` stays a 2-tuple unpack until T8 changes `evaluate` to a 3-tuple.)

- [ ] **Step 6: Add CLI flags to train.py**

In `rl/train.py`, add arguments after `--auto` (line 33):

```python
    p.add_argument("--prior-strength-start", type=float, default=0.95,
                   help="anneal: prior strength at low success (1.0=strict road-adjacency)")
    p.add_argument("--prior-strength-floor", type=float, default=0.2,
                   help="anneal: relaxed prior strength at high success (keeps exploration)")
```

And pass the new args into `train(...)`:

```python
    train(stage=args.stage, updates=args.updates, episodes_per_update=args.episodes,
          lr=args.lr, device=args.device, seed=args.seed, ckpt=args.ckpt,
          placement_reward=args.placement_reward, hidden=args.hidden,
          eval_layout=eval_layout, resume=args.resume, auto=args.auto,
          prior_strength_start=args.prior_strength_start,
          prior_strength_floor=args.prior_strength_floor)
```

(The `--ref-city` flag + `ref_layout=` wiring are added in T6; `--potential-shaping` is added in T4.)

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rl_anneal.py tests/test_rlenv.py -v`
Expected: all pass. Then run a smoke test to confirm the wired loop still runs:
```bash
uv run python -m rl.train --stage 0 --updates 2 --episodes 4 --device cpu
```
Expected: two update lines, no errors (the prior is on by default via the anneal).

- [ ] **Step 8: Commit**

```bash
git add rl/encode.py rl/ppo.py rl/train.py tests/test_rl_anneal.py
git commit -m "feat(rl): annealed action-prior masking in PPO (strict->relaxed by success)"
```

---

## Task 4: Scaled failure penalty + potential-based shaping

The flat −100 gives no gradient on dense cities (the central challenge). Scale the `invalid_placement` penalty by the fraction of buildings left unplaced (early failures penalize more; late placements get a milder penalty → a gradient toward placing more). Add optional potential-based shaping: each placement that raises the partial-layout `road_estimate` earns a bonus, rewarding placement of road-needing buildings (the hard, valuable ones) over fillers. Unroutable (rare with the prior) stays a flat −100.

**Files:**
- Modify: `foeopt/rlenv.py:46-66` (`__init__` stores road-needing count), `foeopt/rlenv.py:68-72` (`reset` inits potential), `foeopt/rlenv.py:95-121` (`step`)
- Test: `tests/test_rlenv.py` (append)

**Interfaces:**
- Produces:
  - `PlacementEnv(layout, *, placement_reward=0.0, potential_shaping=False)`.
  - Terminal `invalid_placement` reward = `INVALID_PENALTY * (unplaced / total_order)`.
  - Terminal `unsatisfied` reward = `INVALID_PENALTY * (n_unsatisfied / n_road_needing)`.
  - Terminal `unroutable` (RouteError) reward = `INVALID_PENALTY` (flat — catastrophic, rare).
  - Non-terminal placement reward = `placement_reward + (potential_delta if potential_shaping)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rlenv.py`:

```python
def test_invalid_penalty_scales_with_unplaced():
    # 4 buildings to place after TH. Fail on the FIRST placement -> 4 unplaced.
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region_grid(3, 1), [th, _b(10, 1, 1), _b(11, 1, 1),
                                    _b(12, 1, 1), _b(13, 1, 1)])
    env.reset()
    res = env.step((0, 0))                       # overlaps TH -> invalid, 4 left
    assert res.info["error"] == "invalid_placement"
    assert res.reward == -100.0 * (4 / 4)


def test_invalid_penalty_scales_down_when_most_placed():
    # Place 3 of 4 successfully on a roomy grid, then force an invalid step.
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region_grid(8, 1), [th, _b(10, 1, 1), _b(11, 1, 1),
                                    _b(12, 1, 1), _b(13, 1, 1)])
    env.reset()
    env.step((2, 0)); env.step((3, 0)); env.step((4, 0))   # 3 placed, 1 left
    res = env.step((0, 0))                       # overlaps TH -> invalid, 1 unplaced
    assert res.reward == -100.0 * (1 / 4)


def test_unroutable_penalty_is_flat():
    th = _b(1, 1, 1, needs=False, th=True)
    env = _env(_region_grid(2, 1), [th, _b(10, 1, 1)])   # no room for a road
    env.reset()
    res = env.step((1, 0))
    assert res.reward == -100.0


def test_potential_shaping_rewards_road_needing_placement():
    th = _b(1, 2, 2, needs=False, th=True)
    cons = _b(10, 4, 4, needs=True)              # road-needing; road_estimate rises 2
    filler = _b(11, 2, 2, needs=False)           # not road-needing; estimate unchanged
    tail = _b(12, 2, 2, needs=True)              # last so filler's step is non-terminal
    env = PlacementEnv(Layout(_region_grid(20, 20), [th, cons, filler, tail], th),
                       placement_reward=0.0, potential_shaping=True)
    env.reset()
    # order is largest-area first: cons(16), then filler(4) and tail(4) by entity_id.
    # place the consumer first -> shaping bonus = road_estimate delta = min(4,4)//2 = 2
    r_cons = env.step(env.valid_actions()[0])
    assert not r_cons.done
    assert r_cons.reward == 2.0
    # place the filler next -> not road-needing, road_estimate unchanged -> reward 0.0
    r_filler = env.step(env.valid_actions()[0])
    assert not r_filler.done
    assert r_filler.reward == 0.0


def test_potential_shaping_off_by_default():
    th = _b(1, 2, 2, needs=False, th=True)
    cons = _b(10, 4, 4, needs=True)
    tail = _b(11, 2, 2, needs=True)              # so the first placement is non-terminal
    env = PlacementEnv(Layout(_region_grid(20, 20), [th, cons, tail], th),
                       placement_reward=0.0)
    env.reset()
    # shaping off, not terminal -> plain placement_reward (0.0)
    assert env.step(env.valid_actions()[0]).reward == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rlenv.py -k "penalty or shaping" -v`
Expected: FAIL (scaled-penalty tests get −100 instead of the scaled value; shaping tests get 0 instead of 2.0).

- [ ] **Step 3: Implement scaled penalty + shaping in the env**

In `foeopt/rlenv.py`, update `__init__` (add `potential_shaping` param + store the road-needing count). Replace lines 48-66:

```python
    def __init__(self, layout: Layout, *, order: list[Building] | None = None,
                 placement_reward: float = 0.0, potential_shaping: bool = False):
        if layout.townhall is None:
            raise ValueError("PlacementEnv requires a Townhall")
        self.region = layout.region
        self.townhall = layout.townhall
        self.placement_reward = placement_reward
        self.potential_shaping = potential_shaping
        movable = [b for b in layout.buildings if not b.is_townhall]
        self._order = order if order is not None else sorted(
            movable, key=lambda b: (-(b.footprint.width * b.footprint.length), b.entity_id)
        )
        self._n_road_needing = len([b for b in self._order if b.needs_road])
        self.target = road_estimate(layout)
        self.reset()
```

Update `reset` to initialise the potential (replace lines 68-72):

```python
    def reset(self) -> Obs:
        self._placed: list[Building] = [self.townhall]
        self._occ: set[tuple[int, int]] = set(self.townhall.footprint.cells())
        self._ptr = 0
        self._potential = self._partial_road_estimate()
        return self._obs()
```

Add a helper (after `_obs` or near it):

```python
    def _partial_road_estimate(self) -> int:
        """road_estimate of the layout formed by the Townhall + buildings placed so far.
        Rises as road-needing buildings are placed — the potential for shaping."""
        partial = Layout(self.region, self._placed, self.townhall, {})
        return road_estimate(partial)
```

Update `step` (replace lines 95-121) with the scaled penalties + shaping:

```python
    def step(self, action: tuple[int, int]) -> StepResult:
        b = self.current
        if b is None:
            raise RuntimeError("step() called on a finished episode")
        w, l = b.footprint.width, b.footprint.length
        fp = Footprint(action[0], action[1], w, l)
        cells = fp.cells()
        if not cells <= (self.region.cells - self._occ):
            unplaced = len(self._order) - self._ptr
            total = len(self._order) or 1
            return StepResult(self._obs(), self.INVALID_PENALTY * (unplaced / total),
                              True, {"error": "invalid_placement"})
        self._placed.append(replace(b, footprint=fp))
        self._occ |= cells
        self._ptr += 1
        if not self.done:
            reward = self.placement_reward
            if self.potential_shaping:
                new_pot = self._partial_road_estimate()
                reward += (new_pot - self._potential)
                self._potential = new_pot
            return StepResult(self._obs(), reward, False, {})
        # all placed -> the router scores the layout
        layout = Layout(self.region, self._placed, self.townhall, {})
        try:
            roads = route(layout)
        except RouteError:
            return StepResult(self._obs(), self.INVALID_PENALTY, True,
                              {"error": "unroutable"})
        layout.roads = roads
        if not is_valid(layout):
            n_bad = len(unsatisfied(layout))
            frac = (n_bad / self._n_road_needing) if self._n_road_needing else 1.0
            return StepResult(self._obs(), self.INVALID_PENALTY * frac, True,
                              {"error": "unsatisfied"})
        nroads = len(roads)
        reward = float(self.target - nroads)
        return StepResult(self._obs(), reward, True,
                          {"roads": nroads, "target": self.target, "layout": layout})
```

Add the import at the top of `foeopt/rlenv.py` (alongside the existing `from foeopt.validate import is_valid`):

```python
from foeopt.validate import is_valid, unsatisfied
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rlenv.py -v`
Expected: all pass (new penalty/shaping tests + existing 8, which use `placement_reward` and the default `potential_shaping=False`, so the `test_placement_reward_shaping` test still sees `0.5`).

- [ ] **Step 5: Wire potential_shaping through the CLI + train loop**

Three coordinated edits:
1. In `rl/ppo.py`'s `train` signature (last edited in T3), add `potential_shaping=False` before `log=print`.
2. In the same `train`'s episode loop, change `env = PlacementEnv(city, placement_reward=placement_reward)` to `env = PlacementEnv(city, placement_reward=placement_reward, potential_shaping=potential_shaping)`.
3. In `rl/train.py`, add the flag and pass it through:

```python
    p.add_argument("--potential-shaping", action="store_true",
                   help="add potential-based reward shaping (road_estimate delta per placement)")
```

And add `potential_shaping=args.potential_shaping` to the `train(...)` call. (When T6 later adds `ref_layout=` to that same call, both kwargs coexist.)

- [ ] **Step 6: Run the full RL smoke test**

Run: `uv run python -m rl.train --stage 0 --updates 2 --episodes 4 --device cpu --potential-shaping`
Expected: two update lines, no errors.

- [ ] **Step 7: Commit**

```bash
git add foeopt/rlenv.py rl/train.py rl/ppo.py tests/test_rlenv.py
git commit -m "feat(rlenv): scaled failure penalty + optional potential-based shaping"
```

---

## Task 5: Random/greedy baseline rollouts

To validate that the policy *learns* (M2/M3), we need comparison baselines: a uniform-random rollout and a one-step-greedy rollout (pick the anchor that minimizes the partial road estimate). These belong in a small `rl/baselines.py` so eval and tests can call them without a trained policy.

**Files:**
- Create: `rl/baselines.py`
- Test: `tests/test_rl_baselines.py` (new)

**Interfaces:**
- Produces:
  - `rl.baselines.random_rollout(layout, *, rng) -> (roads or None, status)` — uniform over `valid_actions()`, no prior.
  - `rl.baselines.greedy_rollout(layout) -> (roads or None, status)` — at each step pick the anchor maximizing `_partial_road_estimate()` after placement (myopic road-estimate greedy), falling back to the first valid action on ties.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rl_baselines.py`:

```python
import random

from foeopt.model import Building, Footprint, Layout, Region
from rl.baselines import random_rollout, greedy_rollout


def _layout():
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    cons = [Building(10 + i, f"c{10+i}", "g", Footprint(0, 0, 2, 2),
                     True, 1, False, None, None, f"b{10+i}") for i in range(4)]
    region = Region(frozenset((x, y) for x in range(12) for y in range(12)))
    return Layout(region, [th, *cons], th, {})


def test_random_rollout_completes_on_roomy_city():
    roads, status = random_rollout(_layout(), rng=random.Random(0))
    assert status == "ok"
    assert isinstance(roads, int) and roads > 0


def test_random_rollout_is_deterministic_given_seed():
    r1, _ = random_rollout(_layout(), rng=random.Random(0))
    r2, _ = random_rollout(_layout(), rng=random.Random(0))
    assert r1 == r2


def test_greedy_rollout_completes_and_beats_or_matches_random():
    g_roads, g_status = greedy_rollout(_layout())
    assert g_status == "ok"
    # greedy is myopic but should be no worse than random on a roomy grid
    r_roads, _ = random_rollout(_layout(), rng=random.Random(0))
    assert g_roads <= r_roads + 4   # generous; greedy shouldn't blow up here
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rl_baselines.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rl.baselines'`.

- [ ] **Step 3: Implement the baselines**

Create `rl/baselines.py`:

```python
"""Non-learned baselines for the placement env: uniform-random and myopic
road-estimate-greedy rollouts. Used to validate that a trained policy actually
learns (M2/M3 signal) and as a fallback comparison."""
from __future__ import annotations

import random

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.rlenv import PlacementEnv


def _run(env: PlacementEnv, choose) -> tuple[int | None, str]:
    env.reset()
    while not env.done:
        valid = env.valid_actions()
        if not valid:
            return None, "stuck"
        res = env.step(choose(valid, env))
        if res.done:
            return res.info.get("roads"), res.info.get("error", "ok")
    return None, "incomplete"


def random_rollout(layout: Layout, *, rng: random.Random) -> tuple[int | None, str]:
    """Uniform-random placement over the full free grid (no prior)."""
    env = PlacementEnv(layout)
    return _run(env, lambda valid, e: rng.choice(valid))


def greedy_rollout(layout: Layout) -> tuple[int | None, str]:
    """Myopic greedy: pick the anchor that maximizes the partial road_estimate
    after placement (a cheap proxy for a route-cheap cluster). Ties -> first."""
    env = PlacementEnv(layout)

    def choose(valid, e):
        best, best_pot = valid[0], -1
        for (x, y) in valid:
            b = e.current
            fp = Footprint(x, y, b.footprint.width, b.footprint.length)
            trial = Layout(e.region, e._placed + [b], e.townhall, {})
            from foeopt.report import road_estimate
            pot = road_estimate(trial)
            if pot > best_pot:
                best, best_pot = (x, y), pot
        return best

    return _run(env, choose)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rl_baselines.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rl/baselines.py tests/test_rl_baselines.py
git commit -m "feat(rl): random + myopic-greedy baseline rollouts for M2/M3 comparison"
```

---

## Task 6: Curriculum — darkzig-like cities for M4 transfer

The square synthetic curriculum can't generalize to `darkzig`'s irregular region and real building mix. Add `make_real_like_city(rng, reference, *, fill=0.9)`: keep the reference's region + Townhall (position + size), sample buildings from the reference's `(w, l, needs_road)` pool to ~90% fill, all at `(0,0)` footprints (the env repositions them). `darkzig.json` itself is **never** a training city — only synthesized variants; it's held out for `--eval-city`.

**Files:**
- Modify: `rl/curriculum.py` (add `make_real_like_city`)
- Modify: `rl/ppo.py` (`train` gains `ref_layout=` and uses `make_real_like_city` for the final stage)
- Modify: `rl/train.py` (add `--ref-city` / `--ref-helper` CLI)
- Test: `tests/test_rl_curriculum.py` (new)

**Interfaces:**
- Consumes: a `Layout` loaded from `darkzig.json` via `foeopt.loader.load_layout` (passed as `ref_layout` into `train`); `collect_episode(prior_strength=)` from T3.
- Produces: `rl.curriculum.make_real_like_city(rng: random.Random, reference: Layout, *, fill: float = 0.9) -> Layout`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rl_curriculum.py`:

```python
import random

from foeopt.model import Building, Footprint, Layout, Region
from rl.curriculum import make_real_like_city


def _reference():
    # a small irregular-region stand-in for darkzig with a TH + a few buildings
    cells = frozenset((x, y) for x in range(10) for y in range(8)) | \
            frozenset((x, y) for x in range(10, 14) for y in range(4, 8))   # L-shaped
    th = Building(1, "c1", "main_building", Footprint(1, 1, 3, 2),
                  False, 1, True, None, None, "TH")
    mix = [Building(10, "c10", "g", Footprint(0, 0, 4, 4), True, 1, False, None, None, "a"),
           Building(11, "c11", "g", Footprint(0, 0, 2, 3), True, 1, False, None, None, "b"),
           Building(12, "c12", "g", Footprint(0, 0, 5, 5), False, 1, False, None, None, "c")]
    return Layout(Region(cells), [th, *mix], th, {})


def test_real_like_city_keeps_reference_region_and_townhall():
    ref = _reference()
    city = make_real_like_city(random.Random(0), ref)
    assert city.region.cells == ref.region.cells
    assert city.townhall is ref.townhall                  # same TH object/position


def test_real_like_city_buildings_at_origin_for_env_to_reposition():
    ref = _reference()
    city = make_real_like_city(random.Random(0), ref)
    for b in city.buildings:
        if not b.is_townhall:
            assert (b.footprint.x, b.footprint.y) == (0, 0)


def test_real_like_city_fill_approximates_target():
    ref = _reference()
    city = make_real_like_city(random.Random(0), ref, fill=0.9)
    region_area = len(ref.region.cells)
    th_area = ref.townhall.footprint.width * ref.townhall.footprint.length
    bld_area = sum(b.footprint.width * b.footprint.length for b in city.buildings)
    assert th_area <= bld_area <= 0.95 * region_area      # ~90% fill, tolerance
    assert bld_area >= 0.8 * region_area


def test_real_like_city_is_deterministic_given_seed():
    ref = _reference()
    c1 = make_real_like_city(random.Random(7), ref)
    c2 = make_real_like_city(random.Random(7), ref)
    assert [(b.footprint.width, b.footprint.length, b.needs_road) for b in c1.buildings] == \
           [(b.footprint.width, b.footprint.length, b.needs_road) for b in c2.buildings]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rl_curriculum.py -v`
Expected: FAIL with `ImportError: cannot import name 'make_real_like_city'`.

- [ ] **Step 3: Implement make_real_like_city**

Append to `rl/curriculum.py`:

```python
def make_real_like_city(rng: random.Random, reference: Layout, *, fill: float = 0.9) -> Layout:
    """A darkzig-like training city: the reference's irregular region + Townhall
    (same position/size), with buildings sampled from the reference's (w,l,needs_road)
    mix to ~`fill` of the region area. Non-TH buildings sit at (0,0); the env
    repositions them during placement. The reference itself (e.g. darkzig.json) is
    held out for eval — only these synthesized variants are trained on."""
    region = reference.region
    th = reference.townhall
    th_area = th.footprint.width * th.footprint.length
    pool = [(b.footprint.width, b.footprint.length, b.needs_road)
            for b in reference.buildings if not b.is_townhall]
    target_area = int(fill * len(region.cells)) - th_area
    blds = [th]
    area, eid = 0, 1000
    while area < target_area and pool:
        w, l, needs = rng.choice(pool)
        blds.append(Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l),
                             needs_road=needs, road_level=1, is_townhall=False,
                             set_id=None, chain_id=None, name=f"b{eid}"))
        area += w * l
        eid += 1
    return Layout(region, blds, th, {})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rl_curriculum.py -v`
Expected: all pass.

- [ ] **Step 5: Wire ref_layout into the train loop + CLI**

In `rl/ppo.py`, add `ref_layout=None` to the `train` signature (after `potential_shaping=False`), and change the per-update city selection (the line `city = curriculum.make_city(stg, rng)` from T3 Step 5) to use real-like cities on the final stage when a reference is provided:

```python
                last = len(curriculum.STAGES) - 1
                if ref_layout is not None and stg >= last:
                    city = curriculum.make_real_like_city(rng, ref_layout)
                else:
                    city = curriculum.make_city(stg, rng)
```

(`last` is already computed in `train` at line 112; reuse it rather than recomputing. Place this where `city` is assigned inside the episode loop.)

In `rl/train.py`, add the CLI flags and load the reference (after the `--potential-shaping` flag from T3):

```python
    p.add_argument("--ref-city", default=None,
                   help="real city (e.g. darkzig.json) to synthesize darkzig-like training "
                        "cities from for the final curriculum stage (held out for eval)")
    p.add_argument("--ref-helper", default=None)
```

And load + pass it:

```python
    ref_layout = None
    if args.ref_city:
        from foeopt.loader import load_layout
        ref_layout = load_layout(args.ref_city, args.ref_helper)

    train(stage=args.stage, updates=args.updates, episodes_per_update=args.episodes,
          lr=args.lr, device=args.device, seed=args.seed, ckpt=args.ckpt,
          placement_reward=args.placement_reward, hidden=args.hidden,
          eval_layout=eval_layout, resume=args.resume, auto=args.auto,
          prior_strength_start=args.prior_strength_start,
          prior_strength_floor=args.prior_strength_floor,
          potential_shaping=args.potential_shaping, ref_layout=ref_layout)
```

- [ ] **Step 6: Verify the wired path works end-to-end on a ref city**

Run a quick smoke test using the bundled fixture as a stand-in reference (not darkzig, to keep the test fast):
```bash
uv run python -c "
import random
from foeopt.loader import load_layout
from rl.curriculum import make_real_like_city
from rl.ppo import train
ref = load_layout('city-user-data.json', 'city-user-data-foe-helper.json')
train(stage=4, updates=2, episodes_per_update=2, device='cpu', ref_layout=ref)
" 2>&1 | tail -3
```
Expected: two `stage 4 upd ...` lines using synthesized real-like cities, no errors. (This confirms the `ref_layout` branch wired in T6 Step 5 calls `make_real_like_city`.)

- [ ] **Step 7: Commit**

```bash
git add rl/curriculum.py rl/ppo.py rl/train.py tests/test_rl_curriculum.py
git commit -m "feat(rl): darkzig-like curriculum cities + ref-city wiring (90% fill, held out)"
```

---

## Task 7: Throughput — profile + frontier-optimized valid_actions (measurement-gated)

The env loop is CPU-bound and `valid_actions()` is O(free × footprint) per step. With the prior on (most of training) it's called twice per step (full + prior). This task first **measures** whether it's the actual bottleneck during a real training burst, then — only if it is — adds an incremental delta-cache so the legal-anchor set is derived by a delta from the previous step instead of a full rescan. Gated on a measurement so we don't optimize a non-bottleneck.

**Files:**
- Modify: `foeopt/rlenv.py` (add delta-cached `valid_actions` path, behind a flag, equivalence-tested)
- Test: `tests/test_rl_throughput.py` (new)

**Interfaces:**
- Produces: `PlacementEnv(..., cache_valid_actions=True)` — when set, `valid_actions()` maintains a cached legal-anchor set updated by an O(footprint + frontier) delta on each `step`, and `valid_actions(prior=)` filters that cached set. Output must be byte-identical to the uncached path.

- [ ] **Step 1: Write the equivalence test (the correctness gate)**

Create `tests/test_rl_throughput.py`:

```python
import random

from foeopt.model import Building, Footprint, Layout, Region
from foeopt.rlenv import PlacementEnv


def _layout(n=8, side=14):
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    rng = random.Random(0)
    bs = [Building(10 + i, f"c{10+i}", "g",
                   Footprint(0, 0, rng.choice([2, 3, 4]), rng.choice([2, 3, 4])),
                   rng.random() < 0.7, 1, False, None, None, f"b{10+i}")
          for i in range(n)]
    region = Region(frozenset((x, y) for x in range(side) for y in range(side)))
    return Layout(region, [th, *bs], th, {})


def test_cached_valid_actions_matches_uncached_across_an_episode():
    layout = _layout()
    slow = PlacementEnv(layout)
    fast = PlacementEnv(layout, cache_valid_actions=True)
    rng = random.Random(123)
    slow.reset(); fast.reset()
    while not slow.done:
        assert slow.valid_actions() == fast.valid_actions()
        assert slow.valid_actions(prior=True) == fast.valid_actions(prior=True)
        a = rng.choice(slow.valid_actions())
        slow.step(a); fast.step(a)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_rl_throughput.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'cache_valid_actions'`.

- [ ] **Step 3: Measure whether valid_actions is the bottleneck (gate)**

Run a profiling burst on the GPU venv (from the repo root):
```bash
~/.venv/foe-rl-rocm/bin/python -c "
import time, random, torch
from rl.ppo import collect_episode
from rl.curriculum import make_city
from rl.encode import grid_bounds
from foeopt.rlenv import PlacementEnv
from rl.policy import PlacementPolicy
dev='cuda'; pol=PlacementPolicy(hidden=64).to(dev)
rng=random.Random(0)
W=H=20
t0=time.time(); n=0
for _ in range(50):
    c=make_city(3,rng); env=PlacementEnv(c, placement_reward=0.1)
    tr,_=collect_episode(env,pol,W,H,dev,prior_strength=0.9,rng=rng); n+=len(tr)
dt=time.time()-t0
print(f'{n} steps in {dt:.2f}s = {n/dt:.0f} steps/s')
"
```
Record the steps/s. If `valid_actions` profiling (e.g. via `cProfile` over the same loop) shows it dominates (>40% of time), implement the delta cache; otherwise skip Step 4 and just commit the equivalence test scaffolding + a `cache_valid_actions` no-op that aliases the uncached path, noting the measurement result in the commit message.

- [ ] **Step 4: Implement the delta cache (only if the gate says yes)**

In `foeopt/rlenv.py`, add a `cache_valid_actions: bool = False` param to `__init__` and store it. Maintain `self._valid_cache: dict[tuple[int,int], list[tuple[int,int]]]` keyed by `(w, l)` for the current free set. On `reset`, populate it for all distinct `(w,l)` in `self._order`. On each successful `step`, invalidate only the anchors whose footprint overlapped the newly occupied cells (and recompute the frontier delta for the prior). The uncached path stays the default. Because this is intricate, lean on the Step-1 equivalence test: it must pass bit-identically across a full randomized episode. (If a correct delta cache proves too error-prone for the time budget, the fallback is to leave the uncached path and instead reduce calls: compute the prior mask once per step and derive the full mask as `prior ∪ (full \ prior)` only when needed — a simpler 1.5× win rather than full delta caching.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rl_throughput.py tests/test_rlenv.py -v`
Expected: all pass (equivalence holds).

- [ ] **Step 6: Commit**

```bash
git add foeopt/rlenv.py tests/test_rl_throughput.py
git commit -m "perf(rlenv): delta-cached valid_actions (equivalence-tested) [if gate met]"
```
(If the gate said no, commit just the test scaffolding: `chore(rl): valid_actions profiling gate — not a bottleneck, no cache added`.)

---

## Task 8: Darkzig gate eval harness

The make-or-break test (spec §9, M4). A small `rl/gate.py` that loads a checkpoint, runs a greedy eval on `darkzig.json`, and prints the verdict against the 158 floor and the 114 Σ/2 target, plus the placement-quality metric (Rule 1/2 from `foeopt/quality.py`) as a secondary signal. This is the script you run after training to decide: keep training, push harder, or fail-fast to the 158 pipeline.

**Files:**
- Create: `rl/gate.py`
- Modify: `rl/ppo.py` (`evaluate` should also return the layout so quality can be computed — minimal change)
- Test: `tests/test_rl_gate.py` (new, on a tiny fixture)

**Interfaces:**
- Consumes: `rl.ppo.evaluate`, `foeopt.loader.load_layout`, `foeopt.quality.quality_report`, `foeopt.report.road_estimate`.
- Produces: `rl.gate.run_gate(ckpt, city_path, *, device="cpu", helper=None) -> dict` with keys `roads`, `status`, `target`, `floor` (158), `verdict` (`"beats_floor"` | `"competitive"` | `"stuck"` | `"unroutable"`), `quality`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rl_gate.py`:

```python
import torch

from rl.gate import run_gate


def test_gate_verdict_stuck_when_policy_cannot_place(tmp_path):
    # an untrained tiny policy on a tiny city -> likely stuck or high roads;
    # we only assert the verdict vocabulary and that roads/status are returned.
    from rl.policy import PlacementPolicy
    from foeopt.loader import load_layout
    layout = load_layout("city-user-data.json", "city-user-data-foe-helper.json")
    ckpt = tmp_path / "c.pt"
    torch.save({"state_dict": PlacementPolicy(hidden=64).state_dict(), "hidden": 64}, ckpt)
    r = run_gate(str(ckpt), "city-user-data.json", helper="city-user-data-foe-helper.json",
                 floor=158)
    assert r["status"] in ("ok", "stuck", "unroutable")
    assert r["verdict"] in ("beats_floor", "competitive", "stuck", "unroutable")
    assert r["floor"] == 158
    assert isinstance(r["target"], int)
    if r["status"] == "ok":
        assert isinstance(r["roads"], int)
        assert isinstance(r["quality"], dict)


def test_gate_beats_floor_when_roads_under_floor():
    # directly exercise the verdict logic with a stub result
    from rl.gate import _verdict
    assert _verdict(150, "ok", floor=158) == "beats_floor"   # <= floor
    assert _verdict(158, "ok", floor=158) == "beats_floor"   # at the floor
    assert _verdict(165, "ok", floor=158) == "competitive"   # above floor
    assert _verdict(None, "stuck", floor=158) == "stuck"
    assert _verdict(None, "unroutable", floor=158) == "unroutable"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_rl_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rl.gate'`.

- [ ] **Step 3: Make evaluate return the layout (minimal change)**

In `rl/ppo.py`, change `evaluate` so its terminal-success branch also exposes the placed layout. Replace the final two lines of `evaluate` (lines 97-98):

```python
        res = env.step(index_to_action(idx, W))
        obs = res.obs
    if res.info.get("roads") is not None:
        return res.info["roads"], res.info.get("error", "ok"), res.info.get("layout")
    return None, res.info.get("error", "ok"), None
```
And update the `@torch.no_grad()` `evaluate` to return a 3-tuple `(roads, status, layout)`. Update the two existing callers: `rl/eval.py` (use `roads, status, _ = evaluate(...)`) and the eval-print line in `rl/ppo.py`'s `train` (`r, st, _ = evaluate(...)`).

- [ ] **Step 4: Implement the gate harness**

Create `rl/gate.py`:

```python
"""The make-or-break gate (spec M4): does a trained policy beat the ~158
local-method floor on darkzig? Prints the verdict, the road count vs the
Sigma/2 target, and the placement-quality metric as a secondary signal.

  python -m rl.gate --ckpt rl_ckpt.pt --city darkzig.json
"""
from __future__ import annotations

import argparse

import torch

from rl.policy import PlacementPolicy
from rl.ppo import evaluate


def _verdict(roads, status, *, floor):
    if status == "unroutable":
        return "unroutable"
    if status == "stuck" or roads is None:
        return "stuck"
    if roads <= floor:
        return "beats_floor"
    return "competitive"      # above the floor but placed+routed — push further


def run_gate(ckpt: str, city_path: str, *, device: str = "cpu",
             helper: str | None = None, floor: int = 158) -> dict:
    from foeopt.loader import load_layout
    from foeopt.report import road_estimate
    from foeopt.quality import quality_report

    layout = load_layout(city_path, helper)
    ck = torch.load(ckpt, map_location=device)
    policy = PlacementPolicy(hidden=ck.get("hidden", 64)).to(device)
    policy.load_state_dict(ck["state_dict"])
    policy.eval()

    roads, status, placed = evaluate(policy, layout, device=device, greedy=True)
    quality = quality_report(placed) if placed is not None else {}
    target = road_estimate(layout)
    return {
        "roads": roads,
        "status": status,
        "target": target,
        "floor": floor,
        "verdict": _verdict(roads, status, floor=floor),
        "quality": quality,
    }


def main(argv=None):
    p = argparse.ArgumentParser(prog="rl.gate")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--city", required=True)
    p.add_argument("--helper", default=None)
    p.add_argument("--device", default="cpu")
    p.add_argument("--floor", type=int, default=158)
    args = p.parse_args(argv)
    r = run_gate(args.ckpt, args.city, device=args.device, helper=args.helper,
                 floor=args.floor)
    q = r["quality"]
    print(f"city={args.city} roads={r['roads']} status={r['status']} "
          f"target(Sigma/2)={r['target']} floor={r['floor']} verdict={r['verdict']}")
    if q:
        print(f"  quality: rule1={q['filler_road_adjacent']}/{q['fillers_total']} "
              f"rule2={q['underused_roads']}/{q['roads_total']}")
    print("  -> the bet pays off" if r["verdict"] == "beats_floor"
          else "  -> keep training earlier stages" if r["verdict"] == "stuck"
          else "  -> competitive; push further")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rl_gate.py tests/test_rlenv.py -v`
Expected: all pass. Then confirm the eval caller still works:
```bash
uv run python -c "
import torch
from rl.policy import PlacementPolicy
from rl.ppo import evaluate
from foeopt.loader import load_layout
torch.save({'state_dict': PlacementPolicy().state_dict(), 'hidden': 64}, '/tmp/_c.pt')
layout = load_layout('city-user-data.json', 'city-user-data-foe-helper.json')
pol = PlacementPolicy(); pol.load_state_dict(torch.load('/tmp/_c.pt')['state_dict'])
print(evaluate(pol, layout, device='cpu', greedy=True)[:2])
"
```
Expected: a `(None, 'stuck')` or `(N, 'ok')` 2-tuple (unpacking the first two of the 3-tuple).

- [ ] **Step 6: Commit**

```bash
git add rl/gate.py rl/ppo.py rl/eval.py tests/test_rl_gate.py
git commit -m "feat(rl): darkzig gate harness — beat-158 verdict + placement-quality signal"
```

---

## Task 9 (OPTIONAL): Tiny-instance optimal oracle for the M2/M3 principled baseline

The spec (§7, §9-M2) calls for a CP-SAT-optimal baseline on small roomy instances ("roads approach the CP-SAT-optimal baseline, not just 'beats random'"). CP-SAT (ortools) is deliberately NOT a repo dependency (lessons.md: prototyped via `uv run --with ortools`, never added). This task provides a **pure-stdlib branch-and-bound oracle** for *tiny* instances (≤4 non-Townhall buildings) so the M2/M3 signal has a principled target without any new dep. It is **optional** — the gate (M4) does not depend on it; the primary M2/M3 signal is success-rate → 100% + beating the random/greedy baselines (T5) + the Σ/2 target. Build it only if you want the stronger "vs optimal" comparison.

**Files:**
- Create: `rl/oracle.py`
- Test: `tests/test_rl_oracle.py` (new)

**Interfaces:**
- Produces: `rl.oracle.optimal_roads(layout, *, budget_s=30) -> int | None` — the minimum 0-unplaced road count over all placements, or `None` if it exceeds `budget_s`. Raises `ValueError` if the layout has >4 non-Townhall buildings (the oracle is only tractable on tiny instances).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rl_oracle.py`:

```python
from foeopt.model import Building, Footprint, Layout, Region
from rl.oracle import optimal_roads


def _layout(buildings):
    th = next(b for b in buildings if b.is_townhall)
    return Layout(Region(frozenset((x, y) for x in range(12) for y in range(12))),
                  buildings, th, {})


def _b(eid, w, l, needs=True, th=False):
    return Building(eid, f"c{eid}", "main_building" if th else "g",
                    Footprint(0, 0, w, l), needs_road=needs, road_level=1,
                    is_townhall=th, set_id=None, chain_id=None, name=f"b{eid}")


def test_oracle_finds_one_road_for_single_consumer_next_to_th():
    # TH 1x1 at (0,0); one 1x1 consumer -> optimum is 1 road.
    layout = _layout([_b(1, 1, 1, needs=False, th=True), _b(10, 1, 1, needs=True)])
    assert optimal_roads(layout) == 1


def test_oracle_matches_trivial_zero_when_no_road_needing():
    layout = _layout([_b(1, 1, 1, needs=False, th=True), _b(10, 2, 2, needs=False)])
    assert optimal_roads(layout) == 0      # no road-needing building -> 0 roads


def test_oracle_refuses_too_many_buildings():
    layout = _layout([_b(1, 1, 1, needs=False, th=True)] +
                    [_b(10 + i, 1, 1, needs=True) for i in range(5)])
    try:
        optimal_roads(layout)
        assert False, "should have raised for >4 non-TH buildings"
    except ValueError:
        pass
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rl_oracle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rl.oracle'`.

- [ ] **Step 3: Implement the branch-and-bound oracle**

Create `rl/oracle.py`:

```python
"""Pure-stdlib branch-and-bound oracle for TINY placement instances (<=4 non-TH
buildings). Gives the optimal 0-unplaced road count for the M2/M3 principled
baseline (spec ss7) without adding ortools as a dependency. Only tractable on
tiny instances; use the random/greedy baselines + the Sigma/2 target for larger
ones. Time-budgeted."""
from __future__ import annotations

import time

from foeopt.model import Building, Footprint, Layout
from foeopt.router import RouteError, route
from foeopt.validate import is_valid

_MAX_NON_TH = 4


def optimal_roads(layout: Layout, *, budget_s: float = 30.0) -> int | None:
    non_th = [b for b in layout.buildings if not b.is_townhall]
    if len(non_th) > _MAX_NON_TH:
        raise ValueError(f"oracle limited to <= {_MAX_NON_TH} non-TH buildings, got {len(non_th)}")
    th = layout.townhall
    order = sorted(non_th, key=lambda b: (-(b.footprint.width * b.footprint.length), b.entity_id))
    deadline = time.time() + budget_s
    best: list[int | None] = [None]
    _dfs(layout.region.cells, set(th.footprint.cells()), [th], layout, order, 0,
         best, deadline)
    return best[0]


def _dfs(region_cells, occ, placed, layout, order, ptr, best, deadline):
    if best[0] == 0:                 # can't beat 0 roads
        return
    if time.time() > deadline:
        return
    if ptr == len(order):
        trial = Layout(layout.region, placed, layout.townhall, {})
        try:
            roads = route(trial)
        except RouteError:
            return
        trial.roads = roads
        if not is_valid(trial):
            return
        n = len(roads)
        if best[0] is None or n < best[0]:
            best[0] = n
        return
    b = order[ptr]
    w, l = b.footprint.width, b.footprint.length
    free = region_cells - occ
    # branch on anchors adjacent to occupancy first (the prior) to find good layouts fast,
    # which makes the bound prune aggressively; fall back to all free if none adjacent.
    frontier = [(x, y) for (x, y) in free
                if any((x + dx, y + dy) in occ for dx in (0, w - 1) for dy in (0, l - 1))]
    candidates = frontier or list(free)
    for (x, y) in sorted(candidates):
        cells = Footprint(x, y, w, l).cells()
        if not cells <= free:
            continue
        from foeopt.model import Building as _B
        placed2 = placed + [_B(b.entity_id, b.cityentity_id, b.type,
                               Footprint(x, y, w, l), b.needs_road, b.road_level,
                               b.is_townhall, b.set_id, b.chain_id, b.name)]
        _dfs(region_cells, occ | cells, placed2, layout, order, ptr + 1, best, deadline)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rl_oracle.py -v`
Expected: all pass (the single-consumer optimum is 1; the no-road-needing optimum is 0; the 5-building case raises).

- [ ] **Step 5: Commit**

```bash
git add rl/oracle.py tests/test_rl_oracle.py
git commit -m "feat(rl): optional tiny-instance optimal oracle (M2/M3 principled baseline)"
```

---

## Validation / running the gate (after all tasks)

After implementing all tasks, the M2→M4 training + gate sequence on the GPU:

```bash
# 1. smoke (CPU, sanity): prior + shaping wired
uv run python -m rl.train --stage 0 --updates 5 --episodes 8 --device cpu --potential-shaping

# 2. M2/M3: train the synthetic curriculum on the GPU (auto-advance, prior anneals)
~/.venv/foe-rl-rocm/bin/python -m rl.train --auto --device cuda \
    --updates 3000 --episodes 64 --potential-shaping \
    --eval-city darkzig.json --ckpt rl_ckpt.pt

# 3. M4: fine-tune on darkzig-like synthesized cities (darkzig held out for eval)
~/.venv/foe-rl-rocm/bin/python -m rl.train --auto --device cuda \
    --updates 2000 --episodes 64 --potential-shaping \
    --ref-city darkzig.json --eval-city darkzig.json --resume rl_ckpt.pt --ckpt rl_ckpt.pt

# 4. the gate
~/.venv/foe-rl-rocm/bin/python -m rl.gate --ckpt rl_ckpt.pt --city darkzig.json --device cuda
```

**Interpreting the gate (spec §9 M4):**
- `verdict=beats_floor` (roads ≤ 158, status=ok) — the bet pays off. Push further (more updates, tune `--prior-strength-floor`, consider the deferred imitation warm-start to push past 158).
- `verdict=competitive` (140s–150s) — close; keep training / lower the prior floor.
- `verdict=stuck`/`unroutable` — can't place everything yet; keep training earlier curriculum stages, raise `--placement-reward`, strengthen the prior (`--prior-strength-start 1.0`). If it stays stuck after substantial training, escalate to the deferred **imitation warm-start** (spec §4.4); if that also fails, fail-fast to productionizing the existing 158 pipeline.

## Deferred (explicitly out of scope for this plan)

- **M5 generalization:** train across a *distribution* of real cities for instant inference on unseen cities (needs multiple real-city references + a held-out eval set).
- **AlphaZero-style MCTS + policy/value:** the ambitious escalation; reconsider only if PPO clears the gate and we want to push well past 158.
- **Imitation warm-start:** pretrain to imitate `repack`/`polish` + CP-SAT optima. Design-for (the env/trajectory format supports it); build only if PPO proves too sample-hungry to clear the gate — it is the gate-failure rescue lever.
- **Building-order policy:** the agent currently picks WHERE, not WHICH (order is fixed largest-area first). Making order part of the policy is a natural future extension.
