"""Provable, placement-independent lower bounds on the road count.

Buildings are movable, so any bound here must hold over ALL feasible
placements — border-based arguments from a specific layout do not qualify.
That makes honest bounds weak (see the 2026-07-02 calibration spec): their
role is to anchor the bottom of the target band, not to be tight. Anything
added here needs an airtight argument in its docstring and a test proving
bound <= a known optimum/achievable value.
"""
from __future__ import annotations

import math

from foeopt.model import Layout


def bound_adjacency(layout: Layout) -> int:
    """roads >= ceil(n_consumers / 3): a road cell has 4 orthogonal
    neighbours, and in any connected network of >= 2 cells (or a 1-cell
    network, which must touch the Townhall border) at least one neighbour is
    a road or the Townhall — so a single road cell serves at most 3
    road-needing buildings."""
    return math.ceil(len(layout.road_needing()) / 3)


def report_bounds(layout: Layout) -> dict[str, int]:
    """All provable bounds plus their max (the usable combined bound)."""
    bounds = {"adjacency": bound_adjacency(layout)}
    bounds["max"] = max(bounds.values())
    return bounds
