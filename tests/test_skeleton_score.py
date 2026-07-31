"""SkeletonScorer must agree EXACTLY with the reference it accelerates.

`foeopt.skeleton_score` reimplements `roads_first._anchor_candidates`'s counting
with bitmask arithmetic. The bar is oracle equivalence on adversarial shapes --
the `reach.py` discipline (a fast path that disagrees with its own oracle is
worse than no fast path, because the disagreement is silent).
"""
from __future__ import annotations

import random

from foeopt.model import Building, Footprint
from foeopt.roads_first import _anchor_candidates, generate_lane_patterns
from foeopt.skeleton_score import SkeletonScorer


def _consumer(eid: int, w: int, l: int) -> Building:
    return Building(eid, f"c{eid}", "g", Footprint(0, 0, w, l),
                    True, 1, False, None, None, f"b{eid}")


def _oracle(region, consumers, th, roads) -> int:
    blocked = set(roads) | set(th.cells())
    return sum(len(_anchor_candidates(b, region, blocked, roads)) for b in consumers)


def test_matches_oracle_on_square_region():
    region = {(x, y) for x in range(12) for y in range(12)}
    consumers = [_consumer(10, 2, 2), _consumer(11, 3, 2), _consumer(12, 2, 4)]
    th = Footprint(0, 0, 2, 2)
    roads = frozenset({(2, 0), (2, 1), (2, 2), (3, 2), (4, 2)})
    scorer = SkeletonScorer(region, consumers)
    assert scorer.opts_total(th, roads) == _oracle(region, consumers, th, roads)


def test_matches_oracle_on_offset_and_holey_region():
    """Region not anchored at the origin and with interior holes -- catches
    bbox-offset and free-vs-region confusion, the two ways bitmask indexing
    goes wrong."""
    region = {(x, y) for x in range(7, 25) for y in range(13, 30)}
    region -= {(12, 18), (13, 18), (12, 19), (20, 25), (21, 25)}
    consumers = [_consumer(10, 2, 3), _consumer(11, 4, 4), _consumer(12, 1, 1),
                 _consumer(13, 5, 2), _consumer(14, 2, 3)]
    th = Footprint(8, 14, 3, 2)
    roads = frozenset({(11, 14), (11, 15), (11, 16), (11, 17),
                       (12, 17), (13, 17), (14, 17), (15, 17)})
    scorer = SkeletonScorer(region, consumers)
    assert scorer.opts_total(th, roads) == _oracle(region, consumers, th, roads)


def test_matches_oracle_on_random_regions_and_skeletons():
    rng = random.Random(7)
    for trial in range(40):
        ox, oy = rng.randrange(0, 9), rng.randrange(0, 9)
        w, h = rng.randrange(8, 18), rng.randrange(8, 18)
        region = {(ox + x, oy + y) for x in range(w) for y in range(h)}
        for _ in range(rng.randrange(0, 12)):        # punch holes
            region.discard((ox + rng.randrange(w), oy + rng.randrange(h)))
        if not region:
            continue
        consumers = [_consumer(100 + i, rng.randrange(1, 5), rng.randrange(1, 5))
                     for i in range(rng.randrange(1, 6))]
        th = Footprint(ox, oy, 2, 2)
        if not th.cells() <= region:
            continue
        cells = sorted(region - th.cells())
        if not cells:
            continue
        roads = frozenset(rng.sample(cells, min(len(cells), rng.randrange(1, 14))))
        scorer = SkeletonScorer(region, consumers)
        assert scorer.opts_total(th, roads) == _oracle(region, consumers, th, roads), \
            f"trial {trial}: offset=({ox},{oy}) size=({w},{h})"


def test_matches_oracle_on_real_generated_lane_patterns():
    """The shapes it will actually be used on: real generator output, including
    the widened pitch range this filter exists to make affordable."""
    region = {(x, y) for x in range(22) for y in range(22)}
    consumers = [_consumer(10, 2, 2), _consumer(11, 3, 3), _consumer(12, 4, 3),
                 _consumer(13, 2, 5), _consumer(14, 3, 3)]
    scorer = SkeletonScorer(region, consumers)
    checked = 0
    for k in (25, 40):
        for pitches in (None, (13, 15)):
            pats = generate_lane_patterns(region, 2, 2, k, random.Random(1), 12,
                                          th_mode="full", pitches=pitches)
            for p in pats:
                assert scorer.opts_total(p.th, p.roads) == \
                    _oracle(region, consumers, p.th, p.roads)
                checked += 1
    assert checked > 0, "no patterns generated -- test asserted nothing"


def test_zero_when_no_footprint_fits():
    region = {(x, y) for x in range(4) for y in range(4)}
    consumers = [_consumer(10, 9, 9)]
    scorer = SkeletonScorer(region, consumers)
    assert scorer.opts_total(Footprint(0, 0, 2, 2), frozenset({(2, 0)})) == 0


def test_identical_sizes_are_multiplied_not_deduplicated():
    region = {(x, y) for x in range(10) for y in range(10)}
    th = Footprint(0, 0, 2, 2)
    roads = frozenset({(2, 0), (2, 1), (2, 2)})
    one = SkeletonScorer(region, [_consumer(10, 2, 2)]).opts_total(th, roads)
    three = SkeletonScorer(region, [_consumer(10, 2, 2), _consumer(11, 2, 2),
                                    _consumer(12, 2, 2)]).opts_total(th, roads)
    assert one > 0
    assert three == 3 * one


def test_mean_free_adjacency_matches_hand_count():
    from foeopt.skeleton_score import mean_free_adjacency
    region = {(x, y) for x in range(5) for y in range(5)}
    th = Footprint(0, 0, 2, 2)
    # a single road cell at (3,0): neighbours (2,0),(4,0),(3,1); (3,-1) is
    # outside the region. All three are free (TH occupies (0..1, 0..1)).
    assert mean_free_adjacency(region, th, frozenset({(3, 0)})) == 3.0
    # (0,2) touches (0,1)=TH [not free], (0,3), (1,2); (-1,2) outside -> 2
    assert mean_free_adjacency(region, th, frozenset({(0, 2)})) == 2.0
    # two road cells adjacent to each other do not count each other as free
    got = mean_free_adjacency(region, th, frozenset({(3, 0), (3, 1)}))
    assert got == (2 + 3) / 2


def test_mean_free_adjacency_empty_skeleton_is_zero():
    from foeopt.skeleton_score import mean_free_adjacency
    region = {(x, y) for x in range(4) for y in range(4)}
    assert mean_free_adjacency(region, Footprint(0, 0, 2, 2), frozenset()) == 0.0


def test_mean_free_adjacency_lower_when_hemmed_in():
    """The directional claim the filter relies on: a skeleton in open ground
    scores higher than the same-size skeleton packed against the region edge."""
    from foeopt.skeleton_score import mean_free_adjacency
    region = {(x, y) for x in range(9) for y in range(9)}
    th = Footprint(0, 0, 2, 2)
    open_ground = frozenset({(4, 4), (4, 5)})
    against_edge = frozenset({(0, 8), (1, 8)})
    assert mean_free_adjacency(region, th, against_edge) < \
        mean_free_adjacency(region, th, open_ground)
