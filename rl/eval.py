"""Play a trained checkpoint on a city and report the road count.

  python -m rl.eval --ckpt rl_ckpt.pt --city darkzig.json
"""
from __future__ import annotations

import argparse

import torch

from rl.policy import PlacementPolicy
from rl.ppo import evaluate


def main(argv=None):
    p = argparse.ArgumentParser(prog="rl.eval")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--city", required=True)
    p.add_argument("--helper", default=None)
    p.add_argument("--device", default="cpu")
    p.add_argument("--sample", action="store_true", help="sample instead of greedy argmax")
    args = p.parse_args(argv)

    from foeopt.loader import load_layout
    from foeopt.report import road_estimate
    layout = load_layout(args.city, args.helper)

    ck = torch.load(args.ckpt, map_location=args.device)
    policy = PlacementPolicy(hidden=ck.get("hidden", 64)).to(args.device)
    policy.load_state_dict(ck["state_dict"])
    policy.eval()

    roads, status = evaluate(policy, layout, device=args.device, greedy=not args.sample)
    print(f"city={args.city} roads={roads} status={status} "
          f"target(Sigma/2)={road_estimate(layout)}")


if __name__ == "__main__":
    main()
