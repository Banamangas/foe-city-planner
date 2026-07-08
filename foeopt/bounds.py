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


def pick_k_start(layout: Layout) -> int:
    """City-aware k_start for the roads-first k-walk.

    k_start = min(k_max, ceil(sigma_half) + 8) where:
      k_max      = region_cells - building_area  (hard area ceiling; above it
                   no placement is possible by simple area accounting)
      sigma_half = sum(min(w, l) for each road-needing consumer) / 2
                   (the 100%-efficiency anchor; optima sit at or below it via
                   stubs/junctions serving 3 buildings per road cell)

    Margin 8 keeps the first probe almost always feasible for the comb family
    while skipping the slack above sigma_half. If sigma_half + 8 is infeasible
    the upward fallback walks up (capped at k_max). Never exceeds k_max.

    Not a bound -- a starting guess. The walk-down stops at the first
    INCONCLUSIVE/INFEASIBLE level, as today (bound_adjacency is unreachable
    in practice and is not used as a stop signal)."""
    region_cells = len(layout.region.cells)
    building_area = sum(b.footprint.width * b.footprint.length for b in layout.buildings)
    k_max = region_cells - building_area
    sigma_half = sum(min(b.footprint.width, b.footprint.length)
                     for b in layout.road_needing()) / 2
    return min(k_max, math.ceil(sigma_half) + 8)
