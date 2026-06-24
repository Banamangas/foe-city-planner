"""Encode a PlacementEnv observation into a grid tensor, and build the action
mask. Action = an (x, y) anchor; we flatten the HxW grid as index = y*W + x."""
from __future__ import annotations

import numpy as np
import torch

from foeopt.rlenv import Obs, PlacementEnv

NUM_CHANNELS = 5
_MAX_SIZE = 8.0   # normaliser for building w/l


def grid_bounds(region) -> tuple[int, int]:
    xs = [c[0] for c in region]
    ys = [c[1] for c in region]
    return max(xs) + 1, max(ys) + 1   # (W, H)


def encode_obs(obs: Obs, W: int, H: int) -> torch.Tensor:
    """[C, H, W] float tensor: region mask, occupancy, current w/l planes, needs-road."""
    g = np.zeros((NUM_CHANNELS, H, W), dtype=np.float32)
    for (x, y) in obs.region:
        g[0, y, x] = 1.0
    for (x, y) in obs.occupied:
        g[1, y, x] = 1.0
    if obs.current_size is not None:
        w, l = obs.current_size
        g[2, :, :] = w / _MAX_SIZE
        g[3, :, :] = l / _MAX_SIZE
        g[4, :, :] = 1.0 if obs.current_needs_road else 0.0
    return torch.from_numpy(g)


def action_mask(env: PlacementEnv, W: int, H: int) -> torch.Tensor:
    """Boolean [H*W]: True where the current building may anchor."""
    m = np.zeros(H * W, dtype=bool)
    for (x, y) in env.valid_actions():
        m[y * W + x] = True
    return torch.from_numpy(m)


def index_to_action(idx: int, W: int) -> tuple[int, int]:
    return (idx % W, idx // W)
