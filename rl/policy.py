"""Fully-convolutional placement policy + value head. Input [B, C, H, W]; the
policy head emits one logit per grid cell (a pointer over anchors), the value
head a scalar. Fully-conv => the same weights work on any grid size."""
from __future__ import annotations

import torch
import torch.nn as nn

from rl.encode import NUM_CHANNELS


class PlacementPolicy(nn.Module):
    def __init__(self, in_ch: int = NUM_CHANNELS, hidden: int = 64, blocks: int = 4):
        super().__init__()
        layers: list[nn.Module] = [nn.Conv2d(in_ch, hidden, 3, padding=1), nn.ReLU()]
        for _ in range(blocks - 1):
            layers += [nn.Conv2d(hidden, hidden, 3, padding=1), nn.ReLU()]
        self.body = nn.Sequential(*layers)
        self.policy_head = nn.Conv2d(hidden, 1, 1)
        self.value_head = nn.Sequential(
            nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(hidden, 1)
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.body(x)
        logits = self.policy_head(h).flatten(1)   # [B, H*W]
        value = self.value_head(h).squeeze(-1)    # [B]
        return logits, value


def masked_dist(logits: torch.Tensor, mask: torch.Tensor) -> torch.distributions.Categorical:
    """Categorical over anchors with illegal cells masked out."""
    neg = torch.finfo(logits.dtype).min
    masked = torch.where(mask, logits, torch.full_like(logits, neg))
    return torch.distributions.Categorical(logits=masked)
