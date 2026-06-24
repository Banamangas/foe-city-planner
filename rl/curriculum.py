"""Synthetic city generator, easy → hard. A fixed grid size per stage so episodes
within a stage batch together. Buildings start at (0,0); the env assigns positions
during placement. The curriculum is how a policy escapes the −100 "all unroutable"
trap on dense cities (start roomy, ramp density/size/diversity)."""
from __future__ import annotations

import random

from foeopt.model import Building, Footprint, Layout, Region

# (grid side, #consumers, #fillers, building-size pool)
STAGES = [
    (10,  4,  2, [(2, 2), (2, 3), (3, 2)]),
    (12,  6,  3, [(2, 2), (2, 3), (3, 2), (3, 3)]),
    (16, 10,  5, [(2, 2), (2, 3), (3, 2), (3, 3), (4, 3), (3, 4)]),
    (20, 16,  8, [(2, 2), (2, 3), (3, 2), (3, 3), (4, 3), (3, 4), (4, 4)]),
    (26, 24, 12, [(2, 2), (2, 3), (3, 2), (3, 3), (4, 3), (3, 4), (4, 4), (6, 4)]),
]


def make_city(stage: int, rng: random.Random) -> Layout:
    side, nc, nf, pool = STAGES[min(stage, len(STAGES) - 1)]
    th = Building(1, "c1", "main_building", Footprint(0, 0, 2, 2),
                  False, 1, True, None, None, "TH")
    blds = [th]
    eid = 10
    for needs, count in ((True, nc), (False, nf)):
        for _ in range(count):
            w, l = rng.choice(pool)
            blds.append(Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l),
                                 needs, 1, False, None, None, f"b{eid}"))
            eid += 1
    region = Region(frozenset((x, y) for x in range(side) for y in range(side)))
    return Layout(region, blds, th, {})
