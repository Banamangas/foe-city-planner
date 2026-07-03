"""Imitation warm-start: extract expert trajectories from repack/polish outputs
and behavioral-clone the placement policy to imitate them. This teaches the
policy road-efficient double-row arrangement (what RL can't learn from the
sparse terminal reward) before RL fine-tuning.

Pipeline:
  1. Generate cities (synthetic curriculum or darkzig-like via ref-city)
  2. Run repack on each → expert layout (road-efficient, 0-unplaced)
  3. Extract trajectory: for each building in env order, look up its anchor in
     the expert layout → (obs, expert_action) pairs
  4. Train the policy with cross-entropy loss to predict expert actions
  5. Save the checkpoint for RL fine-tuning

  python -m rl.imitate --ref-city darkzig.json --fill 0.3 --episodes 20 --ckpt rl_ckpt.pt
  python -m rl.imitate --stage 0 --episodes 20 --ckpt rl_ckpt.pt
"""
from __future__ import annotations

import argparse
import random

import torch
import torch.nn.functional as F

from foeopt.loader import load_layout
from foeopt.packer import repack
from foeopt.report import road_estimate
from foeopt.rlenv import PlacementEnv
from rl import curriculum
from rl.encode import action_mask, encode_obs, grid_bounds, index_to_action
from rl.policy import PlacementPolicy


def extract_expert_trajectory(layout, expert_layout, *, placement_reward=0.0):
    """Step the env through the expert's placements, recording (obs, action) pairs.
    The env is built from the EXPERT layout (TH at the expert's position, other
    buildings reset to (0,0)) so expert anchors are valid. Returns a list of
    {x, mask, action} dicts, or None if the expert placement is invalid."""
    from foeopt.model import Building, Footprint, Layout, Region
    th = expert_layout.townhall
    blds = [th] + [
        Building(b.entity_id, b.cityentity_id, b.type, Footprint(0, 0, b.footprint.width, b.footprint.length),
                 b.needs_road, b.road_level, False, b.set_id, b.chain_id, b.name)
        for b in expert_layout.buildings if not b.is_townhall
    ]
    env_layout = Layout(expert_layout.region, blds, th, {})
    env = PlacementEnv(env_layout, placement_reward=placement_reward)
    W, H = grid_bounds(env_layout.region.cells)
    expert_pos = {b.entity_id: (b.footprint.x, b.footprint.y)
                  for b in expert_layout.buildings if not b.is_townhall}
    obs = env.reset()
    trans = []
    while not env.done:
        b = env.current
        expert_anchor = expert_pos.get(b.entity_id)
        if expert_anchor is None:
            return None
        valid = set(env.valid_actions())
        if expert_anchor not in valid:
            return None
        x = encode_obs(obs, W, H)
        m = action_mask(env, W, H)
        idx = expert_anchor[1] * W + expert_anchor[0]
        trans.append({"x": x, "mask": m, "action": idx})
        res = env.step(expert_anchor)
        if res.done and res.info.get("error"):
            return None
        obs = res.obs
    return trans


def generate_expert_data(*, stage=None, ref_layout=None, fill=0.9, n_cities=20,
                         repack_budget=10.0, seed=0, log=print):
    """Generate expert trajectories by running repack on curriculum or ref cities."""
    rng = random.Random(seed)
    all_trans = []
    cities_generated = 0
    experts_valid = 0
    for i in range(n_cities):
        if ref_layout is not None:
            city = curriculum.make_real_like_city(rng, ref_layout, fill=fill)
        else:
            city = curriculum.make_city(stage or 0, rng)
        cities_generated += 1
        res = repack(city, budget_seconds=repack_budget, seed=rng.randrange(2**32))
        if res.unplaced:
            log(f"  city {i}: repack left {len(res.unplaced)} unplaced, skipping")
            continue
        trans = extract_expert_trajectory(city, res.layout)
        if trans is None:
            log(f"  city {i}: expert trajectory invalid, skipping")
            continue
        n_roads = len(res.layout.roads)
        target = road_estimate(city)
        all_trans.extend(trans)
        experts_valid += 1
        log(f"  city {i}: {len(trans)} steps, roads={n_roads} (target ~{target})")
    log(f"generated {len(all_trans)} expert transitions from {experts_valid}/{cities_generated} cities")
    return all_trans


