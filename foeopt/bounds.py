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


# --- Instance screening (heuristic, NOT bounds) -----------------------------
# Everything above is a provable bound. What follows is a measured *screen*: it
# predicts whether the roads-first search is likely to find anything on a city,
# so a caller can decline in microseconds instead of burning hours. It carries
# no proof and must never be used to reject a city silently -- report it.

def road_pressure(layout: Layout) -> float:
    """`sigma_half / slack` — the roads a city NEEDS over the free cells it HAS.

    slack      = region_cells - building_area  (every cell roads could occupy)
    sigma_half = sum(min(w, l) for road-needing consumers) / 2

    **Heuristic, not a bound.** `sigma_half` is an estimate that real layouts
    beat (darkzig 94 vs 114, FR16 76 vs 88 — both ~120% efficiency), so this
    over-states the requirement; and `slack` is the budget roads compete for
    with nothing else. The ratio is what separates the cities measured so far:

        city     fill%  slack  consumers  sigma/2  pressure  outcome
        darkzig  89.6%    283         63      114      0.40  97.9% SAT, record 94
        FR16     83.3%    206         56       88      0.43  49.6% SAT, record 76
        FR24     90.2%    268        146      238      0.89  0 SAT / 135 probes

    Note darkzig and FR24 have nearly identical *fill* (89.6 vs 90.2%) and
    region size (2720 vs 2736) and opposite outcomes — fill does not
    discriminate, this ratio does. Returns `inf` when slack <= 0 (that case is
    genuinely infeasible by area accounting, which IS provable).
    """
    region_cells = len(layout.region.cells)
    building_area = sum(b.footprint.width * b.footprint.length
                        for b in layout.buildings)
    slack = region_cells - building_area
    if slack <= 0:
        return float("inf")
    sigma_half = sum(min(b.footprint.width, b.footprint.length)
                     for b in layout.road_needing()) / 2.0
    return sigma_half / slack


def screen_city(layout: Layout) -> dict:
    """Cheap go/no-go on whether roads-first is worth running on this city.

    **Calibrated on n=3 cities and confounded**: FR24 has both high pressure
    (0.89) and 2.3x the consumers of the cities that work, and probe time scales
    36s -> 95s -> 301s with consumer count, which points at CP-SAT model size
    rather than packing. Both explanations predict the same failure there, and
    three cities cannot separate them. Treat `verdict` as advice to report to a
    user, never as grounds to refuse silently.
    """
    pressure = road_pressure(layout)
    n_cons = len(layout.road_needing())
    region_cells = len(layout.region.cells)
    building_area = sum(b.footprint.width * b.footprint.length
                        for b in layout.buildings)
    slack = region_cells - building_area

    if slack <= 0:
        verdict, reason = "INFEASIBLE", "buildings already exceed the region area"
    elif pressure >= 0.8:
        verdict = "UNLIKELY"
        reason = (f"road pressure {pressure:.2f}: the road network needs ~"
                  f"{pressure:.0%} of the free cells, leaving almost no room to "
                  f"pack around it (measured 0 SAT / 135 probes at 0.89)")
    elif pressure <= 0.5 and n_cons <= 90:
        verdict = "LIKELY"
        reason = (f"road pressure {pressure:.2f} and {n_cons} consumers, both "
                  "inside the range where every measured city succeeded")
    else:
        verdict = "UNCERTAIN"
        reason = (f"road pressure {pressure:.2f}, {n_cons} consumers — outside "
                  "the measured range (pressure 0.40-0.43 / 56-63 consumers "
                  "succeeded; 0.89 / 146 did not)")
    return {"road_pressure": round(pressure, 3), "consumers": n_cons,
            "slack": slack, "region_cells": region_cells,
            "building_area": building_area, "verdict": verdict, "reason": reason}
