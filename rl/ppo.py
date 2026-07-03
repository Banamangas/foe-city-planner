"""Masked PPO for the placement environment. Self-contained: rollout collection,
GAE, the clipped update, the training loop, and a greedy evaluator.

This code is structurally smoke-tested on CPU (one update step runs) but has NOT
been trained to convergence here — that needs a GPU and many hours. See README.md.
"""
from __future__ import annotations

import random

import torch

from foeopt.report import road_estimate
from foeopt.rlenv import PlacementEnv
from rl import curriculum
from rl.encode import action_mask, encode_obs, grid_bounds, index_to_action
from rl.policy import PlacementPolicy, masked_dist


def prior_strength_for_success(success_rate: float, *, start: float = 1.0,
                               strict_below: float = 0.5, floor: float = 0.2) -> float:
    """Anneal the action-prior strength from strict (``start``) while the policy is
    failing toward ``floor`` as success -> 1.0. Strict below ``strict_below``;
    linear relaxation above it. Keeps ``floor`` exploration off-prior so the
    policy can escape the grow-tree prior (which re-caps at ~158)."""
    if success_rate <= strict_below:
        return start
    t = (success_rate - strict_below) / (1.0 - strict_below)   # 0..1
    return max(floor, start - t * (start - floor))


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


def gae(trans, gamma=0.99, lam=0.95):
    adv, next_value = 0.0, 0.0          # terminal bootstrap = 0
    for t in reversed(range(len(trans))):
        r, v = trans[t]["reward"], trans[t]["value"]
        delta = r + gamma * next_value - v
        adv = delta + gamma * lam * adv
        trans[t]["adv"] = adv
        trans[t]["ret"] = adv + v
        next_value = v


def ppo_update(policy, opt, batch, *, clip=0.2, epochs=4, vf=0.5, ent=0.01, device="cpu"):
    X = torch.stack([b["x"] for b in batch]).to(device)
    masks = torch.stack([b["mask"] for b in batch]).to(device)
    actions = torch.tensor([b["action"] for b in batch], device=device)
    old_logp = torch.tensor([b["logp"] for b in batch], device=device)
    returns = torch.tensor([b["ret"] for b in batch], device=device)
    advs = torch.tensor([b["adv"] for b in batch], device=device)
    advs = (advs - advs.mean()) / (advs.std() + 1e-8)
    stats = {}
    for _ in range(epochs):
        logits, values = policy(X)
        dist = masked_dist(logits, masks)
        logp = dist.log_prob(actions)
        ratio = torch.exp(logp - old_logp)
        surr = torch.min(ratio * advs, torch.clamp(ratio, 1 - clip, 1 + clip) * advs)
        pol_loss = -surr.mean()
        val_loss = ((values - returns) ** 2).mean()
        ent_loss = dist.entropy().mean()
        loss = pol_loss + vf * val_loss - ent * ent_loss
        opt.zero_grad(); loss.backward(); opt.step()
        stats = {"pol": round(pol_loss.item(), 4), "val": round(val_loss.item(), 2),
                 "ent": round(ent_loss.item(), 3)}
    return stats


@torch.no_grad()
def evaluate(policy, layout, device="cpu", greedy=True):
    """Roll out the policy on a fixed layout; return (roads or None, status, layout or None)."""
    W, H = grid_bounds(layout.region.cells)
    env = PlacementEnv(layout)
    obs = env.reset()
    while not env.done:
        mask = action_mask(env, W, H).to(device)
        if not bool(mask.any()):
            return None, "stuck", None
        logits, _ = policy(encode_obs(obs, W, H).unsqueeze(0).to(device))
        dist = masked_dist(logits, mask.unsqueeze(0))
        idx = int(dist.probs.argmax(-1).item() if greedy else dist.sample().item())
        res = env.step(index_to_action(idx, W))
        obs = res.obs
    if res.info.get("roads") is not None:
        return res.info["roads"], res.info.get("error", "ok"), res.info.get("layout")
    return None, res.info.get("error", "ok"), None


def train(*, stage=0, updates=200, episodes_per_update=16, lr=3e-4, device="cpu",
          seed=0, ckpt="rl_ckpt.pt", placement_reward=0.1, hidden=64,
          eval_layout=None, resume=None, auto=False, advance_success=0.9,
          advance_patience=20, prior_strength_start=0.95, prior_strength_floor=0.2,
          potential_shaping=False, ref_layout=None, fill=0.9, log=print):
    rng = random.Random(seed)
    torch.manual_seed(seed)
    policy = PlacementPolicy(hidden=hidden).to(device)
    if resume:
        policy.load_state_dict(torch.load(resume, map_location=device)["state_dict"])
        log(f"resumed from {resume}")
    opt = torch.optim.Adam(policy.parameters(), lr=lr)
    last = len(curriculum.STAGES) - 1
    stages = list(range(stage, last + 1)) if auto else [stage]
    for stg in stages:
        mastered = 0
        succ_prev = 0.0
        for upd in range(updates):
            batch, roads, successes, target = [], [], 0, None
            for _ in range(episodes_per_update):
                if ref_layout is not None and stg >= last:
                    city = curriculum.make_real_like_city(rng, ref_layout, fill=fill)
                else:
                    city = curriculum.make_city(stg, rng)
                W, H = grid_bounds(city.region.cells)
                target = road_estimate(city)
                env = PlacementEnv(city, placement_reward=placement_reward,
                                   potential_shaping=potential_shaping)
                trans, info = collect_episode(
                    env, policy, W, H, device,
                    prior_strength=prior_strength_for_success(
                        succ_prev, start=prior_strength_start,
                        floor=prior_strength_floor),
                    rng=rng)
                if not trans:
                    continue
                gae(trans)
                batch.extend(trans)
                if info.get("roads") is not None:
                    roads.append(info["roads"]); successes += 1
            succ = successes / episodes_per_update
            succ_prev = succ
            stats = ppo_update(policy, opt, batch, device=device) if batch else {}
            mean_roads = round(sum(roads) / len(roads), 1) if roads else None
            log(f"stage {stg} upd {upd:4d} | success {succ:5.0%} | mean_roads {mean_roads} "
                f"(target ~{target}) | {stats}")
            torch.save({"state_dict": policy.state_dict(), "hidden": hidden, "stage": stg}, ckpt)
            if eval_layout is not None and upd % 10 == 0:
                r, st, _ = evaluate(policy, eval_layout, device)
                log(f"     eval: roads={r} ({st})")
            if auto:
                mastered = mastered + 1 if succ >= advance_success else 0
                if mastered >= advance_patience and stg < last:
                    log(f"  -> stage {stg} mastered, advancing")
                    break
    return policy
