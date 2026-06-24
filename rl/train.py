"""Train the placement policy with PPO on the curriculum.

Examples:
  # smoke test on CPU (fast, won't learn much):
  python -m rl.train --stage 0 --updates 5 --episodes 8 --device cpu
  # real run on GPU, with periodic eval on your real city:
  python -m rl.train --stage 0 --updates 2000 --device cuda --eval-city darkzig.json
"""
from __future__ import annotations

import argparse

from rl.ppo import train


def main(argv=None):
    p = argparse.ArgumentParser(prog="rl.train")
    p.add_argument("--stage", type=int, default=0, help="curriculum stage (0=easiest)")
    p.add_argument("--updates", type=int, default=500)
    p.add_argument("--episodes", type=int, default=16, help="episodes per PPO update")
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--device", default="cpu", help='"cpu" or "cuda"')
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--ckpt", default="rl_ckpt.pt")
    p.add_argument("--placement-reward", type=float, default=0.1,
                   help="dense shaping bonus per placed building (escapes the -100 trap)")
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--eval-city", default=None,
                   help="city json to greedily eval every 10 updates (e.g. darkzig.json)")
    p.add_argument("--eval-helper", default=None)
    p.add_argument("--resume", default=None, help="checkpoint to warm-start from")
    p.add_argument("--auto", action="store_true",
                   help="auto-advance the curriculum (stage..last) as each is mastered")
    args = p.parse_args(argv)

    eval_layout = None
    if args.eval_city:
        from foeopt.loader import load_layout
        eval_layout = load_layout(args.eval_city, args.eval_helper)

    train(stage=args.stage, updates=args.updates, episodes_per_update=args.episodes,
          lr=args.lr, device=args.device, seed=args.seed, ckpt=args.ckpt,
          placement_reward=args.placement_reward, hidden=args.hidden,
          eval_layout=eval_layout, resume=args.resume, auto=args.auto)


if __name__ == "__main__":
    main()
