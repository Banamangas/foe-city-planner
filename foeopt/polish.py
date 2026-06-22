from __future__ import annotations

from foeopt.anneal import anneal
from foeopt.model import Layout
from foeopt.packer import PackResult, repack
from foeopt.router import route


def polish(layout: Layout, *, repack_budget: float, anneal_budget: float,
           seed: int = 0) -> PackResult:
    """Re-pack, then refine with annealing (building-move SA).

    Anneal never drops a building and never accepts a worse-than-best layout, so
    the result has the same `unplaced` as the repack base and roads <= the base.
    """
    base = repack(layout, budget_seconds=repack_budget, seed=seed)
    refined = anneal(base.layout, budget_seconds=anneal_budget, seed=seed)
    final = Layout(layout.region, refined.layout.buildings,
                   refined.layout.townhall, route(refined.layout))
    return PackResult(layout=final, unplaced=base.unplaced, trials=base.trials)