def behavioral_clone(policy, trans, *, device="cpu", epochs=30, lr=1e-3, log=print):
    """Train the policy with cross-entropy loss to imitate expert actions."""
    opt = torch.optim.Adam(policy.parameters(), lr=lr)
    X = torch.stack([t["x"] for t in trans]).to(device)
    masks = torch.stack([t["mask"] for t in trans]).to(device)
    actions = torch.tensor([t["action"] for t in trans], device=device)
    for epoch in range(epochs):
        perm = torch.randperm(len(trans))
        total_loss, correct, n = 0.0, 0, 0
        batch_size = min(256, len(trans))
        for start in range(0, len(trans), batch_size):
            idx = perm[start:start + batch_size]
            xb, mb, ab = X[idx], masks[idx], actions[idx]
            logits, _ = policy(xb)
            neg = torch.finfo(logits.dtype).min
            masked = torch.where(mb, logits, torch.full_like(logits, neg))
            log_probs = F.log_softmax(masked, dim=-1)
            loss = F.nll_loss(log_probs, ab)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += loss.item() * len(idx)
            pred = masked.argmax(dim=-1)
            correct += (pred == ab).sum().item()
            n += len(idx)
        log(f"  bc epoch {epoch:3d} | loss {total_loss/n:.4f} | acc {correct/n:.1%}")
    return policy


def imitate(*, stage=None, ref_city=None, ref_helper=None, fill=0.9,
            n_cities=20, repack_budget=10.0, epochs=30, lr=1e-3,
            device="cpu", hidden=64, resume=None, ckpt="rl_ckpt.pt",
            seed=0, log=print):
    """Generate expert trajectories and behavioral-clone the policy."""
    ref_layout = None
    if ref_city:
        ref_layout = load_layout(ref_city, ref_helper)
    trans = generate_expert_data(stage=stage, ref_layout=ref_layout, fill=fill,
                                 n_cities=n_cities, repack_budget=repack_budget,
                                 seed=seed, log=log)
    if not trans:
        log("no expert trajectories generated — nothing to imitate")
        return
    policy = PlacementPolicy(hidden=hidden).to(device)
    if resume:
        policy.load_state_dict(torch.load(resume, map_location=device)["state_dict"])
        log(f"resumed from {resume}")
    behavioral_clone(policy, trans, device=device, epochs=epochs, lr=lr, log=log)
    torch.save({"state_dict": policy.state_dict(), "hidden": hidden}, ckpt)
    log(f"saved pretrained checkpoint to {ckpt}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="rl.imitate")
    p.add_argument("--stage", type=int, default=None, help="curriculum stage (synthetic)")
    p.add_argument("--ref-city", default=None, help="real city for darkzig-like synthesis")
    p.add_argument("--ref-helper", default=None)
    p.add_argument("--fill", type=float, default=0.9, help="fill ratio for ref-city synthesis")
    p.add_argument("--n-cities", type=int, default=20, help="number of expert cities to generate")
    p.add_argument("--repack-budget", type=float, default=10.0, help="seconds per repack")
    p.add_argument("--epochs", type=int, default=30, help="behavioral cloning epochs")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--device", default="cpu")
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--resume", default=None, help="checkpoint to warm-start from")
    p.add_argument("--ckpt", default="rl_ckpt.pt")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)
    imitate(stage=args.stage, ref_city=args.ref_city, ref_helper=args.ref_helper,
            fill=args.fill, n_cities=args.n_cities, repack_budget=args.repack_budget,
            epochs=args.epochs, lr=args.lr, device=args.device, hidden=args.hidden,
            resume=args.resume, ckpt=args.ckpt, seed=args.seed)


if __name__ == "__main__":
    main()
