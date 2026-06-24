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
