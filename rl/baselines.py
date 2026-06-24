"""Non-learned baselines for the placement env: uniform-random and myopic
compact-clustering-greedy rollouts. Used to validate that a trained policy
actually learns (M2/M3 signal) and as a fallback comparison."""
from __future__ import annotations

import random

from foeopt.model import Footprint, Layout
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
    """Myopic greedy: pick the anchor whose footprint border overlaps the most
    with existing occupancy (compact placement -> route-cheap double-rows).
    Ties -> first."""
    env = PlacementEnv(layout)

    def choose(valid, e):
        best, best_score = valid[0], -1
        for (x, y) in valid:
            b = e.current
            fp = Footprint(x, y, b.footprint.width, b.footprint.length)
            score = len(fp.border_cells() & e._occ)
            if score > best_score:
                best, best_score = (x, y), score
        return best

    return _run(env, choose)
