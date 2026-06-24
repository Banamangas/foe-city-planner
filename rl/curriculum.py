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


def make_real_like_city(rng: random.Random, reference: Layout, *, fill: float = 0.9) -> Layout:
    """A darkzig-like training city: the reference's irregular region + Townhall
    (same position/size), with buildings sampled from the reference's (w,l,needs_road)
    mix to ~`fill` of the region area. Non-TH buildings sit at (0,0); the env
    repositions them during placement. The reference itself (e.g. darkzig.json) is
    held out for eval — only these synthesized variants are trained on."""
    region = reference.region
    th = reference.townhall
    th_area = th.footprint.width * th.footprint.length
    pool = [(b.footprint.width, b.footprint.length, b.needs_road)
            for b in reference.buildings if not b.is_townhall]
    target_area = int(fill * len(region.cells)) - th_area
    blds = [th]
    area, eid = 0, 1000
    while area < target_area and pool:
        w, l, needs = rng.choice(pool)
        blds.append(Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l),
                             needs_road=needs, road_level=1, is_townhall=False,
                             set_id=None, chain_id=None, name=f"b{eid}"))
        area += w * l
        eid += 1
    return Layout(region, blds, th, {})
